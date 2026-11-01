"""Trusted-store fixtures test evidence identity/scope, not real PoB/game behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from pok.artifacts.design_record import create_record, parse_record, record_json, seal_record
from pok.artifacts.store import record_immutable_build
from pok.artifacts.tool_results import store_result
from pok.engine.design_evidence import inspect_evidence, value_sha256

ENV = {"loaded_commit": "fixture", "pob_commit": "fixture-pob", "calc_fingerprint": "fixture-code"}
SPEC = {"class_name": "Monk", "level": 100, "items": [{"slot": "Belt", "text": "synthetic item"}]}


def material(
    root: Path, spec: dict[str, Any], identity: str = "20261101-material", metadata: bool = False
) -> dict[str, Any]:
    files = {"spec.json": (json.dumps(spec, indent=2) + "\n").encode()}
    if metadata:
        files["metadata.json"] = b'{"acquisition":"fixture"}'
    stored = record_immutable_build(identity, files, {"kind": "test-material"}, root=root)
    result: dict[str, Any] = {
        "selection": {},
        "spec": {
            "artifact_id": identity,
            "name": "spec.json",
            "sha256": stored["files"]["spec.json"]["sha256"],
            "media_type": "application/json",
        },
    }
    if metadata:
        result["metadata"] = {
            "artifact_id": identity,
            "name": "metadata.json",
            "sha256": stored["files"]["metadata.json"]["sha256"],
            "media_type": "application/json",
        }
    result["revision"] = value_sha256(result)
    return result


def measurement(
    root: Path,
    mat: dict[str, Any],
    spec: dict[str, Any] | None = None,
    usage: str = "current",
    path: str = "/result/stats/CombinedDPS",
    output: Any = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = SPEC if spec is None else spec
    stored = store_result(
        "compute_pob",
        {"build_spec": spec, "stats": ["CombinedDPS"]},
        {"stats": {"CombinedDPS": 100.0}} if output is None else output,
        source=ENV if source is None else source,
        root=root,
    )
    return {
        "id": "e-measure",
        "kind": "measurement",
        "label": "Synthetic trusted-store output",
        "scope": {
            "description": "Fixture input scope",
            "decision_ids": [],
            "usage": usage,
            "material_revision": mat["revision"],
        },
        "source": {"$pok_result": stored["id"], "path": path, "spec_sha256": value_sha256(spec)},
    }


def record(mat: dict[str, Any] | None, evidence: dict[str, Any]) -> str:
    value = create_record("evidence-fixture", "Verify actual refs, not game truth")
    value["material"] = mat
    value["evidence"] = [evidence]
    return record_json(seal_record(value))


def codes(result: dict[str, Any]) -> set[str]:
    return {row["code"] for row in result["diagnostics"]}


def test_actual_stored_input_and_current_spec_match_without_xml_or_game_certificate(
    tmp_path: Path,
) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat)
    assert evidence["source"]["spec_sha256"] != mat["spec"]["sha256"]  # logical JSON vs file bytes
    report = inspect_evidence(record(mat, evidence), root=tmp_path, expected_source=ENV)
    row = report["evidence_assessments"][0]
    assert row["integrity"] == "verified" and row["application"] == "current_spec_verified"
    assert row["source_check"]["status"] == "matched_declared_fields"
    assert report["checks"]["game_feasibility"] == "not_checked"
    assert report["checks"]["xml_spec_consistency"] == "not_checked"


def test_well_shaped_missing_receipt_is_unavailable_not_game_illegal(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat)
    evidence["source"]["$pok_result"] = "0" * 64
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "EVIDENCE_UNAVAILABLE" in codes(report)
    assert report["evidence_assessments"][0]["integrity"] == "unavailable"
    assert report["checks"]["game_feasibility"] == "not_checked"


def test_declared_input_hash_cannot_relabel_another_actual_input(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat)
    evidence["source"]["spec_sha256"] = value_sha256({**SPEC, "level": 99})
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "MEASUREMENT_INPUT_MISMATCH" in codes(report)


def test_actual_old_measurement_cannot_be_current_only_by_changing_scope_label(
    tmp_path: Path,
) -> None:
    changed = {**SPEC, "level": 99}
    mat = material(tmp_path, changed)
    evidence = measurement(tmp_path, mat, spec=SPEC)
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    row = report["evidence_assessments"][0]
    assert row["integrity"] == "verified"  # the old observation is preserved
    assert row["application"] == "different_input"
    assert "CURRENT_MEASUREMENT_INPUT_MISMATCH" in codes(report)


@pytest.mark.parametrize("usage", ["comparison", "historical"])
def test_non_current_measurement_keeps_valid_original_scope(tmp_path: Path, usage: str) -> None:
    mat = material(tmp_path, {**SPEC, "level": 99})
    evidence = measurement(tmp_path, mat, spec=SPEC, usage=usage)
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    row = report["evidence_assessments"][0]
    assert row["integrity"] == "verified" and row["application"] == usage
    assert "CURRENT_MEASUREMENT_INPUT_MISMATCH" not in codes(report)
    assert report["checks"]["current_evidence_application"] == "no_current_machine_refs"


def test_same_spec_different_material_requires_explicit_mapping(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat)
    evidence["scope"]["material_revision"] = "sha256:" + "0" * 64
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "MATERIAL_MAPPING_REVIEW" in codes(report)
    assert report["evidence_assessments"][0]["application"] == "same_spec_reuse_requires_mapping"


@pytest.mark.parametrize("scope", ["base", "variant"])
def test_delta_path_binds_the_actual_selected_subject_with_escaped_label(
    tmp_path: Path, scope: str
) -> None:
    variant = {**SPEC, "level": 99}
    label = "other/input~v"
    subject = SPEC if scope == "base" else variant
    mat = material(tmp_path, subject)
    stored = store_result(
        "evaluate_delta",
        {"base_spec": SPEC, "variants": {label: variant}},
        {
            "base": {"stats": {"CombinedDPS": 100}},
            "variants": {label: {"stats": {"CombinedDPS": 99}}},
        },
        source=ENV,
        root=tmp_path,
    )
    evidence = measurement(tmp_path, mat, subject)
    evidence["source"] = {
        "$pok_result": stored["id"],
        "spec_sha256": value_sha256(subject),
        "path": "/result/base/stats/CombinedDPS"
        if scope == "base"
        else "/result/variants/other~1input~0v/stats/CombinedDPS",
    }
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert report["evidence_assessments"][0]["application"] == "current_spec_verified"


@pytest.mark.parametrize("path", ["/inputs/build_spec", "/source"])
def test_a_stored_input_or_source_is_not_a_calculated_result(tmp_path: Path, path: str) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat, path=path)
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "UNSUPPORTED_MEASUREMENT_SUBJECT" in codes(report)


def test_known_producer_name_does_not_make_an_error_object_measured_data(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(
        tmp_path, mat, path="/result", output={"ok": False, "reason": "fixture failure"}
    )
    assert "UNSUPPORTED_MEASUREMENT_SUBJECT" in codes(
        inspect_evidence(record(mat, evidence), root=tmp_path)
    )


def test_imported_saved_statistics_are_not_a_new_calculation(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    stored = store_result(
        "parse_pob",
        {"build_code": "opaque import fixture"},
        {"stats": {"CombinedDPS": 100.0}},
        source=ENV,
        root=tmp_path,
    )
    evidence = measurement(tmp_path, mat)
    evidence["source"]["$pok_result"] = stored["id"]
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "UNSUPPORTED_MEASUREMENT_SUBJECT" in codes(report)
    assert report["checks"]["current_evidence_application"] == "needs_review"


@pytest.mark.parametrize("output", [{"stats": {}}, {"ok": False, "stats": {"CombinedDPS": 100}}])
def test_failed_or_unmeasured_stats_do_not_pass_current_application(
    tmp_path: Path, output: Any
) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat, path="/result", output=output)
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "MEASUREMENT_FAILED_OR_UNMEASURED" in codes(report)
    assert report["checks"]["current_evidence_application"] == "needs_review"


def test_selected_normalized_null_is_not_a_measured_number(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat, output={"stats": {"CombinedDPS": None}})
    assert "SELECTED_VALUE_UNMEASURED_OR_NORMALIZED" in codes(
        inspect_evidence(record(mat, evidence), root=tmp_path)
    )


def test_truncated_or_modified_receipt_fails_integrity(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat)
    path = (
        tmp_path
        / "artifacts/sessions"
        / ("tool-result-" + evidence["source"]["$pok_result"])
        / "payload.json"
    )
    path.write_bytes(b'{"changed":true}')
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "EVIDENCE_INTEGRITY_FAILURE" in codes(report)


def test_source_compatibility_is_not_inferred_from_input_hash(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat, source={"loaded_commit": "fixture"})
    report = inspect_evidence(record(mat, evidence), root=tmp_path, expected_source=ENV)
    row = report["evidence_assessments"][0]
    assert row["integrity"] == "verified"
    assert row["source_check"]["status"] == "incomplete"
    assert report["checks"]["measurement_source_compatibility"] == "needs_review"
    assert (
        inspect_evidence(record(mat, evidence), root=tmp_path)["checks"][
            "measurement_source_compatibility"
        ]
        == "not_checked"
    )


def test_missing_acquisition_sidecar_does_not_erase_valid_calculator_projection(
    tmp_path: Path,
) -> None:
    mat = material(tmp_path, SPEC, metadata=True)
    evidence = measurement(tmp_path, mat)
    (tmp_path / "artifacts/builds/20261101-material/metadata.json").unlink()
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert report["material_assessment"]["status"] == "unavailable"
    assert report["evidence_assessments"][0]["application"] == "current_spec_verified"
    assert "MATERIAL_UNAVAILABLE" in codes(report)


def test_material_revision_cannot_be_a_freely_changed_label(tmp_path: Path) -> None:
    mat = material(tmp_path, SPEC)
    evidence = measurement(tmp_path, mat)
    mat["revision"] = "sha256:" + "0" * 64
    report = inspect_evidence(record(mat, evidence), root=tmp_path)
    assert "MATERIAL_REVISION_MISMATCH" in codes(report)


def catalog_record() -> dict[str, Any]:
    return {
        "id": "mechanic.synthetic",
        "verification": "GAME_DATA",
        "data": {"stats": ["fixture statement"]},
        "sources": [{"patch": "fixture-patch"}],
    }


def catalog_evidence() -> dict[str, Any]:
    return {
        "id": "e-catalog",
        "kind": "catalog",
        "label": "Fixture text, not a verified mechanism",
        "scope": {"description": "General source text", "decision_ids": [], "usage": "general"},
        "source": {
            "catalog": "kb",
            "entity_id": "mechanic.synthetic",
            "record_sha256": value_sha256(catalog_record()),
            "field_path": "/data/stats/0",
            "patch": "fixture-patch",
        },
    }


def test_catalog_record_identity_hash_and_selected_field_are_checked(tmp_path: Path) -> None:
    evidence = catalog_evidence()
    report = inspect_evidence(
        record(None, evidence), root=tmp_path, _catalog_loader=lambda *_: catalog_record()
    )
    row = report["evidence_assessments"][0]
    assert row["integrity"] == "verified" and row["patch_check"] == "matched"
    assert row["game_mechanism_verified"] is False


@pytest.mark.parametrize("change", ["hash", "identity", "field", "patch"])
def test_catalog_scope_changes_are_not_silently_accepted(tmp_path: Path, change: str) -> None:
    evidence = catalog_evidence()
    actual = catalog_record()
    if change == "hash":
        actual["data"]["stats"] = ["changed"]
        expected = "CATALOG_RECORD_CHANGED_OR_MISMATCH"
    elif change == "identity":
        actual["id"] = "mechanic.other"
        evidence["source"]["record_sha256"] = value_sha256(actual)
        expected = "CATALOG_IDENTITY_MISMATCH"
    elif change == "field":
        evidence["source"]["field_path"] = "/data/missing"
        expected = "CATALOG_FIELD_UNAVAILABLE"
    else:
        evidence["source"]["patch"] = "different-patch"
        expected = "CATALOG_PATCH_SCOPE_UNCONFIRMED"
    report = inspect_evidence(
        record(None, evidence), root=tmp_path, _catalog_loader=lambda *_: actual
    )
    assert expected in codes(report)


def test_catalog_backend_failure_is_unavailable_not_a_confirmed_game_gap(tmp_path: Path) -> None:
    def fail(*_: Any) -> dict[str, Any]:
        raise RuntimeError("fixture lookup failure")

    report = inspect_evidence(record(None, catalog_evidence()), root=tmp_path, _catalog_loader=fail)
    assert "CATALOG_LOOKUP_FAILED" in codes(report)
    assert report["checks"]["game_feasibility"] == "not_checked"


def test_hypothesis_or_user_claim_does_not_become_machine_verified(tmp_path: Path) -> None:
    evidence = {
        "id": "e-claim",
        "kind": "hypothesis",
        "label": "unverified",
        "scope": {"description": "Test needed", "decision_ids": [], "usage": "general"},
        "source": {"statement": "Might trigger", "criterion": "Observe the event in game"},
    }
    report = inspect_evidence(record(None, evidence), root=tmp_path)
    assert report["evidence_assessments"][0]["integrity"] == "caller_claim"
    assert report["checks"]["evidence_integrity"] == "no_machine_refs"


@pytest.mark.parametrize("mode", ["current", "rebase", "changed", "missing_pointer", "xml"])
def test_provider_binding_checks_actual_value_without_claiming_game_equivalence(
    tmp_path: Path, mode: str
) -> None:
    mat = material(tmp_path, SPEC)
    value = parse_record(record(mat, measurement(tmp_path, mat)))
    binding = {
        "material_revision": mat["revision"],
        "representation": "build_spec",
        "pointer": "/items/0/text",
        "value_sha256": value_sha256(SPEC["items"][0]["text"]),
    }
    if mode == "rebase":
        binding["material_revision"] = "sha256:" + "0" * 64
    elif mode == "changed":
        binding["value_sha256"] = "sha256:" + "0" * 64
    elif mode == "missing_pointer":
        binding["pointer"] = "/items/1/text"
    elif mode == "xml":
        binding["representation"] = "pob_xml"
    value["decisions"] = [
        {
            "id": "fixed-item",
            "title": "Prepared fixture item",
            "role": "user_fixed",
            "domains": ["sustain"],
            "condition": {
                "statement": "Preserve declared value",
                "scope": {"description": "Fixture constraint", "decision_ids": []},
            },
            "adoption": "adopted",
            "belief": "user_reported",
            "confidence": "high",
            "providers": [
                {"id": "provider", "kind": "item", "label": "fixture", "binding": binding}
            ],
            "depends_on": [],
            "alternatives": [],
            "evidence_ids": [],
            "costs": [],
        }
    ]
    report = inspect_evidence(record_json(seal_record(value)), root=tmp_path)
    row = report["provider_binding_assessments"][0]
    if mode in {"current", "rebase"}:
        assert row["integrity"] == "verified_value"
        assert row["application"] == (
            "current_spec_value_only"
            if mode == "current"
            else "same_value_revalidated_at_new_material"
        )
    elif mode == "changed":
        assert "PROVIDER_BINDING_VALUE_CHANGED" in codes(report)
    elif mode == "missing_pointer":
        assert "BINDING_POINTER_UNAVAILABLE" in codes(report)
    else:
        assert row["integrity"] == "unavailable"
        assert "BINDING_XML_NODE_UNAVAILABLE" in codes(report)
    assert report["checks"]["game_feasibility"] == "not_checked"
