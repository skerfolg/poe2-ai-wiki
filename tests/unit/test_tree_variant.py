"""Caller-selected branch replacement must create a usable, accurately scoped spec."""

from __future__ import annotations

import asyncio
import collections
import dataclasses
from copy import deepcopy
from typing import Any

import pytest

from pok.engine.tree.graph import TreeGraph, TreeNode
from pok.engine.tree.variant import prepare_tree_variant

START = 44683


def _node(
    node_id: int,
    *,
    kind: str = "small",
    ascendancy: str | None = None,
    constraint: dict[str, object] | None = None,
    position: tuple[float, float] | None = None,
) -> TreeNode:
    return TreeNode(
        node_id, str(node_id), str(node_id), kind, ("test stat",), ascendancy, constraint, position
    )


@pytest.fixture
def graph() -> TreeGraph:
    out = TreeGraph.__new__(TreeGraph)
    out.nodes = {n: _node(n) for n in range(1, 21)}
    out.nodes[3] = _node(3, kind="jewel-socket", position=(0, 0))
    out.nodes[8] = _node(8, kind="notable", position=(100, 100))
    out.nodes[9] = _node(9, constraint={"ascendancy": "Blood Mage"})
    out.nodes[10] = _node(10, constraint={"nodes": [1]})
    out.nodes[11] = _node(11, constraint={"ascendancy": "Blood Mage"})
    out.nodes[100] = _node(100, kind="ascendancy-start", ascendancy="Monk2")
    out.nodes[101] = _node(101, kind="notable", ascendancy="Monk2")
    out.nodes[200] = _node(200, kind="ascendancy-start", ascendancy="Witch2")
    out.nodes[201] = _node(201, kind="notable", ascendancy="Witch2")
    out.nodes[8415] = _node(8415, kind="notable", ascendancy="Witch2")
    out._asc_names = {
        "monk2": "Invoker",
        "invoker": "Invoker",
        "witch2": "Blood Mage",
        "blood mage": "Blood Mage",
    }
    out.adj = collections.defaultdict(set)
    for a, b in [
        (START, 1),
        (1, 2),
        (2, 3),
        (2, 4),
        (START, 5),
        (5, 6),
        (6, 7),
        (2, 8),
        (5, 9),
        (5, 10),
        (5, 11),
        (11, 12),
        (6, 12),
        (100, 101),
        (200, 8415),
        (8415, 201),
        (54447, 1),
    ]:
        out.adj[a].add(b)
        out.adj[b].add(a)
    return out


def _spec() -> dict[str, Any]:
    return {
        "class_name": "Monk",
        "ascendancy": "Monk2",
        "level": 100,
        "tree_nodes": [1, 2, 3, 4, 5, 101],
        "jewels": [{"socket_node_id": 3, "text": "Rarity: RARE\nExisting\nEmerald"}],
        "attribute_choices": {"1": "int", "2": "dex", "4": "str"},
        "items": [],
        "skills": [],
        "derived_from": {"tree": {"old": "measurement context"}},
    }


def test_branch_edit_cleans_ghosts_preserves_evidence_and_input(graph: TreeGraph) -> None:
    base = _spec()
    original = deepcopy(base)
    result = prepare_tree_variant(
        base, graph, [2], add_anchors=[7], protect_nodes=[1], point_budget=5
    )
    assert result["ok"]
    assert result["spec"]["tree_nodes"] == [1, 5, 6, 7, 101]
    assert result["changes"]["requested_removed"] == [2]
    assert result["changes"]["disconnected_removed"] == [3, 4]
    assert result["changes"]["paths"] == {"7": [6, 7]}
    assert result["spec"]["jewels"] == []
    assert result["changes"]["removed_jewels"] == original["jewels"]
    assert result["spec"]["attribute_choices"] == {"1": "int"}
    assert result["changes"]["removed_attribute_choices"] == [["2", "dex"], ["4", "str"]]
    assert result["spec"]["derived_from"] == original["derived_from"]
    assert result["spec"]["derived_from"] is not base["derived_from"]
    assert result["points"]["after"]["general"] == 4
    assert result["points"]["after"]["ascendancy"] == 1
    assert result["measurement_required"] is True
    assert base == original


def test_requested_removal_cannot_be_readded_as_an_anchor_path(graph: TreeGraph) -> None:
    result = prepare_tree_variant(_spec(), graph, [2], add_anchors=[3])
    assert not result["ok"] and "spec" not in result
    assert result["issues"][0]["code"] == "anchor_unreachable"


@pytest.mark.parametrize("protected", [2, 3, 4])
def test_protected_node_or_branch_loss_returns_no_spec(graph: TreeGraph, protected: int) -> None:
    result = prepare_tree_variant(_spec(), graph, [2], protect_nodes=[protected])
    assert not result["ok"] and "spec" not in result
    assert result["issues"][0]["code"] == (
        "conflicting_edits" if protected == 2 else "protected_nodes_removed"
    )


def test_radius_bundle_and_its_socket_are_protected_unless_explicitly_disabled(
    graph: TreeGraph,
) -> None:
    base = _spec()
    base["tree_nodes"].append(8)
    base["jewels"][0]["text"] += "\nRadius: Small\nNotable Passive Skills in Radius grant test stat"
    protected = prepare_tree_variant(base, graph, [2])
    assert not protected["ok"]
    assert protected["changes"]["radius_protected_nodes"] == [3, 8]
    edited = prepare_tree_variant(base, graph, [2], protect_radius_nodes=False)
    assert edited["ok"] and edited["spec"]["jewels"] == []
    assert edited["changes"]["disconnected_removed"] == [3, 4, 8]


@pytest.mark.parametrize("kind", ["small", "notable"])
@pytest.mark.parametrize("center", ["socket", "named-keystone", "massive-ring"])
def test_radius_protection_uses_actual_center_ring_and_all_allocated_node_kinds(
    graph: TreeGraph, kind: str, center: str
) -> None:
    base = _spec()
    point = (50.0, 50.0)
    lines = (
        "Radius: Small\nPassives in Radius can be Allocated without being connected to your tree"
    )
    if center == "named-keystone":
        graph.nodes[19] = dataclasses.replace(
            _node(19, kind="keystone", position=(10000, 10000)), name_en="Remote Keystone"
        )
        point = (10050, 10050)
        lines = (
            "Radius: Small\nPassives in Radius of Remote Keystone can be Allocated "
            "without being connected to your tree"
        )
    elif center == "massive-ring":
        point = (2300, 0)
        lines = (
            "Radius: Variable\nOnly affects Passives in Massive Ring\n"
            "Passives in Radius can be Allocated without being connected to your tree"
        )
    graph.nodes[20] = _node(20, kind=kind, position=point)
    base["tree_nodes"].append(20)
    base["jewels"][0]["text"] += "\n" + lines
    protected = prepare_tree_variant(base, graph, [2])
    assert not protected["ok"] and "spec" not in protected
    assert protected["issues"][0]["code"] == "protected_nodes_removed"
    assert {3, 20} <= set(protected["changes"]["radius_protected_nodes"])
    intentional = prepare_tree_variant(base, graph, [2], protect_radius_nodes=False)
    assert intentional["ok"]
    assert intentional["spec"]["jewels"] == []
    assert 20 in intentional["changes"]["disconnected_removed"]


def test_radius_effect_protects_small_node_and_respects_inner_ring(graph: TreeGraph) -> None:
    base = _spec()
    graph.nodes[4] = _node(4, position=(50, 50))
    base["jewels"][0]["text"] += (
        "\nRadius: Small\nSmall Passive Skills in Radius also grant test stat"
    )
    protected = prepare_tree_variant(base, graph, [4])
    assert not protected["ok"]
    assert 4 in protected["changes"]["radius_protected_nodes"]
    base["jewels"][0]["text"] = base["jewels"][0]["text"].replace(
        "Radius: Small", "Radius: Variable\nOnly affects Passives in Massive Ring"
    )
    outside_ring = prepare_tree_variant(base, graph, [4])
    assert outside_ring["ok"]
    assert 4 not in outside_ring["changes"]["radius_protected_nodes"]


def test_very_large_radius_is_not_reduced_to_large(graph: TreeGraph) -> None:
    base = _spec()
    graph.nodes[4] = _node(4, position=(1700, 0))
    base["jewels"][0]["text"] += "\nRadius: Very Large\nPassives in Radius grant test stat"
    result = prepare_tree_variant(base, graph, [4])
    assert not result["ok"]
    assert 4 in result["changes"]["radius_protected_nodes"]


@pytest.mark.parametrize(
    "effect",
    [
        "Passives in Radius grant test stat",
        "Passives in Radius can be Allocated without being connected to your tree",
    ],
)
def test_unknown_radius_requires_geometry_or_explicit_protection_choice(
    graph: TreeGraph, effect: str
) -> None:
    base = _spec()
    graph.nodes[4] = _node(4, position=(50, 50))
    base["jewels"][0]["text"] += "\n" + effect
    result = prepare_tree_variant(base, graph, [4])
    assert not result["ok"] and "spec" not in result
    assert result["issues"][0]["code"] == "radius_geometry_unknown"
    intentional = prepare_tree_variant(
        base, graph, [4], protect_radius_nodes=False, protect_nodes=[3]
    )
    assert intentional["ok"] and intentional["spec"]["jewels"] == base["jewels"]


@pytest.mark.parametrize("with_center", [True, False])
def test_allocated_keystone_medium_radius_needs_no_separate_radius_declaration(
    graph: TreeGraph, with_center: bool
) -> None:
    base = _spec()
    graph.nodes[4] = _node(4, position=(50, 50))
    if with_center:
        graph.nodes[1] = _node(1, kind="keystone", position=(0, 0))
    base["jewels"][0]["text"] += (
        "\nPassives in medium radius of allocated keystone can be Allocated "
        "without being connected to your tree"
    )
    result = prepare_tree_variant(base, graph, [4])
    assert result["ok"] is not with_center
    if with_center:
        assert result["issues"][0]["code"] == "protected_nodes_removed"
    else:
        assert result["changes"]["radius_protected_nodes"] == [3]


@pytest.mark.parametrize("anchor", [9, 201, 999999])
def test_unknown_locked_or_foreign_ascendancy_anchors_fail(graph: TreeGraph, anchor: int) -> None:
    result = prepare_tree_variant(_spec(), graph, [], add_anchors=[anchor])
    assert not result["ok"] and "spec" not in result


def test_path_avoids_locked_intermediate_node(graph: TreeGraph) -> None:
    result = prepare_tree_variant(_spec(), graph, [], add_anchors=[12])
    assert result["ok"]
    assert result["changes"]["paths"]["12"] == [6, 12]
    assert 11 not in result["spec"]["tree_nodes"]


def test_missing_prerequisite_after_removal_fails_even_when_still_connected(
    graph: TreeGraph,
) -> None:
    base = _spec()
    base["tree_nodes"].append(10)
    result = prepare_tree_variant(base, graph, [1])
    assert not result["ok"]
    assert result["issues"][0]["code"] == "invalid_result_node"
    assert result["issues"][0]["nodes"] == [10]


def test_automatic_grant_is_free_and_cannot_be_removed(graph: TreeGraph) -> None:
    base = {"class_name": "Witch", "ascendancy": "Witch2", "tree_nodes": [1, 8415, 201]}
    result = prepare_tree_variant(base, graph, [], point_budget=1)
    assert result["ok"]
    assert result["points"]["after"]["general"] == 1
    assert result["points"]["after"]["ascendancy"] == 1
    assert result["points"]["after"]["ascendancy_free"] == 1
    removed = prepare_tree_variant(base, graph, [8415])
    assert not removed["ok"] and removed["issues"][0]["code"] == "automatic_node_edit"


def test_budget_excess_does_not_return_partial_spec(graph: TreeGraph) -> None:
    result = prepare_tree_variant(_spec(), graph, [], add_anchors=[7], point_budget=5)
    assert not result["ok"] and "spec" not in result
    assert result["issues"][0]["code"] == "point_budget_exceeded"
    assert result["points"]["after"]["general"] == 7


@pytest.mark.parametrize(
    "edit",
    [
        {"remove_nodes": [1], "add_anchors": [1]},
        {"remove_nodes": [], "add_anchors": [7], "protect_nodes": [7]},
        {"remove_nodes": [True]},
        {"remove_nodes": [7]},
    ],
)
def test_bad_edit_requests_are_explicit_failures(graph: TreeGraph, edit: dict[str, Any]) -> None:
    result = prepare_tree_variant(_spec(), graph, **edit)
    assert not result["ok"] and "spec" not in result


def test_preexisting_disconnected_nodes_are_not_silently_deleted(graph: TreeGraph) -> None:
    base = _spec()
    base["tree_nodes"].append(20)
    result = prepare_tree_variant(base, graph, [2])
    assert not result["ok"]
    assert result["issues"][0]["code"] == "baseline_disconnected"


def test_explicit_jewel_granted_allocations_are_reported_as_unsupported(graph: TreeGraph) -> None:
    base = _spec()
    base["jewels"][0]["allocates"] = [20]
    result = prepare_tree_variant(base, graph, [2])
    assert not result["ok"]
    assert result["issues"][0]["code"] == "unsupported_jewel_allocates"


def test_preexisting_unallocated_jewel_is_not_silently_deleted(graph: TreeGraph) -> None:
    base = _spec()
    base["tree_nodes"].remove(3)
    result = prepare_tree_variant(base, graph, [4])
    assert not result["ok"] and "spec" not in result
    assert result["issues"][0]["code"] == "unallocated_jewel_socket"


def test_radius_island_survives_until_its_socket_is_removed(graph: TreeGraph) -> None:
    base = _spec()
    graph.nodes[20] = _node(20, position=(50, 50))
    base["tree_nodes"].append(20)
    base["jewels"][0]["text"] += (
        "\nRadius: Small\nPassives in Radius can be Allocated without being connected to your tree"
    )
    preserved = prepare_tree_variant(base, graph, [4], protect_radius_nodes=False)
    assert preserved["ok"] and 20 in preserved["spec"]["tree_nodes"]
    removed = prepare_tree_variant(base, graph, [2], protect_radius_nodes=False)
    assert removed["ok"]
    assert 20 in removed["changes"]["disconnected_removed"]
    assert removed["spec"]["jewels"] == []


def test_radius_island_does_not_supply_a_path_to_neighbour(graph: TreeGraph) -> None:
    base = _spec()
    graph.nodes[20] = _node(20, position=(50, 50))
    graph.nodes[19] = _node(19, position=(10000, 10000))
    graph.adj[20].add(19)
    graph.adj[19].add(20)
    base["tree_nodes"].append(20)
    base["jewels"][0]["text"] += (
        "\nRadius: Small\nPassives in Radius can be Allocated without being connected to your tree"
    )
    result = prepare_tree_variant(base, graph, [], add_anchors=[19], protect_radius_nodes=False)
    assert not result["ok"]
    assert result["issues"][0]["code"] == "anchor_unreachable"


def test_alternate_start_is_revoked_when_its_connected_jewel_is_lost(graph: TreeGraph) -> None:
    base = _spec()
    graph.adj[47175].add(20)
    graph.adj[20].add(47175)
    base["tree_nodes"].append(20)
    base["jewels"][0]["text"] += "\nCan Allocate Passive Skills from the Warrior's starting point"
    kept = prepare_tree_variant(base, graph, [4])
    assert kept["ok"] and 20 in kept["spec"]["tree_nodes"]
    removed = prepare_tree_variant(base, graph, [2])
    assert removed["ok"]
    assert 20 in removed["changes"]["disconnected_removed"]


def test_list_attribute_choices_are_trimmed_without_changing_input_format(graph: TreeGraph) -> None:
    base = _spec()
    base["attribute_choices"] = [[1, "int"], [4, "str"]]
    result = prepare_tree_variant(base, graph, [2])
    assert result["ok"]
    assert result["spec"]["attribute_choices"] == [[1, "int"]]


def test_mcp_registration_executes_branch_edit(
    graph: TreeGraph, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastmcp import Client

    from pok.mcp.server import mcp
    from pok.mcp.tools import tree

    monkeypatch.setattr(tree, "_get_graph", lambda: graph)

    async def run() -> Any:
        async with Client(mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
            assert "prepare_tree_variant" in names
            return await client.call_tool(
                "prepare_tree_variant",
                {"build_spec": _spec(), "remove_nodes": [2], "add_anchors": [7], "point_budget": 5},
            )

    result = asyncio.run(run())
    assert not result.is_error
    assert result.data["ok"]
    assert result.data["spec"]["tree_nodes"] == [1, 5, 6, 7, 101]
