"""조건 레버리지·운용 비용 (이관 4 D1·D2·D3).

세션이 앵커의 21,302,501과 우리 302,794를 나란히 놓고 "70배 차이"로 읽었다.
같은 저울에서는 3.7배였다 — 이 절차 없이는 앵커 비교가 전부 오독이다.
"""

from __future__ import annotations

from typing import Any

from pok.engine.leverage import (
    compare_on_same_scale,
    conditional_keys,
    measure_leverage,
    measure_operating_cost,
)

# 이관 노트의 실측 수치 그대로
_TABLE = {
    ("ours", True): 412_098.0,
    ("ours", False): 302_794.0,
    ("anchor", True): 21_302_501.0,
    ("anchor", False): 1_118_557.0,
}


def _fake(spec: dict[str, Any]) -> dict[str, float]:
    return {"CombinedDPS": _TABLE[(spec["class_name"], bool(spec.get("config")))]}


OURS = {
    "class_name": "ours",
    "config": {"conditionEnemyMoving": True, "multiplierBleedsOnEnemy": 5},
}
ANCHOR = {
    "class_name": "anchor",
    "config": {"conditionEnemyMoving": True, "conditionBleedAggravated": True},
}


def test_reproduces_the_reported_measurements() -> None:
    comparison = compare_on_same_scale(OURS, ANCHOR, compute=_fake)
    assert comparison.ours.leverage == 1.361, "우리 1.36배"
    assert comparison.other.leverage == 19.045, "앵커 19.0배"
    assert round(comparison.ratio_off, 1) == 3.7, "같은 저울에서는 3.7배"


def test_the_wrong_reading_is_shown_next_to_the_right_one() -> None:
    """오독한 숫자를 함께 내야 무엇이 어긋났는지 보인다."""
    comparison = compare_on_same_scale(OURS, ANCHOR, compute=_fake)
    assert round(comparison.naive_ratio) == 70, "세션이 '70배'로 읽은 그 값"
    assert any("이렇게 읽으면 안 된다" in n for n in comparison.notes)
    assert any("사전 작업에 더 의존" in n for n in comparison.notes)


def test_only_conditional_keys_are_toggled() -> None:
    """`buff`·`override` 같은 설정성 항목은 사전 작업이 아니다."""
    keys = conditional_keys(
        {"conditionEnemyMoving": True, "multiplierBleedsOnEnemy": 5, "overrideCritChance": 100}
    )
    assert set(keys) == {"conditionEnemyMoving", "multiplierBleedsOnEnemy"}


def test_single_build_still_reports_leverage() -> None:
    reading = measure_leverage(OURS, compute=_fake, label="ours")
    assert reading.leverage == 1.361 and len(reading.conditions) == 2


def test_operating_cost_separates_enemy_and_self() -> None:
    """적 상태 유지와 자기 버프 유지는 손품의 성격이 다르다 (D3)."""
    cost = measure_operating_cost(
        {
            "config": {
                "conditionEnemyMoving": True,
                "conditionEnemyBleeding": True,
                "enemyConditionShocked": True,
                "conditionBleedAggravated": True,
                "multiplierIncisionStackCount": 10,
            },
            "skills": [{"gems": []}, {"gems": []}, {"gems": []}],
        },
        hits_per_second=0.3,
    )
    assert cost.enemy_conditions == 3 and cost.self_conditions == 2
    assert cost.skill_groups == 3
    measured = cost.as_measured()
    assert measured["OperatingLoad"] == 8.0, "목표 판정에 바로 넣을 수 있어야 한다"
    assert measured["HitsPerSecond"] == 0.3
