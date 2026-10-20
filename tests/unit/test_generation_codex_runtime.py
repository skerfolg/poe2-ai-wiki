"""Unit-only tests: every CLI process is fake; no model or KB calls."""

from __future__ import annotations

import importlib.util
import inspect
import json
import subprocess
import tomllib
from pathlib import Path

import jsonschema
import pytest

MODULE = Path(__file__).resolve().parents[2] / "skills/build-generation/codex_runtime.py"
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


@pytest.fixture
def runtime(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("generation_codex_runtime", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(module.Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))
    cli = tmp_path / "codex-fake"
    cli.write_bytes(b"fake CLI executable; never executed")
    monkeypatch.setattr(module.shutil, "which", lambda name: str(cli))
    return module


def fake_process(
    monkeypatch,
    runtime,
    *,
    stderr="",
    answer=None,
    extra_events=(),
    usage=None,
    timeout=False,
    interrupt=False,
    exit_code=0,
):
    calls = []
    cleanup_calls = []
    if usage is None:
        usage = {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 25}
    if answer is None:
        answer = {"ok": True}

    class FakeProcess:
        pid = 987654321

        def __init__(self, args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            self.returncode = None if timeout or interrupt else exit_code
            self.communications = 0
            events = [
                {"type": "thread.started", "thread_id": "fake-thread"},
                {"type": "turn.started"},
                *extra_events,
            ]
            if not timeout and not interrupt:
                events.extend(
                    [
                        {
                            "type": "item.completed",
                            "item": {
                                "id": "reply",
                                "type": "agent_message",
                                "text": "not inspected by event audit",
                            },
                        },
                        {"type": "turn.completed", "usage": usage},
                    ]
                )
                path = Path(args[args.index("--output-last-message") + 1])
                path.write_text(json.dumps(answer), encoding="utf-8")
            kwargs["stdout"].write("\n".join(json.dumps(e) for e in events).encode())
            kwargs["stderr"].write(stderr.encode())

        def communicate(self, data=None, timeout=None):
            self.communications += 1
            calls[0]["communications"] = self.communications
            if interrupt and self.communications == 1:
                raise KeyboardInterrupt("user stopped this run")
            if self.returncode is None:
                raise subprocess.TimeoutExpired("fake-codex", timeout)
            return b"", b""

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    def terminate(process):
        cleanup_calls.append(process.pid)
        process.kill()
        return {"pid": process.pid, "requested": True, "fake_cleanup": True}

    monkeypatch.setattr(runtime.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(runtime, "_terminate_tree", terminate)
    return calls, cleanup_calls


def run(runtime, tmp_path, **kwargs):
    return runtime.run_codex(
        "Return the requested JSON; requests are handled by the caller.",
        SCHEMA,
        tmp_path / "evidence",
        1.5,
        model="caller-model",
        reasoning_effort="high",
        repo_root=tmp_path,
        **kwargs,
    )


def test_arguments_require_explicit_model_effort_and_keep_tool_policy(runtime, tmp_path):
    assert (
        inspect.signature(runtime.run_codex).parameters["model"].default is inspect.Parameter.empty
    )
    assert (
        inspect.signature(runtime.run_codex).parameters["reasoning_effort"].default
        is inspect.Parameter.empty
    )
    args = runtime.build_command(
        tmp_path / "out",
        model="caller-model",
        reasoning_effort="ultra",
        cwd=tmp_path,
        repo_root=tmp_path,
    )
    assert args[args.index("--model") + 1] == "caller-model"
    overrides = [args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "-c"]
    assert 'model_reasoning_effort="ultra"' in overrides
    assert "agents.enabled=false" in overrides
    assert 'web_search="disabled"' in overrides
    assert "project_doc_max_bytes=0" in overrides
    disabled = {args[i + 1] for i, arg in enumerate(args[:-1]) if arg == "--disable"}
    assert {
        "multi_agent",
        "multi_agent_v2",
        "code_mode_host",
        "shell_tool",
        "apps",
        "plugins",
    } <= disabled
    assert {"--ignore-user-config", "--ephemeral", "--no-daemon", "--json"} <= set(args)
    assert args[args.index("--sandbox") + 1] == "read-only"
    with pytest.raises(TypeError):
        runtime.build_command(
            tmp_path,
            cwd=tmp_path,
            model="m",
            reasoning_effort="high",
            extra_args=["--enable", "shell_tool"],
        )


def test_skill_discovery_uses_known_paths_without_probe_or_content_reads(runtime, tmp_path):
    files = [
        tmp_path / ".agents/skills/a/SKILL.md",
        tmp_path / ".codex/skills/b/SKILL.md",
        runtime.Path.home() / ".codex/skills/.system/c/SKILL.md",
        runtime.Path.home() / ".agents/skills/d/SKILL.md",
    ]
    for path in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff invalid UTF-8 must not be read")
    override = runtime.skill_disable_override(tmp_path)
    rows = tomllib.loads(override)["skills"]["config"]
    assert {row["path"] for row in rows} == {path.resolve().as_posix() for path in files}
    assert all(row["enabled"] is False for row in rows)
    assert not (tmp_path / "var").exists()


def test_success_records_raw_usage_without_double_counting(runtime, monkeypatch, tmp_path):
    calls, _ = fake_process(monkeypatch, runtime)
    result = run(runtime, tmp_path)
    assert result["status"] == "completed"
    assert result["runtime_checks_passed"] is True
    assert result["tool_schema_absence_verified"] is False
    assert result["additional_model_calls"] is None
    assert result["usage_totals"] == {
        "input_tokens": 100,
        "cached_input_tokens": 40,
        "cache_write_input_tokens": None,
        "output_tokens": 25,
        "reasoning_output_tokens": None,
    }
    assert result["model"] == "caller-model"
    assert result["reasoning_effort"] == "high"
    assert len(calls) == 1
    assert calls[0]["kwargs"]["shell"] is False
    assert json.loads((tmp_path / "evidence/summary.json").read_text()) == result
    assert (tmp_path / "evidence/request.json").is_file()
    assert "valid_for_comparison" not in result


def test_failed_spawn_in_stderr_invalidates_even_without_json_tool_item(
    runtime, monkeypatch, tmp_path
):
    message = "ERROR codex_core::tools::router: error=collab spawn failed: no rollout found"
    fake_process(monkeypatch, runtime, stderr=message)
    result = run(runtime, tmp_path)
    assert result["status"] == "invalid"
    assert result["unauthorized_tool_items"] == []
    assert result["violations"] == ["native_tool_stderr_error"]
    assert result["native_stderr_errors"][0]["kind"] == "failed_collaboration_spawn"
    assert result["additional_model_calls"] is None
    assert (tmp_path / "evidence/stderr.txt").read_text() == message


def test_blocked_discovery_is_recorded_without_claiming_execution(runtime, monkeypatch, tmp_path):
    stderr = (
        "ERROR codex_core::tools::router: error=code-mode host is disabled\n"
        "WARN codex_core::shell_snapshot: unsupported"
    )
    fake_process(monkeypatch, runtime, stderr=stderr)
    result = run(runtime, tmp_path)
    assert result["status"] == "completed"
    assert result["native_stderr_errors"] == []
    assert result["blocked_native_discovery_attempts"][0]["kind"] == "blocked_code_host_discovery"
    assert len(result["other_stderr_diagnostics"]) == 1
    assert result["tool_schema_absence_verified"] is False


def test_native_item_and_nonrouter_tool_failure_are_rejected(runtime, monkeypatch, tmp_path):
    item = {"id": "tool-1", "type": "command_execution", "command": "forbidden"}
    events = [{"type": "item.started", "item": item}, {"type": "item.completed", "item": item}]
    fake_process(
        monkeypatch,
        runtime,
        stderr="ERROR codex_core::tools::handlers: tool failed",
        extra_events=events,
    )
    result = run(runtime, tmp_path)
    assert result["status"] == "invalid"
    assert set(result["violations"]) == {
        "unauthorized_native_tool_event",
        "native_tool_stderr_error",
    }
    assert len(result["unauthorized_tool_items"]) == 1
    assert result["unauthorized_tool_items"][0]["phases"] == ["item.started", "item.completed"]


def test_timeout_preserves_partial_logs_and_stops_only_spawned_process(
    runtime, monkeypatch, tmp_path
):
    calls, cleanup = fake_process(monkeypatch, runtime, timeout=True, stderr="partial runtime log")
    result = run(runtime, tmp_path)
    assert result["status"] == "timeout"
    assert result["timeout"] is True
    assert len(calls) == 1
    assert cleanup == [987654321]
    assert result["usage_complete"] is False
    assert result["usage_totals"]["input_tokens"] is None
    assert (tmp_path / "evidence/stderr.txt").read_text() == "partial runtime log"
    assert (tmp_path / "evidence/events.jsonl").is_file()
    assert result["answer_error"]["type"] == "missing_answer"


def test_user_interrupt_stops_spawned_process_preserves_summary_and_reraises(
    runtime, monkeypatch, tmp_path
):
    calls, cleanup = fake_process(
        monkeypatch, runtime, interrupt=True, stderr="partial before user interruption"
    )
    with pytest.raises(KeyboardInterrupt, match="user stopped this run"):
        run(runtime, tmp_path)
    assert len(calls) == 1
    assert cleanup == [987654321]
    assert calls[0]["communications"] == 2  # The second call only reaps the stopped process.
    result = json.loads((tmp_path / "evidence/summary.json").read_text())
    assert result["status"] == "interrupted" and result["runtime_checks_passed"] is False
    assert result["interruption"] == {
        "type": "KeyboardInterrupt",
        "message": "user stopped this run",
    }
    assert result["cleanup"]["fake_cleanup"] is True
    assert result["usage_complete"] is False
    assert result["usage_totals"]["input_tokens"] is None
    assert result["answer_error"]["type"] == "missing_answer"
    assert (tmp_path / "evidence/stderr.txt").read_text() == "partial before user interruption"
    assert (tmp_path / "evidence/usage.json").is_file()


def test_interrupt_cleanup_failure_is_recorded_before_original_interrupt_is_reraised(
    runtime, monkeypatch, tmp_path
):
    calls, _ = fake_process(monkeypatch, runtime, interrupt=True)

    def fail_cleanup(process):
        raise OSError("fixture tree termination denied")

    monkeypatch.setattr(runtime, "_terminate_tree", fail_cleanup)
    with pytest.raises(KeyboardInterrupt, match="user stopped this run"):
        run(runtime, tmp_path)
    assert len(calls) == 1 and calls[0]["communications"] == 2
    result = json.loads((tmp_path / "evidence/summary.json").read_text())
    assert result["status"] == "interrupted"
    assert result["cleanup"]["termination_error"] == {
        "type": "OSError",
        "message": "fixture tree termination denied",
    }
    assert result["cleanup"]["reap_error"]["type"] == "TimeoutExpired"
    assert result["runtime_checks_passed"] is False


def test_invalid_input_schema_never_launches_or_creates_output(runtime, monkeypatch, tmp_path):
    calls, _ = fake_process(monkeypatch, runtime)
    with pytest.raises(jsonschema.SchemaError):
        runtime.run_codex(
            "x",
            {"type": "not-a-json-schema-type"},
            tmp_path / "evidence",
            1,
            model="m",
            reasoning_effort="low",
            repo_root=tmp_path,
        )
    assert calls == []
    assert not (tmp_path / "evidence").exists()


def test_invalid_answer_and_size_limit_are_distinct(runtime, monkeypatch, tmp_path):
    fake_process(monkeypatch, runtime, answer={"ok": "wrong type"})
    result = run(runtime, tmp_path, max_answer_chars=1)
    assert result["answer_valid"] is False
    assert result["answer_error"]["type"] == "ValidationError"
    assert result["violations"] == ["answer_size_exceeded"]
    assert result["status"] == "invalid"


@pytest.mark.parametrize("empty", [True, False])
def test_existing_evidence_directory_is_never_reused(runtime, monkeypatch, tmp_path, empty):
    calls, _ = fake_process(monkeypatch, runtime)
    out = tmp_path / "evidence"
    out.mkdir()
    if not empty:
        (out / "sentinel").write_text("original")
    with pytest.raises(FileExistsError):
        run(runtime, tmp_path)
    assert calls == []
    assert sorted(x.name for x in out.iterdir()) == ([] if empty else ["sentinel"])


def test_launch_failure_is_saved_without_retry(runtime, monkeypatch, tmp_path):
    calls = []

    def fail(args, **kwargs):
        calls.append(args)
        raise OSError("fake launch failure")

    monkeypatch.setattr(runtime.subprocess, "Popen", fail)
    result = run(runtime, tmp_path)
    assert len(calls) == 1
    assert result["status"] == "failed"
    assert result["launch_error"] == {"type": "OSError", "message": "fake launch failure"}
    assert (tmp_path / "evidence/summary.json").is_file()


def test_missing_usage_is_unknown_not_zero(runtime, monkeypatch, tmp_path):
    fake_process(monkeypatch, runtime, usage={"input_tokens": 100, "output_tokens": 25})
    result = run(runtime, tmp_path)
    assert result["status"] == "incomplete"
    assert result["usage_totals"]["cached_input_tokens"] is None


@pytest.mark.parametrize(
    "settings",
    [{"model": ""}, {"model": "--enable"}, {"model": "m\n-c"}, {"reasoning_effort": "automatic"}],
)
def test_bad_model_settings_fail_before_launch(runtime, monkeypatch, tmp_path, settings):
    calls, _ = fake_process(monkeypatch, runtime)
    args = {"model": "m", "reasoning_effort": "low", **settings}
    with pytest.raises(ValueError):
        runtime.run_codex("x", SCHEMA, tmp_path / "evidence", 1, repo_root=tmp_path, **args)
    assert calls == []


def test_relative_executable_is_resolved_before_changing_workdir(runtime, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    executable = tmp_path / "relative-codex"
    executable.write_bytes(b"fake")
    args = runtime.build_command(
        tmp_path / "out",
        model="m",
        reasoning_effort="low",
        cwd=tmp_path / "different",
        repo_root=tmp_path,
        codex_exe="relative-codex",
    )
    assert args[0] == str(executable.resolve())
