"""Identity lookup must not wait for descendants retaining output handles."""

from __future__ import annotations

import subprocess
import sys
import time
from types import SimpleNamespace

from pok.mcp import server


def test_wire_response_preserves_structured_content_and_error():
    import json

    from fastmcp.tools.base import ToolResult
    from mcp.types import TextContent

    result = ToolResult(
        content=[TextContent(type="text", text="failure")],
        structured_content={"ok": False},
        is_error=True,
    )
    wire = json.loads(server._wire_json(result))
    assert wire["structuredContent"] == {"ok": False}
    assert wire["isError"] is True


def test_git_identity_timeout_does_not_drain_descendant_pipes(monkeypatch, tmp_path):
    original_run = subprocess.run
    child = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(3)']); "
        "time.sleep(10)"
    )

    def delayed_git(args, **kwargs):
        kwargs["timeout"] = 0.2
        return original_run([sys.executable, "-c", child], **kwargs)

    monkeypatch.setattr(subprocess, "run", delayed_git)
    started = time.monotonic()
    assert server._git_head(tmp_path) == ("", "")
    assert time.monotonic() - started < 1.5


def test_unknown_identity_is_not_reported_as_verified(monkeypatch):
    from pok.kb import store

    monkeypatch.setattr(server, "_LOADED_COMMIT", "")
    monkeypatch.setattr(server, "_git_head", lambda root: ("", ""))
    monkeypatch.setattr(store, "load", lambda: SimpleNamespace(skip_warnings=[]))
    info = server.server_info()
    assert info["identity_status"] == "unavailable"
    assert "인증하지 않는다" in info["note"]


def test_identity_does_not_trigger_cold_or_broken_kb_validation(monkeypatch):
    from pok.kb import store

    def forbidden_load(*args, **kwargs):
        raise AssertionError("Identity lookup must not load the KB")

    monkeypatch.setattr(store, "load", forbidden_load)
    monkeypatch.setattr(server, "_git_head", lambda root: ("abcdef1", "title"))
    info = server.server_info()
    assert info["kb_diagnostics"]["current_validation"] == "not_checked"
    assert info["kb_diagnostics"]["status"] in {"not_loaded", "cached_snapshot"}


def test_untracked_timeout_does_not_drain_descendant_pipes(monkeypatch, tmp_path):
    from pok.kb import store

    original_run = subprocess.run
    child = (
        "import subprocess,sys,time; "
        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(3)']); "
        "time.sleep(10)"
    )

    def delayed_git(args, **kwargs):
        kwargs["timeout"] = 0.2
        return original_run([sys.executable, "-c", child], **kwargs)

    monkeypatch.setattr(subprocess, "run", delayed_git)
    started = time.monotonic()
    assert store._untracked(tmp_path) == frozenset()
    assert time.monotonic() - started < 1.5


def test_git_identity_preserves_unicode_and_rejects_failed_lookup(monkeypatch, tmp_path):
    original_run = subprocess.run
    monkeypatch.setenv("PYTHONIOENCODING", "utf-8")

    def unicode_git(args, **kwargs):
        text = (
            "abcdef1\n한글 — 제목"
            if "--format=%h%n%s" in args
            else ("abcdef1" if "rev-parse" in args else "한글 — 제목")
        )
        return original_run([sys.executable, "-c", "print(" + repr(text) + ")"], **kwargs)

    monkeypatch.setattr(subprocess, "run", unicode_git)
    assert server._git_head(tmp_path) == ("abcdef1", "한글 — 제목")

    def failed_git(args, **kwargs):
        return original_run([sys.executable, "-c", "print('misleading'); exit(1)"], **kwargs)

    monkeypatch.setattr(subprocess, "run", failed_git)
    assert server._git_head(tmp_path) == ("", "")
