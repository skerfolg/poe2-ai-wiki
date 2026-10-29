"""Native double-click regression for original full-path B/C item text.

This invokes the pinned editor code headlessly, not a visible GUI interaction.
Acquisition legality and build quality are independent of editor compatibility.
"""

from __future__ import annotations

from typing import Any

import pytest

from pok.engine.runes import RuneOption, render_runed
from pok.pob.item_editor import audit_item_editor
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 PoB 스냅샷 없음")

# Exact XML Item bodies from B item 1 and C item 4. Keep late/duplicate headers:
# fixing them inside a fixture would destroy the user-reported regression.
_B_STAFF = """Rarity: RARE
Engineered Weapon 1
Gelid Staff
Crafted: true
Prefix: {range:0.5}SpellDamageGainedAsColdTwoHand6
Prefix: {range:0.5}SpellDamageOnTwoHandWeapon8
Prefix: {range:0.5}SpellDamageGainedAsFireTwoHand6
Suffix: {range:0.5}GlobalSpellGemsLevelTwoHandWeapon4
Suffix: {range:0.5}AlloyCastSpeedDamageAsExtraColdHybrid1
Suffix: {range:0.5}SpellCriticalStrikeChanceTwoHand6
Quality: 0
LevelReq: 64
Implicits: 1
Grants Skill: Level 20 Freezing Shards
Gain 58% of Damage as Extra Fire Damage
Gain 58% of Damage as Extra Cold Damage
224% increased Spell Damage
+6 to Level of all Spell Skills
100% increased Critical Hit Chance for Spells
43% increased Cast Speed
Gain 14% of Elemental Damage as Extra Cold Damage
{custom}+1 to Level of all Cold Spell Skills
Corrupted
Sockets: S S S S
Rune: Hedgewitch Assandra's Rune of Wisdom
Rune: Perfect Glacial Rune
Rune: Perfect Glacial Rune
Rune: Perfect Glacial Rune
{rune}+1 to Level of all Spell Skills
{rune}Gain 12% of Damage as Extra Cold Damage
{rune}Gain 12% of Damage as Extra Cold Damage
{rune}Gain 12% of Damage as Extra Cold Damage"""

_C_GLOVES = """Rarity: RARE
Engineered Gloves
Vaal Gloves
Energy Shield: 247
Crafted: true
Prefix: {range:0.5}IncreasedLife9
Prefix: {range:0.5}LocalIncreasedEnergyShield7
Prefix: {range:0.5}LocalIncreasedEnergyShieldPercent7_
Suffix: {range:0.5}ChaosResist6
Suffix: {range:0.5}Dexterity9
Suffix: None
Quality: 20
Sockets: S S S
Rune: Perfect Desert Rune
Rune: Perfect Glacial Rune
Rune: Perfect Storm Rune
LevelReq: 75
Implicits: 5
{enchant}{rune}Bonded: +60 to maximum Life
{enchant}{rune}Bonded: +60 to maximum Mana
{enchant}{rune}+22% to Fire Resistance
{enchant}{rune}+22% to Cold Resistance
{enchant}{rune}+22% to Lightning Resistance
+54 to maximum Energy Shield
96% increased Energy Shield
+135 to maximum Life
+35 to Dexterity
+26% to Chaos Resistance
{custom}{range:0.5}+(9-15) to Strength and Dexterity
{custom}{range:0.5}Damage Penetrates (10-15)% Cold Resistance
Sockets: S S S
Rune: Perfect Desert Rune
Rune: Perfect Glacial Rune
Rune: Perfect Storm Rune
Corrupted"""


@pytest.fixture(scope="module")
def editor_results() -> dict[str, Any]:
    cold = RuneOption("cold", "Perfect Glacial Rune", ("Gain 12% of Damage as Extra Cold Damage",))
    wisdom = RuneOption(
        "wisdom", "Hedgewitch Assandra's Rune of Wisdom", ("+1 to Level of all Spell Skills",)
    )
    glove_runes = [
        RuneOption("fire", "Perfect Desert Rune", ("+22% to Fire Resistance",)),
        RuneOption("cold", "Perfect Glacial Rune", ("+22% to Cold Resistance",)),
        RuneOption("lightning", "Perfect Storm Rune", ("+22% to Lightning Resistance",)),
    ]
    return audit_item_editor(
        {
            "B-original": _B_STAFF,
            "C-original": _C_GLOVES,
            "B-rendered": render_runed(_B_STAFF, [wisdom, cold, cold, cold]),
            "C-rendered": render_runed(_C_GLOVES, glove_runes),
            "normal-wand": "Rarity: NORMAL\nAttuned Wand",
            "count-drift": (
                "Rarity: RARE\nHeader Drift\nAdorned Wraps\nImplicits: 0\n+10 to maximum Life\n"
                "Sockets: S S S\nRune: None\nRune: None\nRune: None"
            ),
            # Editor representation only: this does not claim six attainable slots.
            "six-controls": "Rarity: NORMAL\nAttuned Wand\nSockets: S S S S S S",
        },
        timeout=60,
    )


@pytest.mark.parametrize("label,initial,opened", [("B-original", 4, 8), ("C-original", 6, 9)])
def test_original_fails_only_when_opening_native_details(
    editor_results: dict[str, Any],
    label: str,
    initial: int,
    opened: int,
) -> None:
    assert editor_results["checked"], editor_results
    assert not editor_results["compatible"]
    row = next(row for row in editor_results["items"] if row["label"] == label)
    assert row["checked"] and not row["compatible"]
    assert row["initial_sockets"] == initial
    assert row["opened_sockets"] == opened
    assert row["stage"] == "set_display_item"
    assert "ItemsTab.lua" in row["error"] and "nil value" in row["error"]


@pytest.mark.parametrize(
    "label,count", [("B-rendered", 4), ("C-rendered", 3), ("normal-wand", 0), ("six-controls", 6)]
)
def test_normalized_headers_and_controls_open_natively(
    editor_results: dict[str, Any],
    label: str,
    count: int,
) -> None:
    assert editor_results["checked"], editor_results
    row = next(row for row in editor_results["items"] if row["label"] == label)
    assert row["checked"] and row["compatible"], row
    assert row["stage"] == "complete"
    assert row["initial_sockets"] == row["opened_sockets"] == count


def test_first_open_that_silently_doubles_three_sockets_is_not_compatible(
    editor_results: dict[str, Any],
) -> None:
    row = next(row for row in editor_results["items"] if row["label"] == "count-drift")
    assert row["checked"] and not row["compatible"]
    assert row["initial_sockets"] == 3 and row["opened_sockets"] == 6
    assert row["stage"] == "double_click_count_check"
    assert row["code"] == "count_changed"
