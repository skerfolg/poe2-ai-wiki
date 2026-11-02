"""Declared pins support optional UI/agent compatibility, not native certification."""

import asyncio
import json

import pytest

from pok.pob import versions


def manifest(root, commit):
    path = root / "knowledge/ingest/manifest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pob_commit": commit}), encoding="utf-8", newline="\n")


def test_declaration_does_not_boot_or_require_an_oracle(tmp_path, monkeypatch):
    manifest(tmp_path, "f" * 40)

    def forbidden(*args, **kwargs):
        raise AssertionError("Declaration must not resolve or boot an oracle")

    monkeypatch.setattr(versions, "resolve_snapshot", forbidden)
    monkeypatch.setattr(versions, "find_luajit", forbidden)
    result = versions.runtime_declaration(tmp_path)
    assert result == {
        "format": "pok.pob-runtime-declaration.v1",
        "claim": "configured_pin_not_observed_execution",
        "status": "declared",
        "pob_commit": "f" * 40,
        "snapshot_available": False,
    }


@pytest.mark.parametrize("commit", ["", "1234567", "F" * 40])
def test_invalid_pin_is_unknown_not_a_success(tmp_path, commit):
    manifest(tmp_path, commit)
    result = versions.runtime_declaration(tmp_path)
    assert result["status"] == "unavailable"
    assert result["pob_commit"] is None


def test_missing_manifest_is_unknown(tmp_path):
    assert versions.runtime_declaration(tmp_path)["status"] == "unavailable"


def test_optional_server_info_skips_diagnostics_through_the_actual_mcp_wrapper(monkeypatch):
    from fastmcp import Client

    from pok.kb import store
    from pok.mcp import server

    def forbidden():
        raise AssertionError("Explicitly omitted KB diagnostics must not be read")

    monkeypatch.setattr(store, "cached_diagnostics", forbidden)
    monkeypatch.setattr(versions, "runtime_declaration", lambda: {"status": "declared"})

    async def exercise():
        async with Client(server.mcp) as client:
            result = await client.call_tool("server_info", {"include_kb_diagnostics": False})
            assert result.data["kb_diagnostics"] is None
            assert result.data["kb_skipped_copies"] is None
            assert result.data["kb_diagnostics_included"] is False
            assert result.data["pob_runtime_declaration"] == {"status": "declared"}
            assert "include_kb_diagnostics" in result.data["tools"]["server_info"]

    asyncio.run(exercise())


def test_git_lookup_trusts_only_its_explicit_root_for_this_command(monkeypatch, tmp_path):
    import subprocess
    from types import SimpleNamespace

    from pok.mcp import server

    calls = []

    def run(args, **kwargs):
        calls.append(args)
        kwargs["stdout"].write(b"abcdef1\ntitle\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert server._git_head(tmp_path) == ("abcdef1", "title")
    assert calls[0][1:3] == ["-c", f"safe.directory={tmp_path.resolve().as_posix()}"]
    assert "--global" not in calls[0]
