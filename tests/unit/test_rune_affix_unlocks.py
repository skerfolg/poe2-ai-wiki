"""A crafting unlock must come from the actual rune, slot and written seed."""

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.legality import ItemLegalityChecker

GLOVES = """Rarity: RARE
Rime Grasp
Vaal Wraps
Item Level: 82
Quality: +20%
Sockets: S
Rune: Kolr's Hunt
{rune}Can roll Marksman modifiers
Adds 19 to 32 Physical Damage to Attacks
100% increased Evasion and Energy Shield
+78 to Evasion Rating
+25 to maximum Energy Shield
+2 to Level of all Projectile Skills
34% increased Critical Hit Chance
34% increased Critical Damage Bonus
"""


@pytest.fixture(scope="module")
def checker():
    return ItemLegalityChecker(knowledge_dir())


def test_verified_rune_unlocks_its_real_affixes(checker):
    report = checker.check(GLOVES)
    assert report.is_legal, report
    projectile = next(
        v for v in report.verdicts if v.line == "+2 to Level of all Projectile Skills"
    )
    assert projectile.modifier_id == "modifier.marksmaninfluenceprojectileskills2"
    critical = next(v for v in report.verdicts if v.line == "34% increased Critical Hit Chance")
    assert critical.modifier_id.startswith("modifier.marksmaninfluence")
    assert report.affix_inventory["used"] == {"prefix": 3, "suffix": 3}
    assert report.affix_inventory["rune_unlocked_tags"] == ["marksman"]


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("Rune: Kolr's Hunt\n", ""),
        ("Rune: Kolr's Hunt", "Rune: None"),
        ("Rune: Kolr's Hunt", "Rune: Iron Rune"),
        ("Sockets: S\n", ""),
        ("{rune}Can roll Marksman modifiers\n", ""),
        ("{rune}Can roll Marksman modifiers", "{custom}Can roll Marksman modifiers"),
        ("{rune}Can roll Marksman modifiers", "{rune}Can roll Destruction modifiers"),
        ("Vaal Wraps", "Bastion Sabatons"),
        ("Item Level: 82", "Item Level: 1"),
        ("+2 to Level", "+3 to Level"),
    ],
)
def test_unlock_does_not_waive_supplier_slot_tier_or_level(checker, old, new):
    assert not checker.check(GLOVES.replace(old, new)).is_legal


def test_unlock_does_not_leak_to_later_checks(checker):
    assert checker.check(GLOVES).is_legal
    report = checker.check(GLOVES.replace("Rune: Kolr's Hunt", "Rune: None"))
    assert not report.is_legal
    assert "marksman" not in checker._bases["vaal wraps"]["data"]["spawn_tags"]


def test_unsupported_influence_marker_is_not_silently_discarded(checker):
    report = checker.check(GLOVES.replace("Sockets: S", "Marksman Item\nSockets: S"))
    assert not report.is_legal
    assert any(v.line == "Marksman Item" and v.status == "UNKNOWN" for v in report.verdicts)


def test_duplicate_named_rune_cannot_create_unlock(checker):
    report = checker.check(
        GLOVES.replace("Sockets: S", "Sockets: S S").replace(
            "Rune: Kolr's Hunt", "Rune: Kolr's Hunt\nRune: Kolr's Hunt"
        )
    )
    assert not report.is_legal
