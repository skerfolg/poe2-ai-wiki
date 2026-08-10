"""이동속도 가치 곡선 — 선형이 아닌 축을 선형으로 재지 않는다 (백로그 #25).

사용자 판정 2026-08-09: *"초반에 급격하고 후반으로 갈수록 완만해지는 그래프.
신발 이동속도 + 마법사의 피로 인한 이동속도가 최고치. 그 이후 투자는 효율이 점점
떨어지도록."*
"""

from __future__ import annotations

from pok.engine.valuation import (
    MOVEMENT_AXIS,
    MOVEMENT_SATURATION_PCT,
    axis_gain,
    movement_gain,
    movement_value,
)


def test_early_investment_is_worth_more_than_late() -> None:
    """같은 +20%p라도 **어디서 더하느냐**로 값이 달라진다 — 이 함수의 존재 이유."""
    early = movement_gain(0.0, 20.0)
    mid = movement_gain(30.0, 20.0)
    late = movement_gain(60.0, 20.0)
    assert early > mid > late > 0, (early, mid, late)
    # 포화점 이후는 확실히 완만하다 — "효율이 점점 떨어지도록"
    assert late < early / 3


def test_weight_still_means_what_it_meant() -> None:
    """곡선을 넣었다고 **가중치 의미가 바뀌면** 기존 호출자가 조용히 틀린다.

    x가 작을 때 V(x) ≈ x여야 "이동속도 1%p가 처음에 얼마짜리인가"가 그대로 유지된다.
    """
    assert abs(movement_value(1.0) - 1.0) < 0.02
    assert abs(movement_gain(0.0, 2.0) - 2.0) < 0.08  # 2차항만큼의 오차


def test_saturation_point_comes_from_measurement() -> None:
    """포화점 60%p는 **KB 실측**이다 — 신발 최고 접사 30 + Legacy of Quicksilver 30.

    임의의 수를 넣으면 결론이 임의가 된다(반경 3,800 가정이 「42포인트 절약」을 두 번
    보고하게 만든 것과 같은 형태다).
    """
    assert MOVEMENT_SATURATION_PCT == 60.0
    # 포화점의 한계 가치는 첫 1%p의 e^-2 ≈ 14% 언저리
    ratio = movement_gain(MOVEMENT_SATURATION_PCT, 1.0) / movement_gain(0.0, 1.0)
    assert 0.10 < ratio < 0.18, ratio


def test_penalties_are_not_softened() -> None:
    """감속은 곡선으로 깎지 않는다 — 페널티를 눅여 주면 위험이 숨는다."""
    assert movement_value(-10.0) == -10.0


def test_other_axes_pass_through_unchanged() -> None:
    """곡선이 없는 축은 **델타 그대로**다 — 게이트는 양방향으로 잠근다."""
    assert axis_gain("CombinedDPS", 1234.5) == 1234.5
    assert axis_gain("TotalEHP", -50.0) == -50.0
    # 이동속도는 PoB에서 **비율**로 온다(방랑벽 0.200 = +20%p)
    assert axis_gain(MOVEMENT_AXIS, 0.20, 0.0) < 0.20
    assert axis_gain(MOVEMENT_AXIS, 0.20, 0.60) < axis_gain(MOVEMENT_AXIS, 0.20, 0.0)


def test_scoring_reads_the_baseline_when_given_one() -> None:
    """`base`를 안 주면 **0에서 더하는 것으로 친다** — 곡선은 걸리되 값이 낙관적이다.

    "이미 60%인 빌드"와 "0인 빌드"를 같은 값으로 재면 이 결함(#25)이 그대로 남는다.
    """
    from pok.engine.items import CandidateResult, ItemCandidate

    result = CandidateResult(
        candidate=ItemCandidate("probe", "Boots", "…", "unique-kb"),
        delta_now={MOVEMENT_AXIS: 0.20},
        scaling_axes=(),
        delta_probed=None,
        probe=None,
        floor_violations=(),
    )
    weights = {MOVEMENT_AXIS: 1.0}
    bare = result.score(weights)
    assert bare < 0.20, "곡선은 baseline 없이도 걸린다"
    assert result.score(weights, {MOVEMENT_AXIS: 0.60}) < bare, "이미 빠르면 값이 더 준다"


def test_unscored_axes_compress_by_family_not_by_size() -> None:
    """압축 기준이 **크기가 아니다** — 실측에서 상대 변화율 1% 미만이 0개였다.

    진짜 중복은 **같은 사실의 여러 표현**이다: 화염 저항 하나가 9줄로 나온다.
    그래서 계열로 묶고 대표만 낸다(실측 57축 → 20계열).
    """
    from pok.engine.valuation import unscored_axes

    delta = {
        "FireResist": 30.0,
        "FireResistTotal": 30.0,
        "FireTakenHitMult": -0.3,
        "FireMaximumHitTaken": 303.0,
        "Life": 120.0,
        "CombinedDPS": 5000.0,
    }
    base = {"FireResist": -50.0, "FireResistTotal": -50.0, "FireTakenHitMult": 1.5,
            "FireMaximumHitTaken": 791.0, "Life": 800.0, "CombinedDPS": 10000.0}  # fmt: skip
    axes, note = unscored_axes(delta, base, {"CombinedDPS": 1.0})

    families = {a.family for a in axes}
    assert families == {"Fire", "Life"}, families
    assert "CombinedDPS" not in {a.axis for a in axes}, "이미 점수에 든 축은 빼야 한다"
    fire = next(a for a in axes if a.family == "Fire")
    assert fire.siblings, "묶은 나머지를 숨기지 않는다"
    assert len(fire.siblings) == 3
    assert not note


def test_unscored_axes_never_truncate_silently() -> None:
    """조용한 절단은 "전부 봤다"로 읽힌다 (§0의 규율)."""
    from pok.engine.valuation import unscored_axes

    delta = {f"Axis{i}": float(i + 1) for i in range(12)}
    base = {f"Axis{i}": 100.0 for i in range(12)}
    axes, note = unscored_axes(delta, base, {}, top=3)
    assert len(axes) == 3
    assert "9개" in note, note


def test_already_reported_axes_are_not_repeated() -> None:
    """방어 축은 `defensive_only`가 이미 낸다 — 두 번 말하면 신호가 묽어진다."""
    from pok.engine.items import _DEFENSIVE_AXES
    from pok.engine.valuation import unscored_axes

    delta = {"TotalEHP": 100.0, "StunThreshold": 50.0}
    base = {"TotalEHP": 800.0, "StunThreshold": 200.0}
    axes, _ = unscored_axes(delta, base, {}, already_reported=_DEFENSIVE_AXES)
    assert {a.axis for a in axes} == {"StunThreshold"}
