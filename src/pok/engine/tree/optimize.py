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
    """가지치기로 제거된 가지 하나 — 끝단(죽은 노터블)+막다른 소노드 전체.

    끝단의 단독 기여 ~0이 확인되면 가지 전체를 환급한다: 소노드에 가치가
    있어도 막다른 길에 포인트를 쓰는 건 유저 관점에서 비합리적이므로
    (사용자 지적 2026-07-31), 환급 후 재투자 결과와 실측 비교해 나은 쪽을 취한다.
    """

    endpoint_id: int
    endpoint_name: str
    nodes: tuple[int, ...]  # 제거된 가지 전체 (끝단 포함)
    endpoint_removal_deltas: dict[str, float]  # 끝단 단독 제거 델타 (~0 = 죽음의 증거)


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
    banned: set[int] = set()  # 죽음이 실증된 끝단 — 재채택 금지 (종료 보장)
    current = spec
    budget = point_budget
    rejected = 0
    with PobDaemon() as daemon:
        best_solution: tuple[BuildSpec, PobResult] | None = None  # 단조성 안전장치
        while True:
            # ── 그리디 채택 ──
            rejected = 0
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
            result_now = daemon.compute_build(current)
            best_solution = _better(objective, best_solution, (current, result_now))
            # ── 가지치기: 죽은 끝단이면 막다른 가지 전체 제거·환급 ──
            current, newly_pruned, refund, candidates = _prune_dead_branches(
                spec, current, steps, graph, daemon, measure
            )
            for cand in candidates:  # 끝단만 뺀 중간 해들 — 무료 개선 후보
                best_solution = _better(objective, best_solution, cand)
            pruned.extend(newly_pruned)
            banned.update(p.endpoint_id for p in newly_pruned)
            if refund == 0:
                break  # 죽은 가지 없음 — 안정
            budget += refund  # 환급 포인트를 온전한 묶음에 재투자 (다음 루프)
        # 실측으로 가장 나은 해 반환 (동가치면 포인트 적게 쓴 쪽 — 스텁·죽은 끝단 배제)
        final = daemon.compute_build(current)
        best_solution = _better(objective, best_solution, (current, final))
        assert best_solution is not None
        current, final = best_solution
    return OptimizeResult(current, final, tuple(steps), tuple(pruned), rejected_rounds=rejected)


_PRUNE_EPS = 1e-6  # PoB는 결정적 — 죽은 노드의 제거 델타는 정확히 0


def _value(objective: Objective, result: PobResult) -> float:
    """해 비교용 절대 가치 (가중 합 — 동일 목적끼리의 비교에만 사용)."""
    return sum(w * result.stats.get(s, 0.0) for s, w in objective.weights.items())


_Solution = tuple[BuildSpec, PobResult]


def _better(obj: Objective, a: _Solution | None, b: _Solution) -> _Solution:
    """가치 우선, 동가치면 트리 노드가 적은(포인트를 덜 쓴) 쪽."""
    if a is None:
        return b
    va, vb = _value(obj, a[1]), _value(obj, b[1])
    if abs(va - vb) > _PRUNE_EPS:
        return a if va > vb else b
    return b if len(b[0].tree_nodes) < len(a[0].tree_nodes) else a


def _prune_dead_branches(
    original: BuildSpec,
    current: BuildSpec,
    steps: list[Step],
    graph: TreeGraph,
    daemon: PobDaemon,
    measure: tuple[str, ...],
) -> tuple[BuildSpec, list[Pruned], int, list[_Solution]]:
    """끝단(채택 노터블)의 단독 기여가 ~0이면 **막다른 가지 전체**를 제거한다.

    발견 배경(2026-07-31 실증): 채택 단위가 "노터블+경로" 묶음이라 경로
    소노드 가치에 죽은 노터블이 무임승차한다. 1차 수정(끝단만 제거)은
    가치 있는 소노드 스텁을 남겼는데, 막다른 길에 포인트를 쓰는 건 유저
    관점에서 비합리적(사용자 지적) — 가지 전체를 환급하고 상위 루프가
    재투자한다. 원래 스펙의 노드·분기점(다른 가지가 걸린 노드)은 보존.
    """
    protected = set(original.tree_nodes) | {s.node_delta.node_id for s in steps}
    start = graph.start_of(current.class_name)
    removed: list[Pruned] = []
    candidates: list[_Solution] = []  # "끝단만 뺀" 중간 해 — 무료 개선이므로 후보 등록
    eo_current = current  # 누적 "끝단만 제거" 해 (스텁 유지 + 죽은 끝단 전부 제외)
    base = daemon.compute_build(current)
    for step in steps:
        endpoint = step.node_delta.node_id
        if endpoint not in current.tree_nodes:
            continue  # 이전 라운드에서 이미 제거됨
        alloc = set(current.tree_nodes)
        if len([n for n in graph.adj[endpoint] if n in alloc or n == start]) > 1:
            continue  # 분기점이 된 끝단은 다른 가지의 통로 — 건드리지 않는다
        # ① 끝단 단독 제거로 죽음 판정
        probe = dataclasses.replace(
            current, tree_nodes=tuple(n for n in current.tree_nodes if n != endpoint)
        )
        probe_result = daemon.compute_build(probe)
        endpoint_deltas = {
            k: probe_result.stats.get(k, 0.0) - base.stats.get(k, 0.0) for k in measure
        }
        if any(abs(v) > _PRUNE_EPS for v in endpoint_deltas.values()):
            continue  # 끝단이 살아 있다 — 가지 유지
        eo_current = dataclasses.replace(
            eo_current, tree_nodes=tuple(n for n in eo_current.tree_nodes if n != endpoint)
        )
        candidates.append((eo_current, daemon.compute_build(eo_current)))
        # ② 막다른 가지 수집: 끝단에서 안쪽으로 차수 1 연쇄 (보호 노드 전까지)
        chain: list[int] = []
        cursor: int | None = endpoint
        alloc = set(current.tree_nodes)
        while cursor is not None:
            neighbors = [n for n in graph.adj[cursor] if n in alloc or n == start]
            if len(neighbors) > 1 or (cursor != endpoint and cursor in protected):
                break
            chain.append(cursor)
            alloc.discard(cursor)
            cursor = neighbors[0] if neighbors and neighbors[0] != start else None
        current = dataclasses.replace(
            current, tree_nodes=tuple(n for n in current.tree_nodes if n not in set(chain))
        )
        base = daemon.compute_build(current)
        node = graph.nodes.get(endpoint)
        removed.append(
            Pruned(
                endpoint_id=endpoint,
                endpoint_name=(node.name_ko or node.name_en) if node else str(endpoint),
                nodes=tuple(chain),
                endpoint_removal_deltas=endpoint_deltas,
            )
        )
    return current, removed, sum(len(p.nodes) for p in removed), candidates
