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
from pok.pob.buildxml import BuildSpec, ItemSpec, JewelSpec
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


class _Measurer:
    """트리만 바뀌면 `compute_tree`, 그 외에는 `compute_build`으로 잰다 (#70 후속).

    루프는 노드만 바꾸는데 `compute_build`은 매번 빌드를 통째로 다시 올린다. 실측
    2026-08-13(블러드 메이지): 최소 0.38초 · 장비까지 0.60초 · **스킬까지 3.68초**
    — 스킬 재구성이 +3.16초인데 루프에서 한 번도 안 바뀐다. 데몬의 `TREE` 명령이
    그 재구성을 건너뛴다(3.15초 → 0.29초, **10.8배**).

    ⚠ **무엇이 올라가 있는지는 데몬에게 묻는다**(`daemon.loaded_spec`). `compute_tree`는
    「지금 로드된 빌드」의 트리를 갈아 끼우므로, 중간에 다른 스펙을 `compute_build`으로
    재면(예: 주얼을 꽂은 변형) 그 뒤의 `compute_tree`는 **엉뚱한 빌드 위에서 잰다**.
    이 상태를 측정기가 자기 안에 들고 있으면 안 된다 — `evaluate_bundles`가 안에서
    `evaluate_node_deltas`를 부르는 것처럼 호출자가 여러 겹이면 **바깥은 안쪽이 빌드를
    갈아 끼운 것을 모른다**. 상태를 아는 것은 데몬뿐이다.

    ⚠ **트리만 바뀐 것인지 판정은 「그 외 전부 같은가」로 한다.** 특히
    `attribute_choices`(→ XML `hashOverrides`)가 다르면 `compute_tree`로는 반영되지
    않는다 — 데몬이 로드된 빌드의 hashOverrides를 그대로 넘기기 때문이다. 그 경로로
    조용히 틀린 전력이 있다(2026-08-13: Accuracy 846 → 636, DPS 1.4% 차이).
    """

    def __init__(self, daemon: PobDaemon, base: BuildSpec) -> None:
        self._d = daemon
        self._base = base

    def base(self) -> Any:
        """기준 스펙을 통째로 올리고 잰다. 이후 `compute_tree`의 토대가 된다."""
        return self._d.compute_build(self._base)

    def measure(self, variant: BuildSpec) -> Any:
        loaded = self._d.loaded_spec
        if loaded is not None and _tree_only(loaded, variant):
            return self._d.compute_tree(tuple(variant.tree_nodes))
        if _tree_only(self._base, variant):
            # 다른 빌드가 올라가 있다 — 기준을 다시 올린 뒤 트리만 갈아 끼운다.
            # 재로드 1회를 더 쓰더라도 **엉뚱한 토대 위에서 재는 것보다 낫다**.
            self._d.compute_build(self._base)
            return self._d.compute_tree(tuple(variant.tree_nodes))
        return self._d.compute_build(variant)


def _tree_only(base: BuildSpec, variant: BuildSpec) -> bool:
    """`tree_nodes` 말고는 전부 같은가. 같아야 `compute_tree`가 옳다."""
    return dataclasses.replace(variant, tree_nodes=base.tree_nodes) == base


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
    m = _Measurer(d, spec)
    out: list[NodeDelta] = []
    try:
        base = m.base()
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
                # 주얼을 꽂는 변형은 **아이템이 바뀌므로** 통째로 로드해야 한다 —
                # `_Measurer`가 그 구분을 한다(빈 소켓 측정은 트리만 바뀐다).
                result = m.measure(variant)
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
    # **가는 길에 주운 것** — 경로에 딸려 들어온 목적지(요청 타깃이 아닌 노터블·
    # 키스톤·주얼 소켓). 유저가 길을 고를 때 실제로 세는 값이 이것이다(사용자 정리
    # 2026-08-12: "하나의 길에서 찍을 수 있는 노드가 많은 게 가치가 높은 길").
    # 포인트와 델타만 보면 같아 보이는 두 길이 여기서 갈린다.
    incidental: tuple[tuple[int, str], ...] = ()

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
    m = _Measurer(d, spec)
    out: list[BundleDelta] = []
    try:
        base = m.base()
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
            result = m.measure(variant)
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
                    incidental=tuple(
                        (nid, graph.nodes[nid].name_en)
                        for nid in reached
                        if nid not in nodes
                        and nid in graph.nodes
                        and graph.nodes[nid].kind in ("notable", "keystone", "jewel-socket")
                    ),
                )
            )
    finally:
        if own:
            d.close()
    return out


@dataclass(frozen=True)
class ChangeDelta:
    """변경안 하나의 실측 — 트리 노드·아이템·주얼을 **섞어** 넣을 수 있다."""

    name: str
    deltas: dict[str, float]
    sum_of_parts: dict[str, float]
    parts: tuple[str, ...]

    def synergy(self, stat: str) -> float:
        """묶음 델타 - 개별 합. 양수면 **함께여야 열리는 조합**이다."""
        return round(self.deltas.get(stat, 0.0) - self.sum_of_parts.get(stat, 0.0), 4)


def _apply_change(spec: BuildSpec, change: dict[str, Any], graph: TreeGraph) -> BuildSpec:
    """변경 하나를 스펙에 얹는다 — 아이템은 같은 슬롯을 **교체**한다."""
    out = spec
    if nodes := change.get("nodes"):
        base_tree = set(out.tree_nodes) | {graph.start_of(out.class_name)}
        added: list[int] = []
        grown = set(base_tree)
        for node_id in (int(n) for n in nodes):
            path = graph.shortest_path(grown, node_id)
            if path:
                added.extend(path)
                grown.update(path)
        out = dataclasses.replace(out, tree_nodes=tuple(out.tree_nodes) + tuple(added))
    if item := change.get("item"):
        slot = str(item["slot"])
        kept = tuple(i for i in out.items if i.slot != slot)
        out = dataclasses.replace(out, items=(*kept, ItemSpec(slot=slot, text=str(item["text"]))))
    if jewel := change.get("jewel"):
        out = dataclasses.replace(
            out,
            jewels=(
                *out.jewels,
                JewelSpec(socket_node_id=int(jewel["socket_node_id"]), text=str(jewel["text"])),
            ),
        )
    return out


def evaluate_change_bundle(
    spec: BuildSpec,
    graph: TreeGraph,
    changes: list[dict[str, Any]],
    *,
    name: str = "",
    stats: tuple[str, ...] = ("CombinedDPS", "Life", "TotalEHP"),
    daemon: PobDaemon | None = None,
) -> ChangeDelta:
    """변경들을 **동시에** 넣은 델타와 하나씩 넣은 델타의 합을 함께 낸다.

    `evaluate_bundles`가 트리 노드만 받는 데 비해 여기는 **아이템·주얼도 섞는다**.
    실측 2026-08-05: 눈알 왕관과 래스피스 구체가 각각 단독 델타 **정확히 0**인데
    함께 넣으면 **1.44배**였다. 아이템 단위 평가로는 둘 다 탈락한다.

    `synergy`(묶음 - 개별 합)가 양수면 임계를 넘겨야 열리는 조합이라는 신호다.
    **묶음 구성은 호출자가 한다**(AD-3) — 어떤 조합이 말이 되는가는 판단이다.

    changes = [{"item": {"slot","text"}}, {"nodes": [123]}, {"jewel": {...}}]
    """
    own = daemon is None
    d = daemon or PobDaemon()
    try:
        base = d.compute_build(spec).stats
        together = spec
        for change in changes:
            together = _apply_change(together, change, graph)
        combined = d.compute_build(together).stats
        parts_total = dict.fromkeys(stats, 0.0)
        labels: list[str] = []
        for change in changes:
            single = d.compute_build(_apply_change(spec, change, graph)).stats
            for key in stats:
                parts_total[key] += single.get(key, 0.0) - base.get(key, 0.0)
            labels.append(
                str(
                    (change.get("item") or {}).get("slot")
                    or (change.get("jewel") or {}).get("socket_node_id")
                    or change.get("nodes")
                )
            )
        return ChangeDelta(
            name=name or " + ".join(labels),
            deltas={k: round(combined.get(k, 0.0) - base.get(k, 0.0), 4) for k in stats},
            sum_of_parts={k: round(v, 4) for k, v in parts_total.items()},
            parts=tuple(labels),
        )
    finally:
        if own:
            d.close()
