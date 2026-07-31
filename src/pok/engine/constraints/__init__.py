"""설계 제약 검사기 — D27 (BLUEPRINT §10.0 ②, BUILD_DESIGN §2-3 제약 원장).

설계의 본체는 연속량 최적화가 아니라 이산 제약 충족이다. 이 패키지는 설계
문서의 제약 원장 4종을 **결정적으로** 검사한다 (AD-3: 판단 없음 — 각 검사기는
위반 사유·여유분을 담은 리포트만 반환하고, 무엇을 고를지는 에이전트의 몫):

- points   — 전직 포인트 예산·묶음 배타 (근거: resource.ascendancy-points)
- colors   — 보조 젬 색상 장부·과반 조건 (근거: passive.crystallised-immunities-5332 서술)
- reservation — 점유 산수·로우라이프 경계 (근거: resource.reservation·resource.life)
- exhaust  — 자원 소진: 성유 1회성·보조 슬롯 한도
             (근거: crafting-rules/anoint-rules.json·resource.support-gem-slots)

입력은 BuildSpec이 아니라 설계 단계의 최소 스펙(각 모듈의 dataclass)이다 —
설계 문서(design.md)의 장부는 BuildSpec(PoB 스냅샷)보다 앞서 존재하기 때문.
과도한 스키마화 금지(BUILD_DESIGN §4) — 표·수식에서 옮겨 적을 수 있는 수준만.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pok.engine.constraints.colors import ColorLedgerReport, SkillLinks, check_color_majority
from pok.engine.constraints.exhaust import AnointPlan, ExhaustionReport, check_exhaustion
from pok.engine.constraints.points import Bundle, PointBudgetReport, check_point_budget
from pok.engine.constraints.reservation import (
    ReservationEntry,
    ReservationReport,
    check_reservation,
)

__all__ = [
    "AnointPlan",
    "Bundle",
    "ColorLedgerReport",
    "ExhaustionReport",
    "KbDefaults",
    "PointBudgetReport",
    "ReservationEntry",
    "ReservationReport",
    "SkillLinks",
    "check_color_majority",
    "check_exhaustion",
    "check_point_budget",
    "check_reservation",
    "kb_defaults",
]


@dataclass(frozen=True)
class KbDefaults:
    """KB 수록분에서 읽은 제약 상수 — 하드코딩 대신 정본 인용 (태스크 #35 수록분)."""

    ascendancy_budget: int  # resource.ascendancy-points data.max
    max_supports_per_skill: int  # resource.support-gem-slots data.max_per_skill
    low_life_threshold_pct: float  # resource.life data.low_life_threshold_pct


def kb_defaults(root: Path | None = None) -> KbDefaults:
    """knowledge/ 정본에서 제약 상수를 읽는다 (레코드 부재 = 예외, 조용한 폴백 금지)."""
    from pok.kb.store import load as store_load

    kb = store_load(root)
    return KbDefaults(
        ascendancy_budget=int(kb.get("resource.ascendancy-points").raw["data"]["max"]),
        max_supports_per_skill=int(
            kb.get("resource.support-gem-slots").raw["data"]["max_per_skill"]
        ),
        low_life_threshold_pct=float(kb.get("resource.life").raw["data"]["low_life_threshold_pct"]),
    )
