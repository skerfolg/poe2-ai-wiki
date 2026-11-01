"""Executable R2 shape/hash vectors, not proof of R3 behavior or game validity."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path
from typing import Any

import jsonschema
import pytest

SCHEMA = json.loads(
    files("pok.artifacts").joinpath("design_record.schema.json").read_text(encoding="utf-8")
)
FIXTURES = json.loads(
    Path(__file__).with_name("design_record_contract_fixtures.json").read_text(encoding="utf-8")
)
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA)
RECORDS = [
    (case["id"] + ":" + side, case[side])
    for case in FIXTURES["cases"]
    for side in ("before", "after")
    if side in case
]


def contract_revision(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "revision"}
    raw = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def example(case_id: str) -> dict[str, Any]:
    return deepcopy(next(case["before"] for case in FIXTURES["cases"] if case["id"] == case_id))


def test_schema_is_valid_draft_2020_12() -> None:
    jsonschema.Draft202012Validator.check_schema(SCHEMA)


@pytest.mark.parametrize(("name", "record"), RECORDS, ids=[name for name, _ in RECORDS])
def test_frozen_shape_and_revision_vectors(name: str, record: dict[str, Any]) -> None:
    assert not list(VALIDATOR.iter_errors(record)), name
    assert record["revision"] == contract_revision(record), name


def test_initial_record_does_not_require_pob_anchors_or_completed_evidence() -> None:
    record = example("draft-before-pob")
    assert record["material"] is None
    assert record["decisions"] == record["evidence"] == record["questions"] == []
    VALIDATOR.validate(record)


def test_adoption_and_belief_are_independent() -> None:
    record = example("provider-replacement")
    record["decisions"][0].update(adoption="adopted", belief="hypothesis", confidence="low")
    VALIDATOR.validate(record)


def test_schema_success_is_not_measurement_verification() -> None:
    record = example("well-shaped-unavailable-measurement")
    VALIDATOR.validate(record)
    assert record["evidence"][0]["source"]["$pok_result"] == "0" * 64
    # R3 must look up the actual immutable result; accepting this shape is not
    # a fabricated measurement's successful verification.
    case = next(
        case for case in FIXTURES["cases"] if case["id"] == "well-shaped-unavailable-measurement"
    )
    assert "EVIDENCE_UNAVAILABLE" in case["expected_runtime_diagnostics"]


@pytest.mark.parametrize("location", ["record", "evidence", "source"])
def test_caller_cannot_add_a_verified_flag(location: str) -> None:
    record = example("well-shaped-unavailable-measurement")
    target = {
        "record": record,
        "evidence": record["evidence"][0],
        "source": record["evidence"][0]["source"],
    }[location]
    target["verified"] = True
    assert list(VALIDATOR.iter_errors(record))


def test_measurement_reference_cannot_override_the_saved_result() -> None:
    record = example("well-shaped-unavailable-measurement")
    record["evidence"][0]["source"]["overrides"] = {"stats": {"CombinedDPS": 1_000_000}}
    assert list(VALIDATOR.iter_errors(record))


def test_unsupported_version_is_not_silently_v1() -> None:
    record = example("draft-before-pob")
    record["format"] = "pok.design-record.v999"
    assert list(VALIDATOR.iter_errors(record))


def test_unclassified_extension_is_preserved_and_affects_revision() -> None:
    record = example("draft-before-pob")
    original = record["revision"]
    record["extensions"] = {"future_data": {"verbatim": "unknown | text\r\n<!-- keep -->"}}
    VALIDATOR.validate(record)
    assert json.loads(json.dumps(record))["extensions"] == record["extensions"]
    assert contract_revision(record) != original


def test_hash_scope_is_order_independent_for_objects_but_not_values_or_parent() -> None:
    record = example("draft-before-pob")
    assert contract_revision(dict(reversed(list(record.items())))) == record["revision"]
    changed = deepcopy(record)
    changed["goal"]["summary"] += " changed"
    assert contract_revision(changed) != record["revision"]
    changed = deepcopy(record)
    changed["parents"] = ["sha256:" + "1" * 64]
    assert contract_revision(changed) != record["revision"]


def test_legacy_confirmed_list_is_not_automatically_a_user_fixed_decision() -> None:
    case = next(
        case for case in FIXTURES["cases"] if case["id"] == "legacy-source-is-not-user-fixed"
    )
    record = case["before"]
    assert record["decisions"] == []
    assert "## 확정\r\n" in case["legacy_markdown"]
    raw = case["legacy_markdown"].encode("utf-8")
    assert record["legacy_sources"][0]["sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("field", ["design_id", "revision", "result_id"])
def test_identifiers_reject_trailing_newlines(field: str) -> None:
    record = example("well-shaped-unavailable-measurement")
    if field == "result_id":
        record["evidence"][0]["source"]["$pok_result"] += "\n"
    else:
        record[field] += "\n"
    assert list(VALIDATOR.iter_errors(record))


def test_existing_korean_artifact_slug_remains_representable() -> None:
    record = example("legacy-source-is-not-user-fixed")
    record["legacy_sources"][0]["artifact_id"] = "20261101-독-설계"
    VALIDATOR.validate(record)


@pytest.mark.parametrize(
    "name",
    ["../outside.md", "tiers/../outside.md", "/outside.md", "D:/outside.md", "..\\outside.md"],
)
def test_blob_names_are_relative_artifact_names(name: str) -> None:
    record = example("legacy-source-is-not-user-fixed")
    record["legacy_sources"][0]["name"] = name
    assert list(VALIDATOR.iter_errors(record))


@pytest.mark.parametrize("usage", ["current", "comparison", "historical"])
def test_measurement_relationship_is_explicit_and_preserved(usage: str) -> None:
    record = example("well-shaped-unavailable-measurement")
    record["evidence"][0]["scope"]["usage"] = usage
    VALIDATOR.validate(record)
    assert json.loads(json.dumps(record))["evidence"][0]["scope"]["usage"] == usage


def test_measurement_cannot_claim_context_free_general_evidence() -> None:
    record = example("well-shaped-unavailable-measurement")
    record["evidence"][0]["scope"]["usage"] = "general"
    assert list(VALIDATOR.iter_errors(record))


@pytest.mark.parametrize("field", ["usage", "material_revision"])
def test_measurement_requires_context_instead_of_guessing_current(field: str) -> None:
    record = example("well-shaped-unavailable-measurement")
    del record["evidence"][0]["scope"][field]
    assert list(VALIDATOR.iter_errors(record))


def test_comparison_retains_its_original_input_not_the_current_material() -> None:
    record = example("comparison-keeps-original-context")
    VALIDATOR.validate(record)
    evidence = record["evidence"][0]
    assert evidence["scope"]["usage"] == "comparison"
    assert evidence["scope"]["material_revision"] != record["material"]["revision"]
    assert evidence["source"]["spec_sha256"] != record["material"]["spec"]["sha256"]


def test_catalog_fact_can_be_general_before_any_material_exists() -> None:
    record = example("draft-before-pob")
    record["evidence"] = [
        {
            "id": "e-catalog",
            "kind": "catalog",
            "label": "Synthetic source reference, not verified evidence",
            "scope": {"description": "general source text", "decision_ids": [], "usage": "general"},
            "source": {
                "catalog": "kb",
                "entity_id": "mechanic.synthetic-contract-example",
                "record_sha256": "sha256:" + "0" * 64,
                "field_path": "/data/stats",
            },
        }
    ]
    assert record["material"] is None
    VALIDATOR.validate(record)
