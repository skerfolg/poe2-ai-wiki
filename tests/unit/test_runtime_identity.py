from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.build_runtime import _assert_no_sensitive_paths, _strip_local_direct_url

from pok.common.paths import (
    artifacts_dir,
    cache_home,
    index_db_path,
    knowledge_dir,
    resource_root,
    var_dir,
)
from pok.pob.runtime_identity import runtime_identity
from pok.pob.versions import find_luajit


def test_identity_git_keeps_timeout_cleanup_off_subprocess_pipes(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    from pok.pob.runtime_identity import _git

    def run(args, **kwargs):
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert "capture_output" not in kwargs
        assert kwargs["timeout"] == 10
        kwargs["stdout"].write(" M identity 한글.py\n".encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert _git(tmp_path, "status", "--porcelain") == " M identity 한글.py"


def test_paths_separate_resource_data_and_cache(monkeypatch, tmp_path: Path) -> None:
    resource = tmp_path / "bundle"
    data = tmp_path / "data"
    cache = tmp_path / "cache"
    (resource / "knowledge").mkdir(parents=True)
    (resource / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    monkeypatch.setenv("POK_RESOURCE_ROOT", str(resource))
    monkeypatch.setenv("POK_DATA_HOME", str(data))
    monkeypatch.setenv("POK_CACHE_HOME", str(cache))

    assert resource_root() == resource.resolve()
    assert knowledge_dir() == resource.resolve() / "knowledge"
    assert var_dir() == data.resolve()
    assert artifacts_dir() == data.resolve() / "artifacts"
    assert cache_home() == cache.resolve()
    assert index_db_path() == cache.resolve() / "index.sqlite"


def test_explicit_root_preserves_repo_shaped_paths(monkeypatch, tmp_path: Path) -> None:
    resource = tmp_path / "bundle"
    data = tmp_path / "data"
    cache = tmp_path / "cache"
    root = tmp_path / "repo"
    monkeypatch.setenv("POK_RESOURCE_ROOT", str(resource))
    monkeypatch.setenv("POK_DATA_HOME", str(data))
    monkeypatch.setenv("POK_CACHE_HOME", str(cache))

    assert knowledge_dir(root) == root / "knowledge"
    assert var_dir(root) == root / "var"
    assert artifacts_dir(root) == root / "artifacts"
    assert index_db_path(root) == root / "var" / "index.sqlite"


def test_find_luajit_prefers_bundled_runtime(monkeypatch, tmp_path: Path) -> None:
    exe = tmp_path / "resources" / "luajit" / ("luajit.exe" if os.name == "nt" else "luajit")
    exe.parent.mkdir(parents=True)
    exe.write_text("", encoding="utf-8")
    monkeypatch.setenv("POK_RESOURCE_ROOT", str(tmp_path))
    monkeypatch.setenv("POK_LUAJIT", str(tmp_path / "other.exe"))

    assert find_luajit() == str(exe)


def test_packaged_runtime_identity_reads_verified_manifest(tmp_path: Path) -> None:
    expected = {
        "apiVersion": 1,
        "pok": {"version": "test", "sourceCommit": "abc", "sourceDigest": "src"},
        "pob": {"commit": "def", "sourceDigest": "pob"},
        "kb": {"manifestSha256": "m", "contentSha256": "k", "patch": "0.x"},
        "capabilities": {"computeXml": True, "renderItem": True, "catalogExport": True},
    }
    resources = tmp_path / "resources"
    resources.mkdir()
    (resources / "runtime-manifest.json").write_text(
        json.dumps({"format_version": 1, "identity": expected}), encoding="utf-8"
    )

    assert runtime_identity(tmp_path) == expected


def test_runtime_packaging_strips_local_direct_url_metadata(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    dist = site / "pok-0.0.1.dist-info"
    dist.mkdir(parents=True)
    (dist / "METADATA").write_text("Name: pok\nVersion: 0.0.1\n", encoding="utf-8")
    (dist / "direct_url.json").write_text(
        json.dumps({"url": "file:///D:/Sample Workspace/pok-source"}), encoding="utf-8"
    )

    _strip_local_direct_url(site)

    assert (dist / "METADATA").is_file()
    assert not (dist / "direct_url.json").exists()


def test_runtime_packaging_rejects_source_or_home_paths(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    source = tmp_path / "source"
    runtime.mkdir()
    source.mkdir()
    (runtime / "METADATA").write_text(f"Home-page: {source}\n", encoding="utf-8")

    try:
        _assert_no_sensitive_paths(runtime, source)
    except RuntimeError as exc:
        assert "METADATA" in str(exc)
    else:
        raise AssertionError("source path was accepted in runtime text metadata")


def test_runtime_identity_cache_observes_source_and_kb_changes(tmp_path: Path) -> None:
    commit = "abcdef0123456789abcdef0123456789abcdef01"
    (tmp_path / "pyproject.toml").write_text("[project]\nname='pok-test'\n", encoding="utf-8")
    ingest = tmp_path / "knowledge" / "ingest"
    ingest.mkdir(parents=True)
    (ingest / "manifest.json").write_text(
        json.dumps({"pob_commit": commit, "patch": "0.test"}), encoding="utf-8"
    )
    src = tmp_path / "src" / "pok"
    src.mkdir(parents=True)
    (src / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (src / "example.lua").write_text("return 1\n", encoding="utf-8")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "pob_probe.lua").write_text("return 1\n", encoding="utf-8")
    pob = tmp_path / "external" / "pob" / commit[:7] / "src"
    pob.mkdir(parents=True)
    (pob / "HeadlessWrapper.lua").write_text("return 1\n", encoding="utf-8")

    first = runtime_identity(tmp_path, force_compute=True)
    (src / "example.lua").write_text("return 100\n", encoding="utf-8")
    changed_source = runtime_identity(tmp_path, force_compute=True)
    assert changed_source["pok"]["sourceDigest"] != first["pok"]["sourceDigest"]
    assert changed_source["kb"]["contentSha256"] == first["kb"]["contentSha256"]

    (ingest / "other.json").write_text('{"changed":true}\n', encoding="utf-8")
    changed_kb = runtime_identity(tmp_path, force_compute=True)
    assert changed_kb["kb"]["contentSha256"] != changed_source["kb"]["contentSha256"]
    assert changed_kb["pok"]["sourceDigest"] == changed_source["pok"]["sourceDigest"]


def test_source_patterns_do_not_scan_nested_checkout_copies(tmp_path: Path) -> None:
    from pok.pob.runtime_identity import _tree_signature, sha256_tree

    source = tmp_path / "src" / "pok" / "example.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    patterns = ("src/pok/**/*.py",)
    before = sha256_tree(tmp_path, include=patterns)
    signature = _tree_signature(tmp_path, include=patterns)
    nested = tmp_path / "old-build" / "src" / "pok" / "example.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("VALUE = 2\n", encoding="utf-8")
    assert sha256_tree(tmp_path, include=patterns) == before
    assert _tree_signature(tmp_path, include=patterns) == signature
