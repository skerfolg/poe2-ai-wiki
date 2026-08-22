"""가동률(uptime) — 「얼마나 강한가」가 아니라 **얼마나 켜져 있나** (#94).

방어·버프 축의 값은 크기 x 가동률인데, 도구는 지금까지 **크기만** 냈다. 그래서
설계가 "이 버프를 켜면 피해 30% 감소"까지만 보고 **그게 3초 중 1초만 켜진다**는 것을
못 봤다. 자원 소모를 보는 `sustain.py`와 축이 다르다 — 저건 「버틸 수 있나」,
이건 「켜져 있나」다.

## 주기 공식이 둘이다 — 문구가 가른다

    일반:            주기 = max(지속, 쿨다운)     → 쿨다운 ≤ 지속이면 **100% 가능**
    쿨다운 미회복:    주기 = 지속 + 쿨다운         → **100%에 원리적으로 도달 못 함**

두 번째는 `Cooldown does not recover during Buff effect` 같은 문구가 붙은 스킬이다
(실측 2026-08-21: 46종 중 3종). 이 구분을 안 하면 가동률을 최대 2배까지 부풀린다 —
영구 유지가 되는 스킬과 안 되는 스킬을 같은 산수로 재게 된다.

## 두 축을 함께 본다 (사용자 지적 2026-08-21)

가동률은 **지속시간 증가**와 **쿨다운 회복** 둘의 함수다. 한쪽만 올리면 손해다 —
실측(부인, 기본 28.6%): 지속 +35%만 → 35.0% · 쿨회복 265%만 → 66.1% ·
**둘 다 → 74.3%**. 게다가 두 옵션은 `of Chronomancy` 접미의 **형제 옵션**이라
같은 슬롯 예산을 두고 경쟁한다. 배분이 곧 설계 문제다.

## 판단 없음 (AD-3)

몇 %가 충분한가는 답하지 않는다. 가동률과 **필요 투자량 역산**(목표 가동률을 위한
쿨다운 회복 하한)까지만 낸다 — 어느 축에서 수급할지는 호출자 몫이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 「지속 중에는 쿨다운이 돌지 않는다」 — 주기 공식을 가르는 문구.
# 정본 문구 실측으로 만든 패턴이다(추측 금지): `Cooldown does not recover during
# Buff effect`(부인) 등 46종 중 3종.
_NO_RECOVER_DURING = re.compile(
    r"[Cc]ooldown does not recover|does not recover (?:its cooldown )?(?:during|while)",
    re.I,
)


def cycle_is_additive(skill_texts: tuple[str, ...] | list[str]) -> bool:
    """주기가 `지속 + 쿨다운`인가(= 지속 중 쿨다운이 안 도는가)."""
    return any(_NO_RECOVER_DURING.search(str(t)) for t in skill_texts)


@dataclass(frozen=True)
class UptimeReading:
    """가동률 1건 — 근거가 되는 입력을 함께 들고 다닌다(AD-8)."""

    duration_s: float
    cooldown_s: float
    additive_cycle: bool  # True면 주기 = 지속 + 쿨다운 (100% 불가)
    cycle_s: float
    uptime: float  # 0.0~1.0
    # 100%에 도달할 수 있는 구조인가. False면 아무리 투자해도 상시가 안 된다.
    can_reach_full: bool

    @property
    def uptime_pct(self) -> float:
        return round(self.uptime * 100, 1)


def uptime(
    duration_s: float,
    cooldown_s: float,
    *,
    additive_cycle: bool = False,
) -> UptimeReading:
    """지속·쿨다운에서 가동률을 낸다. `cooldown_s`는 **회복률이 이미 반영된 값**이다.

    쿨다운이 0이면(쿨다운 없는 스킬) 가동률 100%로 본다 — 주기가 지속으로만 정해진다.
    """
    if duration_s <= 0:
        raise ValueError("duration_s는 양수여야 한다 — 지속이 없으면 가동률이 정의되지 않는다")
    if cooldown_s <= 0:
        return UptimeReading(duration_s, 0.0, additive_cycle, duration_s, 1.0, True)
    cycle = duration_s + cooldown_s if additive_cycle else max(duration_s, cooldown_s)
    return UptimeReading(
        duration_s=duration_s,
        cooldown_s=cooldown_s,
        additive_cycle=additive_cycle,
        cycle_s=cycle,
        uptime=min(1.0, duration_s / cycle),
        can_reach_full=not additive_cycle,
    )


def required_cooldown_recovery(
    duration_s: float,
    base_cooldown_s: float,
    target_uptime: float,
    *,
    additive_cycle: bool = False,
) -> float | None:
    """목표 가동률을 위한 **쿨다운 회복 증가율 하한(%)**. 도달 불가면 None.

    요구-수급 장부의 입력이다 — "가동률 80%를 원하면 쿨다운 회복이 몇 % 필요한가"에
    답한다. 판단은 하지 않는다(그 투자가 값어치 있는지는 호출자 몫).

        일반:        필요 쿨다운 = 지속 / 목표
        쿨다운 미회복: 필요 쿨다운 = 지속 x (1 - 목표) / 목표
    """
    if not 0 < target_uptime <= 1:
        raise ValueError(f"target_uptime은 (0, 1] 범위여야 한다: {target_uptime}")
    if additive_cycle:
        if target_uptime >= 1:
            return None  # 주기에 쿨다운이 통째로 더해지므로 100%는 원리적으로 불가
        needed_cd = duration_s * (1 - target_uptime) / target_uptime
    else:
        needed_cd = duration_s / target_uptime
    if needed_cd >= base_cooldown_s:
        return 0.0  # 이미 달성 — 추가 투자 불요
    # cooldown = base / (1 + rate) 를 needed_cd 이하로: rate = base/needed - 1
    return round((base_cooldown_s / needed_cd - 1) * 100, 1)
