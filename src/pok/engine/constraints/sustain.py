"""지속 가능성 경계 검사 — D27 ⑤ (성립 질문의 산수 부분, 2026-08-02 신설).

메커니즘의 부작용·비용(자해·주기 피해·자원 소모)이 가용 자원 안에서 버텨지는가.
"미측정"과 "측정 전에도 상·하한은 계산 가능"은 다르다 — 원본 크기·경감·가용
자원이 수치로 있으면 경계는 측정 없이 산수로 나온다(블라인드 재현 검증 2026-08-02
에서 확립: 두 실행 모두 재료가 전부 있는데도 곱하지 않고 측정 큐로 미뤘다).

    실효 부작용 = 원본 x (1 - 경감%)          # 예: 자해 원본 x (1 - 저항)
    필요 경감   = (1 - 가용 x 목표비율 ÷ 원본)  # 목표 비율을 지키는 경감 하한 역산

판단 없음(AD-3): 위반은 산수적 즉사 경계(실효 ≥ 가용)만. 어떤 비율이 안전한가,
경감을 어디서 수급하는가(요구-수급 장부)는 호출자·에이전트 몫.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SideEffect:
    """부작용·비용 항목 하나 — 메커니즘이 만드는 1회분 크기와 현재 경감."""

    name: str
    base_amount: float  # 원본 크기 (예: 최대 생명력+최대 ES 합)
    mitigation_pct: float = 0.0  # 현재 경감 합 (%, 저항·감폭 등)


@dataclass(frozen=True)
class SustainReport:
    pool: float  # 부작용을 받아내는 가용 자원 (예: 로우라이프 잔여 생명력)
    entries: tuple[tuple[str, float, float], ...]  # (이름, 실효량, 가용 대비 %)
    violations: tuple[str, ...]  # 실효 ≥ 가용 = 한 방 초과 (산수적 즉사 경계)
    required_mitigation: tuple[tuple[str, float, float], ...]
    # (이름, 목표 가용비율%, 그 비율을 지키는 필요 경감% 하한) — 요구-수급 장부의 입력

    @property
    def ok(self) -> bool:
        return not self.violations


def check_sustain(
    effects: tuple[SideEffect, ...],
    pool: float,
    *,
    target_pool_ratio_pct: float | None = None,
) -> SustainReport:
    """부작용 실효량·가용 대비 비율 계산 + 목표 비율의 필요 경감 역산.

    target_pool_ratio_pct(예: 50 = "1회분이 가용의 절반 이하")를 주면 각 항목의
    필요 경감 하한을 역산해 보고한다 — 그 경감의 수급은 요구-수급 장부로 넘긴다.
    """
    if pool <= 0:
        raise ValueError(f"가용 자원 pool 이 양수가 아님: {pool}")
    entries: list[tuple[str, float, float]] = []
    violations: list[str] = []
    required: list[tuple[str, float, float]] = []
    for e in effects:
        passed = e.base_amount * (1.0 - e.mitigation_pct / 100.0)
        ratio = passed / pool * 100.0
        entries.append((e.name, round(passed, 2), round(ratio, 2)))
        if passed >= pool:
            violations.append(
                f"{e.name}: 실효 {passed:.0f} ≥ 가용 {pool:.0f} — 1회분이 자원을 "
                f"초과 (경감 {e.mitigation_pct:g}% 기준, 성립 불가 경계)"
            )
        if target_pool_ratio_pct is not None and e.base_amount > 0:
            need = (1.0 - pool * target_pool_ratio_pct / 100.0 / e.base_amount) * 100.0
            required.append((e.name, target_pool_ratio_pct, round(max(0.0, need), 2)))
    return SustainReport(
        pool=pool,
        entries=tuple(entries),
        violations=tuple(violations),
        required_mitigation=tuple(required),
    )
