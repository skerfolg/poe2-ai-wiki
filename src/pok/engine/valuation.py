"""축 가치 곡선 — **선형이 아닌 축**을 선형으로 재지 않는다 (백로그 #25).

## 왜 곡선인가

점수는 `Σ 가중치 * 델타`라서 **모든 축을 선형으로 본다.** 이동속도는 그렇지 않다:
0 → 20%는 맵 이동 시간을 크게 줄이지만, 60 → 80%는 같은 20인데도 체감이 훨씬 작다
(이동 시간은 `1/(1+속도)`에 비례한다). 선형으로 재면 가중치를 어떻게 잡아도 틀린다 —
작게 잡으면 첫 20%를 놓치고, 크게 잡으면 후반 투자에 딜·EHP를 계속 양보한다.

## 포화점은 실측에서 온다

사용자 판정 2026-08-09: *"신발 이동속도 + 마법사의 피로 인한 이동속도가 최고치.
그 이후 투자는 효율이 점점 떨어지도록."*

KB 실측으로 그 지점을 잡았다 — 추측하지 않는다:

- 신발 접사 최고 티어 `modifier.movementvelocity5` = **30%** (ilvl 65)
- 마법사의 피 `Legacy of Quicksilver` = **MovementSpeed INC 30** (`mechanic.mages-legacy`)

합이 **60%**다. (신발 베이스 임플리싯 10%는 베이스가 정하는 값이라 더하지 않았다 —
있으면 그만큼 더 빨리 포화한다.)

## 곡선

    V(x) = τ · (1 - e^(-x/τ))     τ = 30

`τ`를 곱해 두면 **x가 작을 때 V(x) ≈ x**다. 즉 이 축의 가중치는 "이동속도 1%p가
처음에 얼마짜리인가"라는 뜻을 그대로 유지한다 — 곡선을 넣었다고 가중치 의미가
바뀌면 기존 호출자가 조용히 틀린다.

한계 가치(첫 1%p 대비):

    0%에서   100%
    30%에서   37%
    60%에서   14%   ← 신발+마법사의 피
    90%에서    5%

## ⛔ 측정값은 건드리지 않는다

이 곡선은 **점수**에만 건다. `delta_now`가 담은 실측 델타는 그대로 보고한다 —
측정값을 곡선으로 바꿔 버리면 "PoB가 이렇게 쟀다"가 거짓이 된다(철칙 4).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# PoB 스탯 키. 이름이 `MovementSpeed`가 아니다 — 그 오기로 후보 20종이 전부 0으로
# 찍혔고 세션이 그걸 보고도 넘어갔다(#25 이관이 잡았다).
MOVEMENT_AXIS = "MovementSpeedMod"

# 포화 상수(%p). 위 실측: 신발 최고 접사 30 + Legacy of Quicksilver 30.
MOVEMENT_SATURATION_PCT = 60.0
# 곡선의 시상수. 포화점에서 한계 가치가 첫 1%p의 e^-2 ≈ 14%가 되도록 절반으로 둔다.
_TAU = MOVEMENT_SATURATION_PCT / 2.0


def movement_value(pct: float) -> float:
    """이동속도 `pct`(%p)의 누적 가치. 작을 땐 `≈ pct`, 커질수록 완만해진다."""
    if pct <= 0.0:
        return pct  # 음수(감속)는 곡선을 태우지 않는다 — 페널티는 깎이지 않아야 한다
    return _TAU * (1.0 - math.exp(-pct / _TAU))


def movement_gain(base_pct: float, delta_pct: float) -> float:
    """이미 `base_pct`를 가진 상태에서 `delta_pct`를 더 얻는 값어치.

    같은 +10%p라도 **어디서 더하느냐**에 따라 값이 다르다 — 그게 이 함수의 존재 이유다.
    """
    return movement_value(base_pct + delta_pct) - movement_value(base_pct)


def axis_gain(axis: str, delta: float, base: float = 0.0) -> float:
    """축 하나의 점수 기여분. 곡선이 없는 축은 **델타 그대로** 돌려준다.

    PoB의 `MovementSpeedMod`는 비율(방랑벽 = 0.200)이라 %p로 바꿔 재고 되돌린다.
    """
    if axis != MOVEMENT_AXIS:
        return delta
    return movement_gain(base * 100.0, delta * 100.0) / 100.0


# ── 안 재는 축 보고 (`unscored_axes`, 백로그 10차 이관) ─────────────────
#
# #18(방어) · #22(퀄리티) · #25(이동속도)는 전부 **"측정 축에 없어서 최적화가
# 구조적으로 못 보는 것"**이고 **셋 다 사용자가 지적해줘야 발견됐다.** 일반화한다.
#
# ## 압축 기준이 설계의 핵심이었다
#
# 실측 2026-08-09(완드 1개, 모드 3줄): 전체 619개 스탯 중 **델타가 0이 아닌 축이
# 57개**다. 그대로 내면 매번 57줄이다. 그런데 크기로는 못 줄인다 — **상대 변화율
# 1% 미만이 0개**였다. 진짜 중복은 크기가 아니라 **같은 사실의 여러 표현**이다:
#
#     FireResist · FireResistTotal · FireResistOverTime · MissingFireResist ·
#     FireTakenHit · FireTakenHitMult · FireTakenDotMult · FireResistTakenHitMulti …
#
# 9줄이 "화염 저항이 30 올랐다" 하나다. 그래서 **계열로 묶고 대표만 낸다** —
# 실측 57개 → **20계열**. 나머지는 `siblings`로 함께 실어 보내 숨기지 않는다.
_FAMILY_PREFIXES: tuple[str, ...] = (
    "Fire",
    "Cold",
    "Lightning",
    "Chaos",
    "Physical",
    "Elemental",
    "EnergyShield",
    "Life",
    "Mana",
    "Armour",
    "Evasion",
    "Spell",
    "Attack",
    "Crit",
)


def axis_family(axis: str) -> str:
    """축 이름 → 계열. 접두가 없으면 **자기 자신**이 계열이다(묶지 못하면 안 묶는다)."""
    for prefix in _FAMILY_PREFIXES:
        if axis.startswith(prefix):
            return prefix
    return axis


@dataclass(frozen=True)
class UnscoredAxis:
    """가중치에 없는데 후보가 실제로 **움직인** 축 — 채택은 호출자가 정한다(AD-3)."""

    axis: str  # 계열 대표 (상대 변화율이 가장 큰 것)
    family: str
    delta: float
    relative: float  # 기준 대비 변화율 (기준이 0이면 inf)
    siblings: tuple[str, ...] = ()  # 같은 계열의 나머지 — 숨기지 않는다


def unscored_axes(
    delta: Mapping[str, float],
    base: Mapping[str, float],
    weights: Mapping[str, float],
    *,
    already_reported: Sequence[str] = (),
    top: int = 8,
) -> tuple[tuple[UnscoredAxis, ...], str]:
    """움직였는데 점수에 없는 축 → (계열 대표 목록, 절단 안내).

    반환의 둘째 값은 **몇 개를 잘랐는지**다. 조용한 절단은 "전부 봤다"로 읽힌다(§0).
    """
    skip = set(weights) | set(already_reported)
    moved: dict[str, tuple[float, float]] = {}
    for axis, value in delta.items():
        if axis in skip or not isinstance(value, int | float) or abs(value) < 1e-9:
            continue
        anchor = base.get(axis, 0.0)
        moved[axis] = (float(value), abs(value) / abs(anchor) if anchor else float("inf"))

    grouped: dict[str, list[str]] = {}
    for axis in moved:
        grouped.setdefault(axis_family(axis), []).append(axis)

    out: list[UnscoredAxis] = []
    for family, members in grouped.items():
        members.sort(key=lambda a: -moved[a][1])
        head = members[0]
        value, relative = moved[head]
        out.append(
            UnscoredAxis(
                axis=head,
                family=family,
                delta=round(value, 4),
                relative=round(relative, 4) if relative != float("inf") else relative,
                siblings=tuple(members[1:]),
            )
        )
    out.sort(key=lambda u: -u.relative)
    dropped = len(out) - top
    note = "" if dropped <= 0 else f"⚠ 계열 {dropped}개를 더 냈으나 상위 {top}개만 실었다"
    return tuple(out[:top]), note
