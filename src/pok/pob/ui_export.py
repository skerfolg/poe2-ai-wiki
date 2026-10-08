"""Raw PoB catalog export for desktop UI consumers.

Boundary marker: reads the pinned ``external/pob`` snapshot only for UI export.
"""

from __future__ import annotations

import functools
import json
import re
import subprocess
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from pok.common.paths import resource_root
from pok.pob.runtime_identity import runtime_identity
from pok.pob.versions import find_luajit, resolve_snapshot

SCHEMA_VERSION = 1
EXTRACTOR_VERSION = "1"
_POB_SOURCE_BOUNDARY_MARKER = "external/pob"


def load_catalog(root: Path | None = None) -> dict[str, Any]:
    return catalog_data(root)


def export_catalog(output: Path, root: Path | None = None) -> Path:
    """Write the raw UI catalog, returning the written catalog.json path."""
    target = output / "catalog.json" if output.suffix == "" else output
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(catalog_data(root), ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
        newline="\n",
    )
    return target


def catalog_data(root: Path | None = None) -> dict[str, Any]:
    base = root or resource_root()
    snap = resolve_snapshot(base)
    tree_versions = supported_tree_versions(base)
    default_tree_version = default_tree_version_for(base)
    classes, legacy_by_class, legacy_by_asc = _class_metadata(snap.src_dir, default_tree_version)
    raw = _raw_tables(snap.src_dir)
    identity = runtime_identity(base)

    diagnostics: list[dict[str, Any]] = [_diagnostic_handling(d) for d in raw["diagnostics"]]
    entries: list[dict[str, Any]] = []
    entries.extend(_base_entries(raw["bases"]))
    entries.extend(_unique_entries(raw["uniques"]))
    entries.extend(_mod_entries(raw["mods"]))
    entries.extend(_gem_entries(raw["gems"], raw["skills"]))
    entries.extend(_skill_entries(raw["skills"]))

    for cls in classes:
        cls["legacyId"] = legacy_by_class[cls["name"]]
        for asc in cls["ascendancies"]:
            asc["legacyId"] = legacy_by_asc[asc["id"]]

    return {
        "schemaVersion": SCHEMA_VERSION,
        "extractorVersion": EXTRACTOR_VERSION,
        "defaultTreeVersion": default_tree_version,
        "supportedTreeVersions": tree_versions,
        "classes": classes,
        "entries": entries,
        "source": {
            "pobCommit": str(identity["pob"]["commit"]),
            "pokSourceDigest": str(identity["pok"]["sourceDigest"]),
            "pobSourceDigest": str(identity["pob"]["sourceDigest"]),
            "kbManifestSha256": str(identity["kb"]["manifestSha256"]),
            "kbContentSha256": str(identity["kb"]["contentSha256"]),
            "exporterVersion": EXTRACTOR_VERSION,
        },
        "diagnostics": diagnostics,
    }


def class_metadata(
    root: Path | None = None,
) -> tuple[dict[str, int], dict[str, int], dict[str, tuple[int, str]]]:
    """Compatibility maps for buildxml: internal ids, legacy ids, ascendancy ids."""
    base = root or resource_root()
    snap = resolve_snapshot(base)
    default_tree_version = default_tree_version_for(base)
    classes, legacy_by_class, legacy_by_asc = _class_metadata(snap.src_dir, default_tree_version)
    internal = {str(c["name"]): int(c["internalId"]) for c in classes}
    legacy = {str(c["name"]): int(legacy_by_class[str(c["name"])]) for c in classes}
    ascendancy = {
        str(a["id"]): (int(legacy_by_asc[str(a["id"])]), str(a["name"]))
        for c in classes
        for a in c["ascendancies"]
    }
    return internal, legacy, ascendancy


@functools.lru_cache(maxsize=8)
def _version_metadata(src_dir: Path) -> dict[str, Any]:
    data, diagnostics = _run_lua_export(src_dir, Path(__file__).with_suffix(".lua"), "versions", [])
    if diagnostics or not isinstance(data, dict):
        raise RuntimeError("PoB GameVersions export failed")
    if data.get("targetVersion") != "0_1":
        raise RuntimeError("Unsupported PoB XML target format")
    return data


def supported_tree_versions(root: Path | None = None) -> list[str]:
    snap = resolve_snapshot(root or resource_root())
    declared = _version_metadata(snap.src_dir).get("versions")
    if not isinstance(declared, list) or not declared or len(set(declared)) != len(declared):
        raise RuntimeError("PoB GameVersions has no valid tree version list")
    versions = [str(value) for value in declared]
    for version in versions:
        if _tree_version_key(version) is None or not (
            snap.src_dir / "TreeData" / version / "tree.json"
        ).is_file():
            raise RuntimeError(f"Declared PoB tree data is missing or unsupported: {version}")
    return versions


def default_tree_version_for(root: Path | None = None) -> str:
    snap = resolve_snapshot(root or resource_root())
    latest = str(_version_metadata(snap.src_dir).get("latest", ""))
    if latest not in supported_tree_versions(root):
        raise RuntimeError("PoB latestTreeVersion does not identify a supported tree")
    return latest


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


@functools.lru_cache(maxsize=4)
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
        out["diagnostics"].extend(
            {"source": mode, **diagnostic} for diagnostic in diagnostics
        )
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
        result = subprocess.run(
            cmd,
            cwd=src_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
        )
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
    if not isinstance(levels, (dict, list)):
        return []
    keys = range(1, len(levels) + 1) if isinstance(levels, list) else levels.keys()
    out: list[int] = []
    for key in keys:
        with suppress(TypeError, ValueError):
            out.append(int(key))
    return sorted(set(out))
