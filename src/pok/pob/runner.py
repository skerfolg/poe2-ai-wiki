"""headless PoB 실행 — XML을 넣고 스탯을 받는 왕복 (scripts/pob_driver.lua 프로토콜).

한 번 실행 = LuaJIT 프로세스 1회 (~2초, 트리·데이터 로드가 지배적).
동일 (XML, PoB 커밋) 결과는 `var/pob-cache/`에 캐시 — 파생물이므로 삭제 무해.
최적화 루프용 상주 프로세스(daemon)는 P3 Phase 2에서 별도로 다룬다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.common.paths import project_root, var_dir
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_DRIVER = "scripts/pob_driver.lua"
#: `POK_META` 모양의 판 번호 (#119). **드라이버를 고치면 반드시 올린다.**
#  캐시 키가 `(PoB 커밋, XML)`뿐이라 우리 드라이버만 바뀌면 PoB 커밋이 그대로여서
#  **키가 안 움직인다** — 새 필드 없는 payload가 그대로 적중하고, 없는 키는 0으로
#  읽혀 「갭 없음」·「속도 정상」이라는 **거짓 안심**을 준다(형태 ①의 캐시 재발).
#  3 = items[](#120) · 2 = mainSkillShowsAverage(#113) · 1 = gap*(#110) · 0 = 그 이전
_META_PROTOCOL = 3
_LUA_PATH = "./?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;;"

#: PoB **아이템 상세보기**가 만드는 룬 드롭다운 수 (`Classes/ItemsTab.lua:696` `for i = 1, 6`).
#  `UpdateRuneControls`(:2016)는 `for i = 1, item.itemSocketCount`로 돌며
#  `self.controls["displayItemRune"..i].list = ...`를 쓴다 — 이 수를 넘기면 nil 인덱싱이라
#  **아이템을 클릭하는 순간 예외**다. 계산 경로에서는 안 터져서 조립이 그냥 통과시켰다.
RUNE_CONTROL_SLOTS = 6


def _gap_count(meta: dict[str, object], key: str) -> int:
    """`POK_META`의 갭 카운터 하나를 읽는다 (#110).

    `meta`는 드라이버 JSON이라 값 타입이 `object`다 — `int(...)`를 그대로 부르면
    strict mypy가 거부한다(`call-overload`). 드라이버는 `%d`로 찍으므로 정수이고,
    아니면 프로토콜이 깨진 것이라 0으로 둔다.

    ⚠ **없는 키를 0으로 읽는다** — 갭 키가 없던 시절의 결과에도 안 깨지게 하려는
    선택이다. 그 등가("없는 것 = 0")는 **갭 키 없는 payload가 안 읽힐 때만** 참이고,
    지금 `_cache_path`는 드라이버 프로토콜을 키에 안 넣어 그 보장이 없다(BACKLOG #119).
    """
    value = meta.get(key)
    # bool은 int의 하위형이라 먼저 걸러낸다 (buildxml._config_value_attrs와 같은 이유)
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


@dataclass(frozen=True)
class PobResult:
    """PoB 계산 결과 + 적법성 신호."""

    stats: dict[str, float]  # mainOutput의 유한 숫자 전부
    meta: dict[str, object]  # class/ascendancy/level/alloc* — 드라이버 POK_META
    allocated_nodes: tuple[int, ...]  # 실제 할당된 트리 노드 (시작점 제외)
    pruned_nodes: tuple[int, ...]  # 요청했지만 PoB가 해제한 노드 (비연결 등)
    cached: bool

    @property
    def oracle_gaps(self) -> dict[str, int]:
        """PoB가 **보고도 안 센 것** — 0이 아니면 이 빌드의 딜은 과소평가다 (#110).

        PoB 0.23.1은 플레이어의 트리거·미라주 계산을 꺼 뒀다
        (`Modules/CalcPerform.lua:3433`). 되살려 보니 `CalcTriggers.lua:396`·
        `CalcMirages.lua:59`이 둘 다 `skillFlags`(nil)에서 죽는다 — 정책이 아니라
        **미완성**이고, 상류 `dev` HEAD가 우리 스냅샷이라 올라갈 곳도 없다
        (실측 2026-08-23). 그래서 발동 스킬의 딜은 `CombinedDPS`에 **0**으로 들어간다.

        ⛔ 이 값이 0이 아닌 빌드에서 「딜이 낮다」고 판정하면 안 된다 — 못 잰 것이다.
        """
        return {
            "triggered_skills": _gap_count(self.meta, "gapTriggeredSkills"),
            "mirage_skills": _gap_count(self.meta, "gapMirageSkills"),
            # 방향이 다르다 — 주력기가 발동이면 발동률이 안 걸려 **과대평가** 쪽이다
            "main_skill_triggered": _gap_count(self.meta, "gapMainSkillTriggered"),
        }

    @property
    def main_skill_shows_average(self) -> bool:
        """주력기의 `CombinedDPS`가 **속도 배수를 잃었는가** (#113).

        `CalcOffence.lua:6136`이 `showAverage`일 때 `CombinedDPS`의 밑값을 `TotalDPS`가
        아니라 `AverageDamage`로 잡는다 — 1회 평균 피해라 공격·시전 속도가 안 곱해진다.
        참이면 **`CombinedDPS`로 속도를 판정하면 안 된다**(실측: 채택 35수 중 공격 속도
        노터블 0건).

        ⚠ 이 플래그는 스킬 **피해 모델**의 결함 표지가 아니다 — `TotalDPS`(:4447 =
        Avg x (HitSpeed or Speed))는 정상이고, 망가지는 것은 축 선택 하나다.
        BACKLOG §3이 그 오독을 한 번 뒤집었다.
        """
        return _gap_count(self.meta, "mainSkillShowsAverage") == 1

    @property
    def dps_axis(self) -> str:
        """이 결과에서 **딜로 읽어야 할 축 이름** (#113).

        ⚠ `TotalDPS`로 바뀌면 DoT·상태이상·임페일 가산분이 빠진다. 그건 `TotalDot` 등
        **별도 축에 그대로 실려 있으니 필요한 쪽이 더한다** — 여기서 합성하면 PoB
        재구현이 된다(AD-1).
        """
        return "TotalDPS" if self.main_skill_shows_average else "CombinedDPS"

    @property
    def measures_all_damage(self) -> bool:
        """딜 수치를 **그대로 믿어도 되는가** — 발동·미라주가 없어야 참이다 (#110)."""
        return not any(self.oracle_gaps.values())

    @property
    def is_tree_legal(self) -> bool:
        """요청한 노드가 전부 반영됐는가 — 비연결 노드는 PoB가 소리 없이 잘라낸다."""
        return not self.pruned_nodes

    @property
    def items(self) -> tuple[dict[str, Any], ...]:
        """PoB가 **실제로 읽은** 아이템별 소켓 사실 (#120) — 판정이 아니라 관측.

        각 행: `id`·`name`·`base`·`rarity`·`sockets`(PoB의 `itemSocketCount`)·
        `limit`(허용 칸)·`limitSource`(`unique`/`base`/`none`)·`unknownRunes`.
        옛 캐시·옛 스냅샷에는 없을 수 있으므로 없으면 빈 튜플이다.
        """
        rows = self.meta.get("items")
        if not isinstance(rows, list):
            return ()
        return tuple(r for r in rows if isinstance(r, dict))

    @property
    def item_socket_problems(self) -> tuple[str, ...]:
        """**존재할 수 없는 룬 소켓** — 사유 문자열 (#120). 비어 있으면 통과.

        `is_tree_legal`과 같은 계열이다: 오라클이 낸 사실을 적법성 신호로 읽는다.
        """
        return socket_problems(self.items)

    @property
    def is_item_sockets_legal(self) -> bool:
        return not self.item_socket_problems


def socket_problems(items: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    """아이템 소켓 관측 → 거부 사유 (#120).

    ## 왜 여기가 강제 지점인가 (철칙 5)

    소켓 한도는 **문서와 사유 문구에만** 있었다 — 적법성 검사기는 룬 줄을 볼 때마다
    *"소켓 한도는 `check_constraints(exhaustion.sockets)`로 검사하라"*고 적어 보냈고,
    그 도구는 **에이전트가 손으로 칸 수를 넣어야** 작동한다. 아무도 넣지 않으면 아무도
    모른다. 실측 2026-08-25(사용자 신고 빌드): 12개 중 4개가 한도 초과였고
    (사냥용 신발 3→4 · 룬벼림 장갑 3→4 · 검투사 투구 3→4 · 모리오르 4→**7**)
    조립·계산·기록이 전부 통과했다. 사용자는 PoB에서 **아이템을 클릭했을 때** 알았다.

    ## 판정 근거는 PoB 하나다 (형태 ④ 회피)

    한도를 KB `socket_limit`으로 재면 **정상 유니크를 거부한다** — 베이스 한도를 넘는
    유니크가 실재하고(Atziri's Splendour 6>4 · Runeseeker's Call 5>3 ·
    Darkness Enthroned 2>0), 그중 `Runeseeker's Call`은 정본에 소켓 문구조차 없다
    (KB 수집 갭). 거짓 거부는 게이트 우회를 학습시키므로(형태 ⑪) 판정 주체를 하나로
    둔다: 오라클이 `data.uniques`·`base.socketLimit`을 보고 `limit`을 정한다.
    """
    out: list[str] = []
    for row in items:
        sockets = _as_int(row.get("sockets"))
        limit = _as_int(row.get("limit"))
        label = f"{row.get('name') or '?'}({row.get('base') or '?'})"
        if sockets > limit:
            source = {
                "unique": "유니크 정의",
                "base": "베이스 socketLimit",
                "none": "이 베이스는 룬 소켓을 못 가진다",
            }.get(str(row.get("limitSource")), str(row.get("limitSource")))
            out.append(
                f"{label}: 룬 소켓 {sockets}칸인데 한도는 {limit}칸 — 인게임에서 만들 수 "
                f"없다 (한도 출처: {source}). `Sockets:` 줄을 {limit}칸으로 줄일 것"
            )
        if sockets > RUNE_CONTROL_SLOTS:
            out.append(
                f"{label}: 룬 소켓 {sockets}칸 > {RUNE_CONTROL_SLOTS}칸 — PoB **아이템 "
                f"상세보기가 예외로 죽는다**(`ItemsTab.lua`가 룬 드롭다운을 "
                f"{RUNE_CONTROL_SLOTS}개만 만드는데 `UpdateRuneControls`는 소켓 수까지 "
                f"돌며 인덱싱한다). 계산 경로에서는 안 터지므로 여기서만 잡힌다"
            )
        unknown = row.get("unknownRunes")
        if isinstance(unknown, list) and unknown:
            names = " · ".join(str(u) for u in unknown)
            out.append(
                f"{label}: PoB가 모르는 룬 이름 {len(unknown)}건({names}) — 하나라도 있으면 "
                f"PoB가 `UpdateRunes()`를 **안 돌린다**(`Item.lua:1046~1058`). 손으로 쓴 "
                f"`{{rune}}` 줄이 그대로 남아 값이 조용히 어긋난다"
            )
    return tuple(out)


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


class PobRunError(RuntimeError):
    """드라이버가 POK_OK 없이 끝났다 — stderr/stdout 꼬리를 담는다."""


def _cache_path(xml_text: str, commit: str) -> Path:
    # ⛔ 판 번호가 키에 **들어가야 한다**(#119) — 빼면 드라이버 개정이 캐시를
    #    무효화하지 못해 옛 payload가 적중한다. 캐시는 `var/` 파생물이라
    #    무효화 비용이 없다(재계산 ~2초/건).
    digest = hashlib.sha256(f"{_META_PROTOCOL}\n{commit}\n{xml_text}".encode()).hexdigest()[:32]
    return var_dir() / "pob-cache" / f"{digest}.json"


def parse_lines(
    lines: list[str],
) -> tuple[dict[str, float], dict[str, object], tuple[int, ...]]:
    """POK_* 프로토콜 공통 파서 (driver·daemon 동일 계약). POK_ERR는 예외로 승격."""
    meta: dict[str, object] = {}
    stats: dict[str, float] = {}
    alloc: tuple[int, ...] = ()
    for line in lines:
        if line.startswith("POK_META:"):
            meta = json.loads(line[len("POK_META:") :])
        elif line.startswith("POK_ALLOC:"):
            alloc = tuple(json.loads(line[len("POK_ALLOC:") :]))
        elif line.startswith("POK_JSON:"):
            stats = {k: float(v) for k, v in json.loads(line[len("POK_JSON:") :]).items()}
        elif line.startswith("POK_ERR:"):
            raise PobRunError(line[len("POK_ERR:") :])
    if not stats or not meta:
        tail = "\n".join(lines[-8:])
        raise PobRunError(f"POK_META/POK_JSON 누락:\n{tail}")
    return stats, meta, alloc


def _parse(stdout: str) -> tuple[dict[str, float], dict[str, object], tuple[int, ...]]:
    lines = stdout.splitlines()
    result = parse_lines(lines)  # POK_ERR 사유가 있으면 여기서 먼저 예외로 승격
    if "POK_OK" not in lines:
        raise PobRunError("드라이버가 POK_OK 없이 종료:\n" + "\n".join(lines[-8:]))
    return result


def run_xml(
    xml_text: str,
    *,
    requested_nodes: tuple[int, ...] = (),
    snapshot: PobSnapshot | None = None,
    use_cache: bool = True,
    timeout: float = 120.0,
) -> PobResult:
    """XML 하나를 PoB로 계산한다. requested_nodes를 주면 잘린 노드를 판정."""
    snap = snapshot or resolve_snapshot()
    cache = _cache_path(xml_text, snap.commit)
    hit = use_cache and cache.exists()
    if hit:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    else:
        payload = _run_driver(xml_text, snap, timeout)
        if use_cache:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
                newline="\n",
            )
    allocated = tuple(int(n) for n in payload["alloc"])
    pruned = tuple(sorted(set(requested_nodes) - set(allocated)))
    return PobResult(
        stats=dict(payload["stats"]),
        meta=dict(payload["meta"]),
        allocated_nodes=allocated,
        pruned_nodes=pruned,
        cached=hit,
    )


def run_build(spec: BuildSpec, **kwargs: object) -> PobResult:
    """BuildSpec → XML 직렬화 → 계산. 트리 적법성 판정까지 한 번에."""
    return run_xml(to_xml(spec), requested_nodes=spec.tree_nodes, **kwargs)  # type: ignore[arg-type]


def _run_driver(xml_text: str, snap: PobSnapshot, timeout: float) -> dict[str, object]:
    driver = project_root() / _DRIVER
    digest = hashlib.sha256(xml_text.encode()).hexdigest()[:16]
    xml_file = var_dir() / "pob-cache" / f"_input-{digest}.xml"  # 해시명 = 동시 실행 안전
    xml_file.parent.mkdir(parents=True, exist_ok=True)
    xml_file.write_text(xml_text, encoding="utf-8", newline="\n")
    env = {**os.environ, "LUA_PATH": _LUA_PATH}
    try:
        proc = subprocess.run(
            [find_luajit(), str(driver), str(xml_file)],
            cwd=snap.src_dir,
            env=env,
            input="",  # PoB가 stdin을 읽는 경로 차단 (스파이크에서 echo "" 파이프와 동일)
            capture_output=True,
            text=True,
            # ⛔ **인코딩을 코드에서 고정한다** — `text=True`만 쓰면 Windows에서
            #    로케일 코드페이지(한국어면 cp949)로 디코딩한다. 예전엔 드라이버
            #    출력이 전부 ASCII라 안 드러났는데, `POK_META.items`가 **아이템
            #    이름**을 싣는 순간(#120) 한글 이름이 깨지거나 `json.loads`가 죽는다.
            #    환경변수(`PYTHONUTF8`)로는 못 막는다 — `common/stdio.py`가 같은
            #    이유로 진입점 코드에 강제 지점을 둔다(철칙 5).
            #    `errors="replace"`인 이유: 이름 한 글자 때문에 **측정 전체**를
            #    죽이지 않는다. 이름은 거부 사유의 라벨일 뿐 판정은 숫자로 한다.
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    finally:
        xml_file.unlink(missing_ok=True)
    if proc.returncode != 0 and "POK_" not in proc.stdout:
        raise PobRunError(f"luajit 종료 코드 {proc.returncode}:\n{proc.stderr[-2000:]}")
    stats, meta, alloc = _parse(proc.stdout)
    return {"stats": stats, "meta": meta, "alloc": list(alloc)}
