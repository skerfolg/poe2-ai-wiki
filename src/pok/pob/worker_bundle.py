"""Read-only standalone worker bundle validation; no KB/project discovery."""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.common.execution import checkpoint

FORMAT = "pok.pob-worker-bundle.v1"


def file_sha256(path: Path) -> str:
    # Match the core input observer's read-all semantics. File read failures
    # propagate; never skip a file or substitute a digest on access errors.
    checkpoint()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise OSError(f"Cannot verify bundle file {path}: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    checkpoint()
    return digest


def bundle_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("Expected a portable relative bundle path")
    if any(part in {"", ".", ".."} for part in relative.split("/")):
        raise ValueError("Invalid bundle path component")
    result = root.joinpath(*relative.split("/"))
    if not result.resolve().is_relative_to(root.resolve()):
        raise ValueError("Bundle path resolves outside its root")
    return result


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate bundle manifest key")
        result[key] = value
    return result


@dataclass(frozen=True)
class WorkerBundle:
    manifest_path: Path
    manifest_sha256: str
    data: dict[str, Any]

    @property
    def root(self) -> Path:
        return self.manifest_path.parent

    def path(self, role: str) -> Path:
        return bundle_path(self.root, self.data["paths"][role])

    def validate(self, *, check_interpreter: bool = True) -> None:
        if file_sha256(self.manifest_path) != self.manifest_sha256:
            raise ValueError("Bundle manifest changed after launch")
        for name, entry in self.data["files"].items():
            checkpoint()
            path = bundle_path(self.root, name)
            if (
                not path.is_file()
                or path.stat().st_size != entry["bytes"]
                or file_sha256(path) != entry["sha256"]
            ):
                raise ValueError(f"Bundle file changed or is missing: {name}")
        declared = set(self.data["files"])
        actual = {
            path.relative_to(self.root).as_posix()
            for path in self.root.rglob("*")
            if path.is_file() and path.resolve() != self.manifest_path
        }
        if declared != actual:
            raise ValueError("Bundle file inventory changed")
        if check_interpreter and Path(sys.executable).resolve() != self.path("python").resolve():
            raise ValueError("Bundle was not started with its declared interpreter")
        if self.data["platform"] != sys.platform:
            raise ValueError("Bundle platform does not match this process")


def load_bundle(path: Path, *, check_interpreter: bool = True) -> WorkerBundle:
    manifest_path = path.resolve()
    raw = manifest_path.read_bytes()
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    if not isinstance(data, dict) or set(data) != {
        "format",
        "protocol",
        "platform",
        "pob_commit",
        "paths",
        "files",
        "identity",
        "origin",
    }:
        raise ValueError("Unsupported worker bundle manifest shape")
    if data["format"] != FORMAT or data["protocol"] != "pok.pob-worker.v1":
        raise ValueError("Unsupported worker bundle protocol")
    if not isinstance(data["paths"], dict) or set(data["paths"]) != {
        "python",
        "adapter",
        "pob",
        "luajit",
    }:
        raise ValueError("Bundle launch paths are incomplete")
    if not isinstance(data["files"], dict) or not data["files"]:
        raise ValueError("Bundle has no file inventory")
    for name, entry in data["files"].items():
        bundle_path(manifest_path.parent, name)
        if not isinstance(entry, dict) or set(entry) != {"sha256", "bytes"}:
            raise ValueError("Invalid bundle file descriptor")
        if type(entry["bytes"]) is not int or entry["bytes"] < 0:
            raise ValueError("Invalid bundle byte count")
        digest = entry["sha256"]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValueError("Invalid bundle file SHA256")
    if (
        not isinstance(data["identity"], dict)
        or data["identity"].get("format") != "pok.pob-worker-identity.v1"
    ):
        raise ValueError("Invalid worker bundle identity")
    bundle = WorkerBundle(manifest_path, hashlib.sha256(raw).hexdigest(), data)
    for role in data["paths"]:
        bundle.path(role)
    bundle.validate(check_interpreter=check_interpreter)
    return bundle
