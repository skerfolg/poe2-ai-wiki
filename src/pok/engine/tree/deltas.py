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
from typing import Any

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


@dataclass(frozen=True)
class BundleDelta:
    """묶음 하나의 실측 결과 — 노드들을 **동시에** 넣었을 때의 델타."""

    name: str
    nodes: tuple[int, ...]
    path: tuple[int, ...]  # 실제 추가된 노드 전량 (연결 경로 포함)
    points: int
    deltas: dict[str, float]
    # 같은 노드들을 하나씩 넣었을 때 델타의 합 — 묶음 효과를 드러내는 대조군
    sum_of_parts: dict[str, float]
    unreachable: tuple[int, ...] = ()

    def per_point(self, stat: str) -> float:
        return self.deltas.get(stat, 0.0) / max(self.points, 1)

    def synergy(self, stat: str) -> float:
        """묶음 델타 - 개별 합. 양수면 **임계를 넘겨야 열리는 축**이라는 신호다."""
        return round(self.deltas.get(stat, 0.0) - self.sum_of_parts.get(stat, 0.0), 4)


def evaluate_bundles(
    spec: BuildSpec,
    graph: TreeGraph,
    bundles: list[dict[str, Any]],
    *,
    stats: tuple[str, ...] = ("CombinedDPS", "Life", "TotalEHP"),
    daemon: PobDaemon | None = None,
) -> list[BundleDelta]:
    """묶음을 **통째로** 실측한다 — 노드 단위 그리디가 구조적으로 놓치는 것.

    "치명타 90% 달성"처럼 무기 접미·주얼·노터블을 **동시에** 갖춰야 값이 나오는
    축이 있다. 하나씩 넣어 보는 그리디는 각각의 델타가 작으면 전부 버리므로
    곱연산 축이 구조적으로 탈락한다(실측 2026-08-05: 가산 99포인트보다 치명타
    축 하나가 8.6배 컸는데 그리디로는 열리지 않았다).

    묶음 **구성은 호출자가 한다**(AD-3 — "어떤 조합이 말이 되는가"는 판단이다).
    여기서는 주어진 묶음을 결정적으로 재고, 개별 합과의 차이(`synergy`)를 함께
    내어 "묶어야 열리는지"를 보이기만 한다.

    bundles = [{"name": "치명타 90% 달성", "nodes": [123, 456]}]
    """
    base_tree = set(spec.tree_nodes) | {graph.start_of(spec.class_name)}
    own = daemon is None
    d = daemon or PobDaemon()
    out: list[BundleDelta] = []
    try:
        base = d.compute_build(spec)
        for bundle in bundles:
            nodes = tuple(int(n) for n in bundle.get("nodes", []))
            if not nodes:
                continue
            reached: list[int] = []
            unreachable: list[int] = []
            grown = set(base_tree)
            for node_id in nodes:
                path = graph.shortest_path(grown, node_id)
                if path is None:
                    unreachable.append(node_id)
                    continue
                # 앞 노드를 이미 넣은 상태에서 다음 경로를 잡는다 — 묶음 안에서
                # 경로가 겹치면 포인트가 중복 계산되지 않게
                reached.extend(path)
                grown.update(path)
            if not reached:
                out.append(
                    BundleDelta(
                        name=str(bundle.get("name", "")),
                        nodes=nodes,
                        path=(),
                        points=0,
                        deltas={},
                        sum_of_parts={},
                        unreachable=tuple(unreachable),
                    )
                )
                continue
            variant = dataclasses.replace(spec, tree_nodes=tuple(spec.tree_nodes) + tuple(reached))
            result = d.compute_build(variant)
            if result.pruned_nodes:
                continue  # 요청한 트리가 반영되지 않은 측정은 무효다
            parts = evaluate_node_deltas(spec, graph, list(nodes), stats=stats, daemon=d)
            sum_of_parts = {k: round(sum(p.deltas.get(k, 0.0) for p in parts), 4) for k in stats}
            out.append(
                BundleDelta(
                    name=str(bundle.get("name", "")),
                    nodes=nodes,
                    path=tuple(reached),
                    points=len(reached),
                    deltas={k: result.stats.get(k, 0.0) - base.stats.get(k, 0.0) for k in stats},
                    sum_of_parts=sum_of_parts,
                    unreachable=tuple(unreachable),
                )
            )
    finally:
        if own:
            d.close()
    return out
