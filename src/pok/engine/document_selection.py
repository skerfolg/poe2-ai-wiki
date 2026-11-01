"""Document-bound native effect/mode selection; no gem-slot approximation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pok.artifacts.design_record import canonical_bytes
from pok.artifacts.store import new_build_id, record_immutable_build
from pok.engine.pob_documents import (
    edit_document,
    load_document_measurement,
    measure_document,
    read_document,
)
from pok.pob.buildxml import _mode_index
from pok.pob.document import inspect_xml
from pok.pob.selection import resolve_xml_selection


def plan_selection(
    xml_ref: dict[str, Any],
    expected_revision: str,
    measurement_ref: dict[str, Any],
    active_index: int,
    stat_set_index: int | None = None,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    loaded = load_document_measurement(measurement_ref, xml_ref, root=root)
    if loaded["xml_revision"] != expected_revision:
        raise ValueError("XML revision conflict")
    native = loaded["measurement"].get("meta", {}).get("nativeSelection", {})
    if native.get("format") != "pok.native-selection.v1" or native.get("status") != "observed":
        raise ValueError("A mapped native selection observation is required")
    actual = native.get("actual")
    if not isinstance(actual, dict) or actual.get("selected") is not True:
        raise ValueError("Native main effect is not mapped")
    xml = read_document(xml_ref, root=root)["xml_text"]
    tree = ET.fromstring(xml)
    chosen = resolve_xml_selection(tree)
    if chosen.notes:
        raise ValueError(
            "Saved XML selection used a fallback; resolve it before selecting an effect"
        )
    build = tree.find("Build")
    raw_group = _mode_index(
        build.get("mainSocketGroup", "1") if build is not None else 1, "main_group"
    )
    if actual.get("group_index") != raw_group or chosen.skills is None:
        raise ValueError("Native and source group coordinates do not agree")
    groups = chosen.skills.findall("Skill")
    if not 1 <= raw_group <= len(groups) or groups[raw_group - 1].get("source"):
        raise ValueError("Main XML group is absent or item-generated")
    group = groups[raw_group - 1]
    requested = _mode_index(active_index, "active_index")
    candidates = [
        effect
        for item in native.get("groups", [])
        if item.get("group_index") == raw_group
        for effect in item.get("effects", [])
        if effect.get("active_index") == requested
    ]
    if len(candidates) != 1:
        raise ValueError("Requested native effect is absent or ambiguous")
    target = candidates[0]
    gem_index = _mode_index(target.get("gem_index"), "native gem_index")
    gems = group.findall("Gem")
    if gem_index > len(gems):
        raise ValueError("Native gem slot is not present in the source group")
    gem = gems[gem_index - 1]
    from pok.pob.catalog import canonical_gem_id

    source_id = canonical_gem_id(gem.get("gemId", ""))
    if gem.get("enabled") == "false" or source_id != canonical_gem_id(
        str(target.get("gem_id", ""))
    ):
        raise ValueError("Native source gem does not match the XML slot")
    effect_id = target.get("effect_id")
    if not isinstance(effect_id, str) or not effect_id:
        raise ValueError("Native effect identity is missing")
    mode = _mode_index(
        stat_set_index if stat_set_index is not None else target.get("stat_set_index"),
        "stat_set_index",
    )
    modes = [item for item in target.get("stat_sets", []) if item.get("index") == mode]
    if len(modes) != 1 or (stat_set_index is None and target.get("stat_set_resolved") is not True):
        raise ValueError("Requested mode is absent, ambiguous or unresolved in the observation")
    paths: dict[ET.Element, tuple[int, ...]] = {}
    pending: list[tuple[ET.Element, tuple[int, ...]]] = [(tree, ())]
    while pending:
        element, path = pending.pop()
        paths[element] = path
        pending.extend((child, (*path, index)) for index, child in enumerate(element))
    nodes = {node.path: node for node in inspect_xml(xml)}
    group_node, gem_node = nodes[paths[group]], nodes[paths[gem]]
    changes: list[dict[str, Any]] = []
    if (
        _mode_index(group.get("mainActiveSkill", "1"), "mainActiveSkill") != requested
        or actual.get("active_index") != requested
    ):
        changes.append(
            {
                "path": list(group_node.path),
                "tag": "Skill",
                "attribute": "mainActiveSkill",
                "expected_raw_value": group_node.raw_attributes.get("mainActiveSkill"),
                "value": str(requested),
            }
        )
    if stat_set_index is not None:
        bindings = [
            child
            for child in gem.findall("StatSetIndex")
            if child.get("grantedEffect") == effect_id
        ]
        if len(bindings) > 1:
            raise ValueError("Duplicate source effect-mode bindings are ambiguous")
        old = nodes[paths[bindings[0]]].raw_attributes if bindings else {}
        if bindings and old.get("grantedEffect") != effect_id:
            raise ValueError(
                "Encoded effect identity cannot be safely mapped to the native identifier"
            )
        changes.append(
            {
                "op": "upsert_child_attribute",
                "path": list(gem_node.path),
                "tag": "Gem",
                "child_tag": "StatSetIndex",
                "identity_attribute": "grantedEffect",
                "identity_value": effect_id,
                "attribute": "index",
                "expected_raw_value": old.get("index"),
                "value": str(mode),
            }
        )
    return {
        "xml_ref": dict(xml_ref),
        "xml_revision": expected_revision,
        "document_measurement_ref": dict(measurement_ref),
        "changes": changes,
        "expected_native": {
            "group_index": raw_group,
            "active_index": requested,
            "gem_index": gem_index,
            "gem_id": source_id,
            "effect_id": effect_id,
            "stat_set_index": mode,
            "mode_label": modes[0].get("label"),
        },
        "claim": "document_bound_selection_plan_not_game_validation",
    }


def select_effect(
    xml_ref: dict[str, Any],
    expected_revision: str,
    measurement_ref: dict[str, Any],
    active_index: int,
    stat_set_index: int | None = None,
    *,
    native_timeout_s: float = 180,
    use_cache: bool = True,
    root: Path | None = None,
) -> dict[str, Any]:
    if not 0 < native_timeout_s <= 180:
        raise ValueError("native_timeout_s must be between 0 and 180 seconds")
    plan = plan_selection(
        xml_ref, expected_revision, measurement_ref, active_index, stat_set_index, root=root
    )
    child = edit_document(xml_ref, expected_revision, plan["changes"], root=root)
    result: dict[str, Any] = {
        "format": "pok.document-selection.v1",
        "plan": plan,
        "candidate": child,
        "execution_identity": "not_verified",
        "game_feasibility": "not_checked",
    }
    try:
        measured = measure_document(
            child["xml_ref"],
            stats=[],
            native_timeout_s=native_timeout_s,
            use_cache=use_cache,
            root=root,
        )
        result["measurement"] = measured
        native = measured["meta"].get("nativeSelection", {})
        actual = native.get("actual") or {}
        expected = plan["expected_native"]
        matched = (
            native.get("format") == "pok.native-selection.v1"
            and native.get("status") == "observed"
            and actual.get("selected") is True
            and all(
                actual.get(key) == expected[key]
                for key in (
                    "group_index",
                    "active_index",
                    "gem_index",
                    "effect_id",
                    "stat_set_index",
                )
            )
            and actual.get("stat_set_resolved") is True
        )
        from pok.pob.catalog import canonical_gem_id

        matched = matched and canonical_gem_id(str(actual.get("gem_id", ""))) == expected["gem_id"]
        labels = [
            mode.get("label")
            for mode in actual.get("stat_sets", [])
            if mode.get("index") == expected["stat_set_index"]
        ]
        result["status"] = (
            "native_selection_matched"
            if matched and labels == [expected["mode_label"]]
            else "native_selection_mismatch"
        )
    except Exception as exc:
        result.update(status="measurement_failed", error_type=type(exc).__name__, reason=str(exc))
    identity = new_build_id("pob-document-selection", root=root)
    saved = record_immutable_build(
        identity,
        {"selection.json": canonical_bytes(result)},
        {"kind": "pob-document-selection", "parent_xml_ref": xml_ref, "status": result["status"]},
        root=root,
    )
    result["selection_ref"] = {
        "artifact_id": identity,
        "name": "selection.json",
        "sha256": saved["files"]["selection.json"]["sha256"],
        "media_type": "application/json",
    }
    result["manifest_sha256"] = saved["manifest_sha256"]
    return result
