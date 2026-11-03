"""Owned controller collection: file stdin, real deadlines, partial logs and unknown cleanup."""

import importlib
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills/build-generation")
    )
    module = importlib.import_module("product_run")
    monkeypatch.setattr(module, "_UNCONFIRMED", {})
    return module


SCHEMA = {
    "type": "object",
    "properties": {"status": {"const": "complete"}, "bytes": {"type": "integer"}},
    "required": ["status", "bytes"],
}


def command(output, *, completed=True, hang=False):
    program = """
import sys,json,time
from pathlib import Path
raw = sys.stdin.buffer.read()
print(json.dumps({'type':'thread.started','thread_id':sys.argv[2]}),flush=True)
if sys.argv[3] == 'hang':
    for _ in range(600):
        print(json.dumps({'type':'progress','value':'still running'}),flush=True)
        time.sleep(.1)
else:
    Path(sys.argv[1]).write_text(json.dumps({'status':'complete','bytes':len(raw)}),encoding='utf-8')
    if sys.argv[3] == 'completed':
        print(json.dumps({'type':'turn.completed'}),flush=True)
"""
    return [
        sys.executable,
        "-c",
        program,
        str(output / "answer.json"),
        str(uuid4()),
        "hang" if hang else "completed" if completed else "missing-end",
    ]


def test_file_input_preserves_large_prompt_and_completed_collection(module, tmp_path):
    output = tmp_path / "phase-1"
    prompt = "한글 입력\n" * 20000
    result = module.execute_phase(
        command(output),
        output,
        prompt=prompt,
        schema=SCHEMA,
        cwd=tmp_path / "workspace",
        timeout_s=15,
    )
    assert result["state"] == "completed" and result["turn_completed"]
    assert result["cleanup"]["status"] == "confirmed"
    assert not result["build_quality_verified"]
    assert json.loads((output / "answer.json").read_bytes())["bytes"] == len(prompt.encode("utf-8"))
    assert (output / "prompt.txt").read_bytes() == prompt.encode("utf-8")
    assert json.loads((output / "execution.json").read_bytes()) == result


def test_valid_answer_without_completed_turn_is_not_completion(module, tmp_path):
    output = tmp_path / "phase-1"
    result = module.execute_phase(
        command(output, completed=False),
        output,
        prompt="toy",
        schema=SCHEMA,
        cwd=tmp_path / "workspace",
        timeout_s=15,
    )
    assert result["state"] == "failed" and result["answer_valid"]
    assert not result["turn_completed"]


def test_progress_does_not_extend_deadline_and_partial_output_is_retained(module, tmp_path):
    output = tmp_path / "phase-1"
    started = time.monotonic()
    try:
        result = module.execute_phase(
            command(output, hang=True),
            output,
            prompt="toy",
            schema=SCHEMA,
            cwd=tmp_path / "workspace",
            timeout_s=3,
        )
    finally:
        # Even a failing assertion must not discard an owned live handle.
        for child in module._UNCONFIRMED.values():
            assert module.terminate_owned(child, timeout_s=5)["status"] == "confirmed"
        module._UNCONFIRMED.clear()
    assert time.monotonic() - started < 10
    assert result["state"] == "timed_out" and result["cleanup"]["status"] == "confirmed"
    assert "progress" in (output / "events.jsonl").read_text(encoding="utf-8")
    assert result["session_id"] and not result["answer_valid"]
    process = json.loads((output / "process.json").read_bytes())
    assert process["model_deadline_unix"] < process["deadline_unix"]


def test_unconfirmed_cleanup_blocks_subsequent_phase(module, tmp_path, monkeypatch):
    class Fake:
        pid = 123
        returncode = 0

        def wait(self, timeout):
            return 0

    child = Fake()
    monkeypatch.setattr(module, "spawn_owned", lambda *a, **k: child)
    monkeypatch.setattr(
        module, "terminate_owned", lambda *a, **k: {"status": "unconfirmed", "scope": "fixture"}
    )
    output = tmp_path / "phase-1"
    result = module.execute_phase(
        ["fake"], output, prompt="toy", schema=SCHEMA, cwd=tmp_path / "workspace", timeout_s=15
    )
    assert result["state"] == "termination_unconfirmed"
    assert module._UNCONFIRMED[str(output.resolve())] is child
    with pytest.raises(RuntimeError, match="unconfirmed"):
        module.execute_phase(
            ["fake"],
            tmp_path / "phase-2",
            prompt="toy",
            schema=SCHEMA,
            cwd=tmp_path / "workspace",
            timeout_s=15,
        )
    assert not (tmp_path / "phase-2").exists()


@pytest.mark.parametrize("budget", [0, -1, True, float("nan"), float("inf"), 5401])
def test_invalid_budget_never_launches(module, tmp_path, budget):
    output = tmp_path / "phase-1"
    with pytest.raises(ValueError):
        module.execute_phase(
            ["unused"],
            output,
            prompt="toy",
            schema=SCHEMA,
            cwd=tmp_path / "workspace",
            timeout_s=budget,
        )
    assert not output.exists()


def test_low_storage_never_spawns_model_and_preserves_failure_receipt(
    module, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    monkeypatch.setattr(module.shutil, "disk_usage", lambda p: SimpleNamespace(free=0))

    def forbidden(*a, **k):
        raise AssertionError("Model must not start below disk reserve")

    monkeypatch.setattr(module, "spawn_owned", forbidden)
    output = tmp_path / "phase"
    result = module.execute_phase(
        ["unused"],
        output,
        prompt="toy",
        schema=SCHEMA,
        cwd=tmp_path / "workspace",
        timeout_s=15,
        minimum_free_bytes=1024,
    )
    assert result["state"] == "failed"
    assert result["error"]["type"] == "StorageBudgetExhausted"
    assert result["cleanup"]["status"] == "confirmed"
    assert not (output / "process.json").exists()
    assert json.loads((output / "execution.json").read_bytes()) == result


def test_storage_drop_terminates_owned_model_and_keeps_partial_events(
    module, tmp_path, monkeypatch
):
    from types import SimpleNamespace

    readings = []

    def space(path):
        readings.append(True)
        return SimpleNamespace(free=4096 if len(readings) <= 2 else 0)

    monkeypatch.setattr(module.shutil, "disk_usage", space)
    output = tmp_path / "phase"
    result = module.execute_phase(
        command(output, hang=True),
        output,
        prompt="toy",
        schema=SCHEMA,
        cwd=tmp_path / "workspace",
        timeout_s=20,
        minimum_free_bytes=1024,
    )
    assert result["state"] == "failed" and not result["timed_out"]
    assert result["error"]["type"] == "StorageBudgetExhausted"
    assert result["cleanup"]["status"] == "confirmed"
    assert result["storage_guard"]["last_free_bytes"] == 0
    assert "progress" in (output / "events.jsonl").read_text(encoding="utf-8")
    assert json.loads((output / "execution.json").read_bytes()) == result


@pytest.mark.parametrize("minimum", [0, -1, True, 1.5])
def test_invalid_storage_reserve_never_creates_output(module, tmp_path, minimum):
    output = tmp_path / "phase"
    with pytest.raises(ValueError, match="positive integer"):
        module.execute_phase(
            ["unused"],
            output,
            prompt="toy",
            schema=SCHEMA,
            cwd=tmp_path / "workspace",
            timeout_s=15,
            minimum_free_bytes=minimum,
        )
    assert not output.exists()
