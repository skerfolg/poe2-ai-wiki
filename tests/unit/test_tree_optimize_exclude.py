"""`exclude_nodes` — 설계 판단으로 뺀 노드를 그리디가 다시 뽑지 않게 (제안 A 일부).

그리디는 배타 관계를 모른다. 실측 2026-08-09: 원소 집정관 축을 위해 「검은화염 계약」
(집정관의 `Cannot deal Non-Elemental Damage with Spells`와 정면 충돌)을 손으로 뺐는데,
재실행하자 남은 8포인트로 **그것과 「피의 제물」을 그대로 재채택**했다. PoB가 집정관을
모델링하지 않아(#3) 충돌이 점수에 안 보이기 때문이다.

배타 **감지**는 어렵지만 배타 **지정**은 호출자가 할 수 있다(AD-3: 판단은 호출자).
"""

from __future__ import annotations

import inspect
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from pok.engine.tree import optimize as opt
from pok.engine.tree.clusters import Cluster, ClusterHit
from pok.engine.tree.deltas import evaluate_bundles, evaluate_node_deltas
from pok.engine.tree.graph import TreeGraph, TreeNode
from pok.engine.tree.optimize import optimize_tree
from pok.pob.buildxml import BuildSpec


def test_exclude_nodes_seeds_the_banned_set() -> None:
    """목적지 재선택 금지에 더해 아래 행동 시험이 경유·묶음 누락(#177)을 막는다."""
    source = inspect.getsource(optimize_tree)
    assert "banned: set[int] = set(exclude_nodes)" in source
    signature = inspect.signature(optimize_tree)
    assert signature.parameters["exclude_nodes"].default == ()


def test_mcp_adapter_passes_exclusions_through() -> None:
    from pok.mcp.tools.tree import optimize_tree as mcp_optimize

    signature = inspect.signature(mcp_optimize)
    assert "exclude_nodes" in signature.parameters
    assert "검은화염 계약" in (mcp_optimize.__doc__ or ""), "왜 필요한지가 도구 설명에 있어야 한다"


@pytest.fixture
def graph() -> TreeGraph:
    """1 is the banned shortcut; 2 has a longer legal route, 6 has no alternative."""
    graph = object.__new__(TreeGraph)
    graph._asc_names = {}
    graph.nodes = {
        n: TreeNode(
            n, f"Node {n}", "", "notable" if n in (1, 2, 6) else "small", ("Fire Damage",), None
        )
        for n in (50986, 1, 2, 3, 4, 6)
    }
    graph.adj = {
        50986: {1, 3},
        1: {50986, 2, 6},
        2: {1, 4},
        3: {50986, 4},
        4: {3, 2},
        6: {1},
    }
    return graph


class _Daemon:
    transaction = staticmethod(nullcontext)

    def __init__(self) -> None:
        self.loaded_spec: BuildSpec | None = None
        self.measured: list[tuple[int, ...]] = []

    def compute_build(self, spec: BuildSpec) -> SimpleNamespace:
        self.loaded_spec = spec
        return self.compute_tree(spec.tree_nodes)

    def compute_tree(self, nodes: tuple[int, ...]) -> SimpleNamespace:
        self.measured.append(tuple(nodes))
        return SimpleNamespace(stats={"Life": 100.0 + 10 * len(nodes)}, pruned_nodes=())

    def node_power(self, stats: tuple[str, ...]) -> tuple[dict, dict]:
        return {n: {"CombinedDPS": 100.0} for n in (1, 2, 6)}, {}

    def __enter__(self) -> _Daemon:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


def _spec(nodes: tuple[int, ...] = ()) -> BuildSpec:
    return BuildSpec(class_name="Mercenary", ascendancy="Mercenary3", tree_nodes=nodes)


def test_excluded_target_and_transit_but_legal_detour_remains(graph: TreeGraph) -> None:
    excluded = frozenset({1})
    assert graph.shortest_path({50986}, 1, exclude_nodes=excluded) is None
    assert graph.shortest_path({50986}, 6, exclude_nodes=excluded) is None
    assert graph.shortest_path({50986}, 2, exclude_nodes=excluded) == [3, 4, 2]
    assert [(n, d) for n, _, d in graph.candidates({50986}, 3, exclude_nodes=excluded)] == [(2, 3)]
    assert graph.candidates({50986}, 2, exclude_nodes=excluded) == []


def test_node_delta_never_measures_an_excluded_transit(graph: TreeGraph) -> None:
    daemon = _Daemon()
    result = evaluate_node_deltas(
        _spec(),
        graph,
        [1, 2, 6],
        daemon=daemon,
        stats=("Life",),
        exclude_nodes=frozenset({1}),
    )
    assert [(r.node_id, r.path) for r in result] == [(2, (3, 4, 2))]
    assert all(1 not in tree for tree in daemon.measured)


def test_bundle_generation_and_measurement_keep_exclusion(graph: TreeGraph) -> None:
    excluded = frozenset({1})
    bundles = opt._far_destination_bundles(
        _spec(),
        graph,
        (("Fire", 1.0),),
        (),
        3,
        10,
        exclude_nodes=excluded,
    )
    assert [b["nodes"] for b in bundles] == [[2]]
    daemon = _Daemon()
    measured = evaluate_bundles(
        _spec(),
        graph,
        [*bundles, {"name": "blocked", "nodes": [1, 6]}],
        stats=("Life",),
        daemon=daemon,
        exclude_nodes=excluded,
    )
    assert measured[0].path == (3, 4, 2)
    assert measured[1].path == () and measured[1].unreachable == (1, 6)
    assert all(1 not in tree for tree in daemon.measured)
    scored = opt._bundle_candidates(
        _spec(),
        graph,
        opt.Objective(weights={"Life": 1}),
        daemon.compute_build(_spec()),
        3,
        daemon=daemon,
        stats=("Life",),
        include=(("Fire", 1),),
        exclude=(),
        limit=10,
        exclude_nodes=excluded,
    )
    assert len(scored) == 1 and scored[0][1].path == (3, 4, 2)


@pytest.mark.parametrize("power", [False, True])
@pytest.mark.parametrize("bundles", [False, True])
def test_optimizer_preserves_explicit_exclusion_in_every_candidate_route(
    graph: TreeGraph,
    monkeypatch: pytest.MonkeyPatch,
    power: bool,
    bundles: bool,
) -> None:
    daemon = _Daemon()
    monkeypatch.setattr(opt, "PobDaemon", lambda: daemon)
    result = optimize_tree(
        _spec(),
        graph,
        opt.Objective(weights={"Life": 1}),
        point_budget=3,
        candidate_radius=3,
        power_candidates=power,
        exclude_nodes=(1,),
        cluster_include=(("Fire", 1),) if bundles else (),
    )
    assert set(result.spec.tree_nodes) == {2, 3, 4}
    assert all(1 not in step.node_delta.path for step in result.steps)
    assert all(1 not in tree for tree in daemon.measured)


def test_anchor_connection_uses_legal_detour(graph: TreeGraph) -> None:
    spec, _, cost = opt._seed_anchors(
        _spec(),
        graph,
        (2,),
        3,
        exclude_nodes=frozenset({1}),
    )
    assert set(spec.tree_nodes) == {2, 3, 4} and cost.general == 3


def test_advisory_cluster_hits_also_omit_explicit_exclusions(
    graph: TreeGraph,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cluster = Cluster(
        (0, 0),
        1,
        0,
        "test",
        hits=tuple(ClusterHit(n, "", str(n), 1, ("Fire Damage",), (0, 0)) for n in (1, 2)),
    )
    monkeypatch.setattr(opt, "find_clusters", lambda *args, **kwargs: [cluster])
    far, _ = opt._scan_far_clusters(
        graph,
        _spec(),
        (("Fire", 1),),
        (),
        1,
        exclude_nodes=frozenset({1}),
    )
    assert len(far) == 1 and [h.node_id for h in far[0].hits] == [2]
    assert far[0].total_score == 1


@pytest.mark.parametrize("base,anchors", [((1,), ()), ((), (1,))])
def test_conflicting_exclusion_is_rejected_before_calculation(
    graph: TreeGraph,
    base: tuple[int, ...],
    anchors: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError, match="exclude_nodes conflicts"):
        optimize_tree(
            _spec(base),
            graph,
            opt.Objective(weights={"Life": 1}),
            point_budget=3,
            exclude_nodes=(1,),
            required_anchors=anchors,
        )
