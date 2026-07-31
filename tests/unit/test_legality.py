"""engine/legality — 실제 KB로 합성 아이템 검증 (RC4)."""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.legality import ItemLegalityChecker, _norm, _parse_item


@pytest.fixture(scope="module")
def checker() -> ItemLegalityChecker:
    return ItemLegalityChecker(knowledge_dir())


def test_정규화_키() -> None:
    assert _norm("Adds 1 to (2-3) Cold damage to Attacks") == _norm(
        "Adds 1 to 3 Cold damage to Attacks"
    )


def test_파서_레어() -> None:
    rarity, base, ilvl, mods = _parse_item(
        "Rarity: RARE\n이름\nAltar Robe\nItem Level: 80\n+100 to maximum Life"
    )
    assert (rarity, base, ilvl, mods) == ("rare", "Altar Robe", 80, ["+100 to maximum Life"])


def test_실존_모드는_통과한다(checker: ItemLegalityChecker) -> None:
    # AddedColdDamage1 (Frosted): ring/gloves/quiver weight 1, ilvl 1
    report = checker.check(
        "Rarity: RARE\nPok Ring\nIron Ring\nItem Level: 80\nAdds 1 to 3 Cold damage to Attacks"
    )
    assert report.verdicts[0].status in ("LEGAL", "CONDITIONAL"), report
    assert report.is_legal


def test_없는_모드는_UNKNOWN(checker: ItemLegalityChecker) -> None:
    report = checker.check(
        "Rarity: RARE\nPok Ring\nIron Ring\nItem Level: 80\n+999% to Pok Resistance"
    )
    assert report.verdicts[0].status == "UNKNOWN"
    assert not report.is_legal


def test_티어_범위_밖_수치는_거부(checker: ItemLegalityChecker) -> None:
    report = checker.check(
        "Rarity: RARE\nPok Ring\nIron Ring\nItem Level: 80\nAdds 500 to 900 Cold damage to Attacks"
    )
    assert report.verdicts[0].status in ("ILLEGAL", "UNKNOWN")
    assert not report.is_legal


def _jewel(*mods: str) -> str:
    return "Rarity: RARE\nPok Jewel\nSapphire\nItem Level: 81\n" + "\n".join(mods)


# KB jewel-01.ndjson 실존 모드 (전부 최대 롤 — 티어 범위 검사도 함께 통과해야 한다)
_PRE_SPELL = "15% increased Spell Damage"  # prefix, WeaponSpellDamage
_PRE_TRIGGER = "Triggered Spells deal 18% increased Spell Damage"  # prefix
_PRE_SUFFIX_EFFECT = "60% increased Effect of Suffixes"  # prefix (liquid 경로 — CONDITIONAL)
_SUF_SPELL_CRIT = "15% increased Critical Hit Chance for Spells"  # suffix
_SUF_SPELL_CRIT_DMG = "20% increased Critical Spell Damage Bonus"  # suffix
_SUF_ATK_CRIT_DMG = "20% increased Critical Damage Bonus for Attack Damage"  # suffix
_SUF_CRIT = "15% increased Critical Hit Chance"  # suffix, CriticalStrikeChance


def test_주얼_기본_한도_2_2는_통과(checker: ItemLegalityChecker) -> None:
    report = checker.check(_jewel(_PRE_SPELL, _PRE_TRIGGER, _SUF_SPELL_CRIT, _SUF_SPELL_CRIT_DMG))
    assert report.is_legal, report


def test_주얼_시즌_5줄_2접두_3접미는_통과(checker: ItemLegalityChecker) -> None:
    """0.5 season_override — 총 5모드, 3접미/2접두 (crafting-rules/board-rules.json)."""
    report = checker.check(
        _jewel(
            _PRE_SPELL,
            _PRE_SUFFIX_EFFECT,
            _SUF_SPELL_CRIT,
            _SUF_SPELL_CRIT_DMG,
            _SUF_ATK_CRIT_DMG,
        )
    )
    assert report.is_legal, report


def test_주얼_3접두_3접미는_거부(checker: ItemLegalityChecker) -> None:
    """override는 총 5모드까지 — 3/3(총 6)은 불허."""
    report = checker.check(
        _jewel(
            _PRE_SPELL,
            _PRE_TRIGGER,
            _PRE_SUFFIX_EFFECT,
            _SUF_SPELL_CRIT,
            _SUF_SPELL_CRIT_DMG,
            _SUF_ATK_CRIT_DMG,
        )
    )
    assert not report.is_legal
    assert any("총한도" in e for e in report.errors), report.errors


def test_주얼_4접미는_거부(checker: ItemLegalityChecker) -> None:
    report = checker.check(
        _jewel(_SUF_SPELL_CRIT, _SUF_SPELL_CRIT_DMG, _SUF_ATK_CRIT_DMG, _SUF_CRIT)
    )
    assert not report.is_legal
    assert any("suffix 4개" in e for e in report.errors), report.errors


def test_장비는_여전히_3_3_한도(checker: ItemLegalityChecker) -> None:
    limits, total, label = checker._affix_limits("rare", None)
    assert (limits["prefix"], limits["suffix"], total) == (3, 3, 6)
    assert label == "equipment rare"
    # 주얼 magic엔 카테고리 캡이 없다 — equipment magic 1/1로 폴백, override 미적용
    limits, total, _ = checker._affix_limits("magic", "jewel")
    assert (limits["prefix"], limits["suffix"], total) == (1, 1, 2)


def test_유니크는_KB_실존과_롤_범위로_판정(checker: ItemLegalityChecker) -> None:
    report = checker.check(
        "Rarity: UNIQUE\nLiminal Coil\nTwisted Wand\nItem Level: 80\n"
        "113% increased Spell Damage\n"
        "Curses you inflict ignore Curse limit\n"
        "Spell Hits Gain 31% of Damage as Extra Chaos Damage per Curse on target"
    )
    assert report.is_legal, report
    report2 = checker.check(
        "Rarity: UNIQUE\nLiminal Coil\nTwisted Wand\nItem Level: 80\n"
        "500% increased Spell Damage"  # 롤 범위(71-113) 밖
    )
    assert not report2.is_legal
    report3 = checker.check("Rarity: UNIQUE\n존재하지 않는 유니크\nTwisted Wand")
    assert not report3.is_legal


def test_열거_펼치기() -> None:
    from pok.engine.legality import _expand_enum

    assert _expand_enum("Allocates (2/3/4) Sinister Jewel sockets") == [
        "Allocates 2 Sinister Jewel sockets",
        "Allocates 3 Sinister Jewel sockets",
        "Allocates 4 Sinister Jewel sockets",
    ]
    # 범위 "(a-b)"는 열거가 아니다 — 원문 그대로
    assert _expand_enum("(0-150)% increased Effect") == ["(0-150)% increased Effect"]


def test_유니크_주얼_롤_변형은_열거_대조로_판정(checker: ItemLegalityChecker) -> None:
    """KB 고유 주얼의 "(A/B/C)" 열거(jewel_fixes 규약) ↔ 실물 한 롤 대조."""
    ok = checker.check(
        "Rarity: UNIQUE\nVoices\nSapphire\nItem Level: 80\n"
        "Allocates 3 Sinister Jewel sockets\nCorrupted"
    )
    assert ok.is_legal, ok
    bad = checker.check(
        "Rarity: UNIQUE\nVoices\nSapphire\nItem Level: 80\n"
        "Allocates 5 Sinister Jewel sockets"  # 2/3/4 밖
    )
    assert not bad.is_legal
    cls = checker.check(
        "Rarity: UNIQUE\nSplit Personality\nRuby\nItem Level: 80\n"
        "Can Allocate Passive Skills from the Sorceress's starting point\nCorrupted"
    )
    assert cls.is_legal, cls


def test_유니크_그랜드_스펙트럼_동명_3종_모두_대조된다(checker: ItemLegalityChecker) -> None:
    for line in (
        "2% increased Maximum Life per socketed Grand Spectrum",
        "+6% to all Elemental Resistances per socketed Grand Spectrum",
    ):
        report = checker.check(f"Rarity: UNIQUE\nGrand Spectrum\nRuby\nItem Level: 80\n{line}")
        assert report.is_legal, report
