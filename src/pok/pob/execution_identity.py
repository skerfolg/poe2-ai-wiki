"""Content observations for calculator cache binding, not gameplay certification.

Read actual bytes, never infer content equality from mtime/size or a Git pin.
System libraries outside the supplied runtime remain outside this observation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pok.common.code_identity import code_sha256
from pok.common.execution import checkpoint
from pok.pob.versions import PobSnapshot


def _tree(base: Path, *, lua_only: bool = False) -> dict[str, Any]:
    resolved = base.resolve()
    if not resolved.is_dir():
        raise FileNotFoundError(f"Execution input directory unavailable: {base}")
    digest = hashlib.sha256()
    count = byte_count = 0
    for path in sorted(resolved.rglob("*")):
        if not path.is_file():
            continue
        if lua_only and path.suffix != ".lua":
            continue
        if not lua_only and (
            path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tga", ".tgf"}
            or path.name.lower().endswith(".dds.zst")
        ):
            continue  # Visual assets are not read by the headless calculator.
        checkpoint()
        if not path.resolve().is_relative_to(resolved):
            raise ValueError("Execution input resolves outside the observed directory")
        name = path.relative_to(resolved).as_posix().encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
        count += 1
        byte_count += len(raw)
    if not count:
        raise ValueError(f"Execution input directory contains no observable files: {base}")
    return {
        "root": str(resolved),
        "sha256": digest.hexdigest(),
        "files": count,
        "bytes": byte_count,
    }


def observe_execution_inputs(
    snapshot: PobSnapshot,
    *,
    adapter_root: Path,
    executable: Path,
    adapter_code_sha256: str,
    launch_config: dict[str, str] | None = None,
) -> dict[str, Any]:
    components: dict[str, Any] = {}
    diagnostics = []
    for name, directory, lua_only in (
        ("adapter_lua", adapter_root / "scripts", True),
        ("pob_source", snapshot.src_dir, False),
        ("pob_runtime", snapshot.root / "runtime", False),
    ):
        try:
            components[name] = _tree(directory, lua_only=lua_only)
        except (OSError, ValueError) as exc:
            diagnostics.append({"component": name, "reason": str(exc)})
    try:
        raw = executable.read_bytes()
        components["executable"] = {
            "path": str(executable.resolve()),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
        }
    except OSError as exc:
        diagnostics.append({"component": "executable", "reason": str(exc)})
    payload = {
        "format": "pok.pob-input-observation.v1",
        "status": "observed" if not diagnostics else "unavailable",
        "pob_commit": snapshot.commit,
        "adapter_code_sha256": adapter_code_sha256,
        "launch_config": dict(launch_config or {}),
        "observer_code_sha256": hashlib.sha256(
            (code_sha256(_tree.__code__) + code_sha256(observe_execution_inputs.__code__)).encode(
                "ascii"
            )
        ).hexdigest(),
        "components": components,
        "diagnostics": diagnostics,
        "scope": "loaded_adapter_code_and_disk_calculator_inputs_excluding_visual_assets",
        "loaded_native_modules": "not_verified",
        "external_system_libraries": "not_verified",
    }
    payload["sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload
