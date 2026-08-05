"""곱연산 축 장부 — "가산 한 항만 키우고 있지 않은가" (이관 건 2/2)."""

from __future__ import annotations

from pok.engine.constraints.multipliers import build_ledger, support_more_lines

# 실측 기반 픽스처: 치명타 미개발(1.09) · 화염 저항 -50% · 방어 층 없음
BARE = {
    "CritEffect": 1.09,
    "Life": 2000.0,
    "EnergyShield": 0.0,
    "TotalEHP": 1470.0,
    "FireResist": -50.0,
    "ColdResist": 40.0,
    "LightningResist": 75.0,
    "PhysicalDamageReduction": 0.0,
    "BlockChance": 0.0,
}


def test_neutral_axes_are_surfaced_not_enforced() -> None:
    """1.0 근처 축을 **드러내기만** 한다 — 룬 소켓 선례(AD-3·철칙 3).

    "먼저 채워라"는 판단이라 엔진에 넣지 않는다. 사용자 결정 2026-08-05.
    """
    ledger = build_ledger(BARE)
    assert "crit" in [a.key for a in ledger.undeveloped]
    # 위반 개념이 없다 — ok/violations 같은 필드를 두지 않는다
    assert not hasattr(ledger, "violations")


def test_penalised_is_distinct_from_undeveloped() -> None:
    """저항 -50%는 "아직 안 키웠다"가 아니라 피해를 1.5배 받는 **적자**다."""
    ledger = build_ledger(BARE)
    keys = {a.key for a in ledger.penalised}
    assert "elemental_resist" in keys, "저항 -50%는 적자"
    assert "defence_layers" in keys, "EHP < 풀이면 층이 손해를 내고 있다"
    assert "crit" not in keys, "1.09는 중립보다 위 — 미개발이지 적자가 아니다"


def test_developed_axis_is_not_flagged() -> None:
    """축을 키우면 신호가 꺼져야 한다 — 안 꺼지면 경고가 소음이 된다."""
    strong = {**BARE, "CritEffect": 2.4, "FireResist": 75.0, "TotalEHP": 8000.0}
    ledger = build_ledger(strong)
    flagged = {a.key for a in ledger.undeveloped} | {a.key for a in ledger.penalised}
    assert "crit" not in flagged and "elemental_resist" not in flagged
    assert "defence_layers" not in flagged


def test_product_is_the_multiplicative_total() -> None:
    """축들의 곱 — 가산 항을 뺀 "곱연산 총 배수"."""
    ledger = build_ledger({"CritEffect": 2.0, "Life": 1000.0, "TotalEHP": 3000.0})
    assert ledger.product == 6.0, "치명타 2.0 x 방어 층 3.0"


def test_empty_stats_says_to_pass_full_stats() -> None:
    """기본 24종에는 이 축들이 없다 — 그 사실을 말해줘야 소비자가 고친다."""
    ledger = build_ledger({"Life": 100.0})
    assert not ledger.axes
    assert any('stats=["*"]' in n for n in ledger.notes)


def test_more_lines_separate_from_increased() -> None:
    """`more`(곱)와 `increased`(가산)를 가른다 — 이 구분이 결함의 핵심이었다."""
    lines = support_more_lines(
        {
            "support.heft": ["Supported Skills deal 30% more Maximum Physical Hit Damage"],
            "support.x": ["Supported Skills have 25% increased Damage"],
        }
    )
    assert [g for g, _ in lines] == ["support.heft"]
