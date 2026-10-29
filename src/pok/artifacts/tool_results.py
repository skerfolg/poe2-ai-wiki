"""Immutable large tool results and explicit JSON references, without game decisions.

Only this module owns the files under artifacts/sessions/tool-result-<sha256>.
References address the saved envelope (inputs/result/source), never local paths.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir

FORMAT = "pok.tool-result.v1"
PAGE_BYTES = 4096
_ID = re.compile(r"[0-9a-f]{64}\Z")
_REF_KEYS = {"$pok_result", "path", "overrides"}


def encode(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
        "utf-8"
    )


def digest(value: Any) -> str:
    return hashlib.sha256(encode(value)).hexdigest()


def _resolved(path: Path) -> Path:
    resolved = path.resolve()
    # Windows can retain the extended prefix when a directory is published
    # during resolve(). Compare its ordinary spelling without weakening the
    # preceding symlink/junction resolution or changing the path used for I/O.
    text = str(resolved)
    if os.name == "nt":
        if text.startswith("\\\\?\\UNC\\"):
            return Path("\\\\" + text[8:])
        if re.match(r"\\\\\?\\[A-Za-z]:\\", text):
            return Path(text[4:])
    return resolved


def _directory(result_id: str, root: Path | None) -> Path:
    if not isinstance(result_id, str) or not _ID.fullmatch(result_id):
        raise ValueError("Invalid tool-result ID; expected a SHA256, not a file path")
    artifacts = artifacts_dir(root)
    base = artifacts / "sessions"
    if not _resolved(base).is_relative_to(_resolved(artifacts)):
        raise ValueError("Tool-result sessions directory escapes the artifact store")
    directory = base / f"tool-result-{result_id}"
    if not _resolved(directory).is_relative_to(_resolved(base)):
        raise ValueError("Tool-result directory escapes the artifact store")
    return directory


def _file(directory: Path, name: str) -> Path:
    path = directory / name
    if path.is_symlink() or not _resolved(path).is_relative_to(_resolved(directory)):
        raise ValueError("Tool-result file escapes its artifact directory")
    return path


def store_result(
    tool: str,
    inputs: dict[str, Any],
    result: Any,
    *,
    source: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    """Store actual resolved inputs and the full result, bound by one content hash."""
    payload = {
        "format": FORMAT,
        "tool": tool,
        "inputs": inputs,
        "result": result,
        "source": source or {},
    }
    raw = encode(payload)
    result_id = hashlib.sha256(raw).hexdigest()
    manifest = {
        "format": FORMAT,
        "id": result_id,
        "payload_sha256": result_id,
        "inputs_sha256": digest(inputs),
        "result_sha256": digest(result),
        "source_sha256": digest(source or {}),
        "payload_bytes": len(raw),
        "result_bytes": len(encode(result)),
        "tool": tool,
    }
    directory = _directory(result_id, root)
    files = (("payload.json", raw), ("manifest.json", encode(manifest)))

    def verify_existing() -> None:
        for name, data in files:
            try:
                existing = _file(directory, name).read_bytes()
            except OSError as exc:
                raise ValueError("Stored tool result is incomplete or unreadable") from exc
            if existing != data:
                raise ValueError(f"Stored tool result was modified: {name}")

    if directory.exists():
        verify_existing()
        return manifest
    directory.parent.mkdir(parents=True, exist_ok=True)
    # Publish the complete nonempty directory once. Never replace a published
    # file: Windows readers can otherwise collide with a competing writer's
    # rename, and payload/manifest would become visible in separate operations.
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=directory.parent) as temp:
        for name, data in files:
            (Path(temp) / name).write_bytes(data)
        try:
            # A complete destination is nonempty, so rename cannot replace it
            # on POSIX; Windows also refuses an existing destination directory.
            os.rename(temp, directory)
        except OSError:
            if not directory.exists():
                raise
            # A different writer won publication. Only verify its immutable
            # complete bytes; never retry a replacement or repair partial data.
            verify_existing()
    return manifest


def load_result(
    result_id: str, *, root: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify both content and component hashes before returning any stored value."""
    directory = _directory(result_id, root)
    try:
        raw = _file(directory, "payload.json").read_bytes()
        manifest = json.loads(_file(directory, "manifest.json").read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Tool result is missing or unreadable") from exc
    if hashlib.sha256(raw).hexdigest() != result_id:
        raise ValueError("Tool-result payload hash mismatch")
    try:
        payload = json.loads(raw)
        expected = {
            "format": FORMAT,
            "id": result_id,
            "payload_sha256": result_id,
            "inputs_sha256": digest(payload["inputs"]),
            "result_sha256": digest(payload["result"]),
            "source_sha256": digest(payload["source"]),
            "payload_bytes": len(raw),
            "result_bytes": len(encode(payload["result"])),
            "tool": payload["tool"],
        }
        valid = payload["format"] == FORMAT and manifest == expected
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Malformed tool-result envelope") from exc
    if not valid:
        raise ValueError("Tool-result manifest hash mismatch")
    return payload, manifest


def select(payload: Any, pointer: str) -> Any:
    """RFC 6901 pointer, with strict escapes and array indices; no filesystem use."""
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("Tool-result path must be an empty or absolute JSON pointer")
    value = payload
    for encoded in pointer.split("/")[1:] if pointer else ():
        if re.search(r"~(?![01])", encoded):
            raise ValueError("Invalid JSON pointer escape")
        key = encoded.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            if key not in value:
                raise ValueError("Tool-result pointer key does not exist")
            value = value[key]
        elif isinstance(value, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", key) or int(key) >= len(value):
                raise ValueError("Tool-result pointer array index does not exist")
            value = value[int(key)]
        else:
            raise ValueError("Tool-result pointer traverses a scalar")
    return value


def resolve_references(value: Any, *, root: Path | None = None) -> Any:
    """Expand exact reference objects, with explicit top-level replacement only.

    Existing provenance gates still check the resolved spec. References confer
    no measurement, selection, freshness, or recommendation status themselves.
    """
    cache: dict[str, dict[str, Any]] = {}
    references = 0
    visited = 0

    def visit(node: Any, depth: int) -> Any:
        nonlocal references, visited
        visited += 1
        if depth > 64 or visited > 1_000_000:
            raise ValueError("Tool-result reference expansion limit exceeded")
        if isinstance(node, dict):
            if "$pok_result" in node:
                references += 1
                if references > 256 or set(node) - _REF_KEYS:
                    raise ValueError("Invalid or excessive tool-result references")
                result_id = node["$pok_result"]
                # Validate before using the ID as a cache key (lists are invalid).
                _directory(result_id, root)
                if result_id not in cache:
                    cache[result_id] = load_result(result_id, root=root)[0]
                selected = select(cache[result_id], node.get("path", ""))
                expanded = visit(selected, depth + 1)
                if "overrides" in node:
                    overrides = node["overrides"]
                    if not isinstance(expanded, dict) or not isinstance(overrides, dict):
                        raise ValueError("Reference overrides require two objects")
                    expanded.update(
                        {key: visit(item, depth + 1) for key, item in overrides.items()}
                    )
                return expanded
            return {key: visit(item, depth + 1) for key, item in node.items()}
        if isinstance(node, list):
            return [visit(item, depth + 1) for item in node]
        return copy.deepcopy(node)

    return visit(value, 0)


def _kind(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    return "scalar"


def notice(manifest: Mapping[str, Any], result: Any) -> dict[str, Any]:
    """Bounded handoff without ranking, truncating, or inventing a successful result."""
    result_id = manifest["id"]
    return {
        "stored_tool_result": True,
        "result_ref": {"$pok_result": result_id, "path": "/result"},
        "inputs_ref": {"$pok_result": result_id, "path": "/inputs"},
        "payload_sha256": result_id,
        "inputs_sha256": manifest["inputs_sha256"],
        "result_sha256": manifest["result_sha256"],
        "result_bytes": manifest["result_bytes"],
        "summary": {
            "kind": _kind(result),
            "length": len(result) if isinstance(result, dict | list | str) else None,
        },
        "read": {"tool": "get_tool_result", "result_id": result_id, "path": "/result"},
        "claim": "complete_result_stored_no_selection_or_validation_added",
    }


def _chunk(text: str, output: dict[str, Any], offset: int, budget: int) -> dict[str, Any]:
    if offset > len(text):
        raise ValueError("Tool-result offset exceeds the selected value")
    output.update(total=len(text), offset=offset, chunk="", next_offset=None)
    low, high = 0, min(len(text) - offset, budget)
    while low < high:
        count = (low + high + 1) // 2
        output.update(
            chunk=text[offset : offset + count],
            next_offset=offset + count if offset + count < len(text) else None,
        )
        if len(encode(output)) <= budget:
            low = count
        else:
            high = count - 1
    output.update(
        chunk=text[offset : offset + low],
        next_offset=offset + low if offset + low < len(text) else None,
    )
    if len(encode(output)) > budget or (low == 0 and offset < len(text)):
        raise ValueError(
            "JSON pointer metadata exceeds the page budget; read a parent with mode='json'"
        )
    return output


def read_page(
    result_id: str,
    path: str = "/result",
    offset: int = 0,
    limit: int = 20,
    mode: str = "entries",
    *,
    root: Path | None = None,
    budget: int = PAGE_BYTES,
) -> dict[str, Any]:
    """Read selected entries or recover any entire subtree via serialized JSON chunks.

    Oversized child values have exact references. A giant key or scalar can always
    be recovered with mode='json' on its parent. Chunks use Unicode character
    offsets; next_offset is explicit and every response remains complete JSON.
    """
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 100")
    if mode not in {"entries", "json"}:
        raise ValueError("mode must be entries or json")
    payload, manifest = load_result(result_id, root=root)
    value = select(payload, path)
    output = {
        "result_id": result_id,
        "payload_sha256": manifest["payload_sha256"],
        "path": path,
        "kind": _kind(value),
        "mode": mode,
    }
    if mode == "json":
        return _chunk(encode(value).decode("utf-8"), output, offset, budget)
    if isinstance(value, str):
        return _chunk(value, output, offset, budget)
    if not isinstance(value, dict | list):
        if offset:
            raise ValueError("A scalar has no nonzero offset")
        output["value"] = value
        if len(encode(output)) > budget:
            raise ValueError("Selected scalar exceeds page budget; use mode='json'")
        return output
    entries = list(value.items()) if isinstance(value, dict) else list(enumerate(value))
    if offset > len(entries):
        raise ValueError("Tool-result offset exceeds the selected value")
    output.update(total=len(entries), offset=offset, entries=[], next_offset=None)
    for index in range(offset, min(offset + limit, len(entries))):
        key, item = entries[index]
        pointer = path + "/" + str(key).replace("~", "~0").replace("/", "~1")
        row = {"key": key, "value": item}
        trial = {
            **output,
            "entries": [*output["entries"], row],
            "next_offset": index + 1 if index + 1 < len(entries) else None,
        }
        if len(encode(trial)) > budget and output["entries"]:
            break
        if len(encode(trial)) > budget:
            row = {
                "key": key,
                "kind": _kind(item),
                "value_ref": {"$pok_result": result_id, "path": pointer},
            }
            trial["entries"] = [*output["entries"], row]
        if len(encode(trial)) > budget:
            if not output["entries"]:
                output.update(
                    next_offset=offset,
                    oversized_entry=index,
                    recovery={"mode": "json", "offset": 0},
                )
            break
        output = trial
    if len(encode(output)) > budget:
        raise ValueError(
            "JSON pointer metadata exceeds page budget; read a parent with mode='json'"
        )
    return output
