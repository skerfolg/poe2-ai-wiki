"""engine/legality — 실제 KB로 합성 아이템 검증 (RC4)."""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.legality import ItemLegalityChecker, _norm, _parse_item
from pok.pob.versions import resolve_snapshot


def _pob_snapshot_ready() -> bool:
    try:
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


# 프리즘 풀만 PoB 소스(external/pob 스냅샷)에서 읽는다 — CI엔 스냅샷이 없다.
# 나머지 검증은 KB만 쓰므로 모듈 전체가 아니라 해당 테스트에만 건다 (통합 테스트와 같은 관례).
needs_pob_snapshot = pytest.mark.skipif(
    not _pob_snapshot_ready(), reason="external/pob 스냅샷 없음 (프리즘 풀 = PoB 소스)"
)


@pytest.fixture(scope="module")
def checker() -> ItemLegalityChecker:
    return ItemLegalityChecker(knowledge_dir())


def test_정규화_키() -> None:
    assert _norm("Adds 1 to (2-3) Cold damage to Attacks") == _norm(
        "Adds 1 to 3 Cold damage to Attacks"
    )


def test_파서_레어() -> None:
    # 반환에 소켓 수·룬 효과가 추가됐다 (#31 — 룬 값 검증의 분모)
    rarity, base, ilvl, mods, sockets, rune_effect = _parse_item(
        "Rarity: RARE\n이름\nAltar Robe\nItem Level: 80\n+100 to maximum Life"
    )
    assert (rarity, base, ilvl, mods) == ("rare", "Altar Robe", 80, ["+100 to maximum Life"])
    assert (sockets, rune_effect) == (0, 0.0), "선언이 없으면 0 — 판정 보류의 근거"


def test_파서가_소켓과_룬효과를_읽는다() -> None:
    _, _, _, mods, sockets, rune_effect = _parse_item(
        "\n".join(
            [
                "Rarity: RARE",
                "이름",
                "Attuned Wand",
                "Item Level: 80",
                "Sockets: S S S",
                "200% increased effect of Socketed Runes",
            ]
        )
    )
    assert sockets == 3
    assert rune_effect == 200.0
    assert "Sockets: S S S" not in mods, "스펙 줄은 모드가 아니다 (#30)"


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


@needs_pob_snapshot
def test_프리즘_실존_스킬_젬만_통과(checker: ItemLegalityChecker) -> None:
    """Prism of Belief: +1~3 레벨 x 실존 스킬 젬(KB Skill ∩ PoB prism 풀)."""
    ok = checker.check(
        "Rarity: UNIQUE\nPrism of Belief\nDiamond\nItem Level: 80\n"
        "+3 to Level of all Spark Skills\nCorrupted"
    )
    assert ok.is_legal, ok
    assert any("KB Skill" in v.reason for v in ok.verdicts)


@needs_pob_snapshot
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


# ── 룬 부여 (2026-08-05 실측: 16줄 전부 UNKNOWN이었다) ────────────────


def test_룬_줄은_룬_풀에서_판정한다() -> None:
    """`origins:["rune"]`이 색인에서 빠져 있었고, 룬은 `texts`가 없고 `per_slot`을
    쓴다 — origin만 추가해도 색인이 비었다. 둘 다 고쳐야 잡힌다."""
    checker = ItemLegalityChecker(knowledge_dir())
    item = "\n".join(
        ["Rarity: RARE", "T", "Advanced Vaal Cuirass", "--------", "{rune}+9 to Dexterity"]
    )
    (verdict,) = checker.check(item).verdicts
    assert verdict.status == "LEGAL"
    assert verdict.modifier_id is not None and "rune" in verdict.modifier_id


def test_룬_접두가_없으면_일반_접사로_판정한다() -> None:
    """같은 문구라도 룬과 일반 접사는 다른 풀이다 — 접두를 무시하면 오판한다."""
    checker = ItemLegalityChecker(knowledge_dir())
    item = "\n".join(["Rarity: RARE", "T", "Advanced Vaal Cuirass", "--------", "+9 to Dexterity"])
    (verdict,) = checker.check(item).verdicts
    assert verdict.status != "LEGAL"  # 일반 접사 티어 범위로 걸린다


def test_룬_풀에_없는_문구는_UNKNOWN() -> None:
    checker = ItemLegalityChecker(knowledge_dir())
    item = "\n".join(
        ["Rarity: RARE", "T", "Advanced Vaal Cuirass", "--------", "{rune}존재하지 않는 효과"]
    )
    (verdict,) = checker.check(item).verdicts
    assert verdict.status == "UNKNOWN" and "룬 풀" in verdict.reason


def test_접두_없는_룬은_대안을_안내한다() -> None:
    """실측 2026-08-05: PoB 표기(`{rune}`)를 모르고 손으로 쓴 룬 문구가 일반 접사에
    매칭돼 "티어 범위 밖"으로 거부되고 접사 한도까지 잡아먹었다. 그 때문에 룬 17칸을
    조립본에서 빼야 했고 전달 PoB가 실제치를 과소평가했다(DPS -6.6%·EHP -6.9%)."""
    checker = ItemLegalityChecker(knowledge_dir())
    item = "\n".join(["Rarity: RARE", "T", "Advanced Vaal Cuirass", "--------", "+9 to Dexterity"])
    (verdict,) = checker.check(item).verdicts
    assert verdict.status == "CONDITIONAL"  # ILLEGAL이 아니다 — 룬으로는 가능하다
    assert verdict.modifier_id is not None and "rune" in verdict.modifier_id
    assert "룬으로는 가능" in verdict.reason and "{rune}" in verdict.reason


def test_룬_판정은_접사_한도를_먹지_않는다() -> None:
    """룬은 `affix_type="rune"`이라 접두·접미 계수에서 빠져야 한다."""
    checker = ItemLegalityChecker(knowledge_dir())
    lines = ["+9 to Dexterity"] * 4  # 접사였다면 접두 한도(3) 초과
    item = "\n".join(["Rarity: RARE", "T", "Advanced Vaal Cuirass", "--------", *lines])
    report = checker.check(item)
    assert not any("한도" in e for e in report.errors)


def test_affix_cap_error_hints_at_rune_prefix() -> None:
    """룬을 평문으로 적어 한도가 터졌으면 그렇게 말해 준다 (빌드 회차 2026-08-06 갭1).

    규약(`{rune}` 접두)을 모르면 오류가 "접미 4개 — 한도 3 초과"로만 보인다.
    실측: 세션이 원인을 못 찾아 룬 소켓 13칸 중 6칸을 비운 채 출고했다.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.legality import ItemLegalityChecker

    full = """Rarity: RARE
Test
Sacred Focus
Item Level: 80
Implicits: 0
82% increased Spell Damage
82% increased Lightning Damage
+157 to maximum Mana
30.5% increased Cast Speed
+2 to Level of all Spell Skills
56.5% increased Critical Hit Chance for Spells"""
    checker = ItemLegalityChecker(knowledge_dir())
    plain = checker.check(full + "\n+12% to Fire Resistance")
    assert not plain.is_legal
    assert any("{rune}" in e for e in plain.errors), "원인이 룬이라는 단서를 줘야 한다"
    tagged = checker.check(
        full + "\nSockets: S\nRune: Greater Body Rune\n{rune}+12% to Fire Resistance"
    )
    assert tagged.is_legal, "룬 표기하면 접사 칸 밖 — 한도에 안 걸린다"


def _wand(
    *mods: str, sockets: str = "S S S S S", extra: str = "", declare_runes: bool = True
) -> str:
    """완드 하나. `{rune}` 줄이 있으면 **선언도 함께** 낸다(그게 정상 표기다).

    실측 2026-08-09(`Greater Body Rune` 2개 · 룬 효과 +200%): `Sockets:`+`Rune:`+시드가
    **ES +300**, `Rune:`이 빠지면 +100(**3배 과소**), `Sockets:`가 빠지면 **+0**이다.
    `declare_runes=False`는 그 결함 자체를 시험할 때만 쓴다.
    """
    lines = ["Rarity: RARE", "Probe", "Attuned Wand", "Item Level: 80"]
    if declare_runes and any(m.lstrip().startswith("{rune}") for m in mods):
        lines += ["Rune: Greater Iron Rune"]
    if sockets:
        lines.append(f"Sockets: {sockets}")
    if extra:
        lines.append(extra)
    return "\n".join([*lines, *mods])


def test_pob_spec_lines_are_not_modifiers() -> None:
    """`Sockets:`·`Rune:`·`Radius:`·`Corrupted`는 **스펙 줄·표식**이지 모드가 아니다 (#30).

    모드로 판정하면 **정상 빌드가 비적법으로 찍히고**, 그러면 경고가 신호를 잃는다 —
    실측 2026-08-09: 진짜 실격 4건과 이 오탐 6건이 한 목록에 섞여 나왔다.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.legality import ItemLegalityChecker

    report = ItemLegalityChecker(knowledge_dir()).check(
        "\n".join(
            [
                "Rarity: RARE",
                "Probe",
                "Attuned Wand",
                "Item Level: 80",
                "Sockets: S S S S S",
                "Rune: Perfect Iron Rune",
                "Radius: Large",
                "Corrupted",
            ]
        )
    )
    assert report.is_legal, [v.reason for v in report.verdicts if v.status != "LEGAL"]


def test_rune_value_must_be_explained_by_sockets_and_effect() -> None:
    """룬 줄의 **수치**가 실제 룬 값으로 설명돼야 한다 (#31).

    문구가 룬 풀에 있는지만 보고 통과시켜 왔다. 실측 2026-08-09:
    `150% increased Spell Damage`(실제 룬 30%)가 **5배**인 채 통과했다 —
    일반 접사엔 티어 범위 검사가 있는데 **룬에만 없었다**.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.legality import ItemLegalityChecker

    chk = ItemLegalityChecker(knowledge_dir())
    # 소켓 5칸이면 같은 룬 5개까지가 정상 운용 — 상한 안이면 통과
    assert chk.check(_wand("{rune}150% increased Spell Damage")).is_legal
    # 설명 불가능한 값은 사유와 함께 거부
    bad = chk.check(_wand("{rune}900% increased Spell Damage"))
    assert not bad.is_legal
    assert any("설명되지 않는다" in v.reason for v in bad.verdicts if v.status == "ILLEGAL")
    # 아이템이 룬 효과를 올리면 상한도 오른다(유니크 `Runeseeker's Call` 계열)
    assert chk.check(
        _wand(
            "{rune}450% increased Spell Damage",
            extra="200% increased effect of Socketed Runes",
        )
    ).is_legal


def test_unknown_socket_count_withholds_judgement() -> None:
    """모르는 것을 위반이라 말하지 않는다 — 소켓 선언이 없으면 **값 판정을** 보류한다.

    ⚠ 보류하는 것은 값이지 **선언 누락 자체가 아니다.** 실측 2026-08-09: `Sockets:`가
    없으면 룬 줄이 통째로 빠져 Δ가 **0**이 된다 — 그건 모르는 게 아니라 아는 결함이다.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.legality import ItemLegalityChecker

    report = ItemLegalityChecker(knowledge_dir()).check(
        _wand("{rune}900% increased Spell Damage", sockets="")
    )
    assert not [v for v in report.verdicts if v.status == "ILLEGAL"], (
        "소켓 수를 모르면 상한을 계산할 수 없다"
    )
    assert any("Sockets:" in e for e in report.errors), "선언 누락은 구조 오류로 낸다"


def test_variant_lines_do_not_make_a_unique_illegal(checker: ItemLegalityChecker) -> None:
    """변형 선언은 **스펙 줄**이지 모드가 아니다 (백로그 #45, 2026-08-10).

    `_check_unique`가 자기만의 5개짜리 스펙 줄 목록을 들고 있어서 `_SPEC_LINE_PREFIXES`에
    `variant:`를 넣어 둔 것이 유니크 경로엔 적용되지 않았다 — 판정 주체가 둘이면
    어긋난다(§0 ④). `item.the-unborn-lich`는 변형 12종이라 **변형을 적어야** 어느 스킬을
    부여받는지 정해지는데, 적으면 비적법이 됐다(§0 ⑤).
    """
    head = "Rarity: UNIQUE\nThe Unborn Lich\nStellar Amulet\n"
    mod = "70% increased Desecrated Modifier magnitudes\n"
    plain = checker.check(head + "Item Level: 82\n" + mod)
    with_variant = checker.check(
        head + "Variant: His Winnowing Flame\nSelected Variant: 1\nItem Level: 82\n" + mod
    )
    assert plain.is_legal and with_variant.is_legal
    assert [(v.status, v.line) for v in plain.verdicts] == [
        (v.status, v.line) for v in with_variant.verdicts
    ], "변형 줄을 적었다고 판정이 달라지면 안 된다"
    # 반대 방향 — 스펙 줄을 건너뛴다고 진짜 모드까지 통과시키면 안 된다
    fake = checker.check(head + "Item Level: 82\n999% increased Nonsense\n")
    assert not fake.is_legal


def test_rune_conditional_shows_the_actual_rune_value(checker: ItemLegalityChecker) -> None:
    """ "룬으로는 가능"이 **「그 수치로 가능」**으로 읽혔다 (백로그 #56, 2026-08-10).

    매칭 키가 숫자를 죽인 정규화 텍스트라 `+40 to Intelligence`가 실제 `+12`인
    룬에 붙는다(3.3배). 보고자는 레코드를 따로 열어 보고서야 알았다 — §0 ①의 값 판본.
    """
    head = "Rarity: RARE\nX\nAttuned Wand\nItem Level: 80\n"
    over = checker.check(head + "+40 to Intelligence\n").verdicts[0]
    assert over.status == "CONDITIONAL" and over.modifier_id == "modifier.greater-resolve-rune"
    assert "12" in over.reason and "40" in over.reason, "실제 값과 선언값을 나란히 보여야 한다"
    assert "소켓 4칸" in over.reason, "몇 칸이 필요한지까지 줘야 고칠 수 있다"

    # 값이 맞으면 다르다고 말하지 않는다 — 경고가 소음이 되면 안 읽힌다
    same = checker.check(head + "+25 to all Attributes\n".replace("25", "5")).verdicts[0]
    assert "선언값과 같다" in same.reason


def test_rune_notation_is_accepted_on_uniques(checker: ItemLegalityChecker) -> None:
    """규약대로 `{rune}`을 적었더니 **유니크에서만** 거부됐다 (백로그 #56).

    일반 아이템 경로는 접두를 미리 벗기는데 유니크 경로는 원문을 넘겨서 키가
    어긋났다. 그 때문에 한 회차가 룬 4칸을 비워 뒀다 — #33이 그 축을 DPS +69.6%로
    재 뒀는데도. 금지하려면 대안 경로가 통해야 한다(철칙 5 따름정리).
    """
    text = (
        "Rarity: UNIQUE\nThe Unborn Lich\nStellar Amulet\nItem Level: 82\n"
        "Sockets: R\nRune: Greater Resolve Rune\n"
        "{rune}+12 to Intelligence\n70% increased Desecrated Modifier magnitudes\n"
    )
    report = checker.check(text)
    assert report.is_legal, [(v.status, v.line, v.reason) for v in report.verdicts]
    assert any(v.status == "CONDITIONAL" and "룬" in v.reason for v in report.verdicts)


def test_base_implicit_is_not_judged_as_an_affix(checker: ItemLegalityChecker) -> None:
    """베이스 임플리싯을 접사 풀에서 찾아 **자기 도구의 출력을 거부했다** (백로그 #57).

    `Invoking Belt`의 `Has 1 Charm Slot`은 KB 접사 표기(`+1 charm slot`)와 문구가
    달라 UNKNOWN으로 찍혔다. 그런데 그 줄은 `optimize_rare`가 자동 기재한 것이라
    조립의 **모든 시도**가 실격났고, 접사 0건 · `legal: False` · 사유 없음이 나왔다.
    정본은 베이스 레코드의 `data.implicit`이다.
    """
    head = "Rarity: RARE\nEngineered Belt\nInvoking Belt\nCharm Slots: 1\nImplicits: 1\n"
    # 명세 형식(범위 그대로)도, 롤된 값도 통과해야 한다
    for body in (
        "{range:0.5}(8-12)% increased Cast Speed\nHas 1 Charm Slot\n",
        "10% increased Cast Speed\nHas 1 Charm Slot\n",
    ):
        report = checker.check(head + body)
        assert report.is_legal, [(v.status, v.line, v.reason) for v in report.verdicts]
        assert all("임플리싯" in v.reason for v in report.verdicts)
    # 반대 방향 — 부풀린 임플리싯은 여전히 거부한다
    inflated = checker.check(head + "40% increased Cast Speed\nHas 1 Charm Slot\n")
    assert not inflated.is_legal
    assert any("임플리싯 범위 밖" in v.reason for v in inflated.verdicts)


def test_range_notation_does_not_crash_the_checker(checker: ItemLegalityChecker) -> None:
    """범위 표기 `(5-7)`이 검사기를 통째로 죽였다 (백로그 #56 수정의 회귀, 2026-08-10).

    `_NUM`이 `(a-b)`를 토큰 하나로 잡는데 그대로 `float()`에 넘겼다. 유니크·임플리싯
    텍스트에선 범위 표기가 **정상 형태**라 흔하고, 경로가
    `compute_pob → _items_legal → check`이라 **모든 측정이 같이 죽었다.**
    """
    text = "Rarity: RARE\nX\nStellar Amulet\nItem Level: 80\n{range:0.5}+(5-7) to all Attributes\n"
    report = checker.check(text)  # 터지지 않는 것 자체가 이 테스트의 핵심
    assert report.is_legal


def test_a_broken_note_never_kills_the_verdict() -> None:
    """사유에 덧붙이는 **참고 문구**의 실패는 참고 문구만 잃어야 한다 (§0 ⑤).

    원인(범위 표기)은 고쳤지만 구조가 틀렸다 — 부가 정보가 판정을 죽이면 안 된다.
    """
    from pok.engine.legality import _rune_value_note

    assert _rune_value_note("+(a-b) to X", {"data": {"per_slot": None}}) == ""
    assert _rune_value_note("+40 to Intelligence", {"data": None}) == ""


def test_decorated_rune_line_matches_on_uniques(checker: ItemLegalityChecker) -> None:
    """`{rune}`만 벗기고 `{range:…}`는 안 벗겨 유니크에서 여전히 UNKNOWN이 났다."""
    text = (
        "Rarity: UNIQUE\nThe Unborn Lich\nStellar Amulet\nItem Level: 82\n"
        "{range:0.5}+(10-15) to Intelligence\n70% increased Desecrated Modifier magnitudes\n"
    )
    report = checker.check(text)
    assert report.is_legal, [(v.status, v.line) for v in report.verdicts]


def test_declaration_form_is_judged_like_plain_text(checker: ItemLegalityChecker) -> None:
    """선언형이 **검사에서 통째로 빠져 있었다** (백로그 #60, 2026-08-11).

    `Prefix: {range:0.5}IncreasedLife10` 꼴은 스펙 줄이라 모드 판정을 건너뛰는데,
    그러면 매칭되는 모드가 하나도 없어 접사 수·group 배타가 **전부 공회전**한다.
    같은 목걸이가 평문형에선 한도 초과로 걸리고 선언형에선 판정 0건에 `legal: True`
    였다. #34 이후 `optimize_rare`가 내는 것이 이 형식이라, 아이템 게이트가
    **자기 도구의 출력에 대해 무력**했다.
    """
    head = "Rarity: RARE\nX\nStellar Amulet\nCrafted: true\n"
    over = checker.check(
        head
        + "Suffix: {range:0.5}GlobalSpellGemsLevel3\n"
        + "Suffix: {range:0.5}GlobalProjectileSkillGemLevel3\n"
        + "Suffix: {range:0.5}Intelligence9\nSuffix: {range:0.5}Dexterity9\n"
        + "Prefix: {range:0.5}IncreasedLife10\nPrefix: None\nLevelReq: 80\n"
    )
    assert not over.is_legal
    assert any("한도 3 초과" in e for e in over.errors), over.errors
    assert len(over.verdicts) == 5, "빈 칸(`Prefix: None`)은 세지 않는다"

    # 한도 안이면 통과한다 — 게이트가 정상을 막으면 안 된다(§0 ⑤)
    ok = checker.check(
        head
        + "Suffix: {range:0.5}Intelligence9\n"
        + "Prefix: {range:0.5}IncreasedLife10\nLevelReq: 80\n"
    )
    assert ok.is_legal, (ok.errors, [(v.status, v.line) for v in ok.verdicts])

    # 모르는 키는 조용히 넘기지 않는다
    unknown = checker.check(head + "Suffix: {range:0.5}NotARealModKey\n")
    assert any(v.status == "UNKNOWN" for v in unknown.verdicts)


def test_skill_level_suffixes_are_mutually_exclusive(checker: ItemLegalityChecker) -> None:
    """group이 달라도 배타인 계열 (백로그 #59, 사용자 판정 2026-08-11).

    「+N to Level of all … Skills」는 poe2db에서 대상별로 group이 나뉘어 있어
    (`GlobalIncreaseSpellSkillGemLevel` vs `…ProjectileSkillGemLevel`) group 배타로는
    안 잡혔다 — 37 group·188 모드짜리 계열이다. 규칙은 하드코딩이 아니라 판 규칙
    정본(`board-rules.json::family_exclusion`)에 있다.
    """
    head = "Rarity: RARE\nX\nStellar Amulet\nItem Level: 80\n"
    both = checker.check(
        head + "+3 to Level of all Spell Skills\n+3 to Level of all Projectile Skills\n"
    )
    assert not both.is_legal
    assert any("계열 배타" in e for e in both.errors), both.errors

    # 선언형에서도 같이 잡혀야 한다 — 두 형식의 강도가 갈리면 그게 #60이었다
    declared = checker.check(
        "Rarity: RARE\nX\nStellar Amulet\nCrafted: true\n"
        "Suffix: {range:0.5}GlobalSpellGemsLevel3\n"
        "Suffix: {range:0.5}GlobalProjectileSkillGemLevel3\nLevelReq: 80\n"
    )
    assert any("계열 배타" in e for e in declared.errors), declared.errors

    # 하나만이면 통과 · 무관한 접미와의 공존도 통과 (§0 ⑤)
    assert checker.check(head + "+3 to Level of all Spell Skills\n").is_legal
    assert checker.check(head + "+3 to Level of all Spell Skills\n+35 to Dexterity\n").is_legal


def test_촉매로_넓힌_거부는_촉매라고_말한다(checker: ItemLegalityChecker) -> None:
    """상한을 넓히는 이유가 접미어 효과만이 아니다 (#116 곁가지).

    촉매로 상한을 넓혔는데 사유에 「접미어 효과 확장 포함」이라고 적히면 사용자가
    엉뚱한 곳을 본다 — **거짓 거부보다 「어디를 봐야 하는지」를 잘못 알려주는 것이
    더 비싸다**. 촉매 분기는 `#34` 때부터 실제로 발동하고 있었고, 틀린 것은 라벨이었다.
    """
    text = (
        "Rarity: Rare\nTest Amulet\nStellar Amulet\nItem Level: 82\n"
        "Catalyst: reaver\nCatalystQuality: 20\n"
        "+4 to Level of all Melee Skills\n"
    )
    reason = checker.check(text).verdicts[0].reason
    assert "촉매 reaver 20%" in reason, "상한을 넓힌 주체가 사유에 있어야 한다"
    assert "접미어 효과 확장" not in reason, "촉매인데 접미어 효과라고 말하면 안 된다"
