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
from dataclasses import dataclass
from pathlib import Path

from pok.common.paths import project_root, var_dir
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_DRIVER = "scripts/pob_driver.lua"
#: `POK_META` 모양의 판 번호 (#119). **드라이버를 고치면 반드시 올린다.**
#  캐시 키가 `(PoB 커밋, XML)`뿐이라 우리 드라이버만 바뀌면 PoB 커밋이 그대로여서
#  **키가 안 움직인다** — 새 필드 없는 payload가 그대로 적중하고, 없는 키는 0으로
#  읽혀 「갭 없음」·「속도 정상」이라는 **거짓 안심**을 준다(형태 ①의 캐시 재발).
#  2 = mainSkillShowsAverage(#113) · 1 = gap*(#110) · 0 = 그 이전
_META_PROTOCOL = 2
_LUA_PATH = "./?.lua;../runtime/lua/?.lua;../runtime/lua/?/init.lua;;"


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
            timeout=timeout,
        )
    finally:
        xml_file.unlink(missing_ok=True)
    if proc.returncode != 0 and "POK_" not in proc.stdout:
        raise PobRunError(f"luajit 종료 코드 {proc.returncode}:\n{proc.stderr[-2000:]}")
    stats, meta, alloc = _parse(proc.stdout)
    return {"stats": stats, "meta": meta, "alloc": list(alloc)}
