"""Native item double-click compatibility, isolated from calculation state.

The calculator and Craft/BuildRaw roundtrip do not run the item editor. This
batch probe follows ItemListControl:OnSelClick's double-click branch on a
separate PoB process, preserving the submitted item text and partial failures.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pok.common.paths import project_root, var_dir
from pok.pob.runner import _LUA_PATH
from pok.pob.versions import PobSnapshot, find_luajit, resolve_snapshot

_SCRIPT = Path("scripts") / "pob_item_editor.lua"
_PROTOCOL = 1


def audit_item_editor(
    items: dict[str, str],
    *,
    timeout: float = 60.0,
    snapshot: PobSnapshot | None = None,
) -> dict[str, Any]:
    """Check every item through native double-click; never substitute a pass.

    ``checked`` means every requested item reached a native result (success or
    error). ``compatible`` additionally requires that all results succeeded.
    Missing runtime, malformed output, interruption, and timeouts return an
    explicit unchecked failure. Item labels and order survive partial results.
    """
    if timeout <= 0:
        raise ValueError("timeout must be greater than zero")
    rows: list[dict[str, Any]] = [
        {"label": label, "stage": "pending", "checked": False, "compatible": False}
        for label in items
    ]
    report: dict[str, Any] = {
        "protocol": _PROTOCOL,
        "checked": not items,
        "compatible": not items,
        "items": rows,
        "problems": [],
    }
    if not items:
        return report
    try:
        snap = snapshot or resolve_snapshot()
        lua = find_luajit()
    except (FileNotFoundError, RuntimeError) as exc:
        report["problems"] = [f"PoB item editor unavailable: {exc}"]
        return report
    report["pob_commit"] = snap.commit
    runtime_problem = ""
    partial: dict[str, Any] | None = None
    try:
        directory = var_dir() / "pob-cache"
        directory.mkdir(parents=True, exist_ok=True)
        # Per-invocation files prevent concurrent assemblers clobbering inputs.
        with tempfile.TemporaryDirectory(prefix="item-editor-", dir=directory) as tmp:
            input_path, output_path = (Path(tmp) / name for name in ("input.json", "output.json"))
            input_path.write_text(
                json.dumps(
                    [{"label": label, "text": raw} for label, raw in items.items()],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
                newline="\n",
            )
            try:
                proc = subprocess.run(
                    [lua, str(project_root() / _SCRIPT), str(input_path), str(output_path)],
                    cwd=snap.src_dir,
                    env={**os.environ, "LUA_PATH": _LUA_PATH},
                    input="",
                    capture_output=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                )
                if proc.returncode != 0 or "POK_OK" not in proc.stdout.splitlines():
                    detail = (proc.stderr or proc.stdout)[-1500:].strip()
                    runtime_problem = (
                        f"PoB item editor process failed ({proc.returncode}): {detail}"
                    )
            except subprocess.TimeoutExpired:
                runtime_problem = f"PoB item editor timed out after {timeout:g}s"
            if output_path.is_file():
                try:
                    decoded = json.loads(output_path.read_text(encoding="utf-8"))
                    if isinstance(decoded, dict) and decoded.get("protocol") == _PROTOCOL:
                        partial = decoded
                    else:
                        runtime_problem = runtime_problem or "PoB item editor protocol mismatch"
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    runtime_problem = runtime_problem or f"PoB item editor output unreadable: {exc}"
            else:
                runtime_problem = runtime_problem or "PoB item editor output missing"
    except OSError as exc:
        runtime_problem = f"PoB item editor could not execute: {exc}"

    if partial is not None and partial.get("complete") is not True:
        runtime_problem = runtime_problem or "PoB item editor batch did not complete"
    if partial is not None and isinstance(partial.get("items"), list):
        received = {
            row.get("label"): row
            for row in partial["items"]
            if isinstance(row, dict) and isinstance(row.get("label"), str)
        }
        for row in rows:
            found = received.get(row["label"])
            if found is not None:
                row.update(found)
                row["checked"] = found.get("checked") is True
                row["compatible"] = row["checked"] and found.get("compatible") is True
    problems: list[str] = []
    for row in rows:
        if row["checked"] and not row["compatible"]:
            problems.append(
                f"{row['label']}: {row.get('stage', '?')}: {row.get('error', 'native failure')}"
            )
        elif not row["checked"]:
            problems.append(
                f"{row['label']}: editor not checked (stage={row.get('stage', 'pending')})"
            )
    if runtime_problem:
        problems.insert(0, runtime_problem)
    report["checked"] = not runtime_problem and all(row["checked"] for row in rows)
    report["compatible"] = report["checked"] and all(row["compatible"] for row in rows)
    report["problems"] = problems
    return report
