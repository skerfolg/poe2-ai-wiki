"""Readiness regression: final-context evidence must link without erasing gaps."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from pok.engine.optimization_readiness import measured_review_receipt, optimization_readiness
from pok.engine.tree.graph import TreeGraph, TreeNode


def graph() -> TreeGraph:
    result = object.__new__(TreeGraph)
    result._asc_names = {
        "monk2": "Invoker",
        "invoker": "Invoker",
        "monk1": "Chayula",
        "mercenary3": "Gemling",
    }
    result.nodes = {
        nid: TreeNode(nid, str(nid), str(nid), "small", (), owner)
        for nid, owner in [
            (1, None),
            (2, None),
            (7621, "Monk2"),
            (17268, "Monk2"),
            (23587, "Monk2"),
            (25434, "Monk2"),
            (999, "Mercenary3"),
            (888, "Monk1"),
        ]
    }
    return result


def spec() -> dict[str, Any]:
    return {
        "class_name": "Monk",
        "ascendancy": "Monk2",
        "level": 100,
        "tree_nodes": [1, 7621, 17268],
        "attribute_choices": {},
        "config": {},
        "items": [
            {"slot": "Body Armour", "text": "Iron4"},
            {"slot": "Boots", "text": "Rebirth2Iron1"},
            {"slot": "Belt", "text": "old belt"},
        ],
        "jewels": [],
        "skills": [{"gems": [{"id": "storm-wave", "quality": 20}]}],
    }


def receipt(base, variants, *, component="items", values=None, metadata=None):
    baseline = {"Life": 100.0, "ManaRegen": 100.0, "Evasion": 100.0}
    measurements = values or {name: dict(baseline) for name in variants}
    return measured_review_receipt(
        base,
        variants,
        measurements,
        component=component,
        stats=list(baseline),
        baseline_stats=baseline,
        unresolved=[],
        utility_baseline=baseline,
        utility_measurements=measurements,
        package_components=["items", "tree", "ascendancy"],
        tree_graph=metadata,
    )


@pytest.mark.parametrize("package", [False, True])
def test_ascendancy_reallocation_uses_actual_node_owners(package):
    base = spec()
    variant = deepcopy(base)
    variant["tree_nodes"] = [1, 23587, 25434]
    mark = measured_review_receipt(
        base,
        {"blizzard": variant},
        {"blizzard": {"Life": 100}},
        component="ascendancy",
        stats=["Life"],
        baseline_stats={"Life": 100},
        unresolved=[],
        package_components=["tree", "ascendancy"] if package else None,
        tree_graph=graph(),
    )
    evidence = mark["search_evidence"]
    assert evidence["scope"] == {
        "candidates": ["blizzard"],
        "tree_nodes": [17268, 23587, 25434, 7621],
        "ascendancies": ["Monk2"],
    }
    assert not evidence["unresolved"]


@pytest.mark.parametrize(
    "damage",
    [
        "ordinary",
        "unknown",
        "foreign_nodes",
        "foreign_class",
        "missing_graph",
        "wrong_level",
        "alias_only",
    ],
)
def test_unverified_or_ordinary_changes_never_certify_ascendancy(damage):
    base = spec()
    variant = deepcopy(base)
    variant["tree_nodes"] = [1, 23587, 25434]
    metadata = graph()
    if damage == "ordinary":
        variant["tree_nodes"] = [2, 7621, 17268]
    elif damage == "unknown":
        variant["tree_nodes"] = [1, 7621, 17268, 777]
    elif damage == "foreign_nodes":
        variant["tree_nodes"] = [1, 999]
    elif damage == "foreign_class":
        base["class_name"] = variant["class_name"] = "Witch"
    elif damage == "missing_graph":
        metadata = None
    elif damage == "alias_only":
        variant["tree_nodes"] = list(base["tree_nodes"])
        variant["ascendancy"] = "Invoker"
    else:
        variant["level"] = 99
    mark = receipt(base, {"other": variant}, component="ascendancy", metadata=metadata)
    assert not mark["search_evidence"]["scope"]


def test_ascendancy_identity_switch_requires_matching_allocations():
    base = spec()
    variant = deepcopy(base)
    variant["ascendancy"] = "Monk1"
    variant["tree_nodes"] = [1, 888]
    mark = receipt(base, {"chayula": variant}, component="ascendancy", metadata=graph())
    assert mark["search_evidence"]["scope"]["ascendancies"] == ["Monk1", "Monk2"]
    variant["tree_nodes"] = list(base["tree_nodes"])
    invalid = receipt(base, {"wrong_owner": variant}, component="ascendancy", metadata=graph())
    assert not invalid["search_evidence"]["scope"]


def c_style_final() -> tuple[dict[str, Any], dict[str, Any]]:
    old = spec()
    variants = {}
    for label, body, boots in [
        ("baseline", "Inspiration4", "Rebirth2Iron1"),
        ("boots_iron3", "Iron4", "Iron3"),
        ("body_iron3_inspiration1", "Iron3Inspiration1", "Rebirth2Iron1"),
        ("combined", "Iron3Inspiration1", "Iron3"),
    ]:
        candidate = deepcopy(old)
        candidate["items"][0]["text"] = body
        candidate["items"][1]["text"] = boots
        variants[label] = candidate
    values = {
        name: {
            "Life": 100.0,
            "ManaRegen": 146.1 if name == "baseline" else 111.5,
            "Evasion": 101.0 if name == "boots_iron3" else 100.0,
        }
        for name in variants
    }
    old["derived_from"] = {"items": receipt(old, variants, values=values)}
    history = deepcopy(old["derived_from"]["items"])
    final = deepcopy(old)
    final["items"][2]["text"] = "new belt"
    final["skills"][0]["gems"][0]["quality"] = 21
    current = {}
    for label, index, text in [
        ("boots_current", 1, "Iron3"),
        ("body_current", 0, "Iron3Inspiration1"),
    ]:
        candidate = deepcopy(final)
        candidate["items"][index]["text"] = text
        current[label] = candidate
    asc = deepcopy(final)
    asc["tree_nodes"] = [1, 23587, 25434]
    current["blizzard"] = asc
    final["derived_from"] = {
        component: receipt(final, current, component=component, metadata=graph())
        for component in ("items", "ascendancy")
    }
    final["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "items": {
                "scope": {"slots": ["Body Armour", "Boots"]},
                "allowed_termination_reasons": ["variants_evaluated"],
            },
            "ascendancy": {
                "scope": {"ascendancies": ["Monk2"]},
                "allowed_termination_reasons": ["variants_evaluated"],
            },
        },
    }
    return final, history


def test_c_history_keeps_three_real_gaps_and_links_only_two_remeasured_targets():
    final, history = c_style_final()
    original = deepcopy(final)
    result = optimization_readiness(final, purpose="recommendation")
    assert final == original
    assert result["status"] == "not_ready"
    assert len(result["blockers"]) == 3
    assert {(row["observed"]["label"], row["observed"]["slot"]) for row in result["blockers"]} == {
        ("baseline", "Body Armour"),
        ("combined", "Body Armour"),
        ("combined", "Boots"),
    }
    linked = result["utility_review"]["remeasured_history"]
    assert {(row["label"], row["remeasured_label"]) for row in linked} == {
        ("boots_iron3", "boots_current"),
        ("body_iron3_inspiration1", "body_current"),
    }
    retained = final["derived_from"]["items"]["search_evidence"]["utility_review_history"]
    assert retained[0]["receipt"] == history


@pytest.mark.parametrize("damage", ["different_target", "different_companion", "missing_axis"])
def test_remeasurement_requires_exact_target_owners_and_observed_axes(damage):
    final, _ = c_style_final()
    evidence = final["derived_from"]["items"]["search_evidence"]
    row = next(
        x
        for x in evidence["utility_review"]["measured_candidates"]
        if x["label"] == "boots_current"
    )
    if damage == "different_target":
        row["candidate_sha256"] = "another target"
    elif damage == "different_companion":
        row["change_sha256"] = "another changed slot package"
    else:
        row["observed_axes"] = [x for x in row["observed_axes"] if x != "Evasion"]
    result = optimization_readiness(final)
    assert any(
        row["code"] == "utility_context_unknown" and row["observed"]["label"] == "boots_iron3"
        for row in result["blockers"]
    )
