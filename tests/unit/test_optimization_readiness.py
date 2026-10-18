"""A legal calculator build is not automatically an optimized recommendation."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from pok.engine.optimization_readiness import measured_review_receipt, optimization_readiness
from pok.engine.provenance import missing_procedures, stamp


def _spec() -> dict[str, Any]:
    return {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "level": 100,
        "tree_nodes": [1, 2],
        "attribute_choices": {"1": "str"},
        "config": {},
        "skills": [{"gems": [{"gem_id": "test", "level": 20, "quality": 20}]}],
        "items": [{"slot": "Weapon 1", "text": "A"}],
        "jewels": [],
    }


def _receipt(
    spec: dict[str, Any],
    component: str,
    *,
    scope: dict[str, Any],
    settings: dict[str, Any] | None = None,
    reason: str = "no_improvement",
    converged: bool = True,
    unresolved: list[Any] | None = None,
    revalidated_paths: list[str] | None = None,
) -> dict[str, Any]:
    mark = stamp(spec, component, tool=f"evaluate_{component}")
    mark["search_evidence"] = {
        "scope": scope,
        "settings": settings or {},
        "termination": {"reason": reason, "converged": converged},
        "unresolved": unresolved or [],
        "revalidated_paths": revalidated_paths or [],
    }
    return mark


def _ready() -> dict[str, Any]:
    spec = _spec()
    spec["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "items": {
                "scope": {"slots": ["Weapon 1", "Amulet", "Body Armour"]},
                "settings": {"max_rounds": {"min": 2}, "max_chain": {"min": 2}},
                "allowed_termination_reasons": ["no_improvement"],
            },
            "tree": {
                "scope": {"jewel_templates_used": True},
                "settings": {"base_general": {"max": 60}},
                "allowed_termination_reasons": ["point_budget"],
            },
        },
    }
    spec["derived_from"] = {
        "items": _receipt(
            spec,
            "items",
            scope={"slots": ["Weapon 1", "Amulet", "Body Armour"]},
            settings={"max_rounds": 3, "max_chain": 2},
        ),
        "tree": _receipt(
            spec,
            "tree",
            scope={"jewel_templates_used": True},
            settings={"base_general": 40},
            reason="point_budget",
            converged=False,
        ),
    }
    return spec


def _codes(report: dict[str, Any]) -> set[str]:
    return {row["code"] for row in report["blockers"]}


def _review_with_previous_search() -> tuple[dict[str, Any], dict[str, Any]]:
    spec = _spec()
    original = stamp(
        spec,
        "items",
        tool="optimize_items",
        search_evidence={
            "scope": {"slots": ["Weapon 1", "Helmet", "Gloves"]},
            "settings": {"max_rounds": 2, "max_chain": 2},
            "termination": {"reason": "round_limit", "converged": False},
            "unresolved": [{"code": "old_limit", "scope": ["Helmet"]}],
        },
    )
    spec["derived_from"] = {"items": original}
    spec["config"]["enemyLevel"] = 82  # The earlier search belongs to an old context.
    _replace_with_review(spec)
    spec["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "items": {
                "scope": {"slots": ["Weapon 1"]},
                "allowed_termination_reasons": ["variants_evaluated"],
            }
        },
    }
    return spec, original


def _replace_with_review(spec: dict[str, Any]) -> None:
    variant = copy.deepcopy(spec)
    variant["items"][0]["text"] = "Alternative weapon"
    spec["derived_from"]["items"] = measured_review_receipt(
        spec,
        {"weapon": variant},
        {"weapon": {"Life": 101}},
        component="items",
        stats=["Life"],
        baseline_stats={"Life": 100},
        unresolved=[],
    )


def test_review_preserves_original_search_and_digest_without_aliasing() -> None:
    spec, original = _review_with_previous_search()
    saved = copy.deepcopy(original)
    history = spec["derived_from"]["items"]["execution_history"]
    digest = hashlib.sha256(
        json.dumps(saved, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert history == [{"receipt_sha256": digest, "receipt": saved}]
    assert missing_procedures(spec) == []
    assert optimization_readiness(spec)["status"] == "ready"
    original["search_evidence"]["scope"]["slots"].append("Belt")
    assert history[0]["receipt"] == saved


def test_repeated_reviews_keep_one_unchanged_original_execution_receipt() -> None:
    spec, _ = _review_with_previous_search()
    history = copy.deepcopy(spec["derived_from"]["items"]["execution_history"])
    _replace_with_review(spec)
    assert spec["derived_from"]["items"]["execution_history"] == history
    assert missing_procedures(spec) == []


def test_partial_history_is_not_current_scope_settings_or_termination_evidence() -> None:
    spec, _ = _review_with_previous_search()
    rule = spec["optimization_contract"]["required_components"]["items"]
    rule["scope"]["slots"] = [
        "Weapon 1",
        "Helmet",
        "Gloves",
        "Boots",
        "Belt",
        "Amulet",
        "Ring 1",
        "Ring 2",
        "Body Armour",
    ]
    rule["settings"] = {"max_rounds": {"min": 2}, "max_chain": {"min": 2}}
    rule["allowed_termination_reasons"] = ["round_limit"]
    assert missing_procedures(spec) == []  # Some search ran; no completeness claim.
    report = optimization_readiness(spec, purpose="recommendation")
    assert not report["recommendation_ready"]
    scope = next(row for row in report["blockers"] if row["code"] == "scope_missing")
    assert "Helmet" in scope["expected"]  # Even the old three slots are not inherited.
    assert len(scope["expected"]) == 8
    assert {"settings_mismatch", "termination_not_allowed"} <= _codes(report)


@pytest.mark.parametrize("damage", ["missing_history", "wrong_digest", "changed_original"])
def test_review_without_intact_original_does_not_claim_prior_search(damage: str) -> None:
    spec, _ = _review_with_previous_search()
    mark = spec["derived_from"]["items"]
    if damage == "missing_history":
        del mark["execution_history"]
    elif damage == "wrong_digest":
        mark["execution_history"][0]["receipt_sha256"] = "bad"
    else:
        mark["execution_history"][0]["receipt"]["search_evidence"]["scope"]["slots"] = []
    assert [row["procedure"] for row in missing_procedures(spec)] == ["optimize_items"]


def test_captured_gemling_cannot_be_promoted_by_a_partial_items_stamp() -> None:
    """Portable original data: no ignored artifacts or local PoB installation needed."""
    path = Path(__file__).with_name("gemling_20261012_readiness.json")
    fixture = json.loads(path.read_text(encoding="utf-8"))
    spec = copy.deepcopy(fixture["source_spec"])
    assert "contract_missing" in _codes(optimization_readiness(spec, purpose="recommendation"))
    spec["optimization_contract"] = _ready()["optimization_contract"]
    spec["derived_from"]["items"] = fixture["partial_items_stamp"]
    report = optimization_readiness(spec, purpose="recommendation")
    assert report["recommendation_ready"] is False
    assert "evidence_missing" in _codes(report)
    assert {"stale_evidence", "context_unverified"} & _codes(report)
    assert fixture["original_delivery_all_pass"] is True


def test_current_partial_scope_does_not_satisfy_a_larger_plan() -> None:
    spec = _ready()
    spec["optimization_contract"]["required_components"]["items"]["scope"]["slots"].extend(
        ["Helmet", "Gloves", "Boots", "Belt", "Jewel"]
    )
    report = optimization_readiness(spec, purpose="recommendation")
    assert report["recommendation_ready"] is False
    assert _codes(report) == {"scope_missing"}
    assert report["blockers"][0]["expected"] == ["Helmet", "Gloves", "Boots", "Belt", "Jewel"]


def test_declared_budget_stop_can_be_ready_without_claiming_global_convergence() -> None:
    report = optimization_readiness(_ready(), purpose="recommendation")
    assert report["status"] == "ready"
    assert report["recommendation_ready"] is True
    assert "not_global_optimum" in report["claim"]


def test_undeclared_stop_and_protected_base_limit_fail() -> None:
    spec = _ready()
    evidence = spec["derived_from"]["tree"]["search_evidence"]
    evidence["termination"]["reason"] = "time_budget"
    evidence["settings"]["base_general"] = 106
    assert _codes(optimization_readiness(spec)) == {"termination_not_allowed", "settings_mismatch"}


def test_convergence_must_be_proved_when_requested() -> None:
    spec = _ready()
    spec["optimization_contract"]["required_components"]["tree"]["require_converged"] = True
    assert _codes(optimization_readiness(spec)) == {"not_converged"}


def test_exact_scope_exception_is_visible_and_does_not_cover_later_expansion() -> None:
    spec = _ready()
    expected = spec["optimization_contract"]["required_components"]["items"]["scope"]["slots"]
    expected.append("Belt")
    issue = optimization_readiness(spec)["blockers"][0]
    spec["optimization_contract"]["exceptions"] = [
        {"issue_id": issue["issue_id"], "reason": "Belt is fixed by the requested experiment."}
    ]
    report = optimization_readiness(spec)
    assert report["status"] == "ready_with_exceptions"
    assert report["accepted_exceptions"][0]["expected"] == ["Belt"]
    assert report["qualification"]["kind"] == "explicit_exceptions"
    assert report["qualification"]["known_limitations"][0]["expected"] == ["Belt"]
    expected.append("Helmet")
    assert _codes(optimization_readiness(spec)) == {"scope_missing", "invalid_contract"}


@pytest.mark.parametrize(
    "contract",
    [
        None,
        {},
        {"version": 1, "required_components": {}},
        {"version": 2, "required_components": {"items": {}}},
    ],
)
def test_missing_or_empty_contract_cannot_be_a_final_recommendation(contract: Any) -> None:
    spec = _spec()
    spec["optimization_contract"] = contract
    assert optimization_readiness(spec, purpose="recommendation")["recommendation_ready"] is False


def test_generic_evaluation_receipts_support_user_declared_components() -> None:
    spec = _spec()
    required = {}
    marks = {}
    for component in ("supports", "ascendancy", "jewels"):
        scope = {"candidates": [f"{component}-a", f"{component}-b"]}
        required[component] = {"scope": scope, "allowed_termination_reasons": ["exhausted"]}
        marks[component] = _receipt(spec, component, scope=scope, reason="exhausted")
    spec["optimization_contract"] = {"version": 1, "required_components": required}
    spec["derived_from"] = marks
    assert optimization_readiness(spec)["status"] == "ready"


def test_unmeasured_evidence_blocks_until_exactly_disclosed() -> None:
    spec = _ready()
    spec["derived_from"]["items"]["search_evidence"]["unresolved"] = [
        {"code": "unparsed", "scope": ["item.example"], "detail": "A modifier is unmodeled."}
    ]
    report = optimization_readiness(spec)
    assert _codes(report) == {"unresolved_evidence"}
    spec["optimization_contract"]["exceptions"] = [
        {"issue_id": report["blockers"][0]["issue_id"], "reason": "Explicitly excluded comparison."}
    ]
    qualified = optimization_readiness(spec)
    assert qualified["status"] == "ready_with_exceptions"
    assert qualified["qualification"]["known_limitations"][0]["observed"]["scope"] == [
        "item.example"
    ]


def test_nested_stale_is_not_waived_by_a_reason_but_current_review_can_cover_exact_path() -> None:
    spec = _ready()
    spec["items"][0]["derived_from"] = {"rares": stamp(spec, "rares", tool="optimize_rare")}
    spec["skills"][0]["gems"][0]["quality"] = 21
    for component in ("items", "tree"):
        evidence = spec["derived_from"][component]["search_evidence"]
        spec["derived_from"][component] = stamp(spec, component, tool=f"evaluate_{component}")
        spec["derived_from"][component]["search_evidence"] = evidence
    report = optimization_readiness(spec)
    assert "stale_evidence" in _codes(report)
    issue = next(row for row in report["blockers"] if row["code"] == "stale_evidence")
    spec["optimization_contract"]["exceptions"] = [
        {"issue_id": issue["issue_id"], "reason": "Ignore this old receipt."}
    ]
    assert "invalid_contract" in _codes(optimization_readiness(spec))
    del spec["optimization_contract"]["exceptions"]
    path = "items[0].derived_from.rares"
    spec["derived_from"]["items"]["search_evidence"]["revalidated_paths"] = [path]
    assert "stale_evidence" in _codes(optimization_readiness(spec)), "caller paths are not evidence"
    variant = copy.deepcopy(spec)
    variant["items"][0]["text"] = "Actually compared alternative"
    spec["derived_from"]["items"] = measured_review_receipt(
        spec,
        {"weapon": variant},
        {"weapon": {"Life": 101}},
        component="items",
        stats=["Life"],
        baseline_stats={"Life": 100},
        unresolved=[],
    )
    spec["optimization_contract"]["required_components"]["items"] = {
        "scope": {"slots": ["Weapon 1"], "candidates": ["weapon"]},
        "allowed_termination_reasons": ["variants_evaluated"],
    }
    report = optimization_readiness(spec)
    assert report["status"] == "ready"
    assert report["revalidated_paths"] == {path: "derived_from.items"}


def test_invalid_purpose_does_not_silently_fall_back_to_exploration() -> None:
    with pytest.raises(ValueError, match="purpose"):
        optimization_readiness(_ready(), purpose="recomendation")


def test_missing_unresolved_declaration_is_not_an_implicit_clean_bill() -> None:
    spec = _ready()
    del spec["derived_from"]["items"]["search_evidence"]["unresolved"]
    assert _codes(optimization_readiness(spec)) == {"invalid_evidence"}


@pytest.mark.parametrize("component", ["items", "tree"])
def test_modified_producer_output_cannot_reuse_its_old_search_evidence(component: str) -> None:
    spec = _ready()
    if component == "items":
        spec["items"][0]["text"] = "An unevaluated replacement"
        other = "tree"
    else:
        spec["tree_nodes"].append(999)
        other = "items"
    # Refresh the other receipt to isolate the producer's normally-excluded own axis.
    evidence = spec["derived_from"][other]["search_evidence"]
    spec["derived_from"][other] = stamp(
        spec, other, tool=f"evaluate_{other}", search_evidence=evidence
    )
    report = optimization_readiness(spec)
    assert _codes(report) == {"output_changed"}
    spec["optimization_contract"]["exceptions"] = [
        {"issue_id": report["blockers"][0]["issue_id"], "reason": "Reused the previous search."}
    ]
    assert "invalid_contract" in _codes(optimization_readiness(spec))


@pytest.mark.parametrize("field", ["scope", "settings", "termination"])
def test_missing_search_execution_fields_cannot_be_waived(field: str) -> None:
    spec = _ready()
    del spec["derived_from"]["items"]["search_evidence"][field]
    report = optimization_readiness(spec)
    spec["optimization_contract"]["exceptions"] = [
        {"issue_id": row["issue_id"], "reason": "No execution record was retained."}
        for row in report["blockers"]
    ]
    assert optimization_readiness(spec)["recommendation_ready"] is False
    assert "invalid_contract" in _codes(optimization_readiness(spec))


@pytest.mark.parametrize("value", [None, ""])
def test_empty_scalar_scope_is_not_a_meaningful_contract(value: Any) -> None:
    spec = _ready()
    spec["optimization_contract"]["required_components"]["items"]["scope"] = {"slots": value}
    spec["derived_from"]["items"]["search_evidence"]["scope"] = {"slots": value}
    assert "invalid_contract" in _codes(optimization_readiness(spec))


def _reviewable_items() -> dict[str, Any]:
    spec = _spec()
    spec["items"].append({"slot": "Helmet", "text": "H"})
    for item in spec["items"]:
        item["derived_from"] = {"rares": stamp(spec, "rares", tool="optimize_rare")}
    spec["config"]["enemyLevel"] = 82
    variant = copy.deepcopy(spec)
    variant["items"][0]["text"] = "Alternative weapon"
    spec["derived_from"] = {
        "items": measured_review_receipt(
            spec,
            {"weapon": variant},
            {"weapon": {"Life": 101}},
            component="items",
            stats=["Life"],
            baseline_stats={"Life": 100},
            unresolved=[],
        )
    }
    spec["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "items": {
                "scope": {"slots": ["Weapon 1"]},
                "allowed_termination_reasons": ["variants_evaluated"],
            }
        },
    }
    return spec


def test_measured_review_only_covers_the_owner_that_was_actually_changed() -> None:
    spec = _reviewable_items()
    report = optimization_readiness(spec)
    assert "items[0].derived_from.rares" in report["revalidated_paths"]
    assert "items[1].derived_from.rares" not in report["revalidated_paths"]
    assert "stale_evidence" in _codes(report)


def test_reordering_items_cannot_retarget_a_measured_review() -> None:
    spec = _reviewable_items()
    spec["items"].reverse()
    report = optimization_readiness(spec)
    assert not report["revalidated_paths"]
    assert "invalid_revalidation" in _codes(report)


def test_changed_original_receipt_cannot_reuse_its_review() -> None:
    spec = _reviewable_items()
    spec["items"][0]["derived_from"]["rares"]["tool"] = "another_source"
    assert "invalid_revalidation" in _codes(optimization_readiness(spec))


def test_support_review_cannot_clear_old_item_provenance() -> None:
    spec = _reviewable_items()
    item_receipt = spec["derived_from"]["items"]
    variant = copy.deepcopy(spec)
    variant["skills"][0]["gems"][0]["quality"] += 1
    mark = measured_review_receipt(
        spec,
        {"gem": variant},
        {"gem": {"Life": 101}},
        component="supports",
        stats=["Life"],
        baseline_stats={"Life": 100},
        unresolved=[],
    )
    mark["search_evidence"]["revalidation_receipts"] = item_receipt["search_evidence"][
        "revalidation_receipts"
    ]
    spec["derived_from"] = {"supports": mark}
    spec["optimization_contract"]["required_components"] = {
        "supports": {
            "scope": {"skill_groups": [1]},
            "allowed_termination_reasons": ["variants_evaluated"],
        }
    }
    report = optimization_readiness(spec)
    assert not report["revalidated_paths"]
    assert "invalid_revalidation" in _codes(report)


def test_unchanged_or_confounded_variants_do_not_certify_scope() -> None:
    spec = _spec()
    variant = copy.deepcopy(spec)
    variant["items"][0]["text"] = "B"
    variant["config"]["arbitrary"] = True
    mark = measured_review_receipt(
        spec,
        {"same": spec, "confounded": variant},
        {"same": {"Life": 100}, "confounded": {"Life": 101}},
        component="items",
        stats=["Life"],
        baseline_stats={"Life": 100},
        unresolved=[],
    )
    evidence = mark["search_evidence"]
    assert not evidence["scope"]
    assert not evidence["revalidation_receipts"]
    assert len(evidence["unresolved"]) == 3


def test_jewel_review_binds_socket_and_original_receipt() -> None:
    spec = _spec()
    spec["jewels"] = [{"socket_node_id": 123, "text": "Ruby A"}]
    spec["jewels"][0]["derived_from"] = {"jewels": stamp(spec, "jewels", tool="optimize_jewels")}
    spec["config"]["enemyLevel"] = 82
    variant = copy.deepcopy(spec)
    variant["jewels"][0]["text"] = "Ruby B"
    spec["derived_from"] = {
        "jewels": measured_review_receipt(
            spec,
            {"ruby": variant},
            {"ruby": {"Life": 101}},
            component="jewels",
            stats=["Life"],
            baseline_stats={"Life": 100},
            unresolved=[],
        )
    }
    spec["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "jewels": {
                "scope": {"jewel_sockets": [123]},
                "allowed_termination_reasons": ["variants_evaluated"],
            }
        },
    }
    report = optimization_readiness(spec)
    assert report["status"] == "ready"
    assert report["revalidated_paths"] == {"jewels[0].derived_from.jewels": "derived_from.jewels"}


@pytest.mark.parametrize("field", ["tool", "items_sig", "item_activity_sig"])
def test_missing_producer_or_output_binding_is_not_ready(field: str) -> None:
    spec = _ready()
    del spec["derived_from"]["items"][field]
    assert "invalid_evidence" in _codes(optimization_readiness(spec))


def test_known_model_limit_keeps_real_measurement_but_requires_exact_exception() -> None:
    spec = _reviewable_items()
    del spec["items"][1]["derived_from"]
    evidence = spec["derived_from"]["items"]["search_evidence"]
    evidence["unresolved"] = [
        {"code": "items_pob_gaps", "scope": ["baseline"], "observed": ["unmodeled utility"]}
    ]
    report = optimization_readiness(spec)
    assert _codes(report) == {"unresolved_evidence"}
    assert report["revalidated_paths"]
    spec["optimization_contract"]["exceptions"] = [
        {
            "issue_id": report["blockers"][0]["issue_id"],
            "reason": "Comparison excludes the listed utility; its value is not assumed zero.",
        }
    ]
    assert optimization_readiness(spec)["status"] == "ready_with_exceptions"
    # An actually missing numerical measurement must never clear an old receipt.
    del spec["optimization_contract"]["exceptions"]
    evidence["unresolved"][0]["code"] = "unmeasured_stats"
    assert "stale_evidence" in _codes(optimization_readiness(spec))


def _utility_spec(*, count: int = 1) -> dict[str, Any]:
    from pok.engine.valuation import utility_candidate_digest

    spec = _ready()
    evidence = spec["derived_from"]["items"]["search_evidence"]
    evidence["termination"]["rounds_evaluated"] = 3
    evidence["termination"]["unscored_utility_gains_observed"] = bool(count)
    evidence["utility_review"] = {
        "last_round_matches_returned_spec": True,
        "utility_gain_candidate_count": count,
        "last_round_utility_gain_candidate_count": count,
        "utility_gain_candidate_ids": [
            {
                "label": f"utility-{index}",
                "slot": "Weapon 1",
                "round": 3,
                "candidate_sha256": utility_candidate_digest(f"B{index}"),
                "utility_gains": {"MovementSpeedMod": 0.3},
            }
            for index in range(count)
        ],
    }
    return spec


def _decide_utility(spec: dict[str, Any], decision: str = "reject") -> None:
    report = optimization_readiness(spec, purpose="recommendation")
    spec["optimization_contract"]["utility_decisions"] = [
        {
            **row,
            "decision": decision,
            "reason": "Retain baseline: this alternative spends the damage budget for movement.",
        }
        for row in report["utility_review"]["required_decisions"]
    ]


def test_observed_utility_blocks_recommendation_until_exact_candidate_decisions() -> None:
    spec = _utility_spec(count=2)
    report = optimization_readiness(spec, purpose="recommendation")
    assert not report["recommendation_ready"]
    assert _codes(report) == {"utility_decision_missing"}
    _decide_utility(spec)
    assert optimization_readiness(spec)["status"] == "ready"
    spec["optimization_contract"]["utility_decisions"].pop()
    assert _codes(optimization_readiness(spec)) == {"utility_decision_missing"}


def test_deferred_candidate_is_a_visible_qualification_not_plain_ready() -> None:
    spec = _utility_spec()
    _decide_utility(spec, "defer")
    report = optimization_readiness(spec)
    assert report["status"] == "ready_with_exceptions"
    assert report["recommendation_ready"]
    assert report["qualification"]["known_limitations"][0]["exception_reason"]


@pytest.mark.parametrize("damage", ["source", "slot", "round", "reason", "boolean", "adopt"])
def test_blank_blanket_or_wrong_candidate_decisions_cannot_clear_observation(damage: str) -> None:
    spec = _utility_spec()
    _decide_utility(spec)
    row = spec["optimization_contract"]["utility_decisions"][0]
    if damage == "source":
        row["source_sha256"] = "old-source"
    elif damage == "slot":
        row["slot"] = "Helmet"
    elif damage == "round":
        row["round"] = 2
    elif damage == "reason":
        row["reason"] = "  "
    elif damage == "boolean":
        spec["optimization_contract"]["utility_decisions"] = True
    else:
        row["decision"] = "adopt"
    assert "invalid_utility_decision" in _codes(optimization_readiness(spec))
    assert not optimization_readiness(spec)["recommendation_ready"]


@pytest.mark.parametrize(
    "damage", ["final_context", "earlier_round", "unknown_scope", "source_changed"]
)
def test_observation_or_decision_from_another_measurement_cannot_be_reused(damage: str) -> None:
    spec = _utility_spec()
    _decide_utility(spec)
    evidence = spec["derived_from"]["items"]["search_evidence"]
    if damage == "final_context":
        spec["config"]["enemyLevel"] = 82
    elif damage == "earlier_round":
        evidence["termination"]["rounds_evaluated"] = 4
    elif damage == "unknown_scope":
        evidence["utility_review"]["last_round_matches_returned_spec"] = False
    else:
        evidence["settings"]["new_measurement"] = True
    report = optimization_readiness(spec)
    assert not report["recommendation_ready"]
    assert "invalid_utility_decision" in _codes(report)


def test_blocked_candidates_are_not_available_and_legacy_has_no_new_coverage_claim() -> None:
    spec = _utility_spec(count=0)
    evidence = spec["derived_from"]["items"]["search_evidence"]
    evidence["utility_review"]["omitted_candidates"] = [{"label": "illegal", "blocked": True}]
    assert optimization_readiness(spec)["status"] == "ready"
    legacy = optimization_readiness(_ready())
    assert legacy["utility_review"]["status"] == "not_observed"


def _fresh_utility_review(spec: dict[str, Any], text: str, *, speed: float | None = 1.3) -> None:
    variant = copy.deepcopy(spec)
    variant["items"][0]["text"] = text
    values = {"Life": 100.0, **({"MovementSpeedMod": speed} if speed is not None else {})}
    spec["derived_from"]["items"] = measured_review_receipt(
        spec,
        {"fresh": variant},
        {"fresh": {"Life": 100}},
        component="items",
        stats=["Life"],
        baseline_stats={"Life": 100},
        unresolved=[],
        utility_baseline={"Life": 100.0, "MovementSpeedMod": 1.0},
        utility_measurements={"fresh": values},
    )
    spec["derived_from"].pop("tree", None)  # This fixture reviews only the item axis.
    spec["optimization_contract"]["required_components"] = {
        "items": {
            "scope": {"slots": ["Weapon 1"]},
            "allowed_termination_reasons": ["variants_evaluated"],
        }
    }


def test_review_uses_full_actual_stats_even_when_requested_stats_omit_utility() -> None:
    spec = _ready()
    _fresh_utility_review(spec, "B0")
    report = optimization_readiness(spec)
    assert _codes(report) == {"utility_decision_missing"}
    assert report["utility_review"]["required_decisions"][0]["label"] == "fresh"


def test_review_overwrite_cannot_hide_prior_utility_candidate() -> None:
    spec = _utility_spec()
    prior = spec["derived_from"]["items"]
    spec["config"]["enemyLevel"] = 82
    _fresh_utility_review(spec, "Different candidate", speed=1.0)
    report = optimization_readiness(spec)
    assert _codes(report) == {"utility_context_unknown"}
    saved = copy.deepcopy(
        spec["derived_from"]["items"]["search_evidence"]["utility_review_history"]
    )
    prior["search_evidence"]["utility_review"]["utility_gain_candidate_ids"].clear()
    assert spec["derived_from"]["items"]["search_evidence"]["utility_review_history"] == saved


@pytest.mark.parametrize("speed", [1.3, 1.0, None])
def test_exact_fresh_input_remeasurement_updates_history_without_inventing_missing_zero(
    speed: float | None,
) -> None:
    spec = _utility_spec()
    spec["config"]["enemyLevel"] = 82
    _fresh_utility_review(spec, "B0", speed=speed)
    report = optimization_readiness(spec)
    if speed is None:
        assert "utility_context_unknown" in _codes(report)
        assert not report["utility_review"]["remeasured_history"]
    elif speed > 1:
        assert _codes(report) == {"utility_decision_missing"}
        assert report["utility_review"]["remeasured_history"]
        _decide_utility(spec)
        assert optimization_readiness(spec)["status"] == "ready"
    else:
        assert report["status"] == "ready"
        assert report["utility_review"]["remeasured_history"]


def test_generic_exception_cannot_replace_candidate_judgment() -> None:
    spec = _utility_spec()
    report = optimization_readiness(spec)
    spec["optimization_contract"]["exceptions"] = [
        {"issue_id": report["blockers"][0]["issue_id"], "reason": "All utility was considered."}
    ]
    assert "invalid_contract" in _codes(optimization_readiness(spec))


def test_same_label_other_text_and_unobserved_axis_cannot_discharge_history() -> None:
    spec = _utility_spec()
    spec["config"]["enemyLevel"] = 82
    _fresh_utility_review(spec, "B0-but-different", speed=1.0)
    assert "utility_context_unknown" in _codes(optimization_readiness(spec))
    # Repeating a review must preserve the unresolved original, not just its last peer.
    _fresh_utility_review(spec, "Still another candidate", speed=1.0)
    assert "utility_context_unknown" in _codes(optimization_readiness(spec))


def test_tampered_history_digest_is_rejected() -> None:
    spec = _utility_spec()
    _fresh_utility_review(spec, "Different", speed=1.0)
    history = spec["derived_from"]["items"]["search_evidence"]["utility_review_history"]
    history[0]["source_sha256"] = "not-the-original"
    assert "invalid_utility_evidence" in _codes(optimization_readiness(spec))


def test_actual_new_baseline_adoption_resolves_history_without_prose_adopt() -> None:
    spec = _utility_spec()
    spec["items"][0]["text"] = "B0"
    _fresh_utility_review(spec, "A", speed=1.0)
    report = optimization_readiness(spec)
    assert report["status"] == "ready"
    assert report["utility_review"]["remeasured_history"][0]["remeasured_label"] == "baseline"


@pytest.mark.parametrize(
    "field,value", [("active", False), ("substitutes", ["utility substitute"])]
)
def test_same_text_with_changed_calculator_inputs_cannot_resolve_history(
    field: str, value: Any
) -> None:
    spec = _utility_spec()
    spec["config"]["enemyLevel"] = 82
    variant = copy.deepcopy(spec)
    variant["items"][0].update({"text": "B0", field: value})
    mark = measured_review_receipt(
        spec,
        {"same-label": variant},
        {"same-label": {"MovementSpeedMod": 1.0}},
        component="items",
        stats=["MovementSpeedMod"],
        baseline_stats={"MovementSpeedMod": 1.0},
        unresolved=[],
    )
    spec["derived_from"] = {"items": mark}
    spec["optimization_contract"]["required_components"] = {
        "items": {
            "scope": {"slots": ["Weapon 1"]},
            "allowed_termination_reasons": ["variants_evaluated"],
        }
    }
    assert "utility_context_unknown" in _codes(optimization_readiness(spec))


def test_new_optimizer_stamp_cannot_erase_existing_utility_observation() -> None:
    from pok.mcp.tools.tree import _stamp

    spec = _utility_spec()
    empty = copy.deepcopy(_utility_spec(count=0)["derived_from"]["items"]["search_evidence"])
    spec["derived_from"] = _stamp(spec, "items", tool="optimize_items", search_evidence=empty)
    assert _codes(optimization_readiness(spec)) == {"utility_decision_missing"}


def test_item_optimizer_jewel_observation_can_be_remeasured_by_jewel_review() -> None:
    from pok.engine.valuation import utility_candidate_digest

    spec = _utility_spec()
    spec["jewels"] = [{"socket_node_id": 2, "text": "Jewel A"}]
    old = spec["derived_from"]["items"]["search_evidence"]
    old["utility_review"]["utility_gain_candidate_ids"][0].update(
        {"slot": "Jewel@2", "candidate_sha256": utility_candidate_digest("Jewel B")}
    )
    spec["derived_from"]["items"] = stamp(spec, "items", tool="optimize_items", search_evidence=old)
    spec["config"]["enemyLevel"] = 82
    _fresh_utility_review(spec, "Unrelated weapon", speed=1.0)
    variant = copy.deepcopy(spec)
    variant["jewels"][0]["text"] = "Jewel B"
    spec["derived_from"]["jewels"] = measured_review_receipt(
        spec,
        {"jewel": variant},
        {"jewel": {"MovementSpeedMod": 1.0}},
        component="jewels",
        stats=["MovementSpeedMod"],
        baseline_stats={"MovementSpeedMod": 1.0},
        unresolved=[],
    )
    report = optimization_readiness(spec)
    assert report["status"] == "ready"
    assert report["utility_review"]["remeasured_history"][0]["remeasured_label"] == "jewel"


@pytest.mark.parametrize("observed", [False, None])
def test_current_definite_block_resolves_old_candidate_but_unknown_does_not(observed: Any) -> None:
    spec = _utility_spec()
    spec["config"]["enemyLevel"] = 82
    blocked = copy.deepcopy(spec)
    blocked["items"][0]["text"] = "B0"
    peer = copy.deepcopy(spec)
    peer["items"][0]["text"] = "Peer"
    failure = {"code": "items_legal", "scope": ["blocked"], "observed": observed}
    spec["derived_from"] = {
        "items": measured_review_receipt(
            spec,
            {"blocked": blocked, "peer": peer},
            {"peer": {"MovementSpeedMod": 1.0}},
            component="items",
            stats=["MovementSpeedMod"],
            baseline_stats={"MovementSpeedMod": 1.0},
            unresolved=[failure],
            utility_failures={"blocked": [failure]},
        )
    }
    spec["optimization_contract"]["required_components"] = {
        "items": {
            "scope": {"slots": ["Weapon 1"]},
            "allowed_termination_reasons": ["variants_evaluated"],
        }
    }
    report = optimization_readiness(spec)
    evidence = spec["derived_from"]["items"]["search_evidence"]
    assert evidence["scope"]["candidates"] == ["peer"]
    assert "blocked" not in evidence["measurements"]  # Never invent a zero utility score.
    if observed is False:
        assert _codes(report) == {"unresolved_evidence"}
        assert report["utility_review"]["remeasured_history"][0]["outcome"] == "blocked"
    else:
        assert "utility_context_unknown" in _codes(report)
