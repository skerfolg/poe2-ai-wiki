"""무기 슬롯 조합 규칙 — 성립 불가 조합의 거짓 통과를 막는다 (이관 4 C7).

**거인의 피 없이 양손 철퇴 + 오프핸드 집중구가 정상 계산됐다**(생명력 +84·ES +146·
DPS +378). 규칙은 PoB `Modules/CalcSetup.lua:899`의 **비교(override) 경로에만** 있고
우리 조립 경로에는 없어서, 성립 불가 조합이 정상 수치를 냈다. 세션이 그 값을 근거로
설계를 진행하다 PoB 소스를 읽고서야 발견했다.

## PoB가 쓰는 규칙 (CalcSetup.lua:899~904)

    거인의 피 없이   양손 검·도끼·철퇴 → 오프핸드 **불가**
    권능의 도구 없이 지팡이           → 오프핸드는 **집중구만**
    야생의 군주 없이 부적             → 오프핸드는 **셉터·유니크만**
    활                                → 오프핸드는 **화살통만**

키스톤(거인의 피·권능의 도구·야생의 군주)은 트리에서 확보하므로 입력으로 받는다.

**판단은 하지 않는다**(AD-3) — 위반이면 사유를 내고, 무엇을 바꿀지는 호출자 몫이다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# 오프핸드를 막는 주손 무기 계열 → (해제 키스톤, 예외로 허용되는 오프핸드)
TWO_HAND_TYPES = ("two hand sword", "two hand axe", "two hand mace", "warstaff", "quarterstaff")
_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # (주손 계열 정규식, 해제 키스톤, 그래도 허용되는 오프핸드 계열)
    (r"two hand (sword|axe|mace)|warstaff|quarterstaff", "giants blood", ()),
    (r"\bstaff\b", "instruments of power", ("focus",)),
    (r"talisman", "lord of the wilds", ("sceptre",)),
    (r"\bbow\b", "", ("quiver",)),
)
KEYSTONE_ALIASES = {
    "거인의 피": "giants blood",
    "giant's blood": "giants blood",
    "권능의 도구": "instruments of power",
    "야생의 군주": "lord of the wilds",
}


@dataclass(frozen=True)
class WeaponSlot:
    """한 손에 든 것 — `category`는 KB 베이스의 계열(warstaff·staff·bow…)."""

    slot: str  # "Weapon 1" | "Weapon 2"
    name: str = ""
    category: str = ""
    rarity: str = ""


@dataclass(frozen=True)
class LoadoutReport:
    violations: tuple[str, ...]
    notes: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def _normalise_keystones(keystones: Iterable[str]) -> set[str]:
    out: set[str] = set()
    for raw in keystones:
        key = str(raw).strip().lower()
        out.add(KEYSTONE_ALIASES.get(key, key))
    return out


def check_loadout(
    weapons: Iterable[WeaponSlot | Mapping[str, object]],
    keystones: Iterable[str] = (),
) -> LoadoutReport:
    """주손·오프핸드 조합이 성립하는가. 성립 불가면 **사유와 함께 위반으로 낸다**."""
    slots: list[WeaponSlot] = []
    for raw in weapons:
        if isinstance(raw, WeaponSlot):
            slots.append(raw)
        else:
            slots.append(
                WeaponSlot(
                    slot=str(raw.get("slot", "")),
                    name=str(raw.get("name", "")),
                    category=str(raw.get("category", "")),
                    rarity=str(raw.get("rarity", "")),
                )
            )
    main = next((s for s in slots if s.slot.startswith("Weapon 1")), None)
    off = next((s for s in slots if s.slot.startswith("Weapon 2")), None)
    have = _normalise_keystones(keystones)

    violations: list[str] = []
    notes: list[str] = []
    if main is None or off is None:
        return LoadoutReport((), ("주손·오프핸드 둘 다 있어야 조합 규칙을 본다",))

    main_cat = f"{main.category} {main.name}".lower()
    off_cat = f"{off.category} {off.name}".lower()
    for pattern, keystone, allowed in _RULES:
        if not re.search(pattern, main_cat):
            continue
        if keystone and keystone in have:
            notes.append(f"{main.name or main.category}: {keystone} 보유 — 오프핸드 허용")
            break
        if allowed and any(a in off_cat for a in allowed):
            break
        if not keystone:
            violations.append(
                f"{main.name or main.category}(주손)에는 오프핸드로 "
                f"{'·'.join(allowed)}만 들 수 있다 — 현재 {off.name or off.category}"
            )
            break
        detail = f" (예외: {'·'.join(allowed)})" if allowed else ""
        violations.append(
            f"{main.name or main.category}(주손)은 **{keystone} 없이 오프핸드를 들 수 없다**"
            f"{detail} — 현재 {off.name or off.category}. "
            f"PoB는 비교 경로에서만 이 규칙을 적용해서 조립하면 **거짓 통과**한다"
            f"(CalcSetup.lua:899)"
        )
        break
    return LoadoutReport(tuple(violations), tuple(notes))
