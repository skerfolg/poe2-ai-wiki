"""트리 최적화 루프 — P4 Phase 3 (BLUEPRINT §10.3).

그리디: 매 라운드 후보를 현재 빌드 문맥에서 델타 실측하고, 정책(Objective)
점수가 가장 높은 노드를 채택한다. 채택된 모든 스텝에 실측 델타가 남는다
(= Exit 기준 "포인트마다 델타로 정당화"). 전역 최적은 보장하지 않는다 —
근접-최적 + 근거를 목표로 한다(§10.3 한계 인정).

정책(무엇을 가중할지)은 호출자(에이전트/사용자)의 몫 — 엔진은 점수 계산과
탐색 대행만 한다(AD-3). 단일 축 금지(RC3): Objective는 다축 가중이 기본.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field

from pok.engine.tree.deltas import NodeDelta, evaluate_node_deltas
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec
from pok.pob.daemon import PobDaemon
from pok.pob.runner import PobResult


@dataclass(frozen=True)
class Objective:
    """다차원 목적 가중 (RC3). 점수 = Σ w_s x (델타_s / max(기준_s, floor_s)) / 포인트.

    상대화(기준 대비 %)로 스탯 간 스케일 차이를 흡수한다. floor는 기준값이
    0에 가까울 때의 폭주 방지(예: ES 0인 빌드에서 ES 델타).
    """

    weights: dict[str, float]  # 예: {"CombinedDPS": 1.0, "Life": 0.7, "TotalEHP": 0.5}
    floors: dict[str, float] = field(default_factory=dict)

    def score(self, delta: NodeDelta, base_stats: dict[str, float]) -> float:
        total = 0.0
        for stat, w in self.weights.items():
            base = abs(base_stats.get(stat, 0.0))
            denom = max(base, self.floors.get(stat, 1.0))
            total += w * (delta.deltas.get(stat, 0.0) / denom)
        return total / max(delta.points, 1)


@dataclass(frozen=True)
class Step:
    """채택된 한 수 — 실측 근거 포함."""

    node_delta: NodeDelta
    score: float


@dataclass(frozen=True)
class OptimizeResult:
    spec: BuildSpec  # 최적화 후
    result: PobResult  # 최종 실측
    steps: tuple[Step, ...]  # 채택 순서대로 (각각 델타 근거)
    rejected_rounds: int  # 양의 점수 후보가 없어 중단됐으면 1


def optimize_tree(
    spec: BuildSpec,
    graph: TreeGraph,
    objective: Objective,
    *,
    point_budget: int,
    candidate_radius: int = 8,
    max_candidates_per_round: int = 40,
    stats: tuple[str, ...] | None = None,
) -> OptimizeResult:
    """포인트 예산 안에서 정책 점수가 양수인 최선 수를 반복 채택한다.

    후보 = 현재 트리에서 candidate_radius 안의 notable/keystone/jewel-socket
    (거리순 상한 max_candidates_per_round — 초과분은 다음 라운드에서 트리가
    자라며 자연히 반경에 들어온다). 주얼 소켓의 가치는 장착 주얼이 있어야
    보이므로, 소켓을 평가하려면 spec.jewels에 후보 주얼을 미리 넣어둘 것.
    """
    measure = tuple(stats or objective.weights.keys())
    steps: list[Step] = []
    current = spec
    budget = point_budget
    with PobDaemon() as daemon:
        while budget > 0:
            tree_now = set(current.tree_nodes) | {graph.start_of(current.class_name)}
            cands = [
                nid
                for nid, _, d in graph.candidates(tree_now, max_dist=candidate_radius)
                if d <= budget
            ][:max_candidates_per_round]
            if not cands:
                break
            deltas = evaluate_node_deltas(current, graph, cands, stats=measure, daemon=daemon)
            base = daemon.compute_build(current)
            scored = sorted(
                ((objective.score(nd, base.stats), nd) for nd in deltas),
                key=lambda x: -x[0],
            )
            affordable = [(s, nd) for s, nd in scored if nd.points <= budget and s > 0]
            if not affordable:
                final = daemon.compute_build(current)
                return OptimizeResult(current, final, tuple(steps), rejected_rounds=1)
            best_score, best = affordable[0]
            current = dataclasses.replace(current, tree_nodes=tuple(current.tree_nodes) + best.path)
            budget -= best.points
            steps.append(Step(node_delta=best, score=best_score))
        final = daemon.compute_build(current)
    return OptimizeResult(current, final, tuple(steps), rejected_rounds=0)
