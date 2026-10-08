from __future__ import annotations

import subprocess
from types import SimpleNamespace

from pok.kb.store import _untracked


def test_untracked_paths_use_file_output_and_strict_utf8(monkeypatch, tmp_path):
    def run(args, **kwargs):
        assert "capture_output" not in kwargs
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["timeout"] == 20
        kwargs["stdout"].write("새 노드.json\0other.ndjson\0".encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", run)
    assert _untracked(tmp_path) == {tmp_path / "새 노드.json", tmp_path / "other.ndjson"}


def test_untracked_git_timeout_does_not_skip_unknown_content(monkeypatch, tmp_path):
    def timeout(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 20)

    monkeypatch.setattr(subprocess, "run", timeout)
    assert _untracked(tmp_path) == frozenset()
