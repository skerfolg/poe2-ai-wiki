"""Product-trial command helpers; importing performs no model or MCP execution."""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import UUID

import codex_runtime
from jsonschema import validate
from product_reference import load_reference_policy
from product_server import CONTROL_ROOT, validate_locations

from pok.common.owned_process import spawn_owned, terminate_owned

_UNCONFIRMED: dict[str, subprocess.Popen[Any]] = {}


def build_product_command(
    trial_root: Path,
    *,
    phase: int,
    product_root: Path,
    model: str,
    reasoning_effort: str,
    codex_exe: str,
    luajit_exe: str | None = None,
    session_id: str | None = None,
    control_root: Path = CONTROL_ROOT,
    reference_policy: dict[str, str] | None = None,
) -> list[str]:
    """Build a fresh or exact-session resumed run with the complete product server.

    The same trial namespace/cwd is reused across phases, while output files are
    separate. No --last lookup, R1 catalog policy, or persistent config mutation.
    """
    if type(phase) is not int or phase not in {1, 2}:
        raise ValueError("Expected phase 1 or 2")
    if (phase == 1 and session_id is not None) or (phase == 2 and session_id is None):
        raise ValueError("Only phase 2 requires an explicit session ID")
    if session_id is not None and str(UUID(session_id)) != session_id:
        raise ValueError("Session ID must be the exact canonical UUID from recorded events")
    control = control_root.resolve()
    trial = trial_root.resolve()
    product, namespace = validate_locations(product_root, trial / "server", control)
    if trial == control / "artifacts" or not trial.is_relative_to(control / "artifacts"):
        raise ValueError("Trial root must be a private directory inside workspace artifacts")
    output, cwd = trial / f"phase-{phase}", trial / "workspace"
    command = codex_runtime.build_native_command(
        output,
        model=model,
        reasoning_effort=reasoning_effort,
        cwd=cwd,
        repo_root=control,
        arm="P",
        server_run_dir=namespace,
        codex_exe=codex_exe,
        luajit_exe=luajit_exe,
    )
    # Reuse the existing native transport/tool restrictions, but replace the R1
    # server completely; do not apply its arm/filtering or export wrappers.
    env = {
        "PYTHONPATH": str(product / "src"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(product),
    }
    if luajit_exe is not None:
        env["POK_LUAJIT"] = str(Path(luajit_exe).resolve())
    environment = "{" + ",".join(key + "=" + json.dumps(value) for key, value in env.items()) + "}"
    server_args = [
        str(control / "skills/build-generation/product_server.py"),
        "--product-root",
        str(product),
        "--run-dir",
        str(namespace),
    ]
    if reference_policy is not None:
        load_reference_policy(reference_policy, control)
        server_args.extend(
            [
                "--reference-policy",
                reference_policy["path"],
                "--reference-policy-sha256",
                reference_policy["sha256"],
            ]
        )
    config = (
        "mcp_servers.pok={command="
        + json.dumps(sys.executable)
        + ",args="
        + json.dumps(server_args)
        + ",cwd="
        + json.dumps(str(product))
        + ",env="
        + environment
        + ',enabled=true,required=true,default_tools_approval_mode="approve",'
        + "startup_timeout_sec=60,tool_timeout_sec=1800}"
    )
    positions = [i for i, value in enumerate(command) if value.startswith("mcp_servers.pok=")]
    if len(positions) != 1:
        raise ValueError("Native transport command no longer has one explicit PoK configuration")
    command[positions[0]] = config
    command = [value for value in command if value != "--ephemeral"]
    if session_id is not None:
        resumed = []
        index = 0
        while index < len(command):
            if command[index] in {"--sandbox", "--color", "-C"}:
                index += 2  # These exec-only flags are absent from resume help.
                continue
            resumed.append(command[index])
            index += 1
        resumed.insert(resumed.index("exec") + 1, "resume")
        resumed[-1:-1] = ["-c", 'sandbox_mode="read-only"', session_id]
        command = resumed
    return command


def complete_events(
    path: Path, diagnostics: list[dict[str, Any]] | None = None
) -> Iterator[dict[str, Any]]:
    """Read complete UTF-8 JSON records without decoding an interrupted byte tail."""
    with path.open("rb") as events:
        for line_number, line in enumerate(events, 1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if not line.endswith(b"\n") and not events.read(1):
                    if diagnostics is not None:
                        diagnostics.append({"code": "TRUNCATED_FINAL_EVENT", "line": line_number})
                    return
                raise ValueError("Malformed interior event in session log") from exc
            if not isinstance(event, dict):
                raise ValueError("Session events must be JSON objects")
            yield event


def session_from_events(path: Path) -> str:
    """Accept one recorded ID despite a truncated last event; never guess context."""
    identities = set()
    for event in complete_events(path):
        if event.get("type") == "thread.started":
            identity = event.get("thread_id")
            if not isinstance(identity, str) or str(UUID(identity)) != identity:
                raise ValueError("Recorded thread ID is not a canonical UUID")
            identities.add(identity)
    if len(identities) != 1:
        raise ValueError("Expected exactly one recorded session ID")
    return identities.pop()


def execute_phase(
    command: list[str],
    output_dir: Path,
    *,
    prompt: str,
    schema: dict[str, Any],
    cwd: Path,
    timeout_s: float,
) -> dict[str, Any]:
    """Run once with an absolute budget and owned cleanup; preserve partial files.

    Stdin is a completed file, not a blocking pipe write. Stdout/stderr are files
    so escaped/inherited output handles cannot extend a communicate() deadline.
    This collects execution facts, not build quality or campaign integrity.
    """
    started, wall_started = time.monotonic(), time.time()
    if isinstance(timeout_s, bool) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 5400:
        raise ValueError("Expected a finite phase budget up to 5400 seconds")
    if _UNCONFIRMED:
        raise RuntimeError(
            "An earlier owned launch remains unconfirmed; do not start another phase"
        )
    output = output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    cwd.mkdir(parents=True, exist_ok=True)
    (output / "prompt.txt").write_bytes(prompt.encode("utf-8"))
    (output / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (output / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    deadline = started + timeout_s
    cleanup_reserve = min(5.0, timeout_s / 2)
    model_deadline = deadline - cleanup_reserve
    process = None
    timed_out = False
    error = None
    unexpected: BaseException | None = None
    cleanup: dict[str, Any] = {"status": "confirmed", "scope": "not_started"}
    with (
        (output / "prompt.txt").open("rb") as source,
        (output / "events.jsonl").open("wb") as events,
        (output / "stderr.txt").open("wb") as errors,
    ):
        try:
            if time.monotonic() >= model_deadline:
                raise subprocess.TimeoutExpired(command, timeout_s)
            process = spawn_owned(command, cwd=cwd, stdin=source, stdout=events, stderr=errors)
            (output / "process.json").write_text(
                json.dumps(
                    {
                        "pid": process.pid,
                        "started_at": wall_started,
                        "deadline_unix": wall_started + timeout_s,
                        "model_deadline_unix": wall_started + timeout_s - cleanup_reserve,
                        "budget_s": timeout_s,
                    }
                ),
                encoding="utf-8",
            )
            process.wait(timeout=max(0.001, model_deadline - time.monotonic()))
            timed_out = time.monotonic() >= model_deadline
        except subprocess.TimeoutExpired:
            timed_out = True
        except BaseException as exc:
            error = {"type": type(exc).__name__, "message": str(exc)}
            if process is None:
                process = getattr(exc, "owned_process", None)
                cleanup = getattr(exc, "owned_cleanup", cleanup)
            if not isinstance(exc, OSError | subprocess.SubprocessError):
                unexpected = exc
        finally:
            if process is not None:
                cleanup = terminate_owned(
                    process, timeout_s=max(0.001, min(5.0, deadline - time.monotonic()))
                )
                if cleanup["status"] != "confirmed":
                    _UNCONFIRMED[str(output)] = process
    summary: dict[str, Any] = {
        "format": "pok.product-trial-phase.v1",
        "started_at": wall_started,
        "budget_s": timeout_s,
        "elapsed_s_including_cleanup": time.monotonic() - started,
        "timed_out": timed_out,
        "exit_code": process.returncode if process is not None else None,
        "cleanup": cleanup,
        "error": error,
        "answer_valid": False,
        "turn_completed": False,
        "build_quality_verified": False,
    }
    try:
        summary["session_id"] = session_from_events(output / "events.jsonl")
    except (ValueError, OSError) as exc:
        summary.update(session_id=None, session_error=str(exc))
    event_diagnostics: list[dict[str, Any]] = []
    try:
        for event in complete_events(output / "events.jsonl", event_diagnostics):
            if event.get("type") == "turn.completed":
                summary["turn_completed"] = True
    except (OSError, ValueError) as exc:
        summary["event_error"] = str(exc)
    summary["event_diagnostics"] = event_diagnostics
    answer = output / "answer.json"
    if answer.is_file():
        try:
            data = json.loads(answer.read_bytes())
            validate(data, schema)
            summary.update(
                answer_valid=True,
                answer_status=data.get("status") if isinstance(data, dict) else None,
            )
        except Exception as exc:
            summary["answer_error"] = {"type": type(exc).__name__, "message": str(exc)}
    summary["state"] = (
        "termination_unconfirmed"
        if cleanup["status"] != "confirmed"
        else "timed_out"
        if timed_out
        else "failed"
        if error
        or summary["exit_code"] != 0
        or not summary["answer_valid"]
        or not summary.get("session_id")
        or not summary["turn_completed"]
        or event_diagnostics
        or summary.get("event_error")
        else "completed"
    )
    summary["elapsed_s_including_collection"] = time.monotonic() - started
    (output / "execution.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    if unexpected is not None:
        raise unexpected
    return summary
