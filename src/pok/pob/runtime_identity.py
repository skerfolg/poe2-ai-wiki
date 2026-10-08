"""Runtime identity for desktop packaging and UI version checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pok import __version__
from pok.common.paths import knowledge_dir, resource_root
from pok.pob.versions import pinned_commit, resolve_snapshot

_IGNORED_DIRS = {".git", ".mypy_cache", ".pytest_cache", "__pycache__", "var", "artifacts"}
_CACHE: dict[tuple[str, str], dict[str, Any]] = {}
_PACKAGED_SKILL = "trade-search"
_SOURCE_INCLUDE = (
    "src/pok/**/*.py",
    "src/pok/**/*.lua",
    "scripts/pob*.lua",
    "skills/AGENTS.md",
    f"skills/{_PACKAGED_SKILL}/**/*",
    f".agents/skills/{_PACKAGED_SKILL}/SKILL.md",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _interesting(path: Path, root: Path) -> bool:
    return not any(part in _IGNORED_DIRS for part in path.relative_to(root).parts)


def sha256_tree(root: Path, *, include: tuple[str, ...] = ("*",)) -> str:
    """Deterministic content digest for a directory."""
    digest = hashlib.sha256()
    files: list[Path] = []
    for pattern in include:
        files.extend(p for p in root.glob("**/*" if pattern == "*" else pattern) if p.is_file())
    for path in sorted(set(files), key=lambda p: p.relative_to(root).as_posix()):
        if not _interesting(path, root):
            continue
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def json_sha256(value: Any) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _git(root: Path, *args: str) -> str:
    # File-backed output keeps Windows timeout cleanup independent of inherited pipes.
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=10,
            check=False,
        )
        output.seek(0)
        return output.read().decode("utf-8").rstrip() if result.returncode == 0 else ""


def _source_status(root: Path) -> dict[str, Any]:
    commit = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    return {
        "commit": commit,
        "dirty": bool(status),
        "statusDigest": hashlib.sha256(status.encode()).hexdigest(),
    }


def _tree_signature(root: Path, *, include: tuple[str, ...] = ("*",)) -> str:
    digest = hashlib.sha256()
    files: list[Path] = []
    for pattern in include:
        files.extend(p for p in root.glob("**/*" if pattern == "*" else pattern) if p.is_file())
    for path in sorted(set(files), key=lambda p: p.relative_to(root).as_posix()):
        if not _interesting(path, root):
            continue
        stat = path.stat()
        rel = path.relative_to(root).as_posix()
        digest.update(f"{rel}\0{stat.st_size}\0{stat.st_mtime_ns}\0".encode())
    return digest.hexdigest()


def _observed_signature(root: Path) -> str:
    pob = resolve_snapshot(root)
    return json_sha256({
        "head": _git(root, "rev-parse", "HEAD"),
        "source": _tree_signature(root, include=_SOURCE_INCLUDE),
        "knowledge": _tree_signature(knowledge_dir(root)),
        "pob": _tree_signature(pob.src_dir),
    })


def _manifest_path(root: Path) -> Path:
    return root / "resources" / "runtime-manifest.json"


def _packaged_identity(root: Path) -> dict[str, Any] | None:
    manifest = _manifest_path(root)
    if not manifest.is_file():
        return None
    data = json.loads(manifest.read_text(encoding="utf-8"))
    identity = data.get("identity")
    return dict(identity) if isinstance(identity, dict) else None


def _computed_identity(root: Path) -> dict[str, Any]:
    source = _source_status(root)
    manifest_file = knowledge_dir(root) / "ingest" / "manifest.json"
    ingest = json.loads(manifest_file.read_text(encoding="utf-8"))
    pob = resolve_snapshot(root)
    return {
        "apiVersion": 1,
        "pok": {
            "version": __version__,
            "sourceCommit": source["commit"],
            "sourceDirty": source["dirty"],
            "sourceStatusDigest": source["statusDigest"],
            "sourceDigest": sha256_tree(root, include=_SOURCE_INCLUDE),
        },
        "pob": {
            "commit": pinned_commit(root),
            "sourceDigest": sha256_tree(pob.src_dir),
        },
        "kb": {
            "manifestSha256": sha256_file(manifest_file),
            "contentSha256": sha256_tree(knowledge_dir(root)),
            "patch": str(ingest.get("patch", "")),
        },
        "capabilities": {
            "computeXml": True,
            "renderItem": True,
            "catalogExport": True,
        },
    }


def runtime_identity(root: Path | None = None, *, force_compute: bool = False) -> dict[str, Any]:
    """Return the POK/PoB/KB identity used by desktop and MCP clients."""
    base = (root or resource_root()).resolve()
    if not force_compute:
        packaged = _packaged_identity(base)
        if packaged is not None:
            return packaged
    signature = _observed_signature(base)
    key = (str(base), signature)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    identity = _computed_identity(base)
    _CACHE.clear()
    _CACHE[key] = identity
    return identity


def invalidate_runtime_identity() -> None:
    _CACHE.clear()
