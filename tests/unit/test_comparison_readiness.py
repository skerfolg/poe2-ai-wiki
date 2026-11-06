"""Saved comparison evidence can replace optimizer stamps, never actual inputs."""

from copy import deepcopy

import pytest

from pok.artifacts import store, tool_results
from pok.engine.optimization_readiness import optimization_readiness


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    monkeypatch.setattr(store, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    base = {
        "class_name": "Sorceress",
        "level": 90,
        "items": [{"slot": "Ring 1", "text": "original"}],
    }
    variant = deepcopy(base)
    variant["items"][0]["text"] = "alternative"
    inputs = {"base_spec": base, "variants": {"other": variant}}
    output = {
        "base": {"stats": {"Life": 100}},
        "variants": {"other": {"stats": {"Life": 120}}},
        "comparison": {"measured_comparisons": ["other"], "unresolved": []},
    }
    return base, inputs, output


def recommend(base, inputs, output, selected="baseline"):
    manifest = tool_results.store_result("evaluate_delta", inputs, output)
    spec = deepcopy(base if selected == "baseline" else inputs["variants"][selected])
    spec["optimization_contract"] = {
        "version": 2,
        "required_components": ["items"],
        "comparisons": [
            {
                "result_id": manifest["id"],
                "selected": selected,
                "reason": "회복과 피해의 대가를 고려한 선택",
            }
        ],
    }
    return spec


@pytest.mark.parametrize("selected", ["baseline", "other"])
def test_saved_manual_comparison_needs_no_optimizer_stamp(case, selected):
    base, inputs, output = case
    report = optimization_readiness(recommend(base, inputs, output, selected))
    assert report["recommendation_ready"]
    assert report["version"] == 2
    assert not report["qualification"]["gameplay_validated"]
    assert report["design_record"]["status"] == "not_supplied"


def bind_design(spec, material_spec=None, pending=False, open_question=False):
    from pok.artifacts.design_record import create_record, record_json, seal_record
    from pok.engine.design_checkpoints import save_checkpoint
    from pok.engine.design_service import capture_material

    record = create_record("comparison-design", "Preserve the explicit recommendation input")
    record["material"] = capture_material(build_spec=material_spec or spec)["material"]
    if pending:
        record["decisions"] = [
            {
                "id": "anchor",
                "title": "Anchor under review",
                "role": "mechanism_required",
                "domains": ["offence"],
                "condition": {
                    "statement": "A declared condition",
                    "scope": {"description": "Current build", "decision_ids": []},
                },
                "adoption": "adopted",
                "belief": "hypothesis",
                "confidence": "low",
                "providers": [],
                "depends_on": [],
                "alternatives": [],
                "evidence_ids": [],
                "costs": [],
                "review": {
                    "state": "required",
                    "reasons": ["Changed supplier"],
                    "since_revision": record["revision"],
                },
            }
        ]
    if open_question:
        record["questions"] = [
            {
                "id": "game-check",
                "claim": "Unmodeled interaction",
                "criterion": "Observe the specified interaction in game",
                "owner": "in_game",
                "state": "open",
                "depends_on": [],
                "evidence_ids": [],
            }
        ]
    reference = save_checkpoint(record_json(seal_record(record)))
    spec["optimization_contract"].update(design_ref=reference, require_design_record=True)
    return reference


def test_required_design_cannot_be_replaced_with_comparison_only(case):
    spec = recommend(*case)
    spec["optimization_contract"]["require_design_record"] = True
    assert not optimization_readiness(spec)["recommendation_ready"]


def test_final_v2_recommendation_requires_design_even_if_caller_disables_flag(case):
    spec = recommend(*case)
    spec["optimization_contract"]["require_design_record"] = False
    report = optimization_readiness(spec, purpose="recommendation")
    assert not report["recommendation_ready"]
    assert any(row["code"] == "design_record_missing" for row in report["blockers"])
    assert report["layers"]["comparison"] == "verified_declared_candidates"


def test_game_question_stays_open_and_disclosed_without_false_certification(case):
    spec = recommend(*case)
    bind_design(spec, open_question=True)
    report = optimization_readiness(spec, purpose="recommendation")
    assert report["recommendation_ready"], report
    assert report["design_record"]["open_questions"][0]["state"] == "open"
    assert report["design_record"]["open_questions"][0]["owner"] == "in_game"
    assert report["layers"]["game_feasibility"] == "not_certified"


def test_design_checkpoint_and_current_material_are_bound(case):
    spec = recommend(*case)
    reference = bind_design(spec)
    report = optimization_readiness(spec)
    assert report["recommendation_ready"], report
    assert report["design_record"]["status"] == "input_bound"
    assert report["design_record"]["record_ref"] == reference
    assert report["layers"]["game_feasibility"] == "not_certified"


@pytest.mark.parametrize("failure", ["different_material", "tampered_reference", "pending_anchor"])
def test_design_binding_failures_block_record_required_recommendation(case, failure):
    spec = recommend(*case)
    other = deepcopy(spec)
    other["items"][0]["text"] = "different"
    reference = bind_design(
        spec,
        other if failure == "different_material" else None,
        pending=failure == "pending_anchor",
    )
    if failure == "tampered_reference":
        reference["sha256"] = "sha256:" + "0" * 64
    report = optimization_readiness(spec)
    assert not report["recommendation_ready"]
    assert report["design_record"]["status"] == "needs_review"


def test_changed_selected_input_invalidates_old_measurement(case):
    base, inputs, output = case
    spec = recommend(base, inputs, output)
    spec["items"][0]["text"] = "not measured"
    assert not optimization_readiness(spec)["recommendation_ready"]


def test_changed_config_invalidates_old_measurement(case):
    base, inputs, output = case
    spec = recommend(base, inputs, output)
    spec["config"] = {"enemyIsBoss": True}
    assert not optimization_readiness(spec)["recommendation_ready"]


def test_different_alternative_scenario_is_not_component_evidence(case):
    base, inputs, output = case
    inputs["variants"]["other"]["config"] = {"enemyIsBoss": True}
    spec = recommend(base, inputs, output)
    assert not optimization_readiness(spec)["recommendation_ready"]


def test_general_passive_comparison_does_not_cover_ascendancy(case):
    base, inputs, output = case
    base["ascendancy"] = "Sorceress1"
    inputs["variants"]["other"]["ascendancy"] = "Sorceress1"
    inputs["variants"]["other"]["tree_nodes"] = [22419]
    spec = recommend(base, inputs, output)
    spec["optimization_contract"]["required_components"] = ["ascendancy"]
    report = optimization_readiness(spec)
    assert not report["recommendation_ready"]
    assert any(row["component"] == "ascendancy" for row in report["blockers"])


@pytest.mark.parametrize(
    "deficit",
    ["partial", "unresolved", "no_stats", "identical", "wrong_component", "missing", "reason"],
)
def test_incomplete_or_unrelated_evidence_cannot_claim_ready(case, deficit):
    base, inputs, output = case
    if deficit == "partial":
        output["comparison"]["measured_comparisons"] = []
    elif deficit == "unresolved":
        output["comparison"]["unresolved"] = [{"code": "unmeasured"}]
    elif deficit == "no_stats":
        output["base"]["stats"] = {}
    elif deficit == "identical":
        inputs["variants"]["other"] = deepcopy(base)
    spec = recommend(base, inputs, output)
    if deficit == "wrong_component":
        spec["optimization_contract"]["required_components"] = ["tree"]
    elif deficit == "missing":
        spec["optimization_contract"]["comparisons"][0]["result_id"] = "0" * 64
    elif deficit == "reason":
        spec["optimization_contract"]["comparisons"][0]["reason"] = ""
    assert not optimization_readiness(spec)["recommendation_ready"]


def parser_gap():
    return {
        "code": "items_pob_gaps",
        "scope": ["baseline"],
        "observed": [
            {"slot": "Ring 1", "item": "Example", "unread": ["An unmodelled item modifier"]}
        ],
    }


def acknowledged_case(case):
    base, inputs, output = case
    gap = parser_gap()
    output["comparison"]["unresolved"] = [gap]
    spec = recommend(base, inputs, output)
    spec["optimization_contract"]["comparisons"][0]["acknowledged_limits"] = [
        {
            "diagnostic": deepcopy(gap),
            "reason": "Only the modelled comparison is selected; "
            "the missing effect remains unknown and the gameplay conclusion is limited.",
        }
    ]
    return spec


def test_acknowledged_parser_gap_is_retained_not_certified(case):
    spec = acknowledged_case(case)
    report = optimization_readiness(spec)
    assert report["recommendation_ready"]
    assert report["status"] == "ready_with_limits"
    assert report["measurement_limits"][0]["diagnostic"] == parser_gap()
    assert report["measurement_limits"][0]["reason"]
    assert report["layers"]["game_feasibility"] == "not_certified"
    assert not report["qualification"]["gameplay_validated"]


@pytest.mark.parametrize(
    "failure",
    [
        "unacknowledged",
        "wrong_row",
        "blank",
        "duplicate",
        "failed",
        "illegal",
        "pruned",
        "nonfinite",
        "changed",
    ],
)
def test_parser_acknowledgment_cannot_hide_invalid_measurements(case, failure):
    _, _, output = case
    if failure == "failed":
        output["base"]["ok"] = False
    elif failure == "illegal":
        output["base"]["items_legal"] = False
    elif failure == "pruned":
        output["base"]["pruned_nodes"] = [123]
    elif failure == "nonfinite":
        output["base"]["stats"]["Life"] = float("nan")
        with pytest.raises(ValueError, match="JSON compliant"):
            acknowledged_case(case)
        return
    spec = acknowledged_case(case)
    acknowledgment = spec["optimization_contract"]["comparisons"][0]["acknowledged_limits"]
    if failure == "unacknowledged":
        acknowledgment.clear()
    elif failure == "wrong_row":
        acknowledgment[0]["diagnostic"]["scope"] = ["other"]
    elif failure == "blank":
        acknowledgment[0]["reason"] = " "
    elif failure == "duplicate":
        acknowledgment.append(deepcopy(acknowledgment[0]))
    elif failure == "changed":
        spec["items"][0]["text"] = "unmeasured new item"
    assert not optimization_readiness(spec)["recommendation_ready"]


@pytest.mark.parametrize(
    "gap",
    [
        {"code": "unmeasured", "scope": ["baseline"], "observed": ["missing"]},
        {"code": "items_pob_gaps", "scope": ["baseline"], "observed": []},
    ],
)
def test_nonparser_or_malformed_limit_cannot_be_acknowledged(case, gap):
    base, inputs, output = case
    output["comparison"]["unresolved"] = [gap]
    spec = recommend(base, inputs, output)
    spec["optimization_contract"]["comparisons"][0]["acknowledged_limits"] = [
        {"diagnostic": gap, "reason": "Do not waive this"}
    ]
    assert not optimization_readiness(spec)["recommendation_ready"]
