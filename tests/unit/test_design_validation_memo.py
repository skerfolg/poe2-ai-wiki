"""Successful validation reuse cannot hide mutable content or schema changes."""

import pytest
from jsonschema import Draft202012Validator

from pok.artifacts import design_record as module


def test_mutating_a_validated_object_is_still_rejected():
    record = module.create_record("memo-test", "valid")
    module.record_json(record)
    record["goal"]["summary"] = False
    with pytest.raises(module.DesignRecordError, match="not of type"):
        module.record_json(record)


def test_replaced_validator_with_new_schema_cannot_reuse_old_success(monkeypatch):
    record = module.create_record("schema-test", "valid")
    module.record_json(record)
    schema = module.record_schema()
    schema["required"].append("new_runtime_requirement")
    changed = Draft202012Validator(schema)
    monkeypatch.setattr(module, "_validator", lambda: changed)
    with pytest.raises(module.DesignRecordError, match="new_runtime_requirement"):
        module.record_json(record)


def test_revision_recheck_is_not_skipped_on_validation_memo_hit():
    record = module.create_record("revision-test", "valid")
    record["goal"]["summary"] = "changed but unsealed"
    # Shape validation succeeds, including on the second attempt, but the
    # integrity check must independently reject both serializations.
    for _ in range(2):
        with pytest.raises(module.DesignRecordError, match="unsealed"):
            module.record_json(record)
