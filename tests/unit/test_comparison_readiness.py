"""Saved comparison evidence can replace optimizer stamps, never actual inputs."""

from copy import deepcopy

import pytest

from pok.artifacts import tool_results
from pok.engine.optimization_readiness import optimization_readiness


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
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
