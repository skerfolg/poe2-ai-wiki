"""아이템 텍스트 **왕복 검사** — 우리가 만든 것과 PoB가 쓰는 것이 같은가 (백로그 #34).

## 왜 이것이 강제 지점인가

사용자 지시: *"내가 직접 만드는 아이템과 너가 만드는 아이템이 동일한 것."*
생성기가 **사람이 읽는 문구 줄**을 쓰다 보니 값을 지어냈다 — 실오라기
`204% increased Spell Damage`(옵션에 없는 문구) · 룬 `150%`(실제 30%) · 없는 베이스
`Silk Gloves`. 10슬롯 중 **8슬롯이 인게임에서 못 만들거나 값이 틀렸고**, 그 위에서 낸
`IgniteDPS 168,115`는 전량 폐기됐다.

"규격을 따르자"를 문서에 적으면 안 지켜진다(철칙 5). 그래서 **PoB에게 묻는다**:
`Item.lua::BuildRaw()`(L1396~1601)는 PoB 자신이 아이템을 텍스트로 쓸 때 쓰는 함수이고
`BuildAndParseRaw`(L1604)가 그 출력을 다시 파싱한다 — 즉 **BuildRaw 출력이 정본**이다.
우리 텍스트를 넣어 되쓰게 하고, 돌아온 것과 다르면 그 차이가 곧 결함이다.

⛔ 정본은 사용자가 올린 PoB 코드가 **아니다**(그건 예시다). 규격은 소스다(AD-1).

## 무엇이 걸리나

실측으로 확인된 것(#34의 A~F):

- 문구 줄로 쓴 접사 → PoB는 `Crafted: true` + `Prefix: {range:R}<PobModId>`로 되쓴다
- 손으로 쓴 `{rune}` 줄 → `UpdateRunes()`가 만든 줄과 **겹쳐** 소켓 수보다 많아진다
- 선언 누락(`Implicits:`·`Sockets:`) → 되쓴 텍스트에서 개수가 어긋난다
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.common.paths import project_root, var_dir
from pok.pob.runner import _LUA_PATH
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_SCRIPT = Path("scripts") / "pob_item_roundtrip.lua"


class RoundtripError(RuntimeError):
    """왕복 검사 자체가 실패 — 결과 불일치와 구분한다."""


@dataclass(frozen=True)
class Roundtrip:
    """아이템 하나의 왕복 결과."""

    label: str
    given: str
    rebuilt: str  # PoB가 자기 포맷으로 되쓴 텍스트 (실패 시 빈 문자열)
    error: str = ""

    @property
    def matches(self) -> bool:
        """되쓴 것이 준 것과 같은가 — 줄 끝 공백·빈 줄만 무시한다."""
        return _normalize(self.given) == _normalize(self.rebuilt)

    @property
    def diff(self) -> tuple[tuple[str, str], ...]:
        """(준 줄, 되쓴 줄) 쌍 — 다른 자리만. 길이가 다르면 빈 문자열로 채운다."""
        mine, theirs = _normalize(self.given), _normalize(self.rebuilt)
        width = max(len(mine), len(theirs))
        pairs = [
            (mine[i] if i < len(mine) else "", theirs[i] if i < len(theirs) else "")
            for i in range(width)
        ]
        return tuple((a, b) for a, b in pairs if a != b)


def _normalize(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def roundtrip(
    items: dict[str, str],
    *,
    root: Path | None = None,
    snapshot: PobSnapshot | None = None,
    timeout: float = 300.0,
) -> list[Roundtrip]:
    """아이템 텍스트들을 PoB에 넣어 **되쓰게** 한다 (PoB 1회 부팅).

    판정은 하지 않는다 — 되쓴 텍스트를 그대로 돌려준다. 무엇을 불일치로 볼지는
    호출자가 정한다(AD-3).
    """
    if not items:
        return []
    snap = snapshot or resolve_snapshot(root)
    payload = var_dir() / "pob-cache" / "_roundtrip.txt"
    payload.parent.mkdir(parents=True, exist_ok=True)
    with payload.open("w", encoding="utf-8", newline="\n") as fh:
        for label, text in items.items():
            fh.write(f"#ITEM\t{label}\n")
            fh.writelines(f"{line}\n" for line in text.splitlines())
            fh.write("#END\n")
    try:
        proc = subprocess.run(
            [find_luajit(), str(project_root() / _SCRIPT), str(payload)],
            cwd=snap.src_dir,
            env={**os.environ, "LUA_PATH": _LUA_PATH},
            input="",
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        payload.unlink(missing_ok=True)
    out = proc.stdout.splitlines()
    if "POK_OK" not in out:
        raise RoundtripError("왕복 검사가 POK_OK 없이 끝났다:\n" + "\n".join(out[-8:]))

    rebuilt: dict[str, str] = {}
    errors: dict[str, str] = {}
    for line in out:
        if line.startswith("POK_RAW:"):
            label, _, body = line[len("POK_RAW:") :].partition("\t")
            rebuilt[label] = body.replace("\\n", "\n").replace("\\\\", "\\")
        elif line.startswith("POK_ERR_ITEM:"):
            label, _, why = line[len("POK_ERR_ITEM:") :].partition("\t")
            errors[label] = why
    return [
        Roundtrip(
            label=label, given=text, rebuilt=rebuilt.get(label, ""), error=errors.get(label, "")
        )
        for label, text in items.items()
    ]


def invariants(rebuilt: str) -> tuple[str, ...]:
    """되쓴 텍스트가 **자기 선언과 맞는가** (#34 수용 기준 2).

    개수가 어긋나면 인게임에서 못 만드는 물건이다 — 실측 사고: 모리오르 4소켓에
    룬 효과가 **6줄** 나왔다. 손으로 쓴 `{rune}` 줄이 `UpdateRunes()`가 만든 줄과
    겹쳤기 때문이다. 그래서 **`{rune}` 줄을 생성하지 말고** `Sockets:`+`Rune:`만 쓴다.
    """
    lines = _normalize(rebuilt)
    problems: list[str] = []

    sockets = next((ln for ln in lines if ln.lower().startswith("sockets:")), "")
    slots = len([tok for tok in sockets.split(":", 1)[-1].split() if tok.upper() == "S"])
    declared = len([ln for ln in lines if ln.lower().startswith("rune:")])
    rune_lines = len([ln for ln in lines if "{rune}" in ln])
    if slots and declared > slots:
        problems.append(f"`Rune:` 선언 {declared}개 > 소켓 {slots}칸")
    if slots and rune_lines > slots:
        problems.append(
            f"룬 효과 줄 {rune_lines}개 > 소켓 {slots}칸 — `{{rune}}` 줄을 손으로 쓰면 "
            f"`UpdateRunes()`가 만든 줄과 **겹친다**(실측: 4소켓에 6줄)"
        )

    for line in lines:
        if line.lower().startswith("implicits:"):
            want = int(line.split(":", 1)[1].strip() or 0)
            after = lines[lines.index(line) + 1 :]
            got = 0
            for candidate in after:
                if _SPEC_AFTER_IMPLICITS.match(candidate) or got >= want:
                    break
                got += 1
            if got != want:
                problems.append(f"`Implicits: {want}` 선언인데 뒤따르는 줄이 {got}개")
            break
    return tuple(problems)


# `Implicits:` 뒤의 모드 줄이 끝나는 표식 — 여기부터는 명시 접사·표식이다.
_SPEC_AFTER_IMPLICITS = re.compile(
    r"^(Corrupted|Twice Corrupted|Mirrored|Sanctified|Crafted:|Prefix:|Suffix:)", re.I
)


def build_items(
    specs: dict[str, str],
    *,
    root: Path | None = None,
    snapshot: PobSnapshot | None = None,
    timeout: float = 300.0,
) -> dict[str, str]:
    """**명세 → PoB 정본 텍스트.** 아이템 문구를 우리가 조립하지 않는다 (#34 근본 해결).

    사용자 지시 2026-08-09: *"내가 직접 만드는 아이템과 너가 만드는 아이템이 동일한 것"*
    — 그러려면 우리가 쓸 것은 **명세뿐**이다. 문구·수치·방어값·빈 칸은 PoB가 만든다.

    명세는 사용자 정본이 쓰는 그 형태다:

        Rarity: RARE
        New Item
        Ancestral Tiara
        Crafted: true
        Prefix: {range:1}LocalIncreasedEnergyShield8      ← 모드 id
        Suffix: {range:1}CriticalStrikeChance5
        Sockets: S S S
        Rune: Perfect Iron Rune                           ← 룬 이름

    실측 2026-08-09: 이 명세만 주고 PoB의 `Craft()` → `BuildRaw()`를 태우니
    `+73 to maximum Energy Shield` · `+174 to maximum Life` ·
    `34% increased Critical Hit Chance` · `+45% to Cold Resistance`가
    **사용자가 손으로 쓴 것과 값까지 동일**하게 나왔고 `Energy Shield: 218`도
    PoB가 계산했다. 빈 접사 칸·빈 소켓·`Implicits:` 개수도 자동이다.

    ⚠ **접사 group 배타만은 PoB가 안 봐 준다** — `Craft()`는 검사하지 않는다.
    그건 `check_item_legality`가 계속 맡는다(#34 F).

    실패한 명세는 결과에서 **빠진다** — 조용히 빈 텍스트를 돌려주면 그게 조용한 0이다.
    무엇이 실패했는지는 `roundtrip()`을 직접 불러 `error`를 볼 것.

    ⚡ **상주 데몬을 쓴다.** 호출마다 PoB를 띄우면 9.8초가 든다(실측 2026-08-09) —
    `optimize_rare` 한 번의 시간이 전부 그 부팅이었다. 데몬은 부팅을 1회로 상각한다.
    """
    daemon = _shared_daemon()
    if daemon is not None:
        out: dict[str, str] = {}
        for label, spec in specs.items():
            built = daemon.build_item(spec)
            if built:
                out[label] = built
        return out
    return {
        r.label: r.rebuilt
        for r in roundtrip(specs, root=root, snapshot=snapshot, timeout=timeout)
        if not r.error and r.rebuilt
    }


def _shared_daemon() -> Any:
    """프로세스당 하나의 상주 PoB — 정본은 `pok.pob.daemon.shared_daemon`이다."""
    from pok.pob.daemon import shared_daemon

    return shared_daemon()
