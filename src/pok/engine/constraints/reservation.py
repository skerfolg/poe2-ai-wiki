"""점유 산수 검사 — D27 ③ (근거: mechanic.reservation·resource.life, 태스크 #35 수록분).

공식(mechanic.reservation, SUPPORTED_INFERENCE — 인게임 점유 정보창 대조):

    실제 점유율 = 기본 점유율 ÷ (1 + 총 점유 효율)      # 효율원은 합산(additive)

고정 점유(예: 베이다트의 의지 25%)는 스킬 점유가 아니므로 효율 미적용.
로우라이프 판정: 잔여 생명력 ≤ 임계(resource.life low_life_threshold_pct = 35).

v6 실증(design.md §5): 기본 66%·고정 25%·총 효율 57% → 실제 42.04% +
베이다트 25% = 총점유 67.04%, 잔여 32.96% (로우라이프 성립 확인 IN_GAME).
경계: 총 효율 65% 초과 시 잔여가 35%를 넘어 로우라이프가 풀린다.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReservationEntry:
    """점유 항목 하나 — 최대 자원 대비 기본 점유율(%)."""

    name: str
    base_pct: float
    fixed: bool = False  # True = 점유 효율 미적용 (스킬 점유가 아닌 고정 점유)


@dataclass(frozen=True)
class ReservationReport:
    efficiency_pct: float
    entries: tuple[tuple[str, float], ...]  # (이름, 실제 점유율%)
    total_reserved_pct: float
    remaining_pct: float
    low_life_threshold_pct: float
    low_life: bool  # 잔여 ≤ 임계
    low_life_headroom_pct: float  # 임계 - 잔여 (음수 = 로우라이프 아님, 초과분)
    max_efficiency_for_low_life_pct: float | None  # 로우라이프 유지 가능한 총 효율 상한
    violations: tuple[str, ...]  # 총점유 > 100% 등 산수 불가능 상태만

    @property
    def ok(self) -> bool:
        return not self.violations


def check_reservation(
    entries: tuple[ReservationEntry, ...],
    efficiency_pct: float,
    *,
    low_life_threshold_pct: float,
) -> ReservationReport:
    """점유 효율 공식으로 잔여 자원을 계산하고 로우라이프 경계를 판정한다.

    로우라이프 여부 자체는 위반이 아니다(빌드 목표에 따라 원할 수도, 피할 수도
    있다 — 판단은 에이전트 몫, AD-3). 위반은 총점유 > 100% 같은 불가능 상태만.
    """
    factor = 1.0 + efficiency_pct / 100.0
    actual = tuple(
        (e.name, round(e.base_pct if e.fixed else e.base_pct / factor, 2)) for e in entries
    )
    total = round(sum(pct for _, pct in actual), 2)
    remaining = round(100.0 - total, 2)
    violations: list[str] = []
    if total > 100.0:
        violations.append(f"총점유 {total}% > 100% — 점유 불가능 (자원 부족)")
    fixed_sum = sum(e.base_pct for e in entries if e.fixed)
    scaled_base = sum(e.base_pct for e in entries if not e.fixed)
    # 잔여 ≤ 임계  ⇔  scaled_base/(1+e) ≥ 100 - 임계 - 고정  ⇒  e 상한
    denom = 100.0 - low_life_threshold_pct - fixed_sum
    max_eff: float | None = None
    if scaled_base > 0 and denom > 0:
        max_eff = round((scaled_base / denom - 1.0) * 100.0, 2)
    return ReservationReport(
        efficiency_pct=efficiency_pct,
        entries=actual,
        total_reserved_pct=total,
        remaining_pct=remaining,
        low_life_threshold_pct=low_life_threshold_pct,
        low_life=remaining <= low_life_threshold_pct,
        low_life_headroom_pct=round(low_life_threshold_pct - remaining, 2),
        max_efficiency_for_low_life_pct=max_eff,
        violations=tuple(violations),
    )
