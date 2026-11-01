"""Disk and scoped memory observations around measurements.

Disk equality is useful evidence but does not prove what a cached Python module,
KB object, PoB daemon, or calculator cache actually loaded. Keep that distinction
machine-readable until those execution paths supply their own identities.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import FunctionType, ModuleType
from typing import Any

from pok.common.code_identity import code_sha256
from pok.common.execution import checkpoint
from pok.common.paths import project_root


def observe_loaded_execution(
    *, root: Path | None = None, entrypoint: Callable[..., Any] | None = None
) -> dict[str, Any]:
    """Observe live code objects and the already-loaded KB, not replacement files."""
    from pok.kb.store import loaded_snapshot_identity

    digest = hashlib.sha256(sys.version.encode("utf-8"))
    modules = functions = 0
    expanded: set[int] = set()
    diagnostics = []

    def add(name: str, function: FunctionType, depth: int = 0) -> None:
        nonlocal functions
        try:
            raw = code_sha256(function.__code__).encode("ascii")
        except ValueError as exc:
            diagnostics.append({"function": name, "reason": str(exc)})
            raw = b"unavailable"
        encoded = name.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        functions += 1
        if id(function) in expanded or depth >= 16:
            return
        expanded.add(id(function))
        wrapped = getattr(function, "__wrapped__", None)
        if isinstance(wrapped, FunctionType):
            add(f"{name}.__wrapped__", wrapped, depth + 1)
        for index, cell in enumerate(function.__closure__ or ()):
            try:
                value = cell.cell_contents
            except ValueError:
                continue
            if isinstance(value, FunctionType):
                add(f"{name}.closure[{index}]", value, depth + 1)

    for name, module in sorted(tuple(sys.modules.items())):
        if not (name == "pok" or name.startswith("pok.")) or not isinstance(module, ModuleType):
            continue
        checkpoint()
        modules += 1
        for key, value in sorted(tuple(vars(module).items())):
            if isinstance(value, FunctionType):
                add(f"{name}.{key}", value)
            elif isinstance(value, type) and str(value.__module__).startswith("pok"):
                for member, method in sorted(tuple(vars(value).items())):
                    if isinstance(method, staticmethod | classmethod):
                        method = method.__func__
                    if isinstance(method, FunctionType):
                        add(f"{name}.{key}.{member}", method)
                    elif isinstance(method, property):
                        for accessor in ("fget", "fset", "fdel"):
                            function = getattr(method, accessor)
                            if isinstance(function, FunctionType):
                                add(f"{name}.{key}.{member}.{accessor}", function)
    if isinstance(entrypoint, FunctionType):
        add("measured_entrypoint", entrypoint)
    return {
        "format": "pok.loaded-execution-observation.v1",
        "python": {
            "status": "observed_code_objects" if not diagnostics else "incomplete_code_inventory",
            "sha256": digest.hexdigest(),
            "modules": modules,
            "functions": functions,
            "diagnostics": diagnostics,
        },
        "kb": loaded_snapshot_identity(root),
        "entrypoint": "not_supplied"
        if entrypoint is None
        else "observed_code_object"
        if isinstance(entrypoint, FunctionType)
        else "unavailable",
        "coverage": "loaded_pok_code_objects_and_cached_kb_contents",
        "mutable_python_globals_defaults_and_third_party": "not_verified",
        "non_function_closure_state": "not_verified",
        "native_process": "not_verified",
    }


def _tree(directory: Path, suffixes: frozenset[str]) -> dict[str, Any]:
    if not directory.is_dir():
        raise FileNotFoundError(f"Source directory unavailable: {directory.name}")
    digest = hashlib.sha256()
    count = 0
    byte_count = 0
    for path in sorted(directory.rglob("*")):
        if path.suffix not in suffixes or not path.is_file():
            continue
        # Do not silently hash data outside the named source tree.
        if not path.resolve().is_relative_to(directory.resolve()):
            raise ValueError("Source file resolves outside its declared tree")
        name = path.relative_to(directory).as_posix().encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        count += 1
        byte_count += len(raw)
    return {"sha256": digest.hexdigest(), "files": count, "bytes": byte_count}


def observe_sources(*, root: Path | None = None) -> dict[str, Any]:
    """Read actual content, report unavailable sources rather than inventing identity."""
    base = root or project_root()
    result: dict[str, Any] = {"format": "pok.source-observation.v1"}
    for name, directory, suffixes in (
        ("python_source", base / "src" / "pok", frozenset({".py", ".json"})),
        ("scripts", base / "scripts", frozenset({".lua", ".py"})),
        ("knowledge", base / "knowledge", frozenset({".json", ".ndjson", ".md"})),
    ):
        try:
            result[name] = {"status": "observed", **_tree(directory, suffixes)}
        except (OSError, ValueError) as exc:
            result[name] = {"status": "unavailable", "reason": str(exc)}
    try:
        manifest = json.loads((base / "knowledge" / "ingest" / "manifest.json").read_bytes())
        pin = manifest.get("pob_commit")
        result["pob_pin"] = (
            {"status": "declared", "commit": pin}
            if isinstance(pin, str) and pin
            else {"status": "unavailable"}
        )
    except (OSError, ValueError, AttributeError) as exc:
        result["pob_pin"] = {"status": "unavailable", "reason": str(exc)}
    result["execution_identity"] = "not_verified_disk_observation_only"
    return result


def compare_observations(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    fields = ("python_source", "scripts", "knowledge", "pob_pin")
    unavailable = [
        key
        for key in fields
        if before.get(key, {}).get("status") not in {"observed", "declared"}
        or after.get(key, {}).get("status") not in {"observed", "declared"}
    ]
    changed = [key for key in fields if before.get(key) != after.get(key)]
    return {
        "before": before,
        "after": after,
        "status": "changed" if changed else "incomplete" if unavailable else "stable_observation",
        "changed": changed,
        "unavailable": unavailable,
        "execution_identity": "not_verified_disk_observation_only",
    }
