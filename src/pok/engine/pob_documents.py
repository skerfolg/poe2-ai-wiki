"""Immutable raw-document inspection/editing; no implicit spec regeneration."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pok.artifacts.design_record import canonical_bytes, parse_json_data
from pok.artifacts.store import (
    new_build_id,
    read_build_blob,
    read_immutable_build,
    record_immutable_build,
)
from pok.common.execution import current_execution
from pok.pob.document import (
    inspect_xml,
    set_xml_attribute,
    set_xml_text,
    upsert_xml_child_attribute,
    xml_node_pointer,
    xml_revision,
)


def _read(reference: dict[str, Any], root: Path | None) -> str:
    required = {"artifact_id", "name", "sha256"}
    if not required <= set(reference) <= required | {"media_type"} or not all(
        isinstance(value, str) for value in reference.values()
    ):
        raise ValueError("Expected an XML artifact_id/name/sha256 reference")
    return read_build_blob(
        reference["artifact_id"], reference["name"], reference["sha256"], root=root
    ).decode("utf-8")


def read_document(reference: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    xml = _read(reference, root)
    return {
        "xml_ref": dict(reference),
        "xml_text": xml,
        "xml_revision": xml_revision(xml),
        "claim": "verified_source_bytes_not_build_validation",
    }


def measure_document(
    reference: dict[str, Any],
    *,
    stats: list[str] | None = None,
    native_timeout_s: float = 180,
    use_cache: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    """Measure exactly the referenced XML and retain its full native result.

    The timeout covers the native subprocess, not a complete request lifecycle.
    No BuildSpec reconstruction, set choice or game-feasibility claim is added.
    """
    from pok.pob.runner import run_xml

    if not 0 < native_timeout_s <= 180:
        raise ValueError("native_timeout_s must be between 0 and 180 seconds")
    xml = _read(reference, root)
    revision = xml_revision(xml)
    result = run_xml(xml, timeout=native_timeout_s, use_cache=use_cache)
    measured = {
        "format": "pok.document-measurement.v1",
        "xml_revision": revision,
        "source_xml_ref": dict(reference),
        "stats": result.stats,
        "meta": result.meta,
        "allocated_nodes": list(result.allocated_nodes),
        "cached": result.cached,
        "claim": "native_xml_calculation_not_game_validation",
        "execution_identity": "not_verified",
    }
    identity = new_build_id("pob-document-measurement", root=root)
    saved = record_immutable_build(
        identity,
        {"input.xml": xml.encode("utf-8"), "measurement.json": canonical_bytes(measured)},
        {
            "kind": "pob-document-measurement",
            "xml_revision": revision,
            "source_xml_ref": dict(reference),
        },
        root=root,
    )
    measurement_ref = {
        "format": "pok.document-measurement-ref.v1",
        "artifact_id": identity,
        "sha256": saved["files"]["measurement.json"]["sha256"],
        "manifest_sha256": saved["manifest_sha256"],
    }
    requested = None if stats is None or stats == ["*"] else stats
    return {
        "stats": dict(result.stats)
        if requested is None
        else {name: result.stats[name] for name in requested if name in result.stats},
        "missing_stats": []
        if requested is None
        else [name for name in requested if name not in result.stats],
        "meta": result.meta,
        "xml_revision": revision,
        "measured_xml_ref": {
            "artifact_id": identity,
            "name": "input.xml",
            "sha256": saved["files"]["input.xml"]["sha256"],
            "media_type": "application/xml",
        },
        "document_measurement_ref": measurement_ref,
        "design_evidence_source": {
            "representation": "pob_xml",
            "document_measurement_ref": measurement_ref,
            "xml_sha256": revision,
            "path": "/stats",
        },
        "manifest_sha256": saved["manifest_sha256"],
        "cached": result.cached,
        "claim": measured["claim"],
        "execution_identity": "not_verified",
        "lifecycle_deadline": "bound_request_absolute_deadline"
        if current_execution() is not None
        else "native_timeout_only",
    }


def load_document_measurement(
    reference: dict[str, Any], xml_reference: dict[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    """Verify the entire calculation bundle and its exact XML subject.

    This binds bytes and native observations, not engine execution identity or
    game feasibility. Source ownership is the same trusted-local-store model.
    """
    if (
        set(reference) != {"format", "artifact_id", "sha256", "manifest_sha256"}
        or reference.get("format") != "pok.document-measurement-ref.v1"
        or not all(isinstance(value, str) for value in reference.values())
    ):
        raise ValueError("Malformed document measurement reference")
    manifest, files = read_immutable_build(
        reference["artifact_id"], reference["manifest_sha256"], root=root
    )
    if manifest["metadata"].get("kind") != "pob-document-measurement":
        raise ValueError("Reference is not a document measurement bundle")
    if manifest["files"]["measurement.json"]["sha256"] != reference["sha256"]:
        raise ValueError("Document measurement content hash differs")
    xml = _read(xml_reference, root)
    if files["input.xml"] != xml.encode("utf-8"):
        raise ValueError("Measurement belongs to another XML document")
    measured = parse_json_data(files["measurement.json"].decode("utf-8"))
    if not isinstance(measured, dict) or measured.get("format") != "pok.document-measurement.v1":
        raise ValueError("Unsupported document measurement")
    revision = xml_revision(xml)
    if (
        measured.get("xml_revision") != revision
        or manifest["metadata"].get("xml_revision") != revision
    ):
        raise ValueError("Measurement XML revision is inconsistent")
    return {
        "document_measurement_ref": dict(reference),
        "xml_ref": dict(xml_reference),
        "xml_revision": revision,
        "measurement": measured,
        "binding": "verified_exact_xml_subject",
        "execution_identity": "not_verified",
        "claim": "stored_native_observation_not_game_validation",
    }


def inspect_document(
    reference: dict[str, Any],
    *,
    tag: str | None = None,
    offset: int = 0,
    limit: int = 20,
    root: Path | None = None,
) -> dict[str, Any]:
    if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Expected offset >= 0 and limit between 1 and 100")
    xml = _read(reference, root)
    all_nodes = inspect_xml(xml)
    parents = {node.path[:-1] for node in all_nodes if node.path}
    nodes = [node for node in all_nodes if tag is None or node.tag == tag]
    raw = xml.encode("utf-8")
    end = offset + limit
    return {
        "xml_ref": dict(reference),
        "xml_revision": xml_revision(xml),
        "nodes": [
            {
                "path": list(node.path),
                "tag": node.tag,
                "attributes": node.attributes,
                "raw_attributes": node.raw_attributes,
                "raw_text": (
                    ""
                    if raw[node.start : node.start_end].endswith(b"/>")
                    else raw[node.start_end : node.end_start].decode("utf-8")
                )
                if node.path not in parents
                else None,
                "provider_binding_pointer": xml_node_pointer(node.path),
                "provider_binding_value_sha256": "sha256:"
                + hashlib.sha256(
                    canonical_bytes(raw[node.start : node.end].decode("utf-8"))
                ).hexdigest(),
            }
            for node in nodes[offset:end]
        ],
        "next_offset": end if end < len(nodes) else None,
        "total_matching_nodes": len(nodes),
        "claim": "structural_xml_inspection_not_native_or_game_validation",
    }


def edit_document(
    reference: dict[str, Any],
    expected_revision: str,
    changes: list[dict[str, Any]],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    original = _read(reference, root)
    if xml_revision(original) != expected_revision:
        raise ValueError("XML revision conflict")
    current = original
    base_required = {"path", "tag", "expected_raw_value", "value"}
    for change in changes:
        operation = change.get("op", "set_attribute")
        extra = (
            {"child_tag", "identity_attribute", "identity_value"}
            if operation == "upsert_child_attribute"
            else set()
        )
        if operation not in {"set_attribute", "upsert_child_attribute", "set_text"}:
            raise ValueError("Unsupported explicit XML edit operation")
        required = base_required | ({"attribute"} if operation != "set_text" else set())
        if set(change) - {"op"} != required | extra or not isinstance(change["path"], list):
            raise ValueError("Malformed explicit XML attribute change")
        strings = {"tag", "value"} | extra | ({"attribute"} if operation != "set_text" else set())
        if not all(isinstance(change[key], str) for key in strings):
            raise ValueError("XML tag, attribute and value must be strings")
        if change["expected_raw_value"] is not None and not isinstance(
            change["expected_raw_value"], str
        ):
            raise ValueError("Expected raw attribute value must be a string or null")
        path = tuple(change["path"])
        target = next((node for node in inspect_xml(current) if node.path == path), None)
        if target is None or target.tag != change["tag"]:
            raise ValueError("XML target tag/path conflict")
        if operation == "set_attribute":
            current = set_xml_attribute(
                current,
                xml_revision(current),
                path,
                change["attribute"],
                change["expected_raw_value"],
                change["value"],
            ).xml
        elif operation == "set_text":
            if not isinstance(change["expected_raw_value"], str):
                raise ValueError("Expected raw text must be an explicit string")
            current = set_xml_text(
                current, xml_revision(current), path, change["expected_raw_value"], change["value"]
            ).xml
        else:
            current = upsert_xml_child_attribute(
                current,
                xml_revision(current),
                path,
                change["child_tag"],
                change["identity_attribute"],
                change["identity_value"],
                change["attribute"],
                change["expected_raw_value"],
                change["value"],
            ).xml
    if current == original:
        return {
            "xml_ref": dict(reference),
            "xml_revision": expected_revision,
            "parent_revision": expected_revision,
            "no_change": True,
            "claim": "structural_edit_not_native_or_game_validation",
        }
    identity = new_build_id("pob-document", root=root)
    saved = record_immutable_build(
        identity,
        {
            "original.xml": current.encode("utf-8"),
            "operation.json": canonical_bytes(
                {"parent_ref": reference, "parent_revision": expected_revision, "changes": changes}
            ),
        },
        {
            "kind": "pob-document",
            "parent_ref": reference,
            "parent_revision": expected_revision,
            "xml_revision": xml_revision(current),
        },
        root=root,
    )
    return {
        "xml_ref": {
            "artifact_id": identity,
            "name": "original.xml",
            "sha256": saved["files"]["original.xml"]["sha256"],
            "media_type": "application/xml",
        },
        "xml_revision": xml_revision(current),
        "parent_revision": expected_revision,
        "manifest_sha256": saved["manifest_sha256"],
        "no_change": False,
        "claim": "structural_edit_not_native_or_game_validation",
        "spec_and_metadata_rebinding": "not_performed",
    }
