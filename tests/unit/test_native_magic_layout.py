"""Native MAGIC name/base layout must not turn an ilvl header into a base."""

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.legality import ItemLegalityChecker, _parse_item


@pytest.fixture(scope="module")
def checker():
    return ItemLegalityChecker(knowledge_dir())


def native_text(name="Ultimate Mana Flask", level=83, recovered=80):
    return (
        f"Rarity: MAGIC\n{name}\nItem Level: {level}\nQuality: +20%\n"
        f"{recovered}% increased Amount Recovered\nGains 0.25 Charges per Second"
    )


@pytest.mark.parametrize("base", ["Ultimate Mana Flask", "Ultimate Life Flask"])
def test_native_magic_base_on_name_line_keeps_level_and_affixes(checker, base):
    report = checker.check(native_text(base))
    assert report.is_legal, report
    assert report.affix_inventory["used"] == {"prefix": 1, "suffix": 1}
    assert report.affix_inventory["total_capacity"] == 2


def test_prefixed_magic_name_resolves_real_base_without_fabricating_stats(checker):
    report = checker.check(native_text("Saturated Ultimate Mana Flask of the Wellspring"))
    assert report.is_legal, report
    assert len(report.verdicts) == 2


def test_legacy_magic_separate_name_and_base_still_works(checker):
    text = native_text().replace("Rarity: MAGIC\n", "Rarity: MAGIC\nRegression\n")
    assert checker.check(text).is_legal
    assert _parse_item(text)[1] == "Ultimate Mana Flask"


@pytest.mark.parametrize("change", ["level", "range", "wrong_pool", "duplicate", "unknown"])
def test_native_layout_does_not_waive_legality(checker, change):
    text = native_text()
    if change == "level":
        text = native_text(level=1)
    elif change == "range":
        text = native_text(recovered=999)
    elif change == "wrong_pool":
        text = text.replace("Ultimate Mana Flask", "Amber Amulet")
    elif change == "duplicate":
        text += "\nGains 0.2 Charges per Second"
    else:
        text = text.replace("Ultimate Mana Flask", "Nonexistent Pok Flask")
    assert not checker.check(text).is_legal
