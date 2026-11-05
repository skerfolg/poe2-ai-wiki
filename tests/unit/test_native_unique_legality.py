"""Native selected pools must not become blanket unique-mod allowlists."""

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.legality import ItemLegalityChecker
from pok.pob import uniques

RAW = """Variant Armour
Grand Regalia
Has Alt Variant: true
Selected Variant: 1
Selected Alt Variant: 2
Variant: Current
Variant: Life
Variant: Mana
100% increased Armour
{variant:2}+(40-60) to maximum Life per Socket filled
{variant:3}+(30-50) to maximum Mana per Socket filled"""


@pytest.fixture(scope="module")
def checker():
    return ItemLegalityChecker(knowledge_dir())


@pytest.fixture
def configured(checker, monkeypatch):
    original = uniques.unique_raw
    monkeypatch.setattr(
        uniques,
        "unique_raw",
        lambda name, root=None: RAW if name == "Variant Armour" else original(name, root),
    )
    monkeypatch.setitem(
        checker._uniques,
        "variant armour",
        {
            "id": "item.native-pool-fixture",
            "type": "Item",
            "data": {
                "rarity": "unique",
                "category": "body",
                "base_type": "Grand Regalia",
                "explicits": ["100% increased Armour", "[1 Random Socket Modifier]"],
            },
        },
    )
    return "Rarity: UNIQUE\n" + RAW.replace("(40-60)", "60")


def test_only_selected_native_range_is_recognised(checker, configured):
    report = checker.check(configured)
    assert report.is_legal, report
    assert any(v.status == "CONDITIONAL" and "네이티브" in v.reason for v in report.verdicts)
    wrong = configured.replace("+60 to maximum Life", "+61 to maximum Life")
    assert not checker.check(wrong).is_legal


def test_unselected_and_duplicate_options_still_fail(checker, configured):
    assert not checker.check(configured + "\n+50 to maximum Mana per Socket filled").is_legal
    assert not checker.check(configured + "\n+60 to maximum Life per Socket filled").is_legal


def test_native_controls_and_base_cannot_be_spoofed(checker, configured):
    assert not checker.check(
        configured.replace("Selected Alt Variant: 2", "Selected Alt Variant: 99")
    ).is_legal
    assert not checker.check(configured.replace("Grand Regalia", "Plate Vest")).is_legal
    assert not checker.check(configured.replace("Variant: Life", "Variant: Invented")).is_legal
    assert not checker.check(
        configured.replace("Selected Variant: 1", "Selected Variant: 2")
    ).is_legal


def test_actual_prepared_multiselector_unique_uses_its_real_pool(checker):
    from pok.engine.runes import render_runed
    from pok.engine.unique_items import prepare_unique_item

    result = prepare_unique_item(
        "Morior Invictus",
        {
            "Selected Variant": "Current",
            "Selected Alt Variant": "Spirit",
            "Selected Alt Variant Two": "Life",
            "Selected Alt Variant Three": "Life Regeneration",
        },
        roll_policy="max",
    )
    if not result.get("ok"):
        pytest.skip("Pinned native catalogue unavailable")
    # Native catalogue templates can carry late socket declarations. Use the
    # existing renderer; this test must not bypass its independent ordering gate.
    text = render_runed(result["item_text"], [])
    report = checker.check(text)
    assert report.is_legal, report
    assert any(v.status == "CONDITIONAL" for v in report.verdicts)
    assert not checker.check(text + "\n+999 to Spirit per Socket filled").is_legal
