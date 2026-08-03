"""전직 포인트 예산 검사 — D27 ① (근거: mechanic.ascendancy-points, 예산 8).

v6 실증(design.md §1): 예산 8에 네 묶음 합 10 → 마지막 2포인트에서 분기 강제.
검사기는 "어느 분기를 골라야 하는가"를 판단하지 않는다(AD-3) — 예산 안에 드는
극대 선택 조합(=배타 분기)들을 열거해 보고할 뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True)
class Bundle:
    """선택 묶음 하나 — 선행 경로 비용 포함 포인트 (예: 변화된 살점→베이다트 = 4)."""

    name: str
    points: int
    required: bool = False  # 고정 조건(협상 불가) 묶음


@dataclass(frozen=True)
class PointBudgetReport:
    budget: int
    required_points: int
    total_points: int
    headroom: int  # 예산 - 필수 합 (선택 묶음에 쓸 수 있는 잔여)
    violations: tuple[str, ...]
    branches: tuple[tuple[str, ...], ...]  # 예산 안에 드는 극대 선택 조합 (배타 분기)

    @property
    def ok(self) -> bool:
        return not self.violations


def check_point_budget(bundles: tuple[Bundle, ...], budget: int) -> PointBudgetReport:
    """묶음 합이 예산을 초과하면 위반 보고 + 배타 분기(극대 적합 조합) 열거."""
    required = [b for b in bundles if b.required]
    optional = [b for b in bundles if not b.required]
    required_points = sum(b.points for b in required)
    total = sum(b.points for b in bundles)
    headroom = budget - required_points
    violations: list[str] = []
    if required_points > budget:
        violations.append(
            f"필수 묶음 합 {required_points} > 예산 {budget} — 고정 조건 자체가 불가능"
        )
    if total > budget:
        names = " + ".join(f"{b.name}({b.points})" for b in bundles)
        violations.append(f"전체 묶음 합 {total} > 예산 {budget} — 배타 분기 필요: {names}")
    # 극대 적합 조합: 필수 전부 + 선택 부분집합이 예산 안 & 더 못 늘리는 조합
    fitting: list[tuple[int, ...]] = []
    if required_points <= budget:
        for r in range(len(optional), -1, -1):
            for idx in combinations(range(len(optional)), r):
                pts = required_points + sum(optional[i].points for i in idx)
                if pts > budget:
                    continue
                chosen = set(idx)
                if any(chosen < set(f) for f in fitting):
                    continue  # 이미 있는 조합의 진부분집합 = 극대 아님
                fitting.append(idx)
    branches = tuple(tuple(optional[i].name for i in idx) for idx in fitting)
    return PointBudgetReport(
        budget=budget,
        required_points=required_points,
        total_points=total,
        headroom=headroom,
        violations=tuple(violations),
        branches=branches,
    )
