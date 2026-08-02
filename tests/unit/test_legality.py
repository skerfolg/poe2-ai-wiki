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
    # Diamond = 전 속성 태그(str/dex/int) 주얼 — 민첩 계열 접미(_SUF_ATK_CRIT_DMG)까지
    # 실제로 롤 가능한 베이스. (#34 이전엔 Sapphire였으나, 그 조합은 poe2db:normal
    # CONDITIONAL 탈출 버그가 가려주던 불법 조합이었다)
    return "Rarity: RARE\nPok Jewel\nDiamond\nItem Level: 81\n" + "\n".join(mods)


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


def test_접미어_효과_선반영_상한_확장(checker: ItemLegalityChecker) -> None:
    """접미어 효과 60% 접두가 있으면 접미 수치는 최종 표시값(티어x1.6)까지 허용.

    근거 실측(2026-07-31): PoB는 효과 줄을 계산하지 않는다 — 효과 줄 유무 DPS 동일
    51,792.2, 접미 수치 1.6배 수동 반영 시 59,000.7. 선반영이 정직한 모델링."""
    report = checker.check(
        _jewel(
            _PRE_SUFFIX_EFFECT,  # 60% increased Effect of Suffixes (접두 — 정상 검사)
            "40% increased Chill Duration on Enemies",  # 주얼 전용 접미, 25(상한) x 1.6
            "32% increased Critical Spell Damage Bonus",  # 주얼 티어 20 x 1.6
        )
    )
    assert report.is_legal, report
    expanded = [v for v in report.verdicts if "접미어 효과 60% 반영 상한" in v.reason]
    assert len(expanded) >= 1, report.verdicts


def test_접미어_효과_상한_초과는_거부(checker: ItemLegalityChecker) -> None:
    report = checker.check(
        _jewel(_PRE_SUFFIX_EFFECT, "41% increased Chill Duration on Enemies")  # > 25x1.6
    )
    assert not report.is_legal, report


def test_접미어_효과_줄_없으면_기존_범위(checker: ItemLegalityChecker) -> None:
    report = checker.check(_jewel("40% increased Chill Duration on Enemies"))  # 기존 상한 25
    assert not report.is_legal, report


def test_링_전용_모드는_주얼에서_거부(checker: ItemLegalityChecker) -> None:
    """#34 회귀: 클래스 타깃(ring/gloves/quiver) 밖 베이스는 경로 표지(poe2db:normal)로
    CONDITIONAL 탈출 금지 — poe2db:normal은 크래프팅 동치 표지다."""
    report = checker.check(_jewel("Adds 1 to 3 Cold damage to Attacks"))
    assert report.verdicts[0].status == "ILLEGAL", report.verdicts
    assert not report.is_legal


def test_주얼_liquid_경로는_CONDITIONAL_유지(checker: ItemLegalityChecker) -> None:
    """#34 반례 보존: liquid 주얼 모드는 spawn_weights {"jewel": 0}로 클래스 호환이
    명시돼 있다(C-2 "weight 0 ≠ 죽은 모드") — 베이스 적합성 검사 후에도 CONDITIONAL."""
    report = checker.check(_jewel(_PRE_SUFFIX_EFFECT))
    v = report.verdicts[0]
    assert v.status == "CONDITIONAL" and "poe2db:liquid" in v.reason, v


def test_경로_베이스_적합성_pages_scope(checker: ItemLegalityChecker) -> None:
    """#34: 훼손 모드처럼 spawn_weights가 없는 레코드는 applicable_pages·scope로 판정."""
    from pok.engine.legality import _route_base_fit

    belt = checker._bases["heavy belt"]
    jewel = checker._bases["sapphire"]
    desecrated = {
        "affix_type": "prefix",
        "scope": "equipment",
        "acquisition": ["desecration"],
        "applicable_pages": ["Belts"],
    }
    assert _route_base_fit(desecrated, belt) == (True, "")
    fit, why = _route_base_fit(desecrated, jewel)
    assert not fit and "applicable_pages" in why, (fit, why)
    scoped = {"scope": "jewel", "acquisition": ["desecration"]}
    assert _route_base_fit(scoped, jewel) == (True, "")
    fit, why = _route_base_fit(scoped, belt)
    assert not fit and "scope" in why, (fit, why)
    # 신호가 전혀 없으면 반증 불가 — 적용 가능 취급(CONDITIONAL 유지)
    assert _route_base_fit({"acquisition": ["poe2db:liquid"]}, jewel) == (True, "")


def test_UNKNOWN은_표기_확인_후보를_제시(checker: ItemLegalityChecker) -> None:
    """B-1 실증(2026-08-02): 정본은 '+N to Spirit'인데 '+N to maximum Spirit'으로
    조회해 UNKNOWN → KB 갭으로 오진됐다. 근접 후보 제시로 오진을 구조적으로 차단."""
    armour = "Rarity: RARE\nPok Armour\nAltar Robe\nItem Level: 82\n"
    wrong = checker.check(armour + "+52 to maximum Spirit").verdicts[0]
    assert wrong.status == "UNKNOWN"
    assert "표기 확인 후보" in wrong.reason and "to spirit" in wrong.reason
    # 정본 표기는 정상 통과 — KB에 실재한다는 증거
    right = checker.check(armour + "+52 to Spirit").verdicts[0]
    assert right.status == "LEGAL" and right.modifier_id is not None
    # 진짜 미수록은 후보 없음으로 구분된다
    absent = checker.check(armour + "+999% to Pok Resistance").verdicts[0]
    assert absent.status == "UNKNOWN" and "근접 후보 없음" in absent.reason


def test_훼손_모드는_합성_검증_풀에_포함(checker: ItemLegalityChecker) -> None:
    """훼손(desecrated) origins도 검증 풀 포함(사용자 지시 2026-07-31) —
    spawn_weights가 없어 applicable_pages/scope로 베이스 적합성을 판정한다.
    원문 "(10-18) % chance…"의 % 앞 공백은 _norm 공백 정규화로 흡수."""
    line = "14% chance for Charms you use to not consume Charges"  # Belts, ilvl 65
    ok = checker.check(f"Rarity: RARE\nPok Belt\nHeavy Belt\nItem Level: 81\n{line}")
    v = ok.verdicts[0]
    assert v.status == "CONDITIONAL" and "desecration" in v.reason, v
    wrong_base = checker.check(f"Rarity: RARE\nPok Jewel\nDiamond\nItem Level: 81\n{line}")
    assert wrong_base.verdicts[0].status == "ILLEGAL", wrong_base.verdicts
    low_ilvl = checker.check(f"Rarity: RARE\nPok Belt\nHeavy Belt\nItem Level: 60\n{line}")
    assert low_ilvl.verdicts[0].status == "ILLEGAL", low_ilvl.verdicts


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
    """KB 고유 주얼의 "(A/B/C)" 열거(unique_fixes 규약) ↔ 실물 한 롤 대조."""
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


def test_프리즘_실존_스킬_젬만_통과(checker: ItemLegalityChecker) -> None:
    """Prism of Belief: +1~3 레벨 x 실존 스킬 젬(KB Skill ∩ PoB prism 풀)."""
    ok = checker.check(
        "Rarity: UNIQUE\nPrism of Belief\nDiamond\nItem Level: 80\n"
        "+3 to Level of all Spark Skills\nCorrupted"
    )
    assert ok.is_legal, ok
    assert any("KB Skill" in v.reason for v in ok.verdicts)


def test_프리즘_롤_범위와_풀_제외_거부(checker: ItemLegalityChecker) -> None:
    over = checker.check(
        "Rarity: UNIQUE\nPrism of Belief\nDiamond\nItem Level: 80\n"
        "+4 to Level of all Spark Skills\nCorrupted"
    )
    assert not over.is_legal, over
    # 무기 부여(fromItem) 스킬 — PoB Generated.lua 제외 규칙 반영 (예: Bow Shot)
    from_item = checker.check(
        "Rarity: UNIQUE\nPrism of Belief\nDiamond\nItem Level: 80\n"
        "+2 to Level of all Bow Shot Skills\nCorrupted"
    )
    assert not from_item.is_legal, from_item
    assert any("prism 풀 밖" in v.reason for v in from_item.verdicts)
    fake = checker.check(
        "Rarity: UNIQUE\nPrism of Belief\nDiamond\nItem Level: 80\n"
        "+2 to Level of all Pok Nonexistent Skills\nCorrupted"
    )
    assert not fake.is_legal, fake


def test_과대망상_실존_recipe_노터블_2_3개(checker: ItemLegalityChecker) -> None:
    """Megalomaniac: 실존 노터블(recipe 보유) 2~3줄 — 조달 가정을 CONDITIONAL로 기록."""
    ok = checker.check(
        "Rarity: UNIQUE\nMegalomaniac\nDiamond\nItem Level: 80\n"
        "Allocates Controlling Magic\nAllocates Shredding Force\nCorrupted"
    )
    assert ok.is_legal, ok
    conds = [v for v in ok.verdicts if v.status == "CONDITIONAL"]
    assert len(conds) == 2 and all("조달 가정" in v.reason for v in conds), ok.verdicts


def test_과대망상_풀_밖_거부(checker: ItemLegalityChecker) -> None:
    fake = checker.check(
        "Rarity: UNIQUE\nMegalomaniac\nDiamond\nItem Level: 80\n"
        "Allocates Pok Fake Notable\nAllocates Controlling Magic\nCorrupted"
    )
    assert not fake.is_legal, fake
    one = checker.check(
        "Rarity: UNIQUE\nMegalomaniac\nDiamond\nItem Level: 80\n"
        "Allocates Controlling Magic\nCorrupted"
    )
    assert not one.is_legal and any("2~3개" in e for e in one.errors), one


def _heart(*mods: str) -> str:
    return "Rarity: UNIQUE\nHeart of the Well\nDiamond\nItem Level: 80\n" + "\n".join(mods)


def test_우물의_심장_훼손_풀_선택_2_2_통과(checker: ItemLegalityChecker) -> None:
    """Heart of the Well: ModVeiled UniqueHeart* 풀에서 접두 2·접미 2 선택."""
    report = checker.check(
        _heart(
            "Gain 13% of Damage as Extra Chaos Damage",  # prefix (7-13)
            "Gain 15% of Damage as Extra Lightning Damage",  # prefix (9-15)
            "8% increased Critical Hit Chance",  # suffix (4-8)
            "12% increased Critical Damage Bonus",  # suffix (6-12)
        )
    )
    assert report.is_legal, report


def test_우물의_심장_범위_밖과_풀_밖_거부(checker: ItemLegalityChecker) -> None:
    over = checker.check(_heart("Gain 16% of Damage as Extra Chaos Damage"))  # > 13
    assert not over.is_legal, over
    fake = checker.check(_heart("+999% to Pok Resistance"))
    assert not fake.is_legal and fake.verdicts[0].status == "UNKNOWN", fake


def test_우물의_심장_접두_3개는_거부(checker: ItemLegalityChecker) -> None:
    report = checker.check(
        _heart(
            "Gain 13% of Damage as Extra Chaos Damage",
            "Gain 15% of Damage as Extra Lightning Damage",
            "Gain 15% of Damage as Extra Fire Damage",
        )
    )
    assert not report.is_legal and any("한도 2 초과" in e for e in report.errors), report


def test_우물의_심장_weight0_거부(checker: ItemLegalityChecker) -> None:
    # UniqueHeartPrefixPercentOfLeechIsInstant — weightVal {0,0} (스폰 불가)
    report = checker.check(_heart("10% of Leech is Instant"))
    assert not report.is_legal, report
    assert any("weight 0" in v.reason for v in report.verdicts), report.verdicts


def test_유니크_그랜드_스펙트럼은_Ruby만_실존(checker: ItemLegalityChecker) -> None:
    """사용자 인게임 판정(2026-07-31): 현 시즌 Ruby만 실존 — Emerald/Sapphire 빈값."""
    ok = checker.check(
        "Rarity: UNIQUE\nGrand Spectrum\nRuby\nItem Level: 80\n"
        "2% increased Maximum Life per socketed Grand Spectrum"
    )
    assert ok.is_legal, ok
    for line in (
        "2% increased Spirit per socketed Grand Spectrum",
        "+6% to all Elemental Resistances per socketed Grand Spectrum",
    ):
        report = checker.check(f"Rarity: UNIQUE\nGrand Spectrum\nRuby\nItem Level: 80\n{line}")
        assert not report.is_legal, report
