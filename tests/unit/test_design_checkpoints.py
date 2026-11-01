"""Stored record/view linkage, explicit branches, raw legacy preservation."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from pok.artifacts.design_record import (
    DesignRecordError,
    create_record,
    parse_record,
    record_json,
    render_record,
    seal_record,
)
from pok.artifacts.store import read_immutable_build, record_immutable_build
from pok.engine.design_checkpoints import (
    REF_FORMAT,
    import_legacy_document,
    load_checkpoint,
    save_checkpoint,
    update_checkpoint,
)


def text() -> str:
    record = create_record("checkpoint-test", "목표와 실제 기록")
    record["extensions"] = {"large_int": 9007199254740993, "whole_float": 1.0}
    return record_json(seal_record(record))


def test_save_read_keeps_sealed_text_and_explicit_assessment_scope(tmp_path: Path) -> None:
    raw = text()
    reference = save_checkpoint(raw, artifact_id="20261101-design", root=tmp_path)
    loaded = load_checkpoint(reference, root=tmp_path)
    assert reference["format"] == REF_FORMAT
    assert reference["sha256"] == "sha256:" + hashlib.sha256(raw.encode()).hexdigest()
    assert loaded["record_json"] == raw
    assert loaded["design_md"] == render_record(raw)
    assert loaded["stored_assessment"]["checks"]["evidence_integrity"] == "not_checked"
    assert loaded["assessment_is_current_evidence_verification"] is False


def test_same_explicit_checkpoint_is_idempotent(tmp_path: Path) -> None:
    first = save_checkpoint(text(), artifact_id="20261101-design", root=tmp_path)
    assert save_checkpoint(text(), artifact_id="20261101-design", root=tmp_path) == first


@pytest.mark.parametrize("field", ["revision", "sha256", "manifest_sha256"])
def test_ref_mismatch_is_not_silently_corrected(tmp_path: Path, field: str) -> None:
    reference = save_checkpoint(text(), root=tmp_path)
    reference[field] = "sha256:" + "0" * 64
    with pytest.raises(ValueError):
        load_checkpoint(reference, root=tmp_path)


@pytest.mark.parametrize(
    "reference", [{}, {"format": "unknown"}, {"format": REF_FORMAT, "artifact_id": "../escape"}]
)
def test_malformed_reference_is_rejected(tmp_path: Path, reference: dict[str, Any]) -> None:
    with pytest.raises(DesignRecordError) as error:
        load_checkpoint(reference, root=tmp_path)
    assert error.value.code == "INVALID_DESIGN_REF"


def test_even_well_hashed_bundle_cannot_pair_record_with_a_different_view(tmp_path: Path) -> None:
    record = parse_record(text())
    files = {
        "design-record.json": text().encode(),
        "design.md": b"fake derived view",
        "assessment.json": json.dumps(
            {"design_id": record["design_id"], "revision": record["revision"]}
        ).encode(),
    }
    stored = record_immutable_build(
        "20261101-fake-view",
        files,
        {
            "kind": "design-checkpoint",
            "design_id": record["design_id"],
            "revision": record["revision"],
            "render_version": 1,
        },
        root=tmp_path,
    )
    reference = {
        "format": REF_FORMAT,
        "artifact_id": "20261101-fake-view",
        "revision": record["revision"],
        "sha256": stored["files"]["design-record.json"]["sha256"],
        "manifest_sha256": stored["manifest_sha256"],
    }
    with pytest.raises(DesignRecordError) as error:
        load_checkpoint(reference, root=tmp_path)
    assert error.value.code == "RENDER_MISMATCH"


def test_even_well_hashed_assessment_must_belong_to_this_record(tmp_path: Path) -> None:
    reference = save_checkpoint(text(), root=tmp_path)
    manifest, files = read_immutable_build(
        reference["artifact_id"], reference["manifest_sha256"], root=tmp_path
    )
    assessment = json.loads(files["assessment.json"])
    assessment["revision"] = "sha256:" + "0" * 64
    files["assessment.json"] = json.dumps(assessment).encode()
    stored = record_immutable_build(
        "20261101-other-assessment", files, manifest["metadata"], root=tmp_path
    )
    altered = {
        **reference,
        "artifact_id": stored["artifact_id"],
        "manifest_sha256": stored["manifest_sha256"],
    }
    with pytest.raises(DesignRecordError) as error:
        load_checkpoint(altered, root=tmp_path)
    assert error.value.code == "ASSESSMENT_MISMATCH"


def test_update_writes_a_child_and_never_changes_the_parent(tmp_path: Path) -> None:
    raw = text()
    parent = save_checkpoint(raw, root=tmp_path)
    result = update_checkpoint(
        parent,
        parent["revision"],
        [{"op": "merge_extensions", "value": {"child": True}}],
        root=tmp_path,
    )
    child = load_checkpoint(result["record_ref"], root=tmp_path)
    assert parse_record(child["record_json"])["parents"] == [parent["revision"]]
    assert child["operation_provenance"]["base_revision"] == parent["revision"]
    assert load_checkpoint(parent, root=tmp_path)["record_json"] == raw


def test_noop_reuses_the_same_reference_and_does_not_create_a_directory(tmp_path: Path) -> None:
    parent = save_checkpoint(text(), root=tmp_path)
    before = sorted(p.name for p in (tmp_path / "artifacts/builds").iterdir())
    result = update_checkpoint(parent, parent["revision"], [], root=tmp_path)
    assert result["no_change"] and result["record_ref"] == parent
    assert sorted(p.name for p in (tmp_path / "artifacts/builds").iterdir()) == before


def test_conflicting_update_cannot_publish_another_child(tmp_path: Path) -> None:
    parent = save_checkpoint(text(), root=tmp_path)
    before = sorted(p.name for p in (tmp_path / "artifacts/builds").iterdir())
    with pytest.raises(DesignRecordError) as error:
        update_checkpoint(
            parent,
            "sha256:" + "0" * 64,
            [{"op": "set_goal", "value": {"summary": "bad base"}}],
            root=tmp_path,
        )
    assert error.value.code == "REVISION_CONFLICT"
    assert sorted(p.name for p in (tmp_path / "artifacts/builds").iterdir()) == before


def test_two_changes_preserve_two_explicit_branches(tmp_path: Path) -> None:
    parent = save_checkpoint(text(), root=tmp_path)
    a = update_checkpoint(
        parent,
        parent["revision"],
        [{"op": "merge_extensions", "value": {"branch": "a"}}],
        root=tmp_path,
    )
    b = update_checkpoint(
        parent,
        parent["revision"],
        [{"op": "merge_extensions", "value": {"branch": "b"}}],
        root=tmp_path,
    )
    assert a["record_ref"] != b["record_ref"]
    for result in [a, b]:
        record = parse_record(load_checkpoint(result["record_ref"], root=tmp_path)["record_json"])
        assert record["parents"] == [parent["revision"]]


def test_legacy_import_preserves_bom_crlf_unknown_content_and_classification(
    tmp_path: Path,
) -> None:
    raw = (
        "\ufeff# 이전 기록\r\n## 확정\r\n- 선택했던 구현\r\n"
        "## 알 수 없는 절\r\n<!-- 보존 -->\r\n임의 | 내용\r\n"
    ).encode()
    reference = import_legacy_document(raw, "legacy-test", root=tmp_path)
    loaded = load_checkpoint(reference, root=tmp_path)
    record = parse_record(loaded["record_json"])
    assert record["decisions"] == []
    legacy = record["extensions"]["legacy_import"]
    assert legacy["classification"] == "unclassified"
    assert legacy["extracted"]["confirmed"] == ["선택했던 구현"]
    _, files = read_immutable_build(
        reference["artifact_id"], reference["manifest_sha256"], root=tmp_path
    )
    assert files["original.md"] == raw
    assert record["legacy_sources"][0]["sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()


def test_unsupported_legacy_encoding_is_preserved_as_opaque_not_replaced(tmp_path: Path) -> None:
    raw = b"\xff\xfe\x00not-utf8\x81"
    reference = import_legacy_document(raw, "legacy-opaque", root=tmp_path)
    record = parse_record(load_checkpoint(reference, root=tmp_path)["record_json"])
    assert record["extensions"]["legacy_import"]["decode_status"] == "unsupported_encoding"
    assert record["legacy_sources"][0]["media_type"] == "application/octet-stream"
    assert record["decisions"] == []
    _, files = read_immutable_build(
        reference["artifact_id"], reference["manifest_sha256"], root=tmp_path
    )
    assert files["original.md"] == raw


def test_extra_files_cannot_replace_generated_components(tmp_path: Path) -> None:
    with pytest.raises(DesignRecordError) as error:
        save_checkpoint(text(), extra_files={"design.md": b"not generated"}, root=tmp_path)
    assert error.value.code == "RESERVED_CHECKPOINT_FILE"
    assert not list((tmp_path / "artifacts/builds").glob("*/manifest.json"))


def test_ref_or_record_changes_do_not_mutate_the_callers_objects(tmp_path: Path) -> None:
    parent = save_checkpoint(text(), root=tmp_path)
    before = deepcopy(parent)
    update_checkpoint(
        parent, parent["revision"], [{"op": "merge_extensions", "value": {"x": 1}}], root=tmp_path
    )
    assert parent == before
