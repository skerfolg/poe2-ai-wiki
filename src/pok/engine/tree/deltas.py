"""후보 노드의 PoB 델타 배치 실측 — P4 Phase 2 (AD-8 반프록시).

"이 빌드 문맥에서 노드 X(+연결 경로)를 추가하면 스탯이 얼마나 변하는가"를
상주 데몬으로 일괄 측정한다. 노드 가치는 여기서 나온 수치가 전부다 —
추측·휴리스틱 점수 금지. 연결 비용(경로)은 graph.py, 가치는 이 모듈.

주얼 소켓: 빈 소켓은 델타 0이라 저평가된다(스킬 '주얼 선택 지침') —
jewel_templates를 주면 소켓 후보를 각 템플릿 가정 장착으로 실측하고,
가장 좋은 템플릿의 델타를 그 소켓의 NodeDelta로 삼는다(jewel_text에 기록).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass

from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, JewelSpec
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
    jewel_text: str | None = None  # jewel-socket 후보가 가정 장착한 템플릿 (그 외 None)

    def per_point(self, stat: str) -> float:
        return self.deltas.get(stat, 0.0) / max(self.points, 1)


def _relative_gain(nd: NodeDelta, base_stats: dict[str, float]) -> float:
    """템플릿 선택의 기본 기준 — 기준 대비 상대 이득 합 (스탯 스케일 차 흡수)."""
    return sum(v / max(abs(base_stats.get(k, 0.0)), 1.0) for k, v in nd.deltas.items())


def evaluate_node_deltas(
    spec: BuildSpec,
    graph: TreeGraph,
    candidates: list[int],
    *,
    stats: tuple[str, ...] = ("CombinedDPS", "Life", "TotalEHP"),
    daemon: PobDaemon | None = None,
    jewel_templates: tuple[str, ...] = (),
    jewel_score: Callable[[NodeDelta], float] | None = None,
) -> list[NodeDelta]:
    """후보들을 현재 트리에 최단 연결해 각각의 델타를 실측한다.

    잘린 노드(pruned)가 생기는 변경안은 결과에서 제외한다 — 측정 자체가
    무효이므로(요청한 트리가 반영되지 않음) 조용히 채택되면 안 된다.

    jewel-socket 후보는 jewel_templates 각각을 가정 장착(JewelSpec)해 실측하고,
    jewel_score(기본: 기준 대비 상대 이득 합) 최고인 템플릿의 델타를 채택한다 —
    빈 소켓 측정도 함께 두어 템플릿이 전부 무효/열세면 기존 동작으로 돌아간다.
    """
    base_tree = set(spec.tree_nodes) | {graph.start_of(spec.class_name)}
    own = daemon is None
    d = daemon or PobDaemon()
    out: list[NodeDelta] = []
    try:
        base = d.compute_build(spec)
        score = jewel_score or _partial_relative_gain(base.stats)
        for cand in candidates:
            path = graph.shortest_path(base_tree, cand)
            if path is None or not path:
                continue  # 이미 트리에 있거나 도달 불가
            node = graph.nodes[cand]
            texts: tuple[str | None, ...] = (None,)
            if node.kind == "jewel-socket" and jewel_templates:
                texts = (None, *jewel_templates)
            measured: list[NodeDelta] = []
            for text in texts:
                variant = dataclasses.replace(spec, tree_nodes=tuple(spec.tree_nodes) + tuple(path))
                if text is not None:
                    variant = dataclasses.replace(
                        variant, jewels=(*spec.jewels, JewelSpec(socket_node_id=cand, text=text))
                    )
                result = d.compute_build(variant)
                if result.pruned_nodes:
                    continue
                measured.append(
                    NodeDelta(
                        node_id=cand,
                        name_en=node.name_en,
                        name_ko=node.name_ko,
                        kind=node.kind,
                        points=len(path),
                        path=tuple(path),
                        deltas={
                            k: result.stats.get(k, 0.0) - base.stats.get(k, 0.0) for k in stats
                        },
                        jewel_text=text,
                    )
                )
            if measured:
                out.append(max(measured, key=score))
    finally:
        if own:
            d.close()
    return out


def _partial_relative_gain(base_stats: dict[str, float]) -> Callable[[NodeDelta], float]:
    """루프 밖에서 base_stats를 고정한 스코어러 (B023 회피 — 클로저를 루프에 두지 않는다)."""

    def score(nd: NodeDelta) -> float:
        return _relative_gain(nd, base_stats)

    return score
