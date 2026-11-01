"""Verify stored facts and their declared input scope, without selecting a build.

Verified bytes/inputs are not proof of game feasibility or adequate exploration.
The immutable local tool store is trusted as a producer; this is not a signature
scheme against a host owner who can fabricate both files and their references.
"""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from pok.artifacts.design_record import canonical_bytes, parse_json_data, parse_record
from pok.artifacts.store import (
    ArtifactUnavailableError,
    read_build_blob,
    read_immutable_build,
)
from pok.artifacts.tool_results import load_result, select
from pok.engine.design_records import inspect_record

CatalogLoader = Callable[[str, str, Path | None], dict[str, Any]]


def value_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _catalog_record(catalog: str, identity: str, root: Path | None) -> dict[str, Any]:
    from pok.index.search import get_entry, get_insight

    return get_entry(identity, root=root) if catalog == "kb" else get_insight(identity, root=root)


def _blob(reference: dict[str, Any], root: Path | None) -> bytes:
    return read_build_blob(
        reference["artifact_id"], reference["name"], reference["sha256"], root=root
    )


def _material(
    record: dict[str, Any], root: Path | None
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    material = record["material"]
    report: dict[str, Any] = {
        "status": "unbound",
        "xml_spec_consistency": "not_checked",
        "diagnostics": [],
    }
    if material is None:
        return report, None
    report["revision"] = material["revision"]
    actual_revision = value_sha256(
        {key: value for key, value in material.items() if key != "revision"}
    )
    if actual_revision != material["revision"]:
        report.update(status="mismatch", diagnostics=[{"code": "MATERIAL_REVISION_MISMATCH"}])
        return report, None
    spec = None
    xml = None
    metadata = None
    report["status"] = "verified_blobs"
    for component in ("xml", "spec", "metadata"):
        if component not in material:
            continue
        try:
            raw = _blob(material[component], root)
            if component == "xml":
                xml = raw
                report["xml_sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
            if component in {"spec", "metadata"}:
                parsed = parse_json_data(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise ValueError("Material projection must be an object")
                if component == "spec":
                    spec = parsed
                    report["spec_sha256"] = value_sha256(parsed)
                else:
                    metadata = parsed
        except ArtifactUnavailableError as exc:
            report["status"] = "unavailable"
            report["diagnostics"].append(
                {"code": "MATERIAL_UNAVAILABLE", "component": component, "reason": str(exc)}
            )
        except (ValueError, UnicodeError) as exc:
            report["status"] = "mismatch"
            report["diagnostics"].append(
                {"code": "MATERIAL_INTEGRITY_FAILURE", "component": component, "reason": str(exc)}
            )
    # A missing acquisition sidecar does not erase an independently verified
    # calculator projection. Its separate integrity diagnostic remains visible.
    codes = {issue["code"] for issue in report["diagnostics"]}
    if "MATERIAL_INTEGRITY_FAILURE" in codes:
        report["status"] = "mismatch"
    elif "MATERIAL_UNAVAILABLE" in codes:
        report["status"] = "unavailable"
    if metadata is not None and metadata.get("format") == "pok.socket-sidecar.v1":
        from pok.engine.restore_fidelity import inspect_socket_material

        reference = {key: material["metadata"][key] for key in ("artifact_id", "name", "sha256")}
        binding = inspect_socket_material(
            xml, spec, metadata, reference, selection=material["selection"], root=root
        )
        report["socket_metadata_binding"] = binding
        if binding["status"] != "verified_declared_binding":
            report["diagnostics"].append(
                {"code": "SOCKET_METADATA_BINDING_REQUIRES_REVIEW", **binding}
            )
    report["declared_selection"] = material["selection"]
    return report, spec


def _measurement_subject(
    payload: dict[str, Any], pointer: str
) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    # Validate pointer escapes and existence before interpreting its subject.
    selected = select(payload, pointer)
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer.split("/")[1:]]
    inputs = payload["inputs"]
    if payload["tool"] == "compute_pob" and parts[:1] == ["result"]:
        subject = inputs.get("build_spec")
        output = payload["result"]
    elif payload["tool"] == "evaluate_delta" and parts[:2] == ["result", "base"]:
        subject = inputs.get("base_spec")
        output = payload["result"]["base"]
    elif (
        payload["tool"] == "evaluate_delta"
        and len(parts) >= 3
        and parts[:2] == ["result", "variants"]
    ):
        subject = inputs.get("variants", {}).get(parts[2])
        output = payload["result"]["variants"][parts[2]]
    else:
        raise ValueError("Unsupported measurement tool/path; select one actually measured subject")
    if not isinstance(subject, dict):
        raise ValueError("Stored measurement has no explicit subject spec")
    if not isinstance(output, dict) or not isinstance(output.get("stats"), dict):
        raise ValueError("Stored subject has no calculator statistics object")
    return subject, selected, output


def _source_check(payload: dict[str, Any], expected: Mapping[str, Any] | None) -> dict[str, Any]:
    if not expected:
        return {"status": "not_checked", "fields": []}
    source = payload.get("source", {})
    if not isinstance(source, dict):
        return {"status": "mismatch", "fields": sorted(expected)}
    missing = [key for key in expected if key not in source]
    changed = [key for key in expected if key in source and source[key] != expected[key]]
    return {
        "status": "mismatch" if changed else "incomplete" if missing else "matched_declared_fields",
        "fields": sorted(expected),
        "missing": missing,
        "changed": changed,
    }


def _measurement(
    evidence: dict[str, Any],
    material: dict[str, Any],
    current_spec: dict[str, Any] | None,
    root: Path | None,
    expected_source: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source, scope = evidence["source"], evidence["scope"]
    if source.get("representation") == "pob_xml":
        return _xml_measurement(evidence, material, root, expected_source)
    try:
        payload, _ = load_result(source["$pok_result"], root=root)
    except ValueError as exc:
        unavailable = isinstance(exc.__cause__, OSError)
        return {
            "integrity": "unavailable" if unavailable else "mismatch",
            "application": "unverified",
            "diagnostics": [
                {
                    "code": "EVIDENCE_UNAVAILABLE" if unavailable else "EVIDENCE_INTEGRITY_FAILURE",
                    "reason": str(exc),
                }
            ],
        }
    try:
        subject, selected, output = _measurement_subject(payload, source["path"])
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        return {
            "integrity": "unsupported",
            "application": "unverified",
            "diagnostics": [{"code": "UNSUPPORTED_MEASUREMENT_SUBJECT", "reason": str(exc)}],
        }
    digest = value_sha256(subject)
    if digest != source["spec_sha256"]:
        return {
            "integrity": "mismatch",
            "application": "unverified",
            "diagnostics": [{"code": "MEASUREMENT_INPUT_MISMATCH", "actual_spec_sha256": digest}],
        }
    report: dict[str, Any] = {
        "integrity": "verified",
        "source_check": _source_check(payload, expected_source),
        "tool": payload["tool"],
        "spec_sha256": digest,
        "diagnostics": [],
    }
    if scope["usage"] != "current":
        report["application"] = scope["usage"]
    elif current_spec is None:
        report["application"] = "unverified"
        report["diagnostics"].append({"code": "CURRENT_SPEC_PROJECTION_UNAVAILABLE"})
    elif digest != value_sha256(current_spec):
        report["application"] = "different_input"
        report["diagnostics"].append({"code": "CURRENT_MEASUREMENT_INPUT_MISMATCH"})
    elif scope["material_revision"] != material["revision"]:
        report["application"] = "same_spec_reuse_requires_mapping"
        report["diagnostics"].append({"code": "MATERIAL_MAPPING_REVIEW"})
    else:
        report["application"] = "current_spec_verified"
    if selected is None:
        report["diagnostics"].append({"code": "SELECTED_VALUE_UNMEASURED_OR_NORMALIZED"})
    report["measurement_status"] = "statistics_present" if output["stats"] else "no_statistics"
    if output.get("ok") is False or not output["stats"]:
        report["measurement_status"] = "failed_or_unmeasured"
        report["diagnostics"].append({"code": "MEASUREMENT_FAILED_OR_UNMEASURED"})
    limits = [
        key
        for key in ("tree_connected", "items_legal", "item_sockets_legal")
        if output.get(key) is False
    ]
    limits.extend(
        key
        for key in (
            "pruned_nodes",
            "illegal_items",
            "req_shortfall",
            "unbuilt_declarations",
            "dropped_items",
        )
        if output.get(key)
    )
    report["observed_limit_fields"] = limits
    if limits:
        report["diagnostics"].append({"code": "MEASUREMENT_HAS_SUBJECT_LIMITS", "fields": limits})
    report["selected_value_kind"] = type(selected).__name__
    # Avoid reproducing an arbitrarily large stats/candidate payload in a summary.
    report["selected_value_sha256"] = value_sha256(selected)
    return report


def _xml_measurement(
    evidence: dict[str, Any],
    material: dict[str, Any],
    root: Path | None,
    expected_source: Mapping[str, Any] | None,
) -> dict[str, Any]:
    from pok.engine.pob_documents import load_document_measurement

    source, scope = evidence["source"], evidence["scope"]
    reference = source["document_measurement_ref"]
    try:
        manifest, files = read_immutable_build(
            reference["artifact_id"], reference["manifest_sha256"], root=root
        )
        own_xml_ref = {
            "artifact_id": reference["artifact_id"],
            "name": "input.xml",
            "sha256": manifest["files"]["input.xml"]["sha256"],
        }
        loaded = load_document_measurement(reference, own_xml_ref, root=root)
    except (ValueError, OSError, KeyError) as exc:
        unavailable = isinstance(exc, OSError) or isinstance(exc.__cause__, OSError)
        return {
            "integrity": "unavailable" if unavailable else "mismatch",
            "application": "unverified",
            "diagnostics": [
                {
                    "code": "XML_MEASUREMENT_UNAVAILABLE"
                    if unavailable
                    else "XML_MEASUREMENT_INTEGRITY_FAILURE",
                    "reason": str(exc),
                }
            ],
        }
    measured = loaded["measurement"]
    digest = loaded["xml_revision"]
    if source["xml_sha256"] != digest:
        return {
            "integrity": "mismatch",
            "application": "unverified",
            "diagnostics": [
                {"code": "XML_MEASUREMENT_INPUT_MISMATCH", "actual_xml_sha256": digest}
            ],
        }
    try:
        if not (
            source["path"] == "/stats"
            or source["path"].startswith("/stats/")
            or source["path"] == "/meta"
            or source["path"].startswith("/meta/")
        ):
            raise ValueError("Select native statistics or native metadata, not receipt claims")
        selected = select(measured, source["path"])
    except (ValueError, TypeError, KeyError) as exc:
        return {
            "integrity": "unsupported",
            "application": "unverified",
            "diagnostics": [{"code": "UNSUPPORTED_XML_MEASUREMENT_SUBJECT", "reason": str(exc)}],
        }
    report: dict[str, Any] = {
        "integrity": "verified",
        "representation": "pob_xml",
        "xml_sha256": digest,
        "tool": "compute_pob_document",
        "execution_identity": "not_verified",
        "diagnostics": [],
        "source_check": {
            "status": "incomplete" if expected_source else "not_checked",
            "missing": sorted(expected_source or {}),
            "reason": "Document execution identity is not bound yet",
        },
        "selected_value_kind": type(selected).__name__,
        "selected_value_sha256": value_sha256(selected),
    }
    if scope["usage"] != "current":
        report["application"] = scope["usage"]
    elif "xml_sha256" not in material:
        report["application"] = "unverified"
        report["diagnostics"].append({"code": "CURRENT_XML_UNAVAILABLE"})
    elif material["xml_sha256"] != digest:
        report["application"] = "different_input"
        report["diagnostics"].append({"code": "CURRENT_XML_MEASUREMENT_INPUT_MISMATCH"})
    elif scope["material_revision"] != material["revision"]:
        report["application"] = "same_xml_reuse_requires_mapping"
        report["diagnostics"].append({"code": "MATERIAL_MAPPING_REVIEW"})
    else:
        report["application"] = "current_xml_verified"
        declared = material.get("declared_selection", {})
        if declared:
            try:
                from pok.pob.buildxml import _mode_index
                from pok.pob.selection import resolve_xml_selection

                tree = ET.fromstring(files["input.xml"])
                saved_selection: dict[str, Any] = dict(resolve_xml_selection(tree).resolved)
                build = tree.find("Build")
                saved_selection["main_group"] = _mode_index(
                    build.get("mainSocketGroup", "1") if build is not None else 1, "main_group"
                )
                native_value = measured.get("meta", {}).get("nativeSelection")
                native = native_value if isinstance(native_value, dict) else {}
                actual = native.get("actual") or {}
                if (
                    native.get("format") != "pok.native-selection.v1"
                    or native.get("status") != "observed"
                    or actual.get("selected") is not True
                ):
                    actual = {}
                saved_selection["main_active_skill"] = actual.get("active_index")
                saved_selection["stat_set"] = actual.get("stat_set_index")
                context_fields = {
                    "item_set",
                    "skill_set",
                    "tree_spec",
                    "config_set",
                    "weapon_set",
                    "main_group",
                }
                normalized = resolve_xml_selection(
                    tree, {key: value for key, value in declared.items() if key in context_fields}
                ).resolved
                requested = {
                    key: normalized[key] if key in context_fields else _mode_index(value, key)
                    for key, value in declared.items()
                }
                if any(saved_selection.get(key) != value for key, value in requested.items()):
                    raise ValueError(
                        "Declared selection differs from the measured XML/native selection"
                    )
            except (ValueError, TypeError, KeyError, ET.ParseError) as exc:
                report["application"] = "selection_requires_review"
                report["diagnostics"].append(
                    {"code": "XML_MEASUREMENT_SELECTION_MISMATCH", "reason": str(exc)}
                )
    if selected is None:
        report["diagnostics"].append({"code": "SELECTED_VALUE_UNMEASURED_OR_NORMALIZED"})
    report["measurement_status"] = "native_statistics_or_observation_present"
    native = measured.get("meta", {}).get("nativeSelection", {})
    actual = native.get("actual") or {}
    if actual.get("stat_set_resolved") is False:
        report["diagnostics"].append({"code": "NATIVE_SELECTION_MODE_UNRESOLVED"})
    return report


def _catalog(evidence: dict[str, Any], root: Path | None, loader: CatalogLoader) -> dict[str, Any]:
    source = evidence["source"]
    try:
        actual = loader(source["catalog"], source["entity_id"], root)
    except (KeyError, OSError, ValueError) as exc:
        return {
            "integrity": "unavailable",
            "application": "unverified",
            "diagnostics": [{"code": "CATALOG_ENTRY_UNAVAILABLE", "reason": str(exc)}],
        }
    except Exception as exc:
        return {
            "integrity": "unavailable",
            "application": "unverified",
            "diagnostics": [
                {
                    "code": "CATALOG_LOOKUP_FAILED",
                    "error_type": type(exc).__name__,
                    "reason": str(exc)[:400],
                }
            ],
        }
    if not isinstance(actual, dict):
        return {
            "integrity": "unsupported",
            "application": "unverified",
            "diagnostics": [{"code": "UNSUPPORTED_CATALOG_RECORD"}],
        }
    identities = [actual.get("id")]
    if source["catalog"] == "insight":
        identities.append(actual.get("slug"))
    if source["entity_id"] not in identities:
        return {
            "integrity": "mismatch",
            "application": "unverified",
            "diagnostics": [{"code": "CATALOG_IDENTITY_MISMATCH"}],
        }
    digest = value_sha256(actual)
    if digest != source["record_sha256"]:
        return {
            "integrity": "mismatch",
            "application": "needs_review",
            "current_record_sha256": digest,
            "diagnostics": [{"code": "CATALOG_RECORD_CHANGED_OR_MISMATCH"}],
        }
    try:
        value = select(actual, source["field_path"])
    except ValueError as exc:
        return {
            "integrity": "mismatch",
            "application": "unverified",
            "diagnostics": [{"code": "CATALOG_FIELD_UNAVAILABLE", "reason": str(exc)}],
        }
    diagnostics = []
    patch_check = "not_requested"
    if source.get("patch"):
        sources = actual.get("sources") or []
        patches = {
            row["patch"]
            for row in sources
            if isinstance(row, dict) and isinstance(row.get("patch"), str)
        }
        metadata = actual.get("meta", {})
        if isinstance(metadata, dict) and isinstance(metadata.get("patch"), str):
            patches.add(metadata["patch"])
        patch_check = "matched" if source["patch"] in patches else "unconfirmed"
        if patch_check != "matched":
            diagnostics.append({"code": "CATALOG_PATCH_SCOPE_UNCONFIRMED"})
    return {
        "integrity": "verified",
        "application": "catalog_field_only",
        "diagnostics": diagnostics,
        "record_sha256": digest,
        "value_sha256": value_sha256(value),
        "patch_check": patch_check,
        "catalog_label": actual.get("label", actual.get("verification")),
        "field_value_kind": type(value).__name__,
        "game_mechanism_verified": False,
    }


def _bindings(
    record: dict[str, Any],
    material: dict[str, Any],
    spec: dict[str, Any] | None,
    root: Path | None,
) -> list[dict[str, Any]]:
    from pok.pob.document import select_xml_node

    rows = []
    for decision in record["decisions"]:
        for provider in decision["providers"]:
            binding = provider.get("binding")
            if binding is None:
                continue
            row: dict[str, Any] = {
                "decision_id": decision["id"],
                "provider_id": provider["id"],
                "diagnostics": [],
            }
            is_xml = binding["representation"] == "pob_xml"
            if is_xml:
                try:
                    xml_ref = (record["material"] or {}).get("xml")
                    if xml_ref is None or "xml_sha256" not in material:
                        raise ValueError("Verified XML material is absent")
                    xml = _blob(xml_ref, root).decode("utf-8")
                    actual = select_xml_node(xml, binding["pointer"])
                except (ValueError, OSError) as exc:
                    row.update(integrity="unavailable", application="needs_review")
                    row["diagnostics"].append(
                        {"code": "BINDING_XML_NODE_UNAVAILABLE", "reason": str(exc)}
                    )
                else:
                    digest = value_sha256(actual)
                    row["actual_value_sha256"] = digest
                    row.update(
                        integrity="verified_value"
                        if digest == binding["value_sha256"]
                        else "mismatch",
                        application="current_xml_value_only"
                        if digest == binding["value_sha256"]
                        and binding["material_revision"] == material.get("revision")
                        else "same_value_revalidated_at_new_material"
                        if digest == binding["value_sha256"]
                        else "needs_review",
                    )
                    if digest != binding["value_sha256"]:
                        row["diagnostics"].append(
                            {
                                "code": "PROVIDER_BINDING_VALUE_CHANGED",
                                "user_fixed": decision["role"] == "user_fixed",
                            }
                        )
            elif spec is None:
                row.update(integrity="unavailable", application="not_checked")
                row["diagnostics"].append({"code": "BINDING_SPEC_UNAVAILABLE"})
            else:
                try:
                    actual = select(spec, binding["pointer"])
                except ValueError as exc:
                    row.update(integrity="mismatch", application="needs_review")
                    row["diagnostics"].append(
                        {"code": "BINDING_POINTER_UNAVAILABLE", "reason": str(exc)}
                    )
                else:
                    digest = value_sha256(actual)
                    row["actual_value_sha256"] = digest
                    if digest != binding["value_sha256"]:
                        row.update(integrity="mismatch", application="needs_review")
                        row["diagnostics"].append(
                            {
                                "code": "PROVIDER_BINDING_VALUE_CHANGED",
                                "user_fixed": decision["role"] == "user_fixed",
                            }
                        )
                    else:
                        row.update(
                            integrity="verified_value",
                            application="current_spec_value_only"
                            if binding["material_revision"] == material.get("revision")
                            else "same_value_revalidated_at_new_material",
                        )
            rows.append(row)
    return rows


def inspect_evidence(
    record_text: str,
    *,
    root: Path | None = None,
    expected_source: Mapping[str, Any] | None = None,
    _catalog_loader: CatalogLoader | None = None,
) -> dict[str, Any]:
    """Inspect actual local refs. Expected runtime identity is supplied by the host.

    The test-only loader and expected source are not client-callable resolvers.
    Missing data is not a known illegal build. XML/spec equivalence and native
    gameplay behavior are deliberately not inferred from matching byte hashes.
    """
    record = parse_record(record_text)
    result = inspect_record(record_text)
    material, spec = _material(record, root)
    result["material_assessment"] = material
    rows = []
    for evidence in record["evidence"]:
        kind = evidence["kind"]
        if kind == "measurement":
            report = _measurement(evidence, material, spec, root, expected_source)
        elif kind == "catalog":
            report = _catalog(evidence, root, _catalog_loader or _catalog_record)
        elif kind == "external" and evidence["source"].get("snapshot"):
            try:
                _blob(evidence["source"]["snapshot"], root)
            except ArtifactUnavailableError as exc:
                report = {
                    "integrity": "unavailable",
                    "application": "unverified",
                    "diagnostics": [{"code": "EXTERNAL_SNAPSHOT_UNAVAILABLE", "reason": str(exc)}],
                }
            except ValueError as exc:
                report = {
                    "integrity": "mismatch",
                    "application": "unverified",
                    "diagnostics": [{"code": "EXTERNAL_SNAPSHOT_MISMATCH", "reason": str(exc)}],
                }
            else:
                report = {
                    "integrity": "verified_bytes",
                    "application": "external_claim_not_verified",
                    "diagnostics": [],
                }
        else:
            report = {"integrity": "caller_claim", "application": kind, "diagnostics": []}
        rows.append(
            {"id": evidence["id"], "kind": kind, "usage": evidence["scope"]["usage"], **report}
        )
    result["evidence_assessments"] = rows
    bindings = _bindings(record, material, spec, root)
    result["provider_binding_assessments"] = bindings
    checked = [row for row in rows if row["kind"] in {"measurement", "catalog"}]
    result["checks"]["evidence_integrity"] = (
        "no_machine_refs"
        if not checked
        else "verified_declared_refs"
        if all(row["integrity"] == "verified" for row in checked)
        else "needs_review"
    )
    result["checks"]["game_feasibility"] = "not_checked"
    result["checks"]["xml_spec_consistency"] = "not_checked"
    result["checks"]["material_integrity"] = material["status"]
    result["checks"]["socket_metadata_binding"] = material.get("socket_metadata_binding", {}).get(
        "status", "not_checked"
    )
    result["checks"]["provider_bindings"] = (
        "no_declared_bindings"
        if not bindings
        else "verified_declared_values"
        if all(row["integrity"] == "verified_value" for row in bindings)
        else "needs_review"
    )
    current = [row for row in checked if row["usage"] == "current"]
    result["checks"]["current_evidence_application"] = (
        "no_current_machine_refs"
        if not current
        else "current_declared_inputs_verified"
        if all(
            row["integrity"] == "verified"
            and not row["diagnostics"]
            and row["application"]
            in {"current_spec_verified", "current_xml_verified", "catalog_field_only"}
            for row in current
        )
        else "needs_review"
    )
    measurements = [row for row in current if row["kind"] == "measurement"]
    result["checks"]["measurement_source_compatibility"] = (
        "no_current_measurements"
        if not measurements
        else "not_checked"
        if not expected_source
        else "matched_declared_fields"
        if all(
            row.get("source_check", {}).get("status") == "matched_declared_fields"
            for row in measurements
        )
        else "needs_review"
    )
    result["diagnostics"].extend(material["diagnostics"])
    for row in rows:
        result["diagnostics"].extend(
            {"evidence_id": row["id"], **issue} for issue in row["diagnostics"]
        )
    for row in bindings:
        result["diagnostics"].extend(
            {"decision_id": row["decision_id"], "provider_id": row["provider_id"], **issue}
            for issue in row["diagnostics"]
        )
    return result
