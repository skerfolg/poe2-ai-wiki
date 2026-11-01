"""Read-only, explicit file/mapping checks for frozen product campaigns."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any


def relative_name(value: str) -> PurePosixPath:
    if (
        not isinstance(value, str)
        or not value
        or value == "."
        or "\x00" in value
        or "\\" in value
        or ":" in value
    ):
        raise ValueError("Snapshot entries must be portable relative paths")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Snapshot path is not canonical and relative")
    return path


def load_pinned_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Pinned manifest bytes differ from the controller's expected checksum")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Pinned manifest must be an object")
    return value


def verify_files(
    root: Path,
    expected: Mapping[str, str],
    *,
    shared_roots: Mapping[str, Path],
    inventory_roots: Sequence[str],
) -> dict[str, Any]:
    """Verify declared bytes and source inventory without allowing general escapes.

    Shared junctions are permitted only at named roots and must resolve to the
    exact declared target. Other links/paths cannot be treated as trusted data.
    Derived __pycache__ and Git internals are not source inventory.
    """
    base = root.resolve()
    names = {name: relative_name(name) for name in expected}
    mappings = {relative_name(name): path.resolve() for name, path in shared_roots.items()}
    scopes = [relative_name(name) for name in inventory_roots]
    issues: list[dict[str, Any]] = []
    checked = 0

    def resolved_file(name: str) -> Path:
        relative = relative_name(name)
        path = base.joinpath(*relative.parts)
        resolved = path.resolve()
        matches = [prefix for prefix in mappings if relative.is_relative_to(prefix)]
        if matches:
            prefix = max(matches, key=lambda p: len(p.parts))
            target = mappings[prefix]
            actual_expected = target.joinpath(*relative.relative_to(prefix).parts).resolve()
            if resolved != actual_expected or not resolved.is_relative_to(target):
                raise ValueError("Path differs from its explicitly mapped shared target")
        elif not resolved.is_relative_to(base) or resolved != path:
            raise ValueError(
                "Path escapes or redirects the frozen product without a declared mapping"
            )
        return resolved

    for name, checksum in expected.items():
        if (
            not isinstance(checksum, str)
            or len(checksum) != 64
            or any(c not in "0123456789abcdef" for c in checksum)
        ):
            raise ValueError("Expected SHA256 file checksum")
        try:
            path = resolved_file(name)
            if not path.is_file():
                raise OSError("Snapshot file is unavailable or not a regular file")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            checked += 1
            if actual != checksum:
                issues.append(
                    {"code": "FILE_CHANGED", "path": name, "expected": checksum, "actual": actual}
                )
        except ValueError as exc:
            issues.append({"code": "PATH_MAPPING_MISMATCH", "path": name, "reason": str(exc)})
        except OSError as exc:
            issues.append({"code": "FILE_UNAVAILABLE", "path": name, "reason": str(exc)})

    observed = set()
    for scope in scopes:
        scope_name = scope.as_posix()
        start = base.joinpath(*scope.parts)
        if not start.is_dir():
            issues.append({"code": "INVENTORY_UNAVAILABLE", "path": scope_name})
            continue
        try:
            resolved_file(scope_name)
        except ValueError as exc:
            issues.append({"code": "PATH_MAPPING_MISMATCH", "path": scope_name, "reason": str(exc)})
            continue

        def unavailable(error: OSError, scope_label: str = scope_name) -> None:
            issues.append(
                {"code": "INVENTORY_UNAVAILABLE", "path": scope_label, "reason": str(error)}
            )

        for directory, children, files in os.walk(start, followlinks=False, onerror=unavailable):
            parent = Path(directory)
            children[:] = [name for name in children if name not in {"__pycache__", ".git"}]
            for child in list(children):
                path = parent / child
                if path.is_symlink() or path.is_junction():
                    virtual = path.relative_to(base).as_posix()
                    # A nested mapped root must be inventoried explicitly too.
                    if (
                        relative_name(virtual) not in mappings
                        or relative_name(virtual) not in scopes
                    ):
                        issues.append({"code": "UNDECLARED_LINK", "path": virtual})
                    children.remove(child)
            for filename in files:
                name = (parent / filename).relative_to(base).as_posix()
                observed.add(name)
                try:
                    resolved_file(name)
                except (ValueError, OSError) as exc:
                    issues.append(
                        {"code": "PATH_MAPPING_MISMATCH", "path": name, "reason": str(exc)}
                    )
    declared = {
        name
        for name, path in names.items()
        if any(path.is_relative_to(scope) for scope in scopes)
        and "__pycache__" not in path.parts
        and ".git" not in path.parts
    }
    issues.extend({"code": "UNEXPECTED_FILE", "path": name} for name in sorted(observed - declared))
    issues.extend(
        {"code": "INVENTORY_FILE_MISSING", "path": name} for name in sorted(declared - observed)
    )
    return {
        "status": "verified" if not issues else "unverified",
        "requested_files": len(expected),
        "checked_files": checked,
        "inventory_roots": [scope.as_posix() for scope in scopes],
        "diagnostics": issues,
        "claim": "declared_bytes_and_inventory_only_not_atomic_load_or_OS_readonly_certification",
    }
