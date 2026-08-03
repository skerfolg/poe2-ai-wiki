"""점유 산수 검사 — D27 ③ (근거: mechanic.reservation·resource.life, 태스크 #35 수록분).

공식(mechanic.reservation, SUPPORTED_INFERENCE — 인게임 점유 정보창 대조):

    실제 점유 = 기본 점유 ÷ (1 + 총 점유 효율)      # 효율원은 합산(additive)

**축 무관**이다 — 생명력 축은 최대 생명력 대비 %로, 정신력 축은 절대량으로 적힐 뿐
산수는 같다. `pool`(자원 총량)만 축에 맞게 주면 된다:
  · 생명력 축: pool=100 (기본값, 단위 = 최대 생명력 대비 %)
  · 정신력 축: pool=총 정신력 (단위 = 절대량 — CoC 100·신성 모독 저주당 60 등)

고정 점유(예: 베이다트의 의지 25%)는 스킬 점유가 아니므로 효율 미적용.
로우라이프 판정은 **생명력 축 전용** — `low_life_threshold_pct`를 줄 때만 계산한다
(resource.life low_life_threshold_pct = 35).

v6 실증(design.md §5): 기본 66%·고정 25%·총 효율 57% → 실제 42.04% +
베이다트 25% = 총점유 67.04%, 잔여 32.96% (로우라이프 성립 확인 IN_GAME).
경계: 총 효율 65% 초과 시 잔여가 35%를 넘어 로우라이프가 풀린다.

정신력 축은 축별 점유 장부 규율(BUILD_DESIGN §2-3)의 대상이다 — 한 축의 검증이
다른 축을 대신하지 않는다. 이 검사기가 정액 축을 못 다루던 것이 실증에서 갭으로
드러나 통합했다(2026-08-04).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReservationEntry:
    """점유 항목 하나 — 단위는 축을 따른다(생명력 축 = %, 정신력 축 = 절대량)."""

    name: str
    base_amount: float
    fixed: bool = False  # True = 점유 효율 미적용 (스킬 점유가 아닌 고정 점유)


@dataclass(frozen=True)
class ReservationReport:
    efficiency_pct: float
    pool: float  # 자원 총량 (생명력 축이면 100)
    entries: tuple[tuple[str, float], ...]  # (이름, 실제 점유량)
    total_reserved: float
    remaining: float
    violations: tuple[str, ...]  # 총점유 > 총량 등 산수 불가능 상태만
    # 아래는 생명력 축 전용 (low_life_threshold_pct를 준 경우에만 채워진다)
    low_life_threshold_pct: float | None = None
    low_life: bool | None = None
    low_life_headroom_pct: float | None = None
    max_efficiency_for_low_life_pct: float | None = None

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def remaining_pct(self) -> float:
        """총량 대비 잔여 비율 — 축이 달라도 같은 척도로 읽고 싶을 때."""
        return round(self.remaining / self.pool * 100.0, 2) if self.pool else 0.0


def check_reservation(
    entries: tuple[ReservationEntry, ...],
    efficiency_pct: float,
    *,
    pool: float = 100.0,
    low_life_threshold_pct: float | None = None,
) -> ReservationReport:
    """점유 효율 공식으로 잔여 자원을 계산한다 (생명력·정신력 등 축 무관).

    로우라이프 여부 자체는 위반이 아니다(빌드 목표에 따라 원할 수도, 피할 수도
    있다 — 판단은 에이전트 몫, AD-3). 위반은 총점유 > 총량 같은 불가능 상태만.
    """
    if pool <= 0:
        raise ValueError(f"자원 총량 pool 이 양수가 아님: {pool}")
    factor = 1.0 + efficiency_pct / 100.0
    actual = tuple(
        (e.name, round(e.base_amount if e.fixed else e.base_amount / factor, 2)) for e in entries
    )
    total = round(sum(amount for _, amount in actual), 2)
    remaining = round(pool - total, 2)
    violations: list[str] = []
    if total > pool:
        violations.append(f"총점유 {total} > 총량 {pool} — 점유 불가능 (자원 부족)")

    if low_life_threshold_pct is None:  # 정신력 등 비-생명력 축
        return ReservationReport(
            efficiency_pct=efficiency_pct,
            pool=pool,
            entries=actual,
            total_reserved=total,
            remaining=remaining,
            violations=tuple(violations),
        )

    fixed_sum = sum(e.base_amount for e in entries if e.fixed)
    scaled_base = sum(e.base_amount for e in entries if not e.fixed)
    # 잔여 ≤ 임계  ⇔  scaled_base/(1+e) ≥ pool - 임계 - 고정  ⇒  e 상한
    denom = pool - low_life_threshold_pct - fixed_sum
    max_eff: float | None = None
    if scaled_base > 0 and denom > 0:
        max_eff = round((scaled_base / denom - 1.0) * 100.0, 2)
    return ReservationReport(
        efficiency_pct=efficiency_pct,
        pool=pool,
        entries=actual,
        total_reserved=total,
        remaining=remaining,
        violations=tuple(violations),
        low_life_threshold_pct=low_life_threshold_pct,
        low_life=remaining <= low_life_threshold_pct,
        low_life_headroom_pct=round(low_life_threshold_pct - remaining, 2),
        max_efficiency_for_low_life_pct=max_eff,
    )
