"""R3 sealed-record behavior; actual evidence and persistence are tested separately."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from pok.artifacts.design_record import (
    DesignRecordError,
    canonical_bytes,
    create_record,
    parse_record,
    record_json,
    record_revision,
    record_schema,
    render_record,
    seal_record,
)
from pok.engine.design_records import apply_record_changes, inspect_record

FIXTURES = json.loads(
    Path(__file__).with_name("design_record_contract_fixtures.json").read_text(encoding="utf-8")
)
VECTORS = [
    (case["id"] + ":" + side, case[side])
    for case in FIXTURES["cases"]
    for side in ("before", "after")
    if side in case
]


def fixture(name: str) -> dict[str, Any]:
    result: dict[str, Any] = deepcopy(
        next(case["before"] for case in FIXTURES["cases"] if case["id"] == name)
    )
    return result


def changed_provider(record: dict[str, Any]) -> dict[str, Any]:
    decision = deepcopy(record["decisions"][0])
    decision["providers"] = [{"id": "provider-b", "kind": "action", "label": "대체 공급"}]
    return decision


@pytest.mark.parametrize(("name", "record"), VECTORS, ids=[name for name, _ in VECTORS])
def test_backend_matches_contract_hash_vectors(name: str, record: dict[str, Any]) -> None:
    assert record_revision(record) == record["revision"], name
    assert parse_record(record_json(record)) == record


def test_empty_pre_pob_record_has_no_game_or_evidence_certificate() -> None:
    record = create_record("test-design", "설계를 시작한다")
    report = inspect_record(record_json(record))
    assert record["material"] is None
    assert report["checks"]["record_integrity"] == "valid"
    assert report["checks"]["evidence_integrity"] == "not_checked"
    assert report["checks"]["game_feasibility"] == "not_checked"
    assert report["material_status"] == "unbound"
    assert report["diagnostics"] == []


def test_modified_goal_cannot_reuse_the_original_revision() -> None:
    record = create_record("test-design", "original")
    record["goal"]["summary"] = "different"
    with pytest.raises(DesignRecordError) as error:
        parse_record(json.dumps(record))
    assert error.value.code == "REVISION_MISMATCH"
    with pytest.raises(DesignRecordError):
        record_json(record)


def test_json_number_reserialization_is_not_a_sealed_identity_operation() -> None:
    record = create_record("test-design", "original")
    record["extensions"] = {"whole_float": 1.0, "large_int": 9007199254740993}
    text = record_json(seal_record(record))
    assert parse_record(text)["extensions"]["large_int"] == 9007199254740993
    with pytest.raises(DesignRecordError) as error:
        parse_record(text.replace('"whole_float":1.0', '"whole_float":1'))
    assert error.value.code == "REVISION_MISMATCH"


@pytest.mark.parametrize("text", ['{"a":1,"a":2}', '{"x":{"a":1,"a":2}}'])
def test_duplicate_json_members_are_not_silently_overwritten(text: str) -> None:
    with pytest.raises(DesignRecordError) as error:
        parse_record(text)
    assert error.value.code == "DUPLICATE_JSON_KEY"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), {1: "coerced key"}, (1, 2)])
def test_non_json_values_are_not_silently_normalized(value: Any) -> None:
    with pytest.raises(DesignRecordError) as error:
        canonical_bytes(value)
    assert error.value.code == "INVALID_RECORD_JSON"


def test_duplicate_decision_ids_fail_even_with_different_contents() -> None:
    record = fixture("provider-replacement")
    duplicate = deepcopy(record["decisions"][0])
    duplicate["title"] = "different contents, same ID"
    record["decisions"].append(duplicate)
    with pytest.raises(DesignRecordError) as error:
        seal_record(record)
    assert error.value.code == "DUPLICATE_ID"


def test_returned_schema_does_not_modify_validator_state() -> None:
    schema = record_schema()
    schema["required"] = []
    assert record_schema()["required"]
    record = create_record("test-design", "goal")
    record["forged_field"] = True
    with pytest.raises(DesignRecordError):
        seal_record(record)


def test_explicit_provider_change_keeps_condition_and_marks_dependents() -> None:
    record = fixture("provider-replacement")
    text = record_json(record)
    result = apply_record_changes(
        text, record["revision"], [{"op": "upsert_decision", "value": changed_provider(record)}]
    )
    after = parse_record(result.record_json)
    assert after["decisions"][0]["id"] == record["decisions"][0]["id"]
    assert after["decisions"][0]["condition"] == record["decisions"][0]["condition"]
    assert set(result.review_required_ids) == {"d-sustain", "d-attack", "d-defence"}
    assert after["parents"] == [record["revision"]]
    assert parse_record(text) == record
    assert all(entry["review"]["state"] == "required" for entry in after["decisions"])


def test_partial_upsert_keeps_unmentioned_fields_and_nested_scope() -> None:
    record = fixture("provider-replacement")
    record["decisions"][0]["rationale"] = "Preserve this explanation"
    record = seal_record(record)
    result = apply_record_changes(
        record_json(record),
        record["revision"],
        [
            {
                "op": "upsert_decision",
                "value": {"id": "d-sustain", "condition": {"statement": "Changed condition"}},
            }
        ],
    )
    after = parse_record(result.record_json)["decisions"][0]
    assert after["rationale"] == "Preserve this explanation"
    assert after["condition"]["scope"] == record["decisions"][0]["condition"]["scope"]
    assert after["providers"] == record["decisions"][0]["providers"]


def test_minimal_new_decision_gets_only_explicit_unverified_defaults() -> None:
    record = create_record("test-design", "goal")
    decision = {
        "id": "d-new",
        "title": "A new hypothesis",
        "role": "provisional",
        "domains": ["sustain"],
        "condition": {
            "statement": "Resource condition",
            "scope": {"description": "Selected candidate"},
        },
    }
    result = apply_record_changes(
        record_json(record), record["revision"], [{"op": "upsert_decision", "value": decision}]
    )
    after = parse_record(result.record_json)["decisions"][0]
    assert after["adoption"] == "candidate"
    assert after["belief"] == "unknown"
    assert after["providers"] == after["evidence_ids"] == []
    assert after["condition"]["scope"]["decision_ids"] == []


def test_rationale_edit_does_not_invalidate_unchanged_input_dependencies() -> None:
    record = fixture("provider-replacement")
    decision = deepcopy(record["decisions"][0])
    decision["rationale"] = "Explain the same choice more clearly"
    result = apply_record_changes(
        record_json(record), record["revision"], [{"op": "upsert_decision", "value": decision}]
    )
    assert result.changed_decision_ids == ("d-sustain",)
    assert result.review_required_ids == ()
    assert parse_record(result.record_json)["parents"] == [record["revision"]]


def test_noop_keeps_the_raw_record_and_revision() -> None:
    record = fixture("provider-replacement")
    text = json.dumps(record, ensure_ascii=False, indent=4) + "\n"
    result = apply_record_changes(text, record["revision"], [])
    assert result.no_change
    assert result.record_json == text


def test_same_parent_produces_explicit_branches_not_an_implicit_head() -> None:
    record = create_record("test-design", "goal")
    text = record_json(record)
    a = apply_record_changes(
        text, record["revision"], [{"op": "merge_extensions", "value": {"branch": "a"}}]
    )
    b = apply_record_changes(
        text, record["revision"], [{"op": "merge_extensions", "value": {"branch": "b"}}]
    )
    ra, rb = parse_record(a.record_json), parse_record(b.record_json)
    assert ra["parents"] == rb["parents"] == [record["revision"]]
    assert ra["revision"] != rb["revision"]
    with pytest.raises(DesignRecordError) as error:
        apply_record_changes(a.record_json, record["revision"], [])
    assert error.value.code == "REVISION_CONFLICT"


def test_user_fixed_change_needs_the_specific_reported_user_decision() -> None:
    record = fixture("user-fixed-role-relaxation")
    changed = deepcopy(record["decisions"][0])
    changed["role"] = "provisional"
    change = [{"op": "upsert_decision", "value": changed}]
    for acknowledgments in (None, {"unrelated": "a different user choice"}):
        with pytest.raises(DesignRecordError) as error:
            apply_record_changes(
                record_json(record), record["revision"], change, user_decisions=acknowledgments
            )
        assert error.value.code == "USER_FIXED_CHANGE_REQUIRES_DECISION"
    result = apply_record_changes(
        record_json(record),
        record["revision"],
        change,
        user_decisions={"u-class": "scenario user feedback"},
    )
    assert parse_record(result.record_json)["decisions"][0]["role"] == "provisional"
    assert result.operation_provenance["user_decisions"] == {"u-class": "scenario user feedback"}
    assert inspect_record(result.record_json)["checks"]["evidence_integrity"] == "not_checked"


def test_adopting_an_existing_user_constraint_does_not_ask_again() -> None:
    record = fixture("user-fixed-role-relaxation")
    record["decisions"][0]["adoption"] = "candidate"
    record = seal_record(record)
    changed = deepcopy(record["decisions"][0])
    changed["adoption"] = "adopted"
    result = apply_record_changes(
        record_json(record), record["revision"], [{"op": "upsert_decision", "value": changed}]
    )
    assert parse_record(result.record_json)["decisions"][0]["adoption"] == "adopted"


def test_identical_fixed_value_binding_can_move_to_a_new_material() -> None:
    record = fixture("user-fixed-role-relaxation")
    binding = {
        "material_revision": "sha256:" + "0" * 64,
        "representation": "build_spec",
        "pointer": "/items/0/text",
        "value_sha256": "sha256:" + "1" * 64,
    }
    record["decisions"][0]["providers"] = [
        {"id": "fixed-item", "kind": "item", "label": "fixed item", "binding": binding}
    ]
    record = seal_record(record)
    changed = deepcopy(record["decisions"][0])
    changed["providers"][0]["binding"]["material_revision"] = "sha256:" + "2" * 64
    result = apply_record_changes(
        record_json(record), record["revision"], [{"op": "upsert_decision", "value": changed}]
    )
    assert parse_record(result.record_json)["decisions"][0]["providers"] == changed["providers"]
    changed["providers"][0]["binding"]["value_sha256"] = "sha256:" + "3" * 64
    with pytest.raises(DesignRecordError) as error:
        apply_record_changes(
            record_json(record), record["revision"], [{"op": "upsert_decision", "value": changed}]
        )
    assert error.value.code == "USER_FIXED_CHANGE_REQUIRES_DECISION"


def test_cycle_is_reported_and_change_propagation_terminates() -> None:
    record = fixture("coupled-dependency-cycle")
    text = record_json(record)
    assert inspect_record(text)["dependency_cycles"] == [["d-defence", "d-sustain"]]
    result = apply_record_changes(
        text, record["revision"], [{"op": "upsert_decision", "value": changed_provider(record)}]
    )
    assert set(result.review_required_ids) == {"d-sustain", "d-defence", "d-attack"}


def test_selected_condition_scope_is_also_a_context_dependency() -> None:
    record = fixture("provider-replacement")
    record["decisions"][1]["depends_on"] = []
    record["decisions"][1]["condition"]["scope"]["decision_ids"] = ["d-sustain"]
    record = seal_record(record)
    result = apply_record_changes(
        record_json(record),
        record["revision"],
        [{"op": "upsert_decision", "value": changed_provider(record)}],
    )
    assert "d-attack" in result.review_required_ids


def test_evidence_scope_targets_revalidate_without_a_duplicate_reverse_link() -> None:
    record = fixture("provider-replacement")
    evidence = fixture("well-shaped-unavailable-measurement")["evidence"][0]
    evidence["scope"]["decision_ids"] = ["d-sustain"]
    record["evidence"] = [evidence]
    record = seal_record(record)
    changed = deepcopy(evidence)
    changed["source"]["spec_sha256"] = "sha256:" + "1" * 64
    result = apply_record_changes(
        record_json(record), record["revision"], [{"op": "upsert_evidence", "value": changed}]
    )
    assert set(result.review_required_ids) == {"d-sustain", "d-attack", "d-defence"}


def test_unresolved_draft_reference_is_reported_without_losing_record() -> None:
    record = fixture("unresolved-draft-reference")
    report = inspect_record(record_json(record))
    assert report["checks"]["record_integrity"] == "valid"
    assert any(x["code"] == "UNRESOLVED_REFERENCE" for x in report["diagnostics"])


def test_existing_pending_review_is_not_dropped_by_an_unrelated_edit() -> None:
    record = fixture("provider-replacement")
    record["decisions"][0]["review"] = {
        "state": "required",
        "reasons": ["prior change"],
        "since_revision": record["revision"],
    }
    record = seal_record(record)
    result = apply_record_changes(
        record_json(record),
        record["revision"],
        [{"op": "merge_extensions", "value": {"unrelated": True}}],
    )
    assert "d-sustain" in result.review_required_ids


def test_resolved_dependent_question_reopens_but_deferred_question_stays_deferred() -> None:
    record = fixture("provider-replacement")
    question = deepcopy(fixture("in-game-question-is-not-an-approval-gate")["questions"][0])
    question.update(state="resolved", depends_on=["d-attack"])
    deferred = deepcopy(question)
    deferred.update(id="q-deferred", state="deferred")
    record["questions"] = [question, deferred]
    record = seal_record(record)
    result = apply_record_changes(
        record_json(record),
        record["revision"],
        [{"op": "upsert_decision", "value": changed_provider(record)}],
    )
    questions = parse_record(result.record_json)["questions"]
    assert questions[0]["state"] == "open"
    assert questions[1]["state"] == "deferred"


def test_rejected_later_operation_does_not_return_a_partially_changed_record() -> None:
    record = fixture("provider-replacement")
    text = record_json(record)
    with pytest.raises(DesignRecordError) as error:
        apply_record_changes(
            text,
            record["revision"],
            [
                {"op": "upsert_decision", "value": changed_provider(record)},
                {"op": "invent_new_behavior", "value": True},
            ],
        )
    assert error.value.code == "INVALID_CHANGE"
    assert inspect_record(text)["review_required_ids"] == []


@pytest.mark.parametrize("op", [[], None, {"not": "a string"}])
def test_malformed_operation_has_a_structured_failure(op: Any) -> None:
    record = create_record("test-design", "goal")
    with pytest.raises(DesignRecordError) as error:
        apply_record_changes(record_json(record), record["revision"], [{"op": op}])
    assert error.value.code == "INVALID_CHANGE"


def test_render_is_stable_and_does_not_claim_references_are_verified() -> None:
    record = fixture("well-shaped-unavailable-measurement")
    text = record_json(record)
    assert render_record(text) == render_record(text)
    assert "참조가 있다는 사실은 근거 검증 성공을 뜻하지 않는다" in render_record(text)
    assert "e-unavailable" in render_record(text)
    assert inspect_record(text)["checks"]["evidence_integrity"] == "not_checked"


def test_render_keeps_unknown_extensions_and_escapes_untrusted_table_text() -> None:
    record = fixture("provider-replacement")
    record["decisions"][0]["condition"]["statement"] = (
        "a | b\n<script>x</script> [x](javascript:bad)"
    )
    record["extensions"] = {"unknown": {"text": "keep exact raw data"}}
    text = record_json(seal_record(record))
    rendered = render_record(text)
    assert "<script>" not in rendered
    assert "a \\| b" in rendered
    assert "\\[x\\]" in rendered
    assert "keep exact raw data" in rendered
    assert parse_record(text)["extensions"] == record["extensions"]
