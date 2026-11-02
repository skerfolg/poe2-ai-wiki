"""Bundle integrity failures must remain explicit before native startup."""

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

from pok.pob.worker_bundle import FORMAT, bundle_path, load_bundle


@pytest.fixture
def manifest(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    files = {}
    for name in ("python/python.exe", "adapter/a.py", "pob/src/a.lua", "lua/luajit.exe"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = name.encode()
        path.write_bytes(raw)
        files[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
    data = {
        "format": FORMAT,
        "protocol": "pok.pob-worker.v1",
        "platform": sys.platform,
        "pob_commit": "f" * 40,
        "paths": {
            "python": "python/python.exe",
            "adapter": "adapter",
            "pob": "pob",
            "luajit": "lua/luajit.exe",
        },
        "files": files,
        "identity": {"format": "pok.pob-worker-identity.v1"},
        "origin": {},
    }
    path = root / "worker-manifest.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_relative_bundle_survives_copy_without_identity_rewrite(manifest, tmp_path):
    original = load_bundle(manifest, check_interpreter=False)
    target = tmp_path / "relocated"
    shutil.copytree(manifest.parent, target)
    moved = load_bundle(target / manifest.name, check_interpreter=False)
    assert moved.manifest_sha256 == original.manifest_sha256
    assert moved.path("python") == target / "python/python.exe"


@pytest.mark.parametrize("mutation", ["same_size_bytes", "missing", "extra", "manifest"])
def test_tamper_is_rejected(manifest, mutation):
    bundle = load_bundle(manifest, check_interpreter=False)
    file = manifest.parent / "adapter/a.py"
    if mutation == "same_size_bytes":
        file.write_bytes(b"x" * file.stat().st_size)
    elif mutation == "missing":
        file.unlink()
    elif mutation == "extra":
        (manifest.parent / "extra.py").write_text("extra")
    else:
        manifest.write_bytes(manifest.read_bytes() + b" ")
    with pytest.raises(ValueError):
        bundle.validate(check_interpreter=False)


@pytest.mark.parametrize(
    "name", ["/absolute", "../outside", "a/../outside", "a//b", "a/./b", "C:/outside", "a\\b", ""]
)
def test_nonportable_paths_rejected(tmp_path, name):
    with pytest.raises(ValueError):
        bundle_path(tmp_path, name)


def test_wrong_interpreter_rejected(manifest):
    with pytest.raises(ValueError, match="declared interpreter"):
        load_bundle(manifest)


def test_duplicate_manifest_key_rejected(manifest):
    manifest.write_text('{"format":"one","format":"two"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate"):
        load_bundle(manifest, check_interpreter=False)


def test_access_failure_is_not_hidden(manifest, monkeypatch):
    original = Path.read_bytes
    blocked = manifest.parent / "adapter/a.py"

    def read(path):
        if path == blocked:
            raise PermissionError("fixture access denied")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    with pytest.raises(OSError, match=r"Cannot verify bundle file.*adapter.*fixture access denied"):
        load_bundle(manifest, check_interpreter=False)
