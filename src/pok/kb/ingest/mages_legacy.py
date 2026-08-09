"""마법사의 유산(Mage's Legacy) 개별 보너스 수집 (백로그 #19).

KB에는 **이름 14종만** 있었다. 그래서 마법사의 피를 평가하려면 PoB 소스를 직접 읽어야
했고(빌드 세션 실측 2026-08-09), 그중 **Ruby·Sapphire·Topaz가 최대 저항 +5를 준다**는
설계를 바꾸는 정보가 KB만 보고는 보이지 않았다.

전체 표는 PoB에 있다 — `Modules/CalcPerform.lua`의 `local legacies = {…}`. poe2db
왕복이 필요 없다.

## 중복은 "안 쌓인다"가 아니다 (KB 문구가 오해를 부른다)

레코드의 원문은 *"Only one instance of each Mage's Legacy can apply its bonus"*인데,
`CalcPerform.lua:1502-1528`을 보면 **중복은 전역 배수를 올린다**:

    totalDuplicates = Σ(각 유산의 개수 - 1)
    globalEffect    = 1 + totalDuplicates * (MagesLegacyEffect / 100)
    적용값          = floor(globalEffect * 원래값)

즉 같은 유산을 두 개 끼면 그 보너스가 두 번 붙지는 않지만 **모든 유산의 값이 함께
커진다.** 그리고 이 계산 전체가 `MagebloodEquipped` 플래그 아래에서만 돈다.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# `LegacyOfAmethyst = { effects = { { stat = "ChaosResist", type = "BASE", value = 45 }, } }`
_BLOCK = re.compile(r"(LegacyOf\w+)\s*=\s*\{\s*effects\s*=\s*\{(.*?)\}\s*\}", re.S)
_EFFECT = re.compile(
    r'\{\s*stat\s*=\s*"(\w+)"\s*,\s*type\s*=\s*"(\w+)"\s*,\s*value\s*=\s*(-?\d+(?:\.\d+)?)\s*\}'
)
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")


def _display_name(key: str) -> str:
    """`LegacyOfAmethyst` → `Legacy of Amethyst` (KB `stats`의 표기와 맞춘다)."""
    return _CAMEL.sub(" ", key).replace("Legacy Of ", "Legacy of ")


def parse_legacies(source: str) -> dict[str, list[dict[str, Any]]]:
    """`CalcPerform.lua` 원문 → {표시명: [{stat, type, value}]}."""
    out: dict[str, list[dict[str, Any]]] = {}
    for key, body in _BLOCK.findall(source):
        effects = [
            {"stat": stat, "type": kind, "value": float(value) if "." in value else int(value)}
            for stat, kind, value in _EFFECT.findall(body)
        ]
        if effects:
            out[_display_name(key)] = effects
    return out


def collect(root: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """정본 스냅샷에서 읽는다 — 핀은 `pob_pin` 하나에서 나온다(#16)."""
    from pok.kb.pob_pin import pob_src_dir

    path = pob_src_dir(root) / "Modules" / "CalcPerform.lua"
    if not path.exists():
        return {}
    return parse_legacies(path.read_text(encoding="utf-8", errors="replace"))


def apply(root: Path | None = None, *, write: bool = True) -> dict[str, Any]:
    """`mechanic.mages-legacy`에 개별 보너스와 중복 규칙을 얹는다."""
    from pok.kb.store import patch_records

    legacies = collect(root)
    if not legacies:
        return {"written": False, "why": "PoB 스냅샷에서 legacies 표를 못 찾았다"}
    update = {
        "mechanic.mages-legacy": {
            "legacies": legacies,
            # KB 원문("각각 하나만 적용")이 **중복은 무의미**로 읽히는데 아니다 —
            # 중복은 자기 보너스를 더하지 않는 대신 **모든 유산의 값을 함께 올린다**.
            "duplicate_rule": (
                "totalDuplicates = Σ(각 유산 개수 - 1) · "
                "globalEffect = 1 + totalDuplicates * (MagesLegacyEffect/100) · "
                "적용값 = floor(globalEffect * 원래값). "
                "마법사의 피를 낀 상태(MagebloodEquipped)에서만 계산된다"
            ),
            "_verification": {"legacies": "POB_CODE", "duplicate_rule": "POB_CODE"},
        }
    }
    if write:
        patch_records(update, root=root)
    return {"written": bool(write), "count": len(legacies), "names": sorted(legacies)}
