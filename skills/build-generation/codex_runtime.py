"""Recorded, single-call Codex CLI provider for generation orchestration.

Importing this module starts no processes or model calls. The caller supplies the
model, effort, prompt, schema and budget, and owns all design decisions. Actual
query tools belong to an external broker: this provider only returns structured
model output and never executes requests contained in that output.

Feature settings request native-tool isolation; they do not prove the model's
tool schema. Recorded events and stderr detect observed violations. Missing
usage fields and unobserved tool exposure remain unknown. There are no retries.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[2]
REASONING_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"})
DISABLED_FEATURES = (
    "shell_tool",
    "apps",
    "plugins",
    "multi_agent",
    "multi_agent_v2",
    "memories",
    "skill_search",
    "skill_mcp_dependency_install",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "image_generation",
    "code_mode",
    "code_mode_host",
    "sleep_tool",
    "view_image",
    "goals",
    "workspace_dependencies",
)


def _dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def discover_skill_paths(repo_root: Path) -> list[Path]:
    """List SKILL.md paths in known repo/home roots without reading their contents.

    Plugin tools are disabled separately. This is not an assertion that these
    roots enumerate every skill surface a future CLI may support.
    """
    user_home = Path.home()
    codex_dir = Path(os.environ.get("CODEX_HOME") or user_home / ".codex")
    roots = (
        repo_root / ".agents/skills",
        repo_root / ".codex/skills",
        codex_dir / "skills",
        codex_dir / "skills/.system",
        user_home / ".agents/skills",
    )
    paths: set[Path] = set()
    for root in roots:
        if root.is_dir():
            paths.update(path.resolve() for path in root.glob("*/SKILL.md") if path.is_file())
    return sorted(paths, key=lambda path: path.as_posix())


def skill_disable_override(repo_root: Path) -> str:
    paths = discover_skill_paths(repo_root)
    return (
        "skills.config=["
        + ",".join(
            "{path=" + json.dumps(path.as_posix(), ensure_ascii=False) + ",enabled=false}"
            for path in paths
        )
        + "]"
    )


def _validate_model_settings(model: str, reasoning_effort: str) -> None:
    if not isinstance(model, str) or not model.strip() or model.startswith("-"):
        raise ValueError("model must be an explicit, nonempty model identifier")
    if any(ord(char) < 32 for char in model):
        raise ValueError("model must not contain control characters")
    if not isinstance(reasoning_effort, str) or reasoning_effort not in REASONING_EFFORTS:
        raise ValueError("reasoning_effort must be an explicit supported effort label")


def build_command(
    outdir: Path,
    *,
    model: str,
    reasoning_effort: str,
    cwd: Path,
    repo_root: Path | None = None,
    codex_exe: str | None = None,
) -> list[str]:
    """Build a fixed argument list; no arbitrary CLI/config overrides are accepted.

    Recognition by the CLI, account/model availability and actual tool exposure
    are separate runtime facts. This function only constructs arguments.
    """
    _validate_model_settings(model, reasoning_effort)
    binary: str | None
    if codex_exe and Path(codex_exe).is_file():
        binary = str(Path(codex_exe).resolve())
    else:
        binary = shutil.which(codex_exe or "codex")
    if not binary:
        raise FileNotFoundError("codex executable is unavailable")
    args = [
        str(binary),
        "--no-daemon",
        "exec",
        "--ignore-user-config",
        "--ephemeral",
        "--skip-git-repo-check",
        "--json",
        "--model",
        model,
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "-c",
        "model_reasoning_effort=" + json.dumps(reasoning_effort),
        "-c",
        "project_doc_max_bytes=0",
        "-c",
        'web_search="disabled"',
        "-c",
        "agents.enabled=false",
        "-c",
        skill_disable_override((repo_root or ROOT).resolve()),
    ]
    for feature in DISABLED_FEATURES:
        args.extend(["--disable", feature])
    args.extend(
        [
            "--output-schema",
            str(outdir / "schema.json"),
            "--output-last-message",
            str(outdir / "answer.json"),
            "-C",
            str(cwd),
            "-",
        ]
    )
    return args


def audit_events(path: Path) -> dict[str, Any]:
    """Audit recorded item types; this cannot certify absence from the tool schema."""
    events: Counter[str] = Counter()
    bad_items: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    usages: list[dict[str, Any]] = []
    thread_ids: list[str] = []
    allowed_events = {"thread.started", "turn.started", "turn.completed", "turn.failed", "error"}
    item_events = {"item.started", "item.updated", "item.completed"}
    for number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            errors.append({"line": number, "kind": "invalid_jsonl"})
            continue
        if not isinstance(event, dict):
            errors.append({"line": number, "kind": "event_not_object"})
            continue
        kind = event.get("type")
        events[str(kind)] += 1
        if kind == "thread.started":
            thread_ids.append(str(event.get("thread_id", "")))
        if kind == "turn.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                usages.append(usage)
            else:
                errors.append({"line": number, "kind": "missing_usage"})
        if kind in {"turn.failed", "error"}:
            errors.append({"line": number, "kind": kind})
        if kind in item_events:
            item = event.get("item")
            if not isinstance(item, dict):
                errors.append({"line": number, "kind": "missing_item"})
                continue
            item_type = item.get("type")
            if item_type == "error":
                message = item.get("message")
                notice = {"line": number, "kind": "item_error", "message": message}
                if isinstance(message, str) and message.startswith(
                    (
                        "Under-development features enabled:",
                        "Code Mode is unavailable because code-mode host is disabled.",
                    )
                ):
                    warnings.append(notice)
                else:
                    errors.append(notice)
            elif item_type not in {"agent_message", "reasoning"}:
                key = str(item.get("id", f"line:{number}"))
                row = bad_items.setdefault(
                    key,
                    {
                        "id": key,
                        "type": item_type,
                        "first_line": number,
                        "phases": [],
                    },
                )
                row["phases"].append(kind)
                for field in ("command", "server", "tool", "name"):
                    if field in item:
                        row[field] = item[field]
        elif kind not in allowed_events:
            errors.append({"line": number, "kind": "unknown_event_type", "type": kind})
    totals: dict[str, int | None] = {}
    for field in (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    ):
        values = [usage.get(field) for usage in usages]
        known = bool(values) and all(type(value) is int and value >= 0 for value in values)
        totals[field] = sum(cast(list[int], values)) if known else None
    complete = (
        events["turn.completed"] == 1
        and bool(usages)
        and all(
            totals[field] is not None
            for field in ("input_tokens", "cached_input_tokens", "output_tokens")
        )
    )
    return {
        "event_counts": dict(events),
        "thread_ids": thread_ids,
        "unauthorized_tool_items": list(bad_items.values()),
        "protocol_errors": errors,
        "protocol_warnings": warnings,
        "usage_raw": usages,
        "usage_totals": totals,
        "usage_complete": complete,
        "native_tool_policy": "disabled by configuration; recorded native execution items rejected",
        "tool_schema_absence_verified": False,
    }


def audit_stderr(path: Path) -> dict[str, Any]:
    """Keep failed native attempts separate from explicitly blocked discovery.

    A failed spawn is not a successful subagent result. Neither its error nor
    an empty log proves how many additional remote model requests occurred.
    """
    native_errors = []
    blocked_discovery = []
    other_diagnostics = []
    for number, raw in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
    ):
        line = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw)
        if "codex_core::tools::router" in line:
            row = {"line": number, "message": line}
            if "error=code-mode host is disabled" in line:
                blocked_discovery.append({**row, "kind": "blocked_code_host_discovery"})
            else:
                kind = (
                    "failed_collaboration_spawn"
                    if "collab spawn failed" in line
                    else "native_router_error"
                )
                native_errors.append({**row, "kind": kind})
        elif "collab spawn failed" in line or (
            "codex_core::tools::" in line and re.search(r"\b(?:WARN|ERROR)\b", line)
        ):
            native_errors.append({"line": number, "message": line, "kind": "native_tool_error"})
        elif re.search(r"\b(?:WARN|ERROR)\b", line):
            other_diagnostics.append({"line": number, "message": line})
    return {
        "native_stderr_errors": native_errors,
        "blocked_native_discovery_attempts": blocked_discovery,
        "other_stderr_diagnostics": other_diagnostics,
        "additional_model_calls": None,
        "stderr_scope": "failed attempts and diagnostics; successful extra execution not inferred",
    }


def _terminate_tree(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    """Terminate only the process spawned here and its children."""
    report: dict[str, Any] = {"pid": process.pid, "requested": process.poll() is None}
    if process.poll() is not None:
        return report
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                timeout=10,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            report["tree_termination_exit_code"] = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            report["tree_termination_error"] = type(exc).__name__
    else:
        import signal

        try:
            os.killpg(process.pid, signal.SIGKILL)
            report["process_group_terminated"] = True
        except ProcessLookupError:
            report["process_already_exited"] = True
    if process.poll() is None:
        process.kill()
    return report


def run_codex(
    prompt: str,
    schema: Mapping[str, Any] | str | Path,
    outdir: str | Path,
    timeout_s: float,
    *,
    model: str,
    reasoning_effort: str,
    repo_root: str | Path | None = None,
    cwd: str | Path | None = None,
    codex_exe: str | None = None,
    max_answer_chars: int | None = None,
) -> dict[str, Any]:
    """Run exactly one fresh exec; write evidence and return its summary.

    This function is the ONLY model-launching entry point. The caller must call
    it explicitly. No retries, authentication copying, or config mutation occur.
    """
    _validate_model_settings(model, reasoning_effort)
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be nonempty text")
    if (
        isinstance(timeout_s, bool)
        or not isinstance(timeout_s, int | float)
        or not math.isfinite(timeout_s)
        or timeout_s <= 0
    ):
        raise ValueError("timeout_s must be finite and positive")
    if max_answer_chars is not None and (
        type(max_answer_chars) is not int or max_answer_chars <= 0
    ):
        raise ValueError("max_answer_chars must be a positive integer")
    import jsonschema

    document = (
        dict(schema)
        if isinstance(schema, Mapping)
        else json.loads(Path(schema).read_text(encoding="utf-8-sig"))
    )
    validator_cls = jsonschema.validators.validator_for(document)
    validator_cls.check_schema(document)
    out = Path(outdir).resolve()
    if out.exists():
        raise FileExistsError(f"Refusing to reuse existing runtime evidence directory: {out}")
    workdir = Path(cwd).resolve() if cwd is not None else out
    if cwd is not None and not workdir.is_dir():
        raise NotADirectoryError(workdir)
    args = build_command(
        out,
        model=model,
        reasoning_effort=reasoning_effort,
        cwd=workdir,
        repo_root=Path(repo_root) if repo_root is not None else None,
        codex_exe=codex_exe,
    )
    cli_sha256 = _sha(Path(args[0]).read_bytes())
    out.mkdir(parents=True, exist_ok=False)
    prompt_bytes = prompt.encode("utf-8")
    (out / "prompt.txt").write_bytes(prompt_bytes)
    _dump(out / "schema.json", document)
    _dump(out / "command.json", args)
    started = datetime.now(UTC).isoformat()
    request = {
        "started_at": started,
        "model": model,
        "reasoning_effort": reasoning_effort,
        "timeout_s": timeout_s,
        "max_answer_chars": max_answer_chars,
        "cwd": str(workdir),
        "prompt_sha256": _sha(prompt_bytes),
        "schema_sha256": _sha((out / "schema.json").read_bytes()),
        "runtime_sha256": _sha(Path(__file__).read_bytes()),
        "cli_sha256": cli_sha256,
        "max_exec_processes": 1,
        "native_tool_budget": 0,
        "token_hard_cap": None,
        "auth_copied_or_read_by_provider": False,
        "tool_execution_owner": "external broker; provider does not execute model JSON requests",
        "timeout_scope": "process communicate timeout; cleanup can extend elapsed wall time",
        "max_exec_processes_scope": (
            "provider-launched CLI processes, not a verified remote model-call count"
        ),
    }
    _dump(out / "request.json", request)
    t0 = time.monotonic()
    timeout = False
    launch_error = None
    cleanup: dict[str, Any] | None = None
    interruption: KeyboardInterrupt | None = None
    process = None
    with (out / "events.jsonl").open("wb") as stdout, (out / "stderr.txt").open("wb") as stderr:
        try:
            process = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=stdout,
                stderr=stderr,
                cwd=workdir,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=os.name != "nt",
            )
            try:
                process.communicate(prompt_bytes, timeout=timeout_s)
            except subprocess.TimeoutExpired:
                timeout = True
                cleanup = _terminate_tree(process)
                process.communicate(timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            launch_error = {"type": type(exc).__name__, "message": str(exc)}
            if process is not None and process.poll() is None:
                cleanup = _terminate_tree(process)
        except KeyboardInterrupt as exc:
            # A user interruption must stop the provider-owned process just as a
            # timeout does. Preserve the partial evidence before re-raising so
            # the caller can report interruption without leaving a model running.
            interruption = exc
            if process is not None:
                try:
                    cleanup = _terminate_tree(process)
                except (OSError, subprocess.SubprocessError) as cleanup_exc:
                    cleanup = {
                        "pid": process.pid,
                        "termination_error": {
                            "type": type(cleanup_exc).__name__,
                            "message": str(cleanup_exc),
                        },
                    }
                try:
                    process.communicate(timeout=10)
                except (OSError, subprocess.SubprocessError) as cleanup_exc:
                    cleanup["reap_error"] = {
                        "type": type(cleanup_exc).__name__,
                        "message": str(cleanup_exc),
                    }
    elapsed = time.monotonic() - t0
    audit = audit_events(out / "events.jsonl")
    audit.update(audit_stderr(out / "stderr.txt"))
    answer_path = out / "answer.json"
    answer_valid = False
    answer_error = None
    answer_chars = None
    if answer_path.is_file():
        try:
            answer_text = answer_path.read_text(encoding="utf-8-sig")
            answer_chars = len(answer_text)
            answer = json.loads(answer_text)
            validator_cls(document).validate(answer)
            answer_valid = True
        except (OSError, UnicodeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
            answer_error = {"type": type(exc).__name__, "message": str(exc)}
    else:
        answer_error = {"type": "missing_answer"}
    violations = []
    if audit["unauthorized_tool_items"]:
        violations.append("unauthorized_native_tool_event")
    if audit["native_stderr_errors"]:
        violations.append("native_tool_stderr_error")
    if audit["protocol_errors"]:
        violations.append("event_protocol_error")
    if (
        max_answer_chars is not None
        and answer_chars is not None
        and answer_chars > max_answer_chars
    ):
        violations.append("answer_size_exceeded")
    code = process.returncode if process is not None else None
    status = (
        "interrupted"
        if interruption is not None
        else "invalid"
        if violations
        else "timeout"
        if timeout
        else "failed"
        if launch_error or code != 0
        else "incomplete"
        if not answer_valid or not audit["usage_complete"]
        else "completed"
    )
    summary = {
        **request,
        "ended_at": datetime.now(UTC).isoformat(),
        "wall_seconds": elapsed,
        "status": status,
        "runtime_checks_passed": status == "completed",
        "exit_code": code,
        "timeout": timeout,
        "launch_error": launch_error,
        "interruption": (
            {"type": type(interruption).__name__, "message": str(interruption)}
            if interruption is not None
            else None
        ),
        "cleanup": cleanup,
        "answer_valid": answer_valid,
        "answer_error": answer_error,
        "answer_chars": answer_chars,
        "violations": violations,
        **audit,
        "files": {
            name: str(out / name)
            for name in (
                "request.json",
                "command.json",
                "prompt.txt",
                "schema.json",
                "events.jsonl",
                "stderr.txt",
                "answer.json",
                "usage.json",
                "summary.json",
            )
        },
    }
    _dump(
        out / "usage.json",
        {
            "complete": audit["usage_complete"],
            "raw": audit["usage_raw"],
            "totals": audit["usage_totals"],
            "no_double_counting_cached_or_reasoning": True,
        },
    )
    _dump(out / "summary.json", summary)
    if interruption is not None:
        raise interruption
    return summary
