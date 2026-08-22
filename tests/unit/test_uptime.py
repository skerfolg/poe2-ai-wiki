"""가동률 축(#94) — 「크기」만 보던 도구에 「켜져 있는 비율」을 더한다.

방어·버프의 값은 크기 x 가동률인데 도구는 크기만 냈다. 실측 2026-08-21: 쿨다운·지속을
둘 다 가진 스킬이 **46종**이고, 그중 3종은 「지속 중 쿨다운 미회복」이라 주기 공식이
다르다 — 구분하지 않으면 가동률을 최대 2배 부풀린다.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from pok.engine.constraints.uptime import (
    cycle_is_additive,
    required_cooldown_recovery,
    uptime,
)


def test_일반_주기는_max이고_쿨이_지속보다_짧으면_상시다() -> None:
    """쿨다운 ≤ 지속이면 끊김 없이 재시전할 수 있다."""
    r = uptime(duration_s=8.0, cooldown_s=3.0)
    assert r.cycle_s == 8.0
    assert r.uptime_pct == 100.0
    assert r.can_reach_full


def test_쿨이_지속보다_길면_그_비율만큼만_켜진다() -> None:
    r = uptime(duration_s=4.0, cooldown_s=10.0)
    assert r.cycle_s == 10.0
    assert r.uptime_pct == 40.0


def test_쿨다운_미회복이면_주기가_더해지고_상시가_불가능하다() -> None:
    """`Cooldown does not recover during Buff effect` — 영구화를 막는 장치다.

    실측(부인, 2026-08-21): 지속 4.03 · 쿨 10.03 → 가동률 28.7%.
    일반 공식으로 재면 40.2%가 나와 **1.4배 부풀려진다**.
    """
    additive = uptime(duration_s=4.03, cooldown_s=10.03, additive_cycle=True)
    normal = uptime(duration_s=4.03, cooldown_s=10.03)
    assert additive.uptime_pct == 28.7
    assert normal.uptime_pct == 40.2
    assert not additive.can_reach_full and normal.can_reach_full


def test_문구로_주기_공식을_가른다() -> None:
    assert cycle_is_additive(["Cooldown does not recover during Buff effect"])
    assert not cycle_is_additive(["Buff duration is 4 seconds", "Cooldown is 10 seconds"])


def test_쿨다운이_없으면_상시다() -> None:
    r = uptime(duration_s=5.0, cooldown_s=0.0)
    assert r.uptime_pct == 100.0 and r.can_reach_full


def test_두_축을_함께_올려야_한다() -> None:
    """한쪽만 올리면 손해라는 것이 수치로 나와야 한다 (사용자 지적 2026-08-21).

    실측(부인 기본 28.6%): 지속 +35%만 → 35.0% · 쿨회복 265%만 → 66.1% ·
    **둘 다 → 74.3%**. 두 옵션은 `of Chronomancy` 접미의 형제라 슬롯 예산이 겹친다.
    """
    base = uptime(4.03, 10.03, additive_cycle=True).uptime_pct
    dur_only = uptime(4.03 * 1.35, 10.03, additive_cycle=True).uptime_pct
    cdr_only = uptime(4.03, 10.03 / 3.65, additive_cycle=True).uptime_pct
    both = uptime(4.03 * 1.35, 10.03 / 3.65, additive_cycle=True).uptime_pct
    assert base < dur_only < cdr_only < both
    assert both == pytest.approx(66.2, abs=0.5)


def test_필요_쿨다운_회복_역산() -> None:
    """목표 가동률 → 쿨다운 회복 하한. 요구-수급 장부의 입력이다."""
    # 일반 주기: 지속 4초로 가동률 100%를 원하면 쿨다운 ≤ 4초여야 한다 (10 → 4, +150%)
    assert required_cooldown_recovery(4.0, 10.0, 1.0) == 150.0
    # 이미 달성한 경우는 0
    assert required_cooldown_recovery(8.0, 4.0, 1.0) == 0.0


def test_쿨다운_미회복은_100퍼센트를_None으로_거절한다() -> None:
    """도달 불가를 **수치로 속이지 않는다** — 아무리 투자해도 상시가 안 된다."""
    assert required_cooldown_recovery(4.0, 10.0, 1.0, additive_cycle=True) is None
    # 80%는 가능하다 — 필요 쿨다운 = 4 x 0.2/0.8 = 1초 → 10에서 +900%
    assert required_cooldown_recovery(4.0, 10.0, 0.8, additive_cycle=True) == 900.0


def test_compute_반환에_가동률이_자동으로_붙는다() -> None:
    """강제 지점 — 문서에 적으면 안 지켜진다(철칙 5). 지속·쿨다운이 있으면 매번 싣는다."""
    from pok.mcp.tools.build import _uptime_of

    class _R:
        stats: ClassVar[dict[str, float]] = {"Duration": 4.0, "Cooldown": 10.0}

    out = _uptime_of(_R())  # type: ignore[arg-type]
    assert out is not None
    assert out["uptime_pct"] == 40.0
    assert "지속 + 쿨다운" in out["note"]  # 미회복 문구 주의를 함께 낸다

    class _NoCd:
        stats: ClassVar[dict[str, float]] = {"Duration": 4.0}

    assert _uptime_of(_NoCd()) is None  # type: ignore[arg-type]
