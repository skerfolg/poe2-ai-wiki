"""무기 슬롯 조합 규칙 — 성립 불가 조합의 거짓 통과를 막는다 (이관 4 C7).

거인의 피 없이 양손 철퇴 + 오프핸드 집중구가 **정상 계산됐다**(생명력 +84·DPS +378).
PoB는 이 규칙을 비교(override) 경로에서만 적용해서 조립하면 거짓 통과한다.
"""

from __future__ import annotations

from pok.engine.constraints.loadout import WeaponSlot, check_loadout

MAUL = WeaponSlot("Weapon 1", "Forge Maul", "two hand mace")
FOCUS = WeaponSlot("Weapon 2", "Focus", "focus")


def test_two_hander_without_giants_blood_is_a_violation() -> None:
    report = check_loadout([MAUL, FOCUS])
    assert not report.ok
    assert "giants blood" in report.violations[0]
    assert "거짓 통과" in report.violations[0], "왜 PoB가 안 잡는지도 알려야 한다"


def test_giants_blood_unlocks_it() -> None:
    assert check_loadout([MAUL, FOCUS], ["거인의 피"]).ok, "한글 표기도 받아야 한다"
    assert check_loadout([MAUL, FOCUS], ["giants blood"]).ok


def test_staff_allows_focus_but_bow_needs_quiver() -> None:
    staff = WeaponSlot("Weapon 1", "Ashen Staff", "staff")
    assert check_loadout([staff, FOCUS]).ok, "지팡이 + 집중구는 성립"

    bow = WeaponSlot("Weapon 1", "Bow", "bow")
    shield = WeaponSlot("Weapon 2", "Shield", "shield")
    report = check_loadout([bow, shield])
    assert not report.ok and "quiver" in report.violations[0]


def test_missing_offhand_is_not_a_violation() -> None:
    """한 손만 있으면 조합 규칙을 볼 것이 없다 — 없는 것을 위반으로 만들지 않는다."""
    assert check_loadout([MAUL]).ok
