"""Materialize caller-selected branch edits; never choose or score a build."""

from __future__ import annotations

import dataclasses
import math
import re
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from pok.engine.jewels import allocates_without_path, effective_radius
from pok.engine.tree.counterfactual import _no_path_zones, _reachable, _roots, _target_problem
from pok.engine.tree.graph import ASCENDANCY_POINTS, CLASS_START, GENERAL_POINTS, TreeGraph
from pok.engine.tree.optimize import start_nodes
from pok.pob.buildxml import ASCENDANCY_ID, BuildSpec, spec_from_dict


def _active_tree(spec: BuildSpec, nodes: set[int]) -> BuildSpec:
    return dataclasses.replace(
        spec,
        tree_nodes=tuple(sorted(nodes)),
        jewels=tuple(j for j in spec.jewels if j.socket_node_id in nodes),
    )


def _reach(spec: BuildSpec, graph: TreeGraph, nodes: set[int]) -> tuple[set[int], set[int]]:
    active = _active_tree(spec, nodes)
    enabled: set[int] = set()
    while True:
        supported = dataclasses.replace(
            active, jewels=tuple(j for j in active.jewels if j.socket_node_id in enabled)
        )
        roots = set(_roots(supported, graph)) | start_nodes(graph, supported)
        connected = _reachable(graph, frozenset(nodes | roots), roots)
        # Islands do not seed paths. A jewel cannot keep its own disconnected
        # socket alive through its radius or alternate-start permission.
        valid = connected | _no_path_zones(supported, graph)
        newly_enabled = {j.socket_node_id for j in active.jewels if j.socket_node_id in valid}
        if newly_enabled <= enabled:
            return connected, valid
        enabled.update(newly_enabled)


def _radius_protection(spec: BuildSpec, graph: TreeGraph) -> tuple[set[int], list[int]]:
    """Protect geometric bundles, not an estimate of which nodes are valuable."""
    guarded: set[int] = set()
    unknown: list[int] = []
    for jewel in spec.jewels:
        text = jewel.text or ""
        if not re.search(r"\bin\s+(?:(?:very\s+)?(?:small|medium|large)\s+)?radius\b", text, re.I):
            continue
        guarded.add(jewel.socket_node_id)
        if allocates_without_path(text):
            # This existing parser knows named/allocated keystone centers and
            # annular radii. The socket itself need not lie in that zone.
            guarded.update(
                _no_path_zones(
                    dataclasses.replace(spec, jewels=(jewel,)),
                    graph,
                    unresolved_sockets=unknown,
                )
            )
            continue
        ring = effective_radius(text)
        socket = graph.nodes[jewel.socket_node_id]
        if ring is None or socket.position is None:
            unknown.append(jewel.socket_node_id)
            continue
        inner, outer = ring
        for nid in spec.tree_nodes:
            node = graph.nodes.get(nid)
            if node is None or node.position is None or node.ascendancy:
                continue
            if inner <= math.dist(socket.position, node.position) <= outer:
                guarded.add(nid)
    return guarded, unknown


def prepare_tree_variant(
    build_spec: dict[str, Any],
    graph: TreeGraph,
    remove_nodes: Sequence[int],
    *,
    add_anchors: Sequence[int] = (),
    protect_nodes: Sequence[int] = (),
    point_budget: int = GENERAL_POINTS,
    protect_radius_nodes: bool = True,
) -> dict[str, Any]:
    """Remove specified nodes and disconnected branches, then connect specified anchors.

    Explicit removals remain forbidden to all new paths. Failure returns no spec.
    The successful spec keeps old evidence unchanged so normal staleness checks
    still apply. No oracle, candidate selection, or new optimization receipt runs.
    """
    issues: list[dict[str, Any]] = []
    changes: dict[str, Any] = {}

    def fail(code: str, detail: str, nodes: Sequence[int] = ()) -> dict[str, Any]:
        issues.append({"code": code, "detail": detail, "nodes": sorted(nodes)})
        return {"ok": False, "issues": issues, "changes": changes}

    if isinstance(point_budget, bool) or not isinstance(point_budget, int):
        return fail("invalid_budget", "point_budget must be an integer")
    if not 0 <= point_budget <= GENERAL_POINTS:
        return fail("invalid_budget", f"point_budget must be between 0 and {GENERAL_POINTS}")
    for name, values in (
        ("remove_nodes", remove_nodes),
        ("add_anchors", add_anchors),
        ("protect_nodes", protect_nodes),
    ):
        if any(isinstance(n, bool) or not isinstance(n, int) for n in values):
            return fail("invalid_node_id", f"{name} must contain integer node IDs")
    remove, anchors, explicit_protect = set(remove_nodes), set(add_anchors), set(protect_nodes)
    overlap = (remove & anchors) | (remove & explicit_protect) | (anchors & explicit_protect)
    if overlap:
        return fail(
            "conflicting_edits", "remove/add/protect lists must not overlap", sorted(overlap)
        )
    try:
        spec = spec_from_dict(build_spec, validate_catalog=False)
        graph.start_of(spec.class_name)
    except (KeyError, TypeError, ValueError) as error:
        return fail("invalid_spec", str(error))
    want = graph.resolve_ascendancy(spec.ascendancy)
    matching = [code for code in ASCENDANCY_ID if graph.resolve_ascendancy(code) == want]
    if spec.ascendancy and not any(code.startswith(spec.class_name) for code in matching):
        return fail("class_ascendancy_mismatch", "ascendancy does not belong to the stated class")
    allocated = set(spec.tree_nodes)
    known = set(graph.nodes) | set(CLASS_START.values())
    unknown = (allocated | remove | anchors | explicit_protect) - known
    if unknown:
        return fail("unknown_nodes", "cannot edit nodes absent from the graph", sorted(unknown))
    if missing := (remove | explicit_protect) - allocated:
        return fail(
            "unallocated_edit", "removal/protection requires an allocated node", sorted(missing)
        )
    automatic = set(_roots(spec, graph)) | start_nodes(graph, _active_tree(spec, allocated))
    if forbidden := (remove | anchors) & automatic:
        return fail(
            "automatic_node_edit",
            "automatic roots/granted nodes cannot be removed or added",
            sorted(forbidden),
        )
    if any(j.allocates for j in spec.jewels):
        return fail(
            "unsupported_jewel_allocates",
            "explicit JewelSpec.allocates requires a separate allocation edit",
        )
    for jewel in spec.jewels:
        node = graph.nodes.get(jewel.socket_node_id)
        if node is None or node.kind != "jewel-socket":
            return fail(
                "invalid_jewel_socket",
                "jewel socket is not a known socket node",
                [jewel.socket_node_id],
            )
        if jewel.socket_node_id not in allocated:
            return fail(
                "unallocated_jewel_socket",
                "baseline jewel is not in an allocated socket; no silent removal",
                [jewel.socket_node_id],
            )
    for nid in sorted(allocated - automatic):
        if problem := _target_problem(spec, graph, nid, frozenset(allocated | automatic)):
            return fail("invalid_baseline_node", problem, [nid])
    _, baseline_valid = _reach(spec, graph, allocated)
    if orphans := allocated - baseline_valid:
        return fail(
            "baseline_disconnected",
            "baseline has unsupported disconnected allocations; no silent removal",
            sorted(orphans),
        )

    radius_protect: set[int] = set()
    if protect_radius_nodes:
        radius_protect, unknown_radius = _radius_protection(spec, graph)
        if unknown_radius and (remove or anchors):
            return fail(
                "radius_geometry_unknown",
                "cannot protect a radius bundle without its radius/position; supply the "
                "missing declaration or use protect_radius_nodes=False with protect_nodes",
                unknown_radius,
            )
    protected = explicit_protect | radius_protect
    changes["protected_nodes"] = sorted(explicit_protect)
    changes["radius_protected_nodes"] = sorted(radius_protect)
    current = allocated - remove
    # Recompute active jewels/alternate starts/radius permissions after each cut.
    # Losing a socket may invalidate an island that was valid in the first pass.
    while True:
        _, valid = _reach(spec, graph, current)
        orphans = current - valid
        if not orphans:
            break
        current -= orphans
    changes["requested_removed"] = sorted(remove)
    changes["disconnected_removed"] = sorted((allocated - current) - remove)
    if lost := protected - current:
        return fail(
            "protected_nodes_removed",
            "edit would remove a protected node or its branch",
            sorted(lost),
        )

    pending = list(dict.fromkeys(add_anchors))
    paths: dict[str, list[int]] = {}
    while pending:
        active = _active_tree(spec, current)
        connected, _ = _reach(active, graph, current)
        roots = set(_roots(active, graph)) | start_nodes(graph, active)
        blocked = set(remove) | (set(CLASS_START.values()) - roots)
        for nid, node in graph.nodes.items():
            if (
                (node.ascendancy and graph.resolve_ascendancy(node.ascendancy) != want)
                or node.locked_to not in (None, want)
                or not set(node.requires_nodes) <= current | roots
            ):
                blocked.add(nid)
        progressed = False
        for target in pending:
            if _target_problem(active, graph, target, frozenset(current | roots)):
                continue
            if target in current:
                path: list[int] | None = []
            elif target in _no_path_zones(_active_tree(spec, current | {target}), graph):
                path = [target]
            else:
                path = graph.shortest_path(connected, target, exclude_nodes=blocked)
            if path is None:
                continue
            # Class/ascendancy starts and granted nodes are used for connectivity,
            # but need no new explicit allocation in the materialized build.
            new = [nid for nid in path if nid not in roots]
            current.update(new)
            paths[str(target)] = new
            pending.remove(target)
            progressed = True
            break
        if not progressed:
            for target in pending:
                issue = _target_problem(active, graph, target, frozenset(current | roots))
                issues.append(
                    {
                        "code": "anchor_unreachable",
                        "detail": issue or "no path avoiding explicit removals and locked nodes",
                        "nodes": [target],
                    }
                )
            return {"ok": False, "issues": issues, "changes": changes}

    final_roots = set(_roots(_active_tree(spec, current), graph)) | start_nodes(
        graph, _active_tree(spec, current)
    )
    for nid in sorted(current - final_roots):
        if problem := _target_problem(spec, graph, nid, frozenset(current | final_roots)):
            return fail("invalid_result_node", problem, [nid])
    _, final_valid = _reach(spec, graph, current)
    if orphans := current - final_valid:
        return fail(
            "result_disconnected",
            "edited allocations are not connected or supported radius islands",
            sorted(orphans),
        )
    # Match connect_anchors' output convention: never serialize automatic starts.
    omitted = {
        nid
        for nid in current
        if nid in CLASS_START.values()
        or (graph.nodes.get(nid) is not None and graph.nodes[nid].kind == "ascendancy-start")
    }
    current -= omitted
    changes.update(
        {
            "added_nodes": sorted(current - allocated),
            "removed_nodes": sorted(allocated - current),
            "paths": paths,
            "automatic_starts_omitted": sorted(omitted),
        }
    )
    before = graph.point_split(spec.ascendancy, allocated)
    after = graph.point_split(spec.ascendancy, current)
    after["general_budget"] = point_budget
    after.pop("over_budget", None)
    points = {
        "before": before,
        "after": after,
        "general_delta": after["general"] - before["general"],
        "ascendancy_delta": after["ascendancy"] - before["ascendancy"],
    }
    if after["general"] > point_budget or after["ascendancy"] > ASCENDANCY_POINTS:
        return {
            **fail(
                "point_budget_exceeded",
                "edited tree exceeds the stated general or ascendancy budget",
            ),
            "points": points,
        }
    out = deepcopy(build_spec)
    out["tree_nodes"] = sorted(current)
    removed_jewels = [j for j in out.get("jewels", []) if int(j["socket_node_id"]) not in current]
    if "jewels" in out:
        out["jewels"] = [j for j in out["jewels"] if int(j["socket_node_id"]) in current]
    choices = out.get("attribute_choices") or {}
    pairs = list(choices.items()) if isinstance(choices, dict) else list(choices)
    removed_choices = [[n, choice] for n, choice in pairs if int(n) not in current]
    kept_choices = [(n, choice) for n, choice in pairs if int(n) in current]
    if "attribute_choices" in out:
        out["attribute_choices"] = (
            dict(kept_choices)
            if isinstance(choices, dict)
            else [list(pair) for pair in kept_choices]
        )
    changes["removed_jewels"] = removed_jewels
    changes["removed_attribute_choices"] = removed_choices
    return {
        "ok": True,
        "spec": out,
        "changes": changes,
        "points": points,
        "issues": [],
        "measurement_required": True,
        "claim": "caller_selected_tree_edit_only",
    }
