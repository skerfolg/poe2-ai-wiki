"""A model's final answer cannot certify native tool execution or build quality."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = Path(__file__).resolve().parents[2] / "skills/build-generation/redesign_run.py"
SPEC = importlib.util.spec_from_file_location("redesign_native_audit", PATH)
assert SPEC is not None and SPEC.loader is not None
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


def test_completed_answer_does_not_hide_unauthorized_native_execution():
    rows = [
        {"type": "item.completed", "item": {"type": "command_execution", "command": "anything"}},
        {"type": "turn.completed", "usage": {"output_tokens": 10}},
    ]
    result = RUNNER.audit_native_events(rows, {"list_builds"})
    assert result["turn_completed"] is True
    assert len(result["protocol_violations"]) == 1
    assert result["build_quality_verified"] is False


def test_failed_mcp_call_is_preserved_separately_from_protocol_violation():
    call = {"type": "mcp_tool_call", "server": "pok", "tool": "compute_pob", "status": "failed"}
    result = RUNNER.audit_native_events([{"type": "item.completed", "item": call}], {"compute_pob"})
    assert result["mcp_calls"] == [call]
    assert result["mcp_call_failures"] == [call]
    assert result["execution_failures"] == []
    assert result["protocol_violations"] == []
    assert result["turn_completed"] is False


def test_other_server_and_capacity_failure_are_not_success():
    rows = [
        {
            "type": "item.completed",
            "item": {"type": "mcp_tool_call", "server": "other", "tool": "read"},
        },
        {"type": "turn.failed", "error": {"message": "capacity"}},
    ]
    result = RUNNER.audit_native_events(rows, {"read"})
    assert result["protocol_violations"] and result["execution_failures"]


def test_changed_input_is_detected_before_another_run(tmp_path):
    path = tmp_path / "prompt.md"
    path.write_bytes(b"original")
    frozen = {"files": {"prompt.md": hashlib.sha256(b"original").hexdigest()}}
    assert RUNNER.check_frozen_inputs(frozen, tmp_path) == []
    path.write_bytes(b"changed")
    assert RUNNER.check_frozen_inputs(frozen, tmp_path) == ["prompt.md"]


def test_changed_oracle_binary_is_detected(tmp_path):
    binary = tmp_path / "oracle"
    binary.write_bytes(b"fixed")
    frozen = {
        "files": {},
        "executables": {
            "luajit": {"path": str(binary), "sha256": hashlib.sha256(b"fixed").hexdigest()}
        },
    }
    assert RUNNER.check_frozen_inputs(frozen, tmp_path) == []
    binary.write_bytes(b"changed")
    assert RUNNER.check_frozen_inputs(frozen, tmp_path) == ["executable:luajit"]


def test_fixture_copy_preserves_exact_bytes_and_relative_paths(tmp_path):
    source = tmp_path / "artifacts/common"
    source.mkdir(parents=True)
    data = b'{"fixture": true}\r\n'
    (source / "build.json").write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    manifest = {"files": {"artifacts/common/build.json": digest}}
    destination = tmp_path / "artifacts/run/server/artifacts/inputs"
    assert RUNNER.copy_frozen_inputs(source, destination, manifest, tmp_path) == {
        "build.json": digest
    }
    assert (destination / "build.json").read_bytes() == data
    with pytest.raises(ValueError, match="fresh"):
        RUNNER.copy_frozen_inputs(source, destination, manifest, tmp_path)


@pytest.mark.parametrize("expected", [None, "wrong-hash"])
def test_unfrozen_or_changed_fixture_is_rejected_before_copy(tmp_path, expected):
    source = tmp_path / "artifacts/common"
    source.mkdir(parents=True)
    (source / "build.json").write_bytes(b"fixture")
    manifest = {"files": {} if expected is None else {"artifacts/common/build.json": expected}}
    destination = tmp_path / "artifacts/run/inputs"
    with pytest.raises(ValueError, match="not frozen or has changed"):
        RUNNER.copy_frozen_inputs(source, destination, manifest, tmp_path)
    assert not destination.exists()


def test_fixture_outside_artifacts_is_rejected(tmp_path):
    source = tmp_path / "other"
    source.mkdir()
    with pytest.raises(ValueError, match="inside repository artifacts"):
        RUNNER.copy_frozen_inputs(source, tmp_path / "output", {"files": {}}, tmp_path)


def test_launch_failure_still_preserves_run_summary(monkeypatch, tmp_path):
    prompt = tmp_path / "prompt.md"
    prompt.write_bytes(b"infrastructure test")
    manifest = tmp_path / "inputs.json"
    manifest.write_text(
        json.dumps({"files": {"prompt.md": hashlib.sha256(prompt.read_bytes()).hexdigest()}})
    )
    out = tmp_path / "artifacts/failed"
    monkeypatch.setattr(RUNNER, "ROOT", tmp_path)
    monkeypatch.setattr(
        RUNNER,
        "load_runtime",
        lambda: SimpleNamespace(build_native_command=lambda *a, **k: ["missing-executable"]),
    )

    def cannot_launch(*args, **kwargs):
        raise OSError("launch denied")

    monkeypatch.setattr(RUNNER.subprocess, "Popen", cannot_launch)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "runner",
            "--arm",
            "F",
            "--out",
            str(out),
            "--prompt",
            str(prompt),
            "--frozen-inputs",
            str(manifest),
            "--codex-exe",
            "missing",
            "--model",
            "gpt-6-astra",
            "--effort",
            "ultra",
        ],
    )
    RUNNER.main()
    result = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert result["launch_error"]["message"] == "launch denied"
    assert result["answer_exists"] is False
    assert result["turn_completed"] is False
