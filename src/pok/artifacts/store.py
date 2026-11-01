"""빌드 산출물 기록 — artifacts/builds/<build-id>/ (PROJECT_STRUCTURE §6).

build-id = 타임스탬프+슬러그 (예: 20260730-spark-stormweaver, §9-2 확정).
사람이 읽고 대화에서 지칭하는 용도 — 내용 추적·중복 탐지는 manifest의
content_hash가 담당한다. 같은 날 같은 슬러그는 -2, -3… 접미로 회피.

이 모듈은 **파일 기록만** 한다 — 무엇을 기록할지(XML·빌드코드·검증 결과)의
조합은 상위 계층(engine)의 몫 (의존 계약상 artifacts는 pob를 import할 수 없다).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir

_SLUG = re.compile(r"[^a-z0-9가-힣-]+")
IMMUTABLE_BUILD_FORMAT = "pok.immutable-build.v1"
_ARTIFACT_ID = re.compile(r"[A-Za-z0-9가-힣][A-Za-z0-9가-힣._-]{0,199}\Z")
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z")
_DEVICES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


class ArtifactUnavailableError(ValueError):
    """A referenced artifact is absent/unreadable, not evidence of game illegality."""


class ArtifactIntegrityError(ValueError):
    """Present bytes do not match the declared identity."""


def _resolved(path: Path) -> Path:
    value = str(path.resolve())
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            return Path("\\\\" + value[8:])
        if re.match(r"\\\\\?\\[A-Za-z]:\\", value):
            return Path(value[4:])
    return Path(value)


def _artifact_directory(kind: str, artifact_id: str, root: Path | None) -> Path:
    if (
        kind not in {"builds", "anchors"}
        or not isinstance(artifact_id, str)
        or not _ARTIFACT_ID.fullmatch(artifact_id)
    ):
        raise ValueError("Invalid artifact ID or kind")
    if artifact_id.split(".")[0].casefold() in _DEVICES or artifact_id.endswith("."):
        raise ValueError("Artifact ID is not a portable directory name")
    artifacts = artifacts_dir(root)
    parent = artifacts / kind
    directory = parent / artifact_id
    if directory.is_symlink() or directory.is_junction():
        raise ValueError("Artifact directory cannot be a symbolic alias")
    if not _resolved(parent).is_relative_to(_resolved(artifacts)) or not _resolved(
        directory
    ).is_relative_to(_resolved(parent)):
        raise ValueError("Artifact directory escapes its store")
    return directory


def _artifact_file(directory: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\\" in name or ":" in name or "\x00" in name:
        raise ValueError("Expected a relative portable artifact file name")
    parts = name.split("/")
    if any(
        not part
        or part in {".", ".."}
        or part.endswith((".", " "))
        or part.split(".")[0].casefold() in _DEVICES
        for part in parts
    ):
        raise ValueError("Invalid artifact file component")
    path = directory.joinpath(*parts)
    if path.is_symlink() or not _resolved(path).is_relative_to(_resolved(directory)):
        raise ValueError("Artifact file escapes its directory")
    return path


def _lock_path(directory: Path) -> Path:
    identity = hashlib.sha256(directory.name.encode("utf-8")).hexdigest()
    return directory.parent / f".write-{identity}.lock"


@contextmanager
def _publication_lock(directory: Path) -> Iterator[None]:
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(directory)
    token = secrets.token_hex(24).encode("ascii")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise ValueError(
            "Artifact publication pending; a lock alone does not prove a live writer"
        ) from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(token)
            stream.flush()
            os.fsync(stream.fileno())
        yield
    finally:
        # Remove only this claim. Never remove a replaced/unknown writer's lock.
        try:
            if not lock.is_symlink() and lock.read_bytes() == token:
                lock.unlink()
        except OSError:
            pass


def _manifest_bytes(value: dict[str, Any]) -> bytes:
    try:
        raw = json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        if json.loads(raw) != value:
            raise ValueError("Manifest metadata must contain JSON values")
        return raw
    except (TypeError, UnicodeError) as exc:
        raise ValueError("Manifest metadata must contain finite JSON values") from exc


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def slugify(text: str) -> str:
    s = _SLUG.sub("-", text.strip().lower()).strip("-")
    return s or "build"


def new_build_id(slug: str, *, root: Path | None = None, now: datetime | None = None) -> str:
    """YYYYMMDD-슬러그 (이미 있으면 -2, -3… — 디렉터리 실존 기준)."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
    base = f"{stamp}-{slugify(slug)}"
    builds = artifacts_dir(root) / "builds"
    build_id, n = base, 1
    while (builds / build_id).exists() or _lock_path(builds / build_id).exists():
        n += 1
        build_id = f"{base}-{n}"
    return build_id


def _record(
    kind: str,
    id_key: str,
    artifact_id: str,
    files: dict[str, str],
    manifest: dict[str, Any],
    root: Path | None,
) -> Path:
    out = _artifact_directory(kind, artifact_id, root)
    for name in files:
        if name.casefold() == "manifest.json":
            raise ValueError("manifest.json is reserved")
        _artifact_file(out, name)
    with _publication_lock(out):
        if out.exists() and any(out.iterdir()):
            try:
                existing = json.loads(_artifact_file(out, "manifest.json").read_bytes())
            except (OSError, ValueError) as exc:
                raise ValueError("Existing artifact is incomplete; refusing silent repair") from exc
            if not isinstance(existing, dict):
                raise ValueError("Existing artifact manifest is not an object")
            if existing.get("format") == IMMUTABLE_BUILD_FORMAT:
                raise ValueError("Legacy writes cannot replace an immutable artifact")
        out.mkdir(parents=True, exist_ok=True)
        hasher = hashlib.sha256()
        for name in sorted(files):
            hasher.update(name.encode())
            hasher.update(files[name].encode("utf-8"))
            target = _artifact_file(out, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(files[name], encoding="utf-8")
        full = {
            id_key: artifact_id,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "content_hash": hasher.hexdigest(),
            **manifest,
        }
        _artifact_file(out, "manifest.json").write_text(
            json.dumps(full, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
    return out


def record_build(
    build_id: str,
    files: dict[str, str],
    manifest: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    """산출물 기록. files = {파일명: 내용}, manifest에 계보·content_hash를 얹는다.

    content_hash는 files 전체(이름 포함)의 sha256 — 같은 빌드의 재기록을 탐지한다.
    """
    return _record("builds", "build_id", build_id, files, manifest, root)


def new_anchor_id(slug: str, *, root: Path | None = None, now: datetime | None = None) -> str:
    """앵커 id = YYYYMMDD-슬러그 (builds와 같은 규약, anchors/ 실존 기준 회피)."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
    base = f"{stamp}-{slugify(slug)}"
    anchors = artifacts_dir(root) / "anchors"
    anchor_id, n = base, 1
    while (anchors / anchor_id).exists() or _lock_path(anchors / anchor_id).exists():
        n += 1
        anchor_id = f"{base}-{n}"
    return anchor_id


def record_anchor(
    anchor_id: str,
    files: dict[str, str],
    manifest: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    """외부 앵커 빌드 보관 — artifacts/anchors/<id>/ (D30, 계보 manifest 필수).

    manifest에는 source(url·site·provenance)가 있어야 한다 — 계보 없는 앵커는
    "근거 있는 재조합"(RC5)의 근거가 될 수 없다.
    """
    if "source" not in manifest:
        raise ValueError("앵커 manifest에 source(계보)가 없음 — url·site·provenance 필수")
    return _record("anchors", "anchor_id", anchor_id, files, manifest, root)


def find_by_hash(content_hash: str, *, root: Path | None = None) -> list[str]:
    """같은 content_hash를 가진 기존 build-id들 (중복 탐지)."""
    builds = artifacts_dir(root) / "builds"
    if not builds.exists():
        return []
    hits = []
    for mf in sorted(builds.glob("*/manifest.json")):
        try:
            if json.loads(mf.read_text(encoding="utf-8")).get("content_hash") == content_hash:
                hits.append(mf.parent.name)
        except (OSError, json.JSONDecodeError):
            continue
    return hits


def read_immutable_build(
    build_id: str,
    manifest_sha256: str,
    *,
    root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Verify the whole published bundle, including audit metadata, before use."""
    if not isinstance(manifest_sha256, str) or not _HASH.fullmatch(manifest_sha256):
        raise ValueError("Expected a manifest SHA256")
    directory = _artifact_directory("builds", build_id, root)
    try:
        raw = _artifact_file(directory, "manifest.json").read_bytes()
        if _sha256(raw) != manifest_sha256:
            raise ValueError("Immutable manifest hash mismatch")
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or set(manifest) != {
            "format",
            "build_id",
            "files",
            "metadata",
        }:
            raise ValueError("Invalid immutable manifest shape")
        if manifest["format"] != IMMUTABLE_BUILD_FORMAT or manifest["build_id"] != build_id:
            raise ValueError("Wrong immutable artifact format or identity")
        if not isinstance(manifest["files"], dict) or not isinstance(manifest["metadata"], dict):
            raise ValueError("Invalid immutable manifest files/metadata")
        if raw != _manifest_bytes(manifest):
            raise ValueError("Immutable manifest is not its canonical encoding")
        data: dict[str, bytes] = {}
        seen: set[str] = set()
        for name, entry in manifest["files"].items():
            if (
                not isinstance(name, str)
                or name.casefold() in seen
                or name.casefold() == "manifest.json"
            ):
                raise ValueError("Invalid or aliased immutable file name")
            seen.add(name.casefold())
            if not isinstance(entry, dict) or set(entry) != {"sha256", "bytes"}:
                raise ValueError("Invalid immutable file descriptor")
            value = _artifact_file(directory, name).read_bytes()
            if (
                type(entry["bytes"]) is not int
                or entry["bytes"] != len(value)
                or entry["sha256"] != _sha256(value)
            ):
                raise ValueError("Immutable artifact file was modified or truncated")
            data[name] = value
        return manifest, data
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Immutable artifact is missing, incomplete or unreadable") from exc


def read_build_blob(artifact_id: str, name: str, sha256: str, *, root: Path | None = None) -> bytes:
    """Read only a named build blob matching its expected bytes.

    A legacy build can supply a blob without being an immutable checkpoint.
    Byte integrity does not attest the truth of its contents or audit history.
    """
    if not isinstance(sha256, str) or not _HASH.fullmatch(sha256):
        raise ValueError("Expected a blob SHA256")
    directory = _artifact_directory("builds", artifact_id, root)
    path = _artifact_file(directory, name)
    try:
        if not path.is_file():
            raise ArtifactUnavailableError("Build blob is missing or not a regular file")
        raw = path.read_bytes()
    except OSError as exc:
        raise ArtifactUnavailableError("Build blob is unreadable") from exc
    if _sha256(raw) != sha256:
        raise ArtifactIntegrityError("Build blob hash mismatch")
    return raw


def open_immutable_build(
    build_id: str, *, root: Path | None = None
) -> tuple[dict[str, Any], dict[str, bytes], str]:
    """Discover a named local manifest and verify its whole bundle.

    This does not claim agreement with a caller-held original manifest hash.
    Use read_immutable_build when that original hash is available.
    """
    directory = _artifact_directory("builds", build_id, root)
    try:
        raw = _artifact_file(directory, "manifest.json").read_bytes()
    except OSError as exc:
        raise ArtifactUnavailableError("Immutable artifact manifest unavailable") from exc
    digest = _sha256(raw)
    manifest, files = read_immutable_build(build_id, digest, root=root)
    return manifest, files, digest


def discover_immutable_builds(
    *, offset: int = 0, limit: int = 20, root: Path | None = None
) -> dict[str, Any]:
    """Bounded directory discovery, not content verification or a current-head index.

    Offsets count visible directory entries, including legacy or invalid entries.
    Callers may receive an empty filtered page with a non-null next_offset.
    """
    if isinstance(offset, bool) or isinstance(limit, bool) or offset < 0 or not 1 <= limit <= 100:
        raise ValueError("Expected offset >= 0 and limit between 1 and 100")
    artifacts = artifacts_dir(root)
    parent = artifacts / "builds"
    if (
        parent.is_symlink()
        or parent.is_junction()
        or not _resolved(parent).is_relative_to(_resolved(artifacts))
    ):
        raise ValueError("Build store cannot be a symbolic alias or escape its root")
    if not parent.exists():
        return {"entries": [], "diagnostics": [], "next_offset": None}
    names = sorted(path.name for path in parent.iterdir() if not path.name.startswith("."))
    entries = []
    diagnostics = []
    for identity in names[offset : offset + limit]:
        try:
            directory = _artifact_directory("builds", identity, root)
            if not directory.is_dir():
                continue
            raw = _artifact_file(directory, "manifest.json").read_bytes()
            manifest = json.loads(raw)
            if not isinstance(manifest, dict):
                raise ValueError("Artifact manifest must be an object")
            if manifest.get("format") != IMMUTABLE_BUILD_FORMAT:
                continue
            entries.append(
                {
                    "artifact_id": identity,
                    "manifest_sha256": _sha256(raw),
                    "manifest": manifest,
                }
            )
        except (OSError, ValueError) as exc:
            diagnostics.append(
                {"artifact_id": identity, "code": "DISCOVERY_FAILED", "reason": str(exc)}
            )
    end = offset + limit
    return {
        "entries": entries,
        "diagnostics": diagnostics,
        "next_offset": end if end < len(names) else None,
    }


def record_immutable_build(
    build_id: str,
    files: dict[str, bytes],
    metadata: dict[str, Any],
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Stage bytes+manifest, then publish once; never replace/repair an existing ID.

    Locks serialize writers using both legacy and immutable APIs. A stale lock
    is preserved, not evidence of a live job. new_build_id skips claimed IDs.
    This promises complete publication and verification, not full power-loss
    durability of every filesystem or protection from a hostile host owner.
    """
    directory = _artifact_directory("builds", build_id, root)
    descriptors: dict[str, dict[str, Any]] = {}
    folded: set[str] = set()
    for name, raw in files.items():
        if (
            not isinstance(name, str)
            or name.casefold() in folded
            or name.casefold() == "manifest.json"
        ):
            raise ValueError("Immutable file names must be unique and not manifest.json")
        _artifact_file(directory, name)
        if not isinstance(raw, bytes):
            raise ValueError("Immutable files must be exact bytes")
        folded.add(name.casefold())
        descriptors[name] = {"sha256": _sha256(raw), "bytes": len(raw)}
    for name in folded:
        parts = name.split("/")
        if any("/".join(parts[:index]) in folded for index in range(1, len(parts))):
            raise ValueError("A file cannot also be a parent directory")
    manifest = {
        "format": IMMUTABLE_BUILD_FORMAT,
        "build_id": build_id,
        "files": descriptors,
        "metadata": metadata,
    }
    manifest_raw = _manifest_bytes(manifest)
    digest = _sha256(manifest_raw)
    result = {"artifact_id": build_id, "manifest_sha256": digest, "files": descriptors}

    def verify_existing() -> None:
        stored, actual = read_immutable_build(build_id, digest, root=root)
        if stored != manifest or actual != files:
            raise ValueError("Immutable artifact identity/content conflict")

    if directory.exists():
        verify_existing()
        return result
    with _publication_lock(directory):
        if directory.exists():
            verify_existing()
            return result
        with tempfile.TemporaryDirectory(prefix=".publish-", dir=directory.parent) as temporary:
            stage = Path(temporary)
            if not _resolved(stage).is_relative_to(_resolved(directory.parent)):
                raise ValueError("Staging directory escapes artifact store")
            for name, raw in [*files.items(), ("manifest.json", manifest_raw)]:
                path = _artifact_file(stage, name)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            # All writers in this module use the same exclusive claim. A
            # published directory is nonempty and cannot be replaced by rename.
            if directory.exists():
                verify_existing()
                return result
            os.rename(stage, directory)
    verify_existing()
    return result
