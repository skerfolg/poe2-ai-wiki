"""PoB-native UI catalog export with explicit snapshot and no KB identity.

Raw extraction adapts the archived UI exporter; runtime input provenance is v2
and comes from the standalone worker, never a fabricated KB fingerprint.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from pok.common.execution import checkpoint
from pok.pob.runner import run_native_capture
from pok.pob.versions import PobSnapshot, find_luajit

SCHEMA_VERSION = 2
EXTRACTOR_VERSION = "2"


def version_metadata(snapshot: PobSnapshot) -> dict[str, Any]:
    data, diagnostics = _run_lua_export(
        snapshot.src_dir, Path(__file__).with_suffix(".lua"), "versions", []
    )
    if diagnostics or not isinstance(data, dict) or data.get("targetVersion") != "0_1":
        raise ValueError("Unsupported PoB version metadata")
    return data


def catalog_data(snapshot: PobSnapshot, identity: dict[str, Any]) -> dict[str, Any]:
    if (
        identity.get("format") != "pok.pob-worker-identity.v1"
        or identity.get("pob_commit") != snapshot.commit
    ):
        raise ValueError("Catalog identity does not match the explicit PoB snapshot")
    versions = version_metadata(snapshot)
    supported = versions.get("versions")
    latest = versions.get("latest")
    if not isinstance(supported, list) or not supported or len(set(supported)) != len(supported):
        raise ValueError("PoB has no valid tree version list")
    if not isinstance(latest, str) or latest not in supported:
        raise ValueError("PoB latest tree is not supported")
    for version in supported:
        if (
            not isinstance(version, str)
            or _tree_version_key(version) is None
            or not (snapshot.src_dir / "TreeData" / version / "tree.json").is_file()
        ):
            raise ValueError("Declared tree data is missing")
    classes, legacy, ascendancies = _class_metadata(snapshot.src_dir, latest)
    raw = _raw_tables(snapshot.src_dir)
    for cls in classes:
        cls["legacyId"] = legacy[cls["name"]]
        for asc in cls["ascendancies"]:
            asc["legacyId"] = ascendancies[asc["id"]]
    entries = [
        *_base_entries(raw["bases"]),
        *_unique_entries(raw["uniques"]),
        *_mod_entries(raw["mods"]),
        *_gem_entries(raw["gems"], raw["skills"]),
        *_skill_entries(raw["skills"]),
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "extractorVersion": EXTRACTOR_VERSION,
        "defaultTreeVersion": latest,
        "supportedTreeVersions": supported,
        "classes": classes,
        "entries": entries,
        "source": {
            "format": "pok.pob-catalog-source.v2",
            "identity": identity,
            "identitySha256": identity["sha256"],
            "pobCommit": snapshot.commit,
            "exporterVersion": EXTRACTOR_VERSION,
        },
        "diagnostics": [_diagnostic_handling(row) for row in raw["diagnostics"]],
    }


def _diagnostic_handling(diagnostic: dict[str, Any]) -> dict[str, Any]:
    result = dict(diagnostic)
    kind, source, path = (result.get(key, "") for key in ("kind", "source", "path"))
    if kind == "unsupported-lua-function" and (
        (source == "mods" and re.fullmatch(r"\$\.data\.AffixData\.[^.]+\.apply", str(path)))
        or (source == "skills" and re.fullmatch(r"\$\.data\.[^.]+\.preDamageFunc", str(path)))
    ):
        result.update(handling="delegated-to-pob", severity="info")
    elif kind == "json-key-collision":
        result.update(
            kind="typed-map-conversion", originalKind=kind, handling="lossless", lossless=True
        )
    else:
        result.update(handling="unhandled", severity="error")
    return result


def _tree_version_key(value: str) -> tuple[int, ...] | None:
    if not re.fullmatch(r"\d+(?:_\d+)*", value):
        return None
    return tuple(int(part) for part in value.split("_"))


def _class_metadata(
    src_dir: Path, version: str
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, int]]:
    data = json.loads((src_dir / "TreeData" / version / "tree.json").read_text(encoding="utf-8"))
    legacy_by_class, legacy_by_asc = _legacy_ids(src_dir / "TreeData" / version / "tree.lua")
    starts = _start_nodes(data)
    classes: list[dict[str, Any]] = []
    for cls in data["classes"]:
        name = str(cls["name"])
        classes.append(
            {
                "id": name,
                "internalId": int(cls["integerId"]),
                "legacyId": legacy_by_class[name],
                "name": name,
                **({"startNodeId": str(starts[name])} if name in starts else {}),
                "ascendancies": [
                    {
                        "id": str(a["internalId"]),
                        "name": str(a["name"]),
                        "legacyId": legacy_by_asc[str(a["internalId"])],
                    }
                    for a in cls.get("ascendancies", [])
                ],
            }
        )
    return classes, legacy_by_class, legacy_by_asc


def _legacy_ids(tree_lua: Path) -> tuple[dict[str, int], dict[str, int]]:
    text = tree_lua.read_text(encoding="utf-8", errors="replace")
    legacy_by_class: dict[str, int] = {}
    legacy_by_asc: dict[str, int] = {}
    for cm in re.finditer(r"\[(\d+)\]=\{\n\t\t\tascendancies=\{", text):
        tail = text[cm.end() : cm.end() + 20000]
        im = re.search(r'\n\t\t\tintegerId=(\d+),\n\t\t\tname="([^"]+)"', tail)
        if im is None:
            continue
        legacy_by_class[im.group(2)] = int(cm.group(1))
        for m in re.finditer(
            r'\[(\d+)\]=\{.*?internalId="([^"]+)",\n\t\t\t\t\tname="([^"]+)"',
            tail[: im.start()],
            re.S,
        ):
            legacy_by_asc[m.group(2)] = int(m.group(1))
    return legacy_by_class, legacy_by_asc


def _start_nodes(tree: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for node_id, node in tree.get("nodes", {}).items():
        if not isinstance(node, dict) or not node.get("isAscendancyStart"):
            continue
        for stat in node.get("stats") or []:
            match = re.search(r"from the ([A-Za-z ]+)'s starting point", str(stat))
            if match:
                out[match.group(1)] = int(node_id)
    return out


def _raw_tables(src_dir: Path) -> dict[str, Any]:
    helper = Path(__file__).with_suffix(".lua")
    bases = sorted((src_dir / "Data" / "Bases").glob("*.lua"))
    uniques = sorted((src_dir / "Data" / "Uniques").glob("*.lua"))
    skills = sorted((src_dir / "Data" / "Skills").glob("*.lua"))
    out: dict[str, Any] = {"diagnostics": []}
    for mode, files in {
        "gems": [],
        "bases": bases,
        "mods": _mod_files(src_dir),
        "uniques": uniques,
        "skills": skills,
    }.items():
        data, diagnostics = _run_lua_export(src_dir, helper, mode, files)
        out[mode] = data
        out["diagnostics"].extend({"source": mode, **diagnostic} for diagnostic in diagnostics)
    return out


def _run_lua_export(
    src_dir: Path, helper: Path, mode: str, files: list[Path]
) -> tuple[Any, list[dict[str, Any]]]:
    with tempfile.TemporaryDirectory(prefix=f"pok-ui-export-{mode}-") as tmp:
        out = Path(tmp) / f"{mode}.json"
        cmd = [
            find_luajit(),
            str(helper),
            str(src_dir).replace("\\", "/"),
            mode,
            str(out),
            *map(str, files),
        ]
        checkpoint()
        result = run_native_capture(cmd, cwd=src_dir, env=dict(os.environ), timeout=120)
        checkpoint()
        if result.returncode != 0:
            raise RuntimeError(f"PoB UI export failed for {mode}: {result.stderr or result.stdout}")
        payload = json.loads(out.read_text(encoding="utf-8"))
        return payload["data"], payload.get("diagnostics", [])


def _mod_files(src_dir: Path) -> list[Path]:
    return sorted(p for p in (src_dir / "Data").glob("Mod*.lua") if p.name != "ModCache.lua")


def _entry(id_: str, type_: str, name: str, raw: dict[str, Any], **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"id": id_, "type": type_, "name": name, "raw": raw}
    out.update({k: v for k, v in extra.items() if v not in (None, "", [], {})})
    return out


def _base_entries(rows: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _entry(str(id_), "base", str(id_), raw, category=raw.get("type"))
        for id_, raw in sorted(rows.items())
        if isinstance(raw, dict)
    ]


def _unique_entries(rows: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for text in rows:
        if not isinstance(text, str):
            continue
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        variants = [
            {"id": str(i), "name": ln.removeprefix("Variant:").strip()}
            for i, ln in enumerate((ln for ln in lines if ln.startswith("Variant:")), start=1)
        ]
        out.append(
            _entry(
                f"unique:{lines[0]}:{lines[1]}",
                "unique",
                lines[0],
                {"text": text},
                category=lines[1],
                variants=variants,
            )
        )
    return out


def _mod_entries(rows: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _entry(
            str(id_),
            "mod",
            str(raw.get("affix") or id_),
            raw,
            category=raw.get("type"),
            subType=raw.get("group"),
        )
        for id_, raw in sorted(rows.items())
        if isinstance(raw, dict)
    ]


def _gem_entries(gems: dict[str, Any], skills: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for id_, raw in sorted(gems.items()):
        if not isinstance(raw, dict):
            continue
        effect = str(raw.get("grantedEffectId") or "")
        skill = skills.get(effect) if effect else None
        levels = _levels(skill if isinstance(skill, dict) else raw)
        out.append(
            _entry(
                str(id_),
                "gem",
                str(raw.get("name") or raw.get("baseTypeName") or id_),
                raw,
                category=raw.get("gemType"),
                gemId=str(id_),
                gameId=raw.get("gameId"),
                levels=levels,
            )
        )
    return out


def _skill_entries(skills: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        _entry(
            str(id_),
            "skill",
            str(raw.get("name") or id_),
            raw,
            category=raw.get("baseTypeName"),
            levels=_levels(raw),
        )
        for id_, raw in sorted(skills.items())
        if isinstance(raw, dict)
    ]


def _levels(raw: dict[str, Any]) -> list[int]:
    levels = raw.get("levels") if isinstance(raw, dict) else None
    if not isinstance(levels, dict | list):
        return []
    keys = range(1, len(levels) + 1) if isinstance(levels, list) else levels.keys()
    out: list[int] = []
    for key in keys:
        with suppress(TypeError, ValueError):
            out.append(int(key))
    return sorted(set(out))
