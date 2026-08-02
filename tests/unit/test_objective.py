"""engine/objective — D28 목표 상태(임계·캡) 사전식 판정 (수치 = v6 실측)."""

from __future__ import annotations

import pytest

from pok.engine.objective import Target, evaluate_targets

# v6 목표 상태의 축약: ① 로우라이프 유지(잔여 ≤ 35, 최우선) ② 빨강 과반(> 50%)
# ③ 폭발 간격 ≥ 3초 ④ 치명타 확률 ≥ 60
_V6_TARGETS = (
    Target("remaining_life_pct", "<=", 35.0, label="로우라이프 경계 (resource.life)"),
    Target("red_support_ratio_pct", ">=", 50.01, label="결정화된 면역 빨강 과반"),
    Target("infernal_flame_burst_interval_s", ">=", 3.0, label="지옥불꽃 폭발 간격 (v6 §13)"),
    Target("CritChance", ">=", 60.0, label="CoC 엔진 목표 치명타 (v6 §7.6)"),
)


def test_v6_충족분과_미측정_병목() -> None:
    # 실측: 점유 검사기 결과(잔여 32.96)·색상 장부(6/10=60%). 폭발 간격·치명타는 미측정.
    report = evaluate_targets(
        _V6_TARGETS, {"remaining_life_pct": 32.96, "red_support_ratio_pct": 60.0}
    )
    assert not report.satisfied
    low_life, red, burst, _crit = report.results
    assert low_life.satisfied and low_life.margin == pytest.approx(2.04)  # 35 - 32.96
    assert red.satisfied and red.margin == pytest.approx(9.99)
    assert not burst.satisfied and burst.measured is None  # 측정 전 = 충족 아님 (AD-8)
    assert report.next_bottleneck is burst  # 사전식 첫 미충족 = 다음 병목
    assert report.unmeasured == ("infernal_flame_burst_interval_s", "CritChance")


def test_경계_이탈은_병목이_우선순위로_잡힌다() -> None:
    # 효율 초과로 잔여 36.5% → 로우라이프 풀림: 하위 목표가 다 충족돼도 병목은 1순위
    report = evaluate_targets(
        _V6_TARGETS,
        {
            "remaining_life_pct": 36.5,
            "red_support_ratio_pct": 60.0,
            "infernal_flame_burst_interval_s": 3.4,
            "CritChance": 87.13,  # 앵커 실측(poe.ninja 26a2b PlayerStat)
        },
    )
    assert not report.satisfied
    assert report.next_bottleneck is report.results[0]
    assert report.results[0].margin == pytest.approx(-1.5)


def test_전_목표_충족() -> None:
    report = evaluate_targets(
        _V6_TARGETS,
        {
            "remaining_life_pct": 32.96,
            "red_support_ratio_pct": 60.0,
            "infernal_flame_burst_interval_s": 3.4,
            "CritChance": 87.13,
        },
    )
    assert report.satisfied and report.next_bottleneck is None and not report.unmeasured


def test_잘못된_op는_거부() -> None:
    with pytest.raises(ValueError, match="불허"):
        evaluate_targets((Target("x", "==", 1.0),), {"x": 1.0})
