"""Compose immutable design checkpoints in the existing build artifact store.

No mutable server head, build choice, or implicit PoB calculation is introduced.
Stored assessments are historical structural reports, not current evidence or
game-feasibility certificates. Actual evidence inspection is separate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pok.artifacts.design import parse_design
from pok.artifacts.design_record import (
    RENDER_VERSION,
    DesignRecordError,
    canonical_bytes,
    create_record,
    parse_record,
    record_json,
    render_record,
    seal_record,
)
from pok.artifacts.store import new_build_id, read_immutable_build, record_immutable_build
from pok.engine.design_records import apply_record_changes, inspect_record

REF_FORMAT = "pok.design-ref.v1"
_REF_FIELDS = {"format", "artifact_id", "revision", "sha256", "manifest_sha256"}
_CORE_FILES = {"design-record.json", "design.md", "assessment.json", "manifest.json"}


def save_checkpoint(
    record_text: str,
    *,
    artifact_id: str | None = None,
    operation_provenance: Mapping[str, Any] | None = None,
    extra_files: Mapping[str, bytes] | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    record = parse_record(record_text)
    identity = artifact_id or new_build_id(
        f"design-{record['design_id'][:32]}-{record['revision'][-12:]}", root=root
    )
    additions = dict(extra_files or {})
    if any(name.casefold() in _CORE_FILES for name in additions):
        raise DesignRecordError(
            "RESERVED_CHECKPOINT_FILE", "Cannot replace generated checkpoint files"
        )
    assessment = inspect_record(record_text)
    files = {
        **additions,
        "design-record.json": record_text.encode("utf-8"),
        "design.md": render_record(record_text).encode("utf-8"),
        "assessment.json": canonical_bytes(assessment),
    }
    result = record_immutable_build(
        identity,
        files,
        {
            "kind": "design-checkpoint",
            "design_id": record["design_id"],
            "revision": record["revision"],
            "render_version": RENDER_VERSION,
            "assessment_scope": "structural_only",
            "goal_preview": record["goal"]["summary"][:240],
            "operation_provenance": dict(operation_provenance or {}),
        },
        root=root,
    )
    reference = {
        "format": REF_FORMAT,
        "artifact_id": identity,
        "revision": record["revision"],
        "sha256": result["files"]["design-record.json"]["sha256"],
        "manifest_sha256": result["manifest_sha256"],
    }
    # Return success only after checking the actual published bytes and links.
    load_checkpoint(reference, root=root)
    return reference


def load_checkpoint(reference: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    if (
        not isinstance(reference, Mapping)
        or set(reference) != _REF_FIELDS
        or reference.get("format") != REF_FORMAT
        or any(not isinstance(reference[key], str) for key in _REF_FIELDS)
    ):
        raise DesignRecordError("INVALID_DESIGN_REF", "Unsupported or malformed design reference")
    manifest, files = read_immutable_build(
        reference["artifact_id"], reference["manifest_sha256"], root=root
    )
    metadata = manifest["metadata"]
    if metadata.get("kind") != "design-checkpoint":
        raise DesignRecordError("WRONG_ARTIFACT_KIND", "Reference is not a design checkpoint")
    if metadata.get("render_version") != RENDER_VERSION:
        raise DesignRecordError(
            "UNSUPPORTED_RENDER_VERSION", "Stored renderer version is unsupported"
        )
    try:
        raw = files["design-record.json"]
        if reference["sha256"] != "sha256:" + hashlib.sha256(raw).hexdigest():
            raise DesignRecordError(
                "RECORD_REF_MISMATCH", "Stored record differs from its reference"
            )
        text = raw.decode("utf-8")
        record = parse_record(text)
        if (
            record["revision"] != reference["revision"]
            or metadata.get("revision") != record["revision"]
            or metadata.get("design_id") != record["design_id"]
        ):
            raise DesignRecordError("RECORD_REF_MISMATCH", "Design identity/revision differs")
        rendered = render_record(text)
        if files["design.md"] != rendered.encode("utf-8"):
            raise DesignRecordError(
                "RENDER_MISMATCH", "Stored view is not the record's stable rendering"
            )
        assessment = json.loads(files["assessment.json"])
        if (
            not isinstance(assessment, dict)
            or assessment.get("revision") != record["revision"]
            or assessment.get("design_id") != record["design_id"]
        ):
            raise DesignRecordError(
                "ASSESSMENT_MISMATCH", "Stored assessment belongs to another record"
            )
    except (KeyError, UnicodeError, json.JSONDecodeError) as exc:
        raise DesignRecordError(
            "INCOMPLETE_CHECKPOINT", "Checkpoint components cannot be read"
        ) from exc
    return {
        "record_ref": dict(reference),
        "record_json": text,
        "design_md": rendered,
        "stored_assessment": assessment,
        "assessment_is_current_evidence_verification": False,
        "operation_provenance": metadata.get("operation_provenance", {}),
    }


def update_checkpoint(
    reference: Mapping[str, Any],
    expected_revision: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    user_decisions: Mapping[str, str] | None = None,
    artifact_id: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    current = load_checkpoint(reference, root=root)
    change = apply_record_changes(
        current["record_json"], expected_revision, changes, user_decisions=user_decisions
    )
    target = (
        dict(reference)
        if change.no_change
        else save_checkpoint(
            change.record_json,
            artifact_id=artifact_id,
            operation_provenance=change.operation_provenance,
            root=root,
        )
    )
    return {
        "record_ref": target,
        "changed_decision_ids": list(change.changed_decision_ids),
        "review_required_ids": list(change.review_required_ids),
        "diagnostics": list(change.diagnostics),
        "no_change": change.no_change,
        "evidence_integrity": "not_checked",
    }


def import_legacy_document(
    raw: bytes,
    design_id: str,
    *,
    goal: str | None = None,
    artifact_id: str | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    """Preserve exact source bytes; extracted confirmed text never becomes user_fixed."""
    identity = artifact_id or new_build_id(f"design-import-{design_id[:32]}", root=root)
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeError:
        legacy: dict[str, Any] = {
            "decode_status": "unsupported_encoding",
            "classification": "unclassified",
        }
        source_goal = None
    else:
        document = parse_design(decoded)
        # Parser tuples become a JSON projection, never a replacement for raw.
        extracted = json.loads(json.dumps(asdict(document), ensure_ascii=False, allow_nan=False))
        legacy = {
            "decode_status": "utf8_projection",
            "classification": "unclassified",
            "extracted": extracted,
        }
        source_goal = document.goal
    record = create_record(design_id, goal or source_goal or "가져온 설계 문서 검토")
    record["legacy_sources"] = [
        {
            "artifact_id": identity,
            "name": "original.md",
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
            "media_type": "application/octet-stream"
            if legacy["decode_status"] == "unsupported_encoding"
            else "text/markdown",
        }
    ]
    record["extensions"]["legacy_import"] = legacy
    record = seal_record(record)
    return save_checkpoint(
        record_json(record),
        artifact_id=identity,
        extra_files={"original.md": raw},
        operation_provenance={"operation": "legacy_import", "role_assignment": "not_performed"},
        root=root,
    )
