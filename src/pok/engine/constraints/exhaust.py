"""자원 소진 검사 — D27 ④ (성유 1회성·보조 슬롯 한도).

근거(태스크 #35 수록분):
- 성유: crafting-rules/anoint-rules.json — 아이템당 성유 부여는 동시에 1개만
  (v6: "목걸이 기존 성유 고정, 추가 주입 불가능" — 기존 부여 위에 다른 노드를
  주입으로 해결할 수 없다)
- 보조 슬롯: resource.support-gem-slots — 액티브 젬당 보조 최대 5개
"""

from __future__ import annotations

from dataclasses import dataclass

from pok.engine.constraints.colors import SkillLinks


@dataclass(frozen=True)
class AnointPlan:
    """아이템 하나의 성유 상태 — 기존 부여와 설계가 요구하는 부여."""

    item: str
    existing: str | None = None  # 이미 부여된 성유 노드 (없으면 None)
    planned: str | None = None  # 설계가 이 아이템에 요구하는 성유 노드


@dataclass(frozen=True)
class ExhaustionReport:
    support_slots: tuple[tuple[str, int, int], ...]  # (스킬, 사용 수, 한도)
    slot_headroom: tuple[tuple[str, int], ...]  # (스킬, 잔여 슬롯)
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def check_exhaustion(
    skills: tuple[SkillLinks, ...],
    anoints: tuple[AnointPlan, ...] = (),
    *,
    max_supports_per_skill: int,
) -> ExhaustionReport:
    """소진 자원 장부 검사 — 슬롯 한도 초과·성유 중복 배분을 위반으로 보고."""
    violations: list[str] = []
    slots: list[tuple[str, int, int]] = []
    headroom: list[tuple[str, int]] = []
    for grp in skills:
        used = len(grp.supports)
        slots.append((grp.skill, used, max_supports_per_skill))
        headroom.append((grp.skill, max_supports_per_skill - used))
        if used > max_supports_per_skill:
            violations.append(
                f"{grp.skill}: 보조 {used}개 > 한도 {max_supports_per_skill} "
                f"(resource.support-gem-slots)"
            )
    for plan in anoints:
        if plan.existing and plan.planned and plan.planned != plan.existing:
            violations.append(
                f"{plan.item}: 성유 중복 배분 — 기존 {plan.existing!r} 위에 "
                f"{plan.planned!r} 추가 불가 (anoint-rules: 아이템당 1개). "
                f"직접 경로·주얼·장비로 확보 필요"
            )
    return ExhaustionReport(
        support_slots=tuple(slots),
        slot_headroom=tuple(headroom),
        violations=tuple(violations),
    )
