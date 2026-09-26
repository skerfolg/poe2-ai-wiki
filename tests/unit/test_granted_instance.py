"""아이템 부여 스킬 인스턴스는 젬과 별개다 (#167).

사용자 인게임 확인(2026-09-26): 부재·한탄 목걸이 베이스가 주는 스킬은 **무료**(정신력
점유 없음)이고 같은 스킬 젬을 직접 등록한 것과 **중복해서** 돈다. 레코드의
`reservation: 100`·`granted_by: [Absent Amulet]`만 본 세션이 「Cast on Dodge는 목걸이
하나뿐」이라고 답했고, 사용자는 세션마다 이것을 다시 설명해야 했다.
"""

from __future__ import annotations

from pok.index.search import get_entry


def test_gem_skill_granted_by_amulet_reports_a_second_instance() -> None:
    """fields로 좁혀도 붙는다 — 고른 필드에 없어서 못 본 것이 결함이었다."""
    granted = get_entry("skill.cast-on-dodge", fields=["name"])["granted_instance"]
    assert "Absent Amulet" in granted["granted_by_items"]
    assert granted["gem_route"] is True
    assert "중복" in granted["stacks_with_gem"]
    assert "점유하지 않는다" in granted["reservation"]
    assert "Absent Amulet" in granted["verified_for"]


def test_granting_items_come_from_item_text_not_granted_by() -> None:
    """`granted_by`(poe2db From 카드)는 한탄 목걸이를 빠뜨린다 — 문구에서 뽑아야 잡힌다."""
    record = get_entry("skill.alchemists-boon")
    assert "Lament Amulet" not in (record["data"].get("granted_by") or [])
    assert "Lament Amulet" in record["granted_instance"]["granted_by_items"]


def test_non_amulet_givers_are_marked_unverified() -> None:
    """인게임 확인 범위는 목걸이 베이스다 — 유니크·무기 부여분까지 확인됐다고 말하지 않는다."""
    granted = get_entry("skill.herald-of-ash", fields=["name"])["granted_instance"]
    assert "Lament Amulet" in granted["verified_for"]
    assert "The Coming Calamity" in granted["unverified_for"]


def test_gem_only_skill_carries_no_annotation() -> None:
    assert "granted_instance" not in get_entry("skill.fireball", fields=["name"])
