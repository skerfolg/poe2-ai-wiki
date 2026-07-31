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
class Pruned:
    """가지치기로 제거된 노드 — 단독 기여가 ~0임을 실측한 근거 포함."""

    node_id: int
    name: str
    removal_deltas: dict[str, float]  # 제거 시 스탯 변화 (죽은 노드면 전부 ~0)


@dataclass(frozen=True)
class OptimizeResult:
    spec: BuildSpec  # 최적화 후
    result: PobResult  # 최종 실측
    steps: tuple[Step, ...]  # 채택 순서대로 (각각 델타 근거)
    pruned: tuple[Pruned, ...]  # 가지치기로 회수된 죽은 노드들
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
    pruned: list[Pruned] = []
    banned: set[int] = set()  # 가지치기로 죽은 노드 판정 — 재채택 금지 (무한 루프 방지)
    current = spec
    budget = point_budget
    rejected = 0
    with PobDaemon() as daemon:
        while True:
            # ── 그리디 채택 ──
            while budget > 0:
                tree_now = set(current.tree_nodes) | {graph.start_of(current.class_name)}
                cands = [
                    nid
                    for nid, _, d in graph.candidates(tree_now, max_dist=candidate_radius)
                    if d <= budget and nid not in banned
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
                    rejected = 1
                    break
                best_score, best = affordable[0]
                current = dataclasses.replace(
                    current, tree_nodes=tuple(current.tree_nodes) + best.path
                )
                budget -= best.points
                steps.append(Step(node_delta=best, score=best_score))
            # ── 가지치기: 채택 끝단의 단독 기여 격리 → ~0이면 제거·환급 ──
            current, newly_pruned, refund = _prune_dead_ends(
                spec, current, steps, graph, objective, daemon, measure
            )
            pruned.extend(newly_pruned)
            banned.update(p.node_id for p in newly_pruned)
            if refund == 0 or rejected:
                break  # 환급 없으면 안정, 후보 소진이면 재탐색 무의미
            budget += refund
        final = daemon.compute_build(current)
    return OptimizeResult(current, final, tuple(steps), tuple(pruned), rejected_rounds=rejected)


_PRUNE_EPS = 1e-6  # PoB는 결정적 — 죽은 노드의 제거 델타는 정확히 0


def _prune_dead_ends(
    original: BuildSpec,
    current: BuildSpec,
    steps: list[Step],
    graph: TreeGraph,
    objective: Objective,
    daemon: PobDaemon,
    measure: tuple[str, ...],
) -> tuple[BuildSpec, list[Pruned], int]:
    """채택된 끝단 노드부터 안쪽으로, 제거해도 목적 손실이 없는 노드를 걷어낸다.

    발견 배경(2026-07-31 실증): 채택 단위가 "노터블+연결 경로" 묶음이라
    경로 소노드의 가치에 죽은 노터블(예: 미니언 조건 — 미니언 없는 빌드)이
    무임승차할 수 있다. 제거는 항상 실측으로 정당화한다 — 가치 있는 경로
    소노드는 손실이 측정되므로 남는다. 원래 스펙의 노드는 건드리지 않는다.
    """
    protected = set(original.tree_nodes) | {s.node_delta.node_id for s in steps}
    start = graph.start_of(current.class_name)
    removed: list[Pruned] = []
    base = daemon.compute_build(current)
    for step in steps:
        chain_head = step.node_delta.node_id
        cursor: int | None = chain_head
        while cursor is not None:
            alloc = set(current.tree_nodes)
            neighbors = [n for n in graph.adj[cursor] if n in alloc or n == start]
            if len(neighbors) > 1:  # 분기점 — 다른 가지가 걸려 있어 제거 불가
                break
            if cursor != chain_head and cursor in protected:
                break  # 다른 채택 노터블/원본 노드는 건드리지 않는다
            variant = dataclasses.replace(
                current, tree_nodes=tuple(n for n in current.tree_nodes if n != cursor)
            )
            result = daemon.compute_build(variant)
            if result.pruned_nodes:
                break  # 연결이 깨지면 제거 불가 (이론상 도달 안 함 — 방어)
            deltas = {k: result.stats.get(k, 0.0) - base.stats.get(k, 0.0) for k in measure}
            loss = sum(
                w * (deltas.get(s, 0.0) / max(abs(base.stats.get(s, 0.0)), 1.0))
                for s, w in objective.weights.items()
            )
            if loss < -_PRUNE_EPS:
                break  # 제거하면 손해 — 이 노드부터는 가치가 있다
            node = graph.nodes.get(cursor)
            removed.append(
                Pruned(
                    node_id=cursor,
                    name=(node.name_ko or node.name_en) if node else str(cursor),
                    removal_deltas=deltas,
                )
            )
            current = variant
            base = result
            cursor = neighbors[0] if neighbors and neighbors[0] != start else None
    return current, removed, len(removed)
