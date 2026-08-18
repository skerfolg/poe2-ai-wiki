"""반경 주얼 표기 — `Radius:` 선언이 없으면 조용히 0 (백로그 제안 B).

발의는 *"PoB `ModParser`에 패턴이 없어 파싱되지 않는다"*로 봤는데 **패턴은 있다**
(`ModParser.lua:7041`). 진짜 원인은 **우리가 반경을 선언하지 않은 것**이다.

실측 2026-08-09 (`Time-Lost Diamond`, 반경 내 할당 노터블 6개):

    반경 선언 없음          CritChance 10.44 (= 주얼 없음과 동일, Δ0)
    Radius: Small                     12.24
    Radius: Very Large                15.84

반경이 커질수록 값이 오른다 — PoB는 정상 계산한다. 그래서 "서로 다른 소켓의 델타가
동일"이라는 증상이 나왔다: 어느 소켓이든 0이었던 것이다. 룬(#33)과 같은 계열이다.
"""

from __future__ import annotations

import pytest

from pok.engine.jewels import (
    RADIUS_LABELS,
    declared_radius,
    effective_radius,
    needs_radius_declaration,
    radius_index,
    render_radius_jewel,
)

_GRANT = "Notable Passive Skills in Radius also grant 10% increased Critical Hit Chance for Spells"
_BASE = f"Rarity: RARE\nProbe\nTime-Lost Diamond\nItem Level: 80\n{_GRANT}"


def test_missing_declaration_is_detected() -> None:
    """이게 **조용한 0**의 조건이다 — 오류가 아니라 과소 계상이라 아무도 모른다."""
    assert needs_radius_declaration(_BASE)
    assert declared_radius(_BASE) is None


def test_declaration_clears_it() -> None:
    declared = render_radius_jewel(_BASE, "Very Large")
    assert declared_radius(declared) == "Very Large"
    assert not needs_radius_declaration(declared)


def test_plain_jewel_is_not_flagged() -> None:
    """반경 부여 줄이 없으면 선언도 필요 없다 — 없는 경고를 만들지 않는다."""
    plain = "Rarity: RARE\nProbe\nDiamond\nItem Level: 80\n10% increased Critical Hit Chance"
    assert not needs_radius_declaration(plain)


def test_engine_does_not_guess_the_radius() -> None:
    """반경은 아이템이 정하는 값이라 **엔진이 지어내지 않는다**."""
    with pytest.raises(ValueError, match="모르는 반경 라벨"):
        render_radius_jewel(_BASE, "Massive")
    assert RADIUS_LABELS == ("Small", "Medium", "Large", "Very Large")


def test_declaration_replaces_not_duplicates() -> None:
    """두 줄이 남으면 PoB가 뒤엣것만 읽는다 — 갈아 끼운다."""
    once = render_radius_jewel(_BASE, "Small")
    twice = render_radius_jewel(once, "Large")
    assert twice.count("Radius:") == 1
    assert declared_radius(twice) == "Large"


def test_checker_reports_the_silent_zero() -> None:
    """검사기가 이 누락을 **구조 오류로** 낸다 — 줄 판정이 아니라 아이템 판정이다."""
    from pok.common.paths import knowledge_dir
    from pok.engine.legality import ItemLegalityChecker

    checker = ItemLegalityChecker(knowledge_dir())
    assert any("Radius:" in e for e in checker.check(_BASE).errors)
    assert not checker.check(render_radius_jewel(_BASE, "Large")).errors


# ── 어느 링인가 (BACKLOG #71) ──
#
# `Radius:` 라벨만 보면 틀린다. 실제 링은 **모드 문구**가 정한다(PoB ModParser).

_CTRL_META = (
    "Rarity: UNIQUE\nControlled Metamorphosis\nDiamond\nRadius: Variable\n"
    "Only affects Passives in Massive Ring\n"
    "Passives in Radius can be Allocated without being connected to your tree"
)
_TINY_RING = (
    "Rarity: RARE\n작은 링\nRuby\nRadius: Variable\nOnly affects Passives in Very Small Ring"
)
_TIME_LOST = (
    "Rarity: UNIQUE\nAgainst the Darkness\nTime-Lost Diamond\nRadius: Small\n"
    "Notable Passive Skills in Radius also grant Gain 5% of Damage as Extra Fire Damage"
)
_UPGRADED = _TIME_LOST + "\nUpgrades Radius to Very Large"


def test_링_지목이_라벨을_이긴다() -> None:
    """`Radius: Variable`은 표시용이다 — 실제 링은 "Massive Ring"이 정한다."""
    assert radius_index(_CTRL_META) == 12
    assert effective_radius(_CTRL_META) == (2160.0, 2520.0)


def test_긴_이름을_먼저_본다() -> None:
    """ "very small"이 "small"에 먹히면 8배 큰 링으로 잰다."""
    assert radius_index(_TINY_RING) == 5
    assert effective_radius(_TINY_RING) == (780.0, 1140.0)


def test_반경_승급이_라벨을_덮는다() -> None:
    """Time-Lost 계열은 부여 문구로 반경이 오른다 — 라벨만 보면 과소 계상이다."""
    assert effective_radius(_TIME_LOST) == (0.0, 1200.0)
    assert effective_radius(_UPGRADED) == (0.0, 1800.0)


def test_선언이_없으면_None() -> None:
    """⛔ 추측하지 않는다 — 모르면 모른다고 한다(이 모듈의 존재 이유)."""
    assert effective_radius("Rarity: RARE\n이름\nRuby\n+10 to Strength") is None


def test_도넛은_안쪽을_안_덮는다() -> None:
    """Variable 링 8개는 전부 도넛이다 — inner를 버리면 과대평가한다(#71)."""
    from pok.engine.tree.clusters import JEWEL_RADIUS_BY_INDEX

    assert len(JEWEL_RADIUS_BY_INDEX) == 12, "PoB Data.lua는 12개다"
    assert all(inner == 0 for inner, _ in list(JEWEL_RADIUS_BY_INDEX.values())[:4]), "1~4는 원"
    assert all(inner > 0 for inner, _ in list(JEWEL_RADIUS_BY_INDEX.values())[4:]), "5~12는 도넛"
