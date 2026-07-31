"""후보 노드의 PoB 델타 배치 실측 — P4 Phase 2 (AD-8 반프록시).

"이 빌드 문맥에서 노드 X(+연결 경로)를 추가하면 스탯이 얼마나 변하는가"를
상주 데몬으로 일괄 측정한다. 노드 가치는 여기서 나온 수치가 전부다 —
추측·휴리스틱 점수 금지. 연결 비용(경로)은 graph.py, 가치는 이 모듈.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec
from pok.pob.daemon import PobDaemon


@dataclass(frozen=True)
class NodeDelta:
    """후보 하나의 실측 결과. points = 실제 소모 포인트(연결 경로 포함)."""

    node_id: int
    name_en: str
    name_ko: str
    kind: str
    points: int
    path: tuple[int, ...]  # 추가로 할당된 노드들 (후보 자신 포함)
    deltas: dict[str, float]  # stat → (변경안 - 기준)

    def per_point(self, stat: str) -> float:
        return self.deltas.get(stat, 0.0) / max(self.points, 1)


def evaluate_node_deltas(
    spec: BuildSpec,
    graph: TreeGraph,
    candidates: list[int],
    *,
    stats: tuple[str, ...] = ("CombinedDPS", "Life", "TotalEHP"),
    daemon: PobDaemon | None = None,
) -> list[NodeDelta]:
    """후보들을 현재 트리에 최단 연결해 각각의 델타를 실측한다.

    잘린 노드(pruned)가 생기는 변경안은 결과에서 제외한다 — 측정 자체가
    무효이므로(요청한 트리가 반영되지 않음) 조용히 채택되면 안 된다.
    """
    base_tree = set(spec.tree_nodes) | {graph.start_of(spec.class_name)}
    own = daemon is None
    d = daemon or PobDaemon()
    out: list[NodeDelta] = []
    try:
        base = d.compute_build(spec)
        for cand in candidates:
            path = graph.shortest_path(base_tree, cand)
            if path is None or not path:
                continue  # 이미 트리에 있거나 도달 불가
            variant = dataclasses.replace(spec, tree_nodes=tuple(spec.tree_nodes) + tuple(path))
            result = d.compute_build(variant)
            if result.pruned_nodes:
                continue
            node = graph.nodes[cand]
            out.append(
                NodeDelta(
                    node_id=cand,
                    name_en=node.name_en,
                    name_ko=node.name_ko,
                    kind=node.kind,
                    points=len(path),
                    path=tuple(path),
                    deltas={k: result.stats.get(k, 0.0) - base.stats.get(k, 0.0) for k in stats},
                )
            )
    finally:
        if own:
            d.close()
    return out
