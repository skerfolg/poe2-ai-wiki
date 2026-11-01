"""Preserve source XML and scope restoration claims; bind socket provenance explicitly.

Socket routes are caller declarations. Binding their bytes does not verify an
actual item drop or trade. No acquisition route is inferred from socket counts.
"""

from __future__ import annotations

import copy
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pok.artifacts.design_record import canonical_bytes, parse_json_data
from pok.artifacts.store import new_build_id, read_build_blob, record_immutable_build
from pok.engine.item_sockets import audit_item_sockets
from pok.pob.codec import decode, encode
from pok.pob.restore import RestoredBuild, spec_from_pob, spec_from_pob_xml
from pok.pob.restore import _int as _restore_int
from pok.pob.selection import resolve_xml_selection

FORMAT = "pok.socket-sidecar.v1"


def _hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def projection_revision(spec: dict[str, Any]) -> str:
    return _hash(canonical_bytes(spec))


def _item_text(item: dict[str, Any]) -> str:
    # The XML restorer strips outer whitespace and normalizes XML newlines.
    return str(item["text"]).replace("\r\n", "\n").replace("\r", "\n").strip()


def create_socket_sidecar(
    build_code: str,
    expected_projection_revision: str,
    socket_sources_by_slot: dict[str, list[str]],
    *,
    selection: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    restored = spec_from_pob(build_code, selection=selection)
    sidecar = _sidecar_payload(
        build_code, restored, expected_projection_revision, socket_sources_by_slot
    )
    revision = projection_revision(restored.spec)
    xml = decode(build_code).encode("utf-8")
    raw = canonical_bytes(sidecar)
    identity = new_build_id("socket-provenance", root=root)
    saved = record_immutable_build(
        identity,
        {"socket-sidecar.json": raw, "original.xml": xml},
        {"kind": "socket-provenance-sidecar", "projection_revision": revision},
        root=root,
    )
    return {
        "sidecar_ref": {
            "artifact_id": identity,
            "name": "socket-sidecar.json",
            "sha256": _hash(raw),
        },
        "manifest_sha256": saved["manifest_sha256"],
        "source_xml_sha256": _hash(xml),
        "projection_revision": revision,
        "claim": "declarations_stored_not_acquisition_certificate",
    }


def _sidecar_payload(
    build_code: str,
    restored: RestoredBuild,
    expected_projection_revision: str,
    socket_sources_by_slot: dict[str, list[str]],
) -> dict[str, Any]:
    revision = projection_revision(restored.spec)
    if revision != expected_projection_revision:
        raise ValueError("Restored projection revision differs from the supplied base")
    items = {item["slot"]: item for item in restored.spec.get("items", [])}
    if len(items) != len(restored.spec.get("items", [])):
        raise ValueError("Ambiguous duplicate item slots")
    rows = []
    for slot, routes in sorted(socket_sources_by_slot.items()):
        if slot not in items:
            raise ValueError(f"No selected item in slot: {slot}")
        if not isinstance(routes, list) or any(not isinstance(route, str) for route in routes):
            raise ValueError("Socket sources must be explicit string lists")
        rows.append(
            {
                "slot": slot,
                "item_text_sha256": _hash(_item_text(items[slot]).encode("utf-8")),
                "socket_sources": routes,
            }
        )
    xml = decode(build_code).encode("utf-8")
    return {
        "format": FORMAT,
        "xml_sha256": _hash(xml),
        "projection_revision": revision,
        "items": rows,
        "selection": dict(restored.selection),
        "claim": "caller_declared_acquisition_routes_not_drop_verification",
    }


def rebind_socket_sidecar(
    source_xml_ref: dict[str, Any],
    sidecar_ref: dict[str, Any],
    target_xml_ref: dict[str, Any],
    expected_projection_revision: str,
    *,
    target_selection: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Explicitly transfer declarations only across unchanged selected slot items.

    All original bindings are verified before publication. No drop provenance,
    item equivalence or replacement acquisition route is inferred.
    """

    def read(reference: dict[str, Any]) -> bytes:
        required = {"artifact_id", "name", "sha256"}
        if not required <= set(reference) <= required | {"media_type"} or not all(
            isinstance(value, str) for value in reference.values()
        ):
            raise ValueError("Expected a verified artifact blob reference")
        return read_build_blob(
            reference["artifact_id"], reference["name"], reference["sha256"], root=root
        )

    original_raw = read(source_xml_ref)
    target_raw = read(target_xml_ref)
    metadata = parse_json_data(read(sidecar_ref).decode("utf-8"))
    if not isinstance(metadata, dict) or metadata.get("format") != FORMAT:
        raise ValueError("Unsupported source socket sidecar")
    source_code = encode(original_raw.decode("utf-8"))
    original = spec_from_pob(source_code, selection=metadata.get("selection"))
    checked = assess_restoration(
        source_code,
        original,
        {key: sidecar_ref[key] for key in ("artifact_id", "name", "sha256")},
        root=root,
    )
    if checked["restore_fidelity"]["socket_metadata"] != "matched_socket_sidecar":
        raise ValueError("Original socket sidecar binding could not be verified")
    target_code = encode(target_raw.decode("utf-8"))
    target = spec_from_pob(target_code, selection=target_selection)
    if projection_revision(target.spec) != expected_projection_revision:
        raise ValueError("Target projection revision differs from the supplied base")
    source_items = {item["slot"]: item for item in original.spec.get("items", [])}
    target_items = {item["slot"]: item for item in target.spec.get("items", [])}
    if len(target_items) != len(target.spec.get("items", [])):
        raise ValueError("Ambiguous duplicate target item slots")
    routes: dict[str, list[str]] = {}
    for row in metadata["items"]:
        slot = row["slot"]
        if slot not in target_items or _item_text(source_items[slot]) != _item_text(
            target_items[slot]
        ):
            raise ValueError(f"Declared socket item changed or disappeared: {slot}")
        routes[slot] = list(row["socket_sources"])
    sidecar = _sidecar_payload(target_code, target, expected_projection_revision, routes)
    sidecar["rebinding"] = {
        "source_xml_ref": dict(source_xml_ref),
        "source_sidecar_ref": dict(sidecar_ref),
        "target_xml_ref": dict(target_xml_ref),
        "verification": "unchanged_normalized_item_text_at_same_selected_slot",
    }
    raw = canonical_bytes(sidecar)
    identity = new_build_id("socket-provenance", root=root)
    saved = record_immutable_build(
        identity,
        {"socket-sidecar.json": raw, "original.xml": target_raw},
        {
            "kind": "socket-provenance-sidecar",
            "projection_revision": expected_projection_revision,
            "rebinding": sidecar["rebinding"],
        },
        root=root,
    )
    return {
        "sidecar_ref": {
            "artifact_id": identity,
            "name": "socket-sidecar.json",
            "sha256": _hash(raw),
        },
        "manifest_sha256": saved["manifest_sha256"],
        "source_xml_sha256": _hash(target_raw),
        "projection_revision": expected_projection_revision,
        "selection_resolved": dict(target.selection),
        "transferred_slots": sorted(routes),
        "rebinding": sidecar["rebinding"],
        "claim": "declarations_rebound_not_acquisition_certificate",
    }


def socket_sidecar_for_export(
    build_code: str, source_spec: dict[str, Any]
) -> tuple[str | None, dict[str, Any]]:
    """Prepare a sidecar in the assembly bundle before it is published.

    Re-render the supplied source to account for explicit substitute modeling;
    transfer declarations only when its selected item text equals the export.
    A failed binding is reported, never guessed or used to block arithmetic.
    """
    declared = [item for item in source_spec.get("items", []) if item.get("socket_sources")]
    if not declared:
        return None, {"status": "no_declared_routes"}
    try:
        from pok.pob.buildxml import spec_from_dict, to_xml
        from pok.pob.restore import spec_from_pob_xml

        exported = spec_from_pob(build_code)
        expected = spec_from_pob_xml(to_xml(spec_from_dict(source_spec)))
        target_items = {item["slot"]: item for item in exported.spec.get("items", [])}
        expected_items = {item["slot"]: item for item in expected.spec.get("items", [])}
        routes: dict[str, list[str]] = {}
        for item in declared:
            slot = item["slot"]
            if slot in routes or slot not in expected_items or slot not in target_items:
                raise ValueError("Declared socket slot is absent or ambiguous in the export")
            if _item_text(expected_items[slot]) != _item_text(target_items[slot]):
                raise ValueError(f"Exported item differs from the supplied source: {slot}")
            routes[slot] = item["socket_sources"]
        sidecar = _sidecar_payload(build_code, exported, projection_revision(exported.spec), routes)
        sidecar["source_spec_revision"] = projection_revision(source_spec)
        raw = canonical_bytes(sidecar)
        return raw.decode("utf-8"), {
            "status": "bound_declarations",
            "sha256": _hash(raw),
            "projection_revision": sidecar["projection_revision"],
            "source_spec_revision": sidecar["source_spec_revision"],
            "slots": sorted(routes),
            "claim": "caller_declarations_not_drop_verification",
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return None, {"status": "not_bound", "reason": str(exc)}


def assess_restoration(
    build_code: str,
    restored: RestoredBuild,
    sidecar_ref: dict[str, Any] | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    xml = decode(build_code)
    xml_hash = _hash(xml.encode("utf-8"))
    base_revision = projection_revision(restored.spec)
    spec = copy.deepcopy(restored.spec)
    diagnostics: list[dict[str, Any]] = []
    metadata_status = "not_encoded_in_pob"
    if sidecar_ref is not None:
        try:
            if set(sidecar_ref) != {"artifact_id", "name", "sha256"}:
                raise ValueError("Malformed socket sidecar reference")
            raw = read_build_blob(
                sidecar_ref["artifact_id"], sidecar_ref["name"], sidecar_ref["sha256"], root=root
            )
            sidecar = parse_json_data(raw.decode("utf-8"))
            if not isinstance(sidecar, dict) or sidecar.get("format") != FORMAT:
                raise ValueError("Unsupported socket sidecar")
            if (
                sidecar.get("xml_sha256") != xml_hash
                or sidecar.get("projection_revision") != base_revision
            ):
                raise ValueError("Socket sidecar belongs to another XML or selected projection")
            expected_selection = sidecar.get("selection")
            if expected_selection is None:
                # Earlier v1 sidecars were created only for saved active sets.
                expected_selection = resolve_xml_selection(ET.fromstring(xml)).resolved
            actual_selection = dict(restored.selection)
            if isinstance(expected_selection, dict):
                expected_selection = dict(expected_selection)
                if "main_group" in expected_selection or "main_group" in actual_selection:
                    build = ET.fromstring(xml).find("Build")
                    raw_main = build.get("mainSocketGroup", "1") if build is not None else "1"
                    default_main = _restore_int(raw_main, 1)
                    expected_selection.setdefault("main_group", default_main)
                    actual_selection.setdefault("main_group", default_main)
            if expected_selection != actual_selection:
                raise ValueError("Socket sidecar belongs to another XML selection")
            selected = {item["slot"]: item for item in spec.get("items", [])}
            if len(selected) != len(spec.get("items", [])):
                raise ValueError("Ambiguous duplicate item slots")
            rows = sidecar.get("items")
            if not isinstance(rows, list):
                raise ValueError("Socket sidecar items must be a list")
            seen = set()
            for row in rows:
                if not isinstance(row, dict) or set(row) != {
                    "slot",
                    "item_text_sha256",
                    "socket_sources",
                }:
                    raise ValueError("Malformed socket sidecar item")
                slot = row["slot"]
                if not isinstance(slot, str) or slot in seen or slot not in selected:
                    raise ValueError("Sidecar item slot is absent or ambiguous")
                seen.add(slot)
                if row["item_text_sha256"] != _hash(_item_text(selected[slot]).encode("utf-8")):
                    raise ValueError("Socket sidecar item text mismatch")
                if not isinstance(row["socket_sources"], list) or any(
                    not isinstance(route, str) for route in row["socket_sources"]
                ):
                    raise ValueError("Socket routes must be explicit strings")
            # Validate every binding before applying any metadata.
            for row in rows:
                selected[row["slot"]]["socket_sources"] = row["socket_sources"]
            metadata_status = "matched_socket_sidecar"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            metadata_status = "sidecar_not_applied"
            diagnostics.append({"code": "SOCKET_SIDECAR_REJECTED", "reason": str(exc)})
    acquisition = audit_item_sockets(spec, root=root)
    unproven = [
        row["slot"] for row in acquisition["items"] if row["status"] == "acquisition_unproven"
    ]
    if unproven:
        diagnostics.append(
            {
                "code": "SOCKET_ACQUISITION_UNPROVEN",
                "slots": unproven,
                "reason": "PoB XML does not establish the missing acquisition routes",
            }
        )
    return {
        "build_spec": spec,
        "original_xml": xml,
        "source_xml_sha256": xml_hash,
        "restored_projection_revision": base_revision,
        "selection_resolved": dict(restored.selection),
        "effective_spec_revision": projection_revision(spec),
        "socket_acquisition": acquisition,
        "socket_sidecar_ref": copy.deepcopy(sidecar_ref)
        if metadata_status == "matched_socket_sidecar"
        else None,
        "restore_fidelity": {
            "calculation_projection_faithful": restored.faithful,
            "calculation_scope": "restorer_projection_not_native_or_game_equivalence",
            "socket_metadata": metadata_status,
            "other_design_metadata": "not_reconstructed",
            "source_xml_preserved": True,
            "diagnostics": diagnostics,
        },
        "faithful_scope": "pob_calculation_projection_only",
    }


def inspect_socket_material(
    xml: bytes | None,
    spec: dict[str, Any] | None,
    metadata: dict[str, Any],
    reference: dict[str, Any],
    *,
    selection: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Verify sidecar association and applied routes, not full XML/spec equivalence."""
    if xml is None or spec is None:
        return {"status": "incomplete", "reason": "Both verified XML and spec are required"}
    try:
        text = xml.decode("utf-8")
        restored = spec_from_pob_xml(text, selection=selection)
        result = assess_restoration(encode(text), restored, reference, root=root)
        if result["restore_fidelity"]["socket_metadata"] != "matched_socket_sidecar":
            return {
                "status": "mismatch",
                "diagnostics": result["restore_fidelity"]["diagnostics"],
            }
        source_revision = metadata.get("source_spec_revision")
        expected_revision = source_revision or result["effective_spec_revision"]
        if projection_revision(spec) != expected_revision:
            return {
                "status": "mismatch",
                "reason": "Sidecar is bound to another source spec revision",
            }
        by_slot = {item["slot"]: item for item in spec.get("items", [])}
        if len(by_slot) != len(spec.get("items", [])):
            return {"status": "mismatch", "reason": "Duplicate selected material item slots"}
        for row in metadata["items"]:
            if by_slot.get(row["slot"], {}).get("socket_sources") != row["socket_sources"]:
                return {"status": "mismatch", "reason": "Declared routes differ from current spec"}
        return {
            "status": "verified_declared_binding",
            "spec_revision": projection_revision(spec),
            "slots": [row["slot"] for row in metadata["items"]],
            "claim": "declared_routes_not_drop_or_full_xml_spec_equivalence",
        }
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"status": "unavailable", "reason": str(exc)}
