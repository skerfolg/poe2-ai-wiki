"""Public design operations: immutable checkpoints plus fresh evidence inspection.

The caller owns the current reference. No server-side head or build choice exists.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pok.artifacts.design_record import (
    DesignRecordError,
    canonical_bytes,
    create_record,
    parse_json_data,
    parse_record,
    record_json,
    seal_record,
)
from pok.artifacts.store import (
    discover_immutable_builds,
    new_build_id,
    read_build_blob,
    read_immutable_build,
    record_immutable_build,
)
from pok.engine.design_checkpoints import (
    REF_FORMAT,
    import_legacy_document,
    load_checkpoint,
    save_checkpoint,
    update_checkpoint,
)
from pok.engine.design_evidence import inspect_evidence, value_sha256


def read_design(reference: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    """Keep the historical assessment separate from a fresh local evidence check."""
    result = load_checkpoint(reference, root=root)
    result["current_assessment"] = inspect_evidence(result["record_json"], root=root)
    return result


def create_design(design_id: str, goal: str, *, root: Path | None = None) -> dict[str, Any]:
    text = record_json(create_record(design_id, goal))
    # Check before publication as well as after reading the published bytes.
    inspect_evidence(text, root=root)
    reference = save_checkpoint(text, root=root)
    return read_design(reference, root=root)


def capture_material(
    *,
    build_spec: dict[str, Any] | None = None,
    build_code: str | None = None,
    xml_text: str | None = None,
    metadata_ref: Mapping[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Atomically snapshot explicit inputs, producing schema-valid content refs.

    No current design head is changed and no XML/spec equivalence is inferred.
    Unknown spec fields and exact XML bytes remain available for later inspection.
    """
    if build_code is not None and xml_text is not None:
        raise DesignRecordError("AMBIGUOUS_XML_SOURCE", "Supply build_code or xml_text, not both")
    if build_code is not None:
        from pok.pob.codec import decode

        xml_text = decode(build_code)
    if build_spec is None and xml_text is None:
        raise DesignRecordError("MATERIAL_SOURCE_REQUIRED", "Supply a spec or original XML")
    files: dict[str, bytes] = {}
    components: dict[str, tuple[str, str]] = {}
    if build_spec is not None:
        files["spec.json"] = canonical_bytes(build_spec)
        components["spec"] = ("spec.json", "application/json")
    if xml_text is not None:
        files["original.xml"] = xml_text.encode("utf-8")
        components["xml"] = ("original.xml", "application/xml")
    if metadata_ref is not None:
        required = {"artifact_id", "name", "sha256"}
        if not required <= set(metadata_ref) <= required | {"media_type"} or not all(
            isinstance(value, str) for value in metadata_ref.values()
        ):
            raise DesignRecordError("INVALID_METADATA_REF", "Unsupported metadata blob reference")
        raw = read_build_blob(
            metadata_ref["artifact_id"], metadata_ref["name"], metadata_ref["sha256"], root=root
        )
        if not isinstance(parse_json_data(raw.decode("utf-8")), dict):
            raise DesignRecordError(
                "INVALID_METADATA_OBJECT", "Material metadata must be a JSON object"
            )
        files["metadata.json"] = raw
        components["metadata"] = ("metadata.json", "application/json")
    identity = new_build_id("design-material", root=root)
    material: dict[str, Any] = {"selection": dict(selection or {})}
    for component, (name, media_type) in components.items():
        material[component] = {
            "artifact_id": identity,
            "name": name,
            "sha256": "sha256:" + hashlib.sha256(files[name]).hexdigest(),
            "media_type": media_type,
        }
    material["revision"] = value_sha256(material)
    record = create_record("material-snapshot", "명시한 구성의 스냅샷")
    record["material"] = material
    text = record_json(seal_record(record))  # Validate the actual wire shape before publishing.
    saved = record_immutable_build(
        identity,
        files,
        {
            "kind": "design-material",
            "material_revision": material["revision"],
            "input_metadata_ref": dict(metadata_ref) if metadata_ref is not None else None,
        },
        root=root,
    )
    checked = inspect_evidence(text, root=root)
    return {
        "material": material,
        "manifest_sha256": saved["manifest_sha256"],
        "material_assessment": checked["material_assessment"],
        "claim": "caller_input_snapshot_not_build_validation",
        "selection_verification": "not_checked",
    }


def update_design(
    reference: Mapping[str, Any],
    expected_revision: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    user_decisions: Mapping[str, str] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    result = update_checkpoint(
        reference, expected_revision, changes, user_decisions=user_decisions, root=root
    )
    result.update(read_design(result["record_ref"], root=root))
    checks = result["current_assessment"]["checks"]
    result["change_summary"] = {
        "record_ref": result["record_ref"],
        "changed_decision_count": len(result["changed_decision_ids"]),
        "review_required_count": len(result["review_required_ids"]),
        "diagnostic_count": len(result["current_assessment"]["diagnostics"]),
        "no_change": result["no_change"],
        "checks": {
            name: checks[name]
            for name in (
                "record_integrity",
                "references",
                "evidence_integrity",
                "game_feasibility",
            )
        },
        "claim": "change_report_not_build_recommendation_or_game_certificate",
    }
    return result


def inspect_design(reference: Mapping[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    current = load_checkpoint(reference, root=root)
    return {
        "record_ref": dict(reference),
        "current_assessment": inspect_evidence(current["record_json"], root=root),
    }


def link_document_measurement(
    reference: Mapping[str, Any],
    expected_revision: str,
    document_measurement_ref: Mapping[str, Any],
    *,
    evidence_id: str,
    label: str,
    description: str,
    path: str = "/stats",
    usage: str = "current",
    material_revision: str | None = None,
    decision_ids: Sequence[str] = (),
    root: Path | None = None,
) -> dict[str, Any]:
    """Attach verified native evidence without guessing its input or adoption role."""
    from pok.engine.pob_documents import load_document_measurement

    current = load_checkpoint(reference, root=root)
    record = parse_record(current["record_json"])
    if record["revision"] != expected_revision:
        raise DesignRecordError(
            "REVISION_CONFLICT", "Expected revision differs from the provided base"
        )
    if usage not in {"current", "comparison", "historical"}:
        raise DesignRecordError("INVALID_EVIDENCE_USAGE", "Unsupported measurement usage")
    if usage == "current":
        material = record.get("material")
        if not material or "xml" not in material:
            raise DesignRecordError(
                "XML_MATERIAL_REQUIRED", "Current evidence requires XML material"
            )
        if material_revision is not None and material_revision != material["revision"]:
            raise DesignRecordError(
                "MATERIAL_REVISION_CONFLICT", "Current material revision differs"
            )
        material_revision = material["revision"]
    elif material_revision is None:
        raise DesignRecordError(
            "MATERIAL_REVISION_REQUIRED", "Preserve the original material revision"
        )
    manifest, _ = read_immutable_build(
        document_measurement_ref["artifact_id"],
        document_measurement_ref["manifest_sha256"],
        root=root,
    )
    own_xml_ref = {
        "artifact_id": document_measurement_ref["artifact_id"],
        "name": "input.xml",
        "sha256": manifest["files"]["input.xml"]["sha256"],
    }
    loaded = load_document_measurement(dict(document_measurement_ref), own_xml_ref, root=root)
    evidence = {
        "id": evidence_id,
        "kind": "measurement",
        "label": label,
        "scope": {
            "description": description,
            "decision_ids": list(decision_ids),
            "usage": usage,
            "material_revision": material_revision,
        },
        "source": {
            "representation": "pob_xml",
            "document_measurement_ref": dict(document_measurement_ref),
            "xml_sha256": loaded["xml_revision"],
            "path": path,
        },
    }
    candidate = dict(record)
    candidate["evidence"] = [e for e in record["evidence"] if e["id"] != evidence_id] + [evidence]
    assessment = inspect_evidence(record_json(seal_record(candidate)), root=root)
    row = next(e for e in assessment["evidence_assessments"] if e["id"] == evidence_id)
    if row["integrity"] != "verified" or (
        usage == "current" and row["application"] != "current_xml_verified"
    ):
        raise DesignRecordError("MEASUREMENT_ASSOCIATION_REJECTED", str(row))
    return update_design(
        reference,
        expected_revision,
        [{"op": "upsert_evidence", "value": evidence}],
        root=root,
    )


def import_design(
    design_id: str,
    *,
    document_text: str | None = None,
    source_ref: Mapping[str, Any] | None = None,
    goal: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Import literal UTF-8 text or exact bytes from a verified local blob."""
    if (document_text is None) == (source_ref is None):
        raise DesignRecordError("IMPORT_SOURCE_REQUIRED", "Supply exactly one import source")
    if source_ref is not None:
        if set(source_ref) != {"artifact_id", "name", "sha256"} or not all(
            isinstance(value, str) for value in source_ref.values()
        ):
            raise DesignRecordError("INVALID_IMPORT_SOURCE", "Malformed import blob reference")
        raw = read_build_blob(
            source_ref["artifact_id"], source_ref["name"], source_ref["sha256"], root=root
        )
    else:
        assert document_text is not None
        raw = document_text.encode("utf-8")
    reference = import_legacy_document(raw, design_id, goal=goal, root=root)
    return read_design(reference, root=root)


def list_designs(
    *,
    design_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
    root: Path | None = None,
) -> dict[str, Any]:
    """Discover and verify stored checkpoints; never infer a current branch head."""
    page = discover_immutable_builds(offset=offset, limit=limit, root=root)
    records = []
    diagnostics = list(page["diagnostics"])
    for entry in page["entries"]:
        try:
            manifest = entry["manifest"]
            metadata = manifest.get("metadata", {})
            if not isinstance(metadata, dict):
                raise ValueError("Immutable artifact metadata must be an object")
            if metadata.get("kind") != "design-checkpoint":
                continue
            if design_id is not None and metadata.get("design_id") != design_id:
                continue
            reference = {
                "format": REF_FORMAT,
                "artifact_id": entry["artifact_id"],
                "manifest_sha256": entry["manifest_sha256"],
                "revision": metadata["revision"],
                "sha256": manifest["files"]["design-record.json"]["sha256"],
            }
            loaded = load_checkpoint(reference, root=root)
            records.append(
                {
                    "record_ref": loaded["record_ref"],
                    "design_id": metadata["design_id"],
                    "goal_preview": metadata.get("goal_preview", ""),
                    "checkpoint_integrity": "verified",
                    "current_evidence_verification": "not_performed",
                }
            )
        except (ValueError, KeyError, TypeError) as exc:
            diagnostics.append(
                {
                    "artifact_id": entry["artifact_id"],
                    "code": "CHECKPOINT_DISCOVERY_INVALID",
                    "reason": str(exc),
                }
            )
    return {
        "records": records,
        "diagnostics": diagnostics,
        "next_offset": page["next_offset"],
        "pagination_scope": "artifact_directory_entries_not_matching_records",
        "current_head": "caller_owned_not_inferred",
    }
