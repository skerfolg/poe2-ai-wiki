"""One independently recorded native F/O/P run, without fixed design stages."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
P_REFERENCES = (
    "skills/build-assembly/AGENTS.md",
    "skills/AGENTS.md",
    "docs/BUILD_DESIGN.md",
)
ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["complete", "incomplete"]},
        "build_id": {"type": "string"},
        "pob_code": {"type": "string"},
        "report_markdown": {"type": "string"},
        "remaining_work": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "build_id", "pob_code", "report_markdown", "remaining_work"],
    "additionalProperties": False,
}


def audit_native_events(rows: list[dict[str, Any]], allowed: set[str]) -> dict[str, Any]:
    """Distinguish tool execution, model completion and a good build."""
    violations, failures, calls, warnings = [], [], [], []
    usage = []
    finished = False
    for row in rows:
        if row.get("type") in {"error", "turn.failed"}:
            failures.append(row)
        if row.get("type") == "turn.completed":
            finished = True
            usage.append(row.get("usage"))
        if row.get("type") != "item.completed":
            continue
        item = row.get("item", {})
        kind = item.get("type")
        if kind == "mcp_tool_call":
            calls.append(item)
            if item.get("server") != "pok" or item.get("tool") not in allowed:
                violations.append(item)
        elif kind == "error":
            if str(item.get("message", "")).startswith("Under-development features enabled:"):
                warnings.append(item)
            else:
                failures.append(item)
        elif kind not in {"agent_message", "reasoning"}:
            violations.append(item)
    return {
        "turn_completed": finished,
        "protocol_violations": violations,
        "execution_failures": failures,
        "mcp_call_failures": [
            call for call in calls if call.get("status") == "failed" or call.get("error")
        ],
        "warnings": warnings,
        "mcp_calls": calls,
        "usage_raw": usage,
        "build_quality_verified": False,
    }


def check_frozen_inputs(manifest: dict[str, Any], root: Path) -> list[str]:
    changed = []
    for relative, expected in manifest["files"].items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError("Frozen input path escapes the repository")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            changed.append(relative)
    for name, binary in manifest.get("executables", {}).items():
        executable = Path(binary["path"])
        if (
            not executable.is_file()
            or hashlib.sha256(executable.read_bytes()).hexdigest() != binary["sha256"]
        ):
            changed.append("executable:" + name)
    return changed


def load_runtime() -> Any:
    spec = importlib.util.spec_from_file_location(
        "recorded_native_runtime", ROOT / "skills/build-generation/codex_runtime.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def copy_frozen_inputs(
    source: Path, destination: Path, manifest: dict[str, Any], root: Path
) -> dict[str, str]:
    """Copy a common fixture only after every file passes the frozen manifest."""
    root = root.resolve()
    source = source.absolute()
    if not source.is_relative_to(root / "artifacts") or not source.is_dir():
        raise ValueError("Fixture directory must be inside repository artifacts")
    pending = []
    for path in [source, *source.rglob("*")]:
        if path.is_symlink() or path.resolve() != path:
            raise ValueError("Fixture paths must not contain symbolic links")
        if path.is_dir():
            continue
        manifest_key = path.relative_to(root).as_posix()
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if manifest["files"].get(manifest_key) != digest:
            raise ValueError(f"Fixture file is not frozen or has changed: {manifest_key}")
        pending.append((path.relative_to(source), data, digest))
    if destination.exists():
        raise ValueError("Fixture destination must be fresh")
    destination.mkdir(parents=True)
    for relative, data, _ in pending:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return {relative.as_posix(): digest for relative, _, digest in pending}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["F", "O", "P", "R"], required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--frozen-inputs", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path)
    parser.add_argument("--codex-exe", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--timeout", type=float, default=5400)
    args = parser.parse_args()
    if not 0 < args.timeout <= 5400:
        raise ValueError("Expected an explicit wall-clock budget up to 5400 seconds")
    out = args.out.resolve()
    if not out.is_relative_to(ROOT / "artifacts") or out.exists():
        raise ValueError("Use a fresh run directory inside artifacts")
    frozen = json.loads(args.frozen_inputs.read_text(encoding="utf-8"))
    changed = check_frozen_inputs(frozen, ROOT)
    if changed:
        raise ValueError(f"Inputs changed before launch: {changed}")
    prompt_path = args.prompt.resolve()
    if (
        not prompt_path.is_relative_to(ROOT)
        or prompt_path.relative_to(ROOT).as_posix() not in frozen["files"]
    ):
        raise ValueError("Prompt must be included in the frozen input manifest")
    # Startup, prompt handoff and all model/tool work share one deadline.
    started = time.monotonic()
    runtime = load_runtime()
    executables = frozen.get("executables", {})
    if (
        "codex" in executables
        and Path(args.codex_exe).resolve() != Path(executables["codex"]["path"]).resolve()
    ):
        raise ValueError("CLI executable differs from the frozen input")
    command = runtime.build_native_command(
        out,
        model=args.model,
        reasoning_effort=args.effort,
        cwd=out,
        repo_root=ROOT,
        arm=args.arm,
        server_run_dir=out / "server",
        codex_exe=args.codex_exe,
        luajit_exe=executables.get("luajit", {}).get("path"),
    )
    out.mkdir(parents=True)
    prompt = args.prompt.read_bytes()
    (out / "prompt.txt").write_bytes(prompt)
    (out / "schema.json").write_text(json.dumps(ANSWER_SCHEMA), encoding="utf-8")
    (out / "command.json").write_text(json.dumps(command, indent=2), encoding="utf-8")
    (out / "frozen-inputs.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    if args.input_dir is not None:
        copied = copy_frozen_inputs(args.input_dir, out / "server/artifacts/inputs", frozen, ROOT)
        (out / "copied-inputs.json").write_text(json.dumps(copied, indent=2), encoding="utf-8")
    if args.arm == "P":
        for reference in P_REFERENCES:
            if reference not in frozen["files"]:
                raise ValueError(f"P reference must be frozen: {reference}")
        for reference in P_REFERENCES:
            destination = out / "server/artifacts/reference" / reference
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((ROOT / reference).read_bytes())
    timed_out = False
    process: subprocess.Popen[bytes] | None = None
    launch_error = None
    cleanup = None
    with (out / "events.jsonl").open("wb") as events, (out / "stderr.txt").open("wb") as errors:
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=events,
                stderr=errors,
                cwd=out,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                start_new_session=os.name != "nt",
            )
            (out / "process.json").write_text(
                json.dumps(
                    {"pid": process.pid, "started_at": time.time(), "budget_s": args.timeout}
                ),
                encoding="utf-8",
            )
            process.communicate(
                prompt, timeout=max(0.1, args.timeout - (time.monotonic() - started))
            )
        except subprocess.TimeoutExpired:
            timed_out = True
            if process is not None:
                cleanup = runtime._terminate_tree(process)
                process.communicate(timeout=10)
        except (OSError, subprocess.SubprocessError) as exc:
            launch_error = {"type": type(exc).__name__, "message": str(exc)}
            if process is not None and process.poll() is None:
                cleanup = runtime._terminate_tree(process)
    rows, malformed = [], []
    for number, line in enumerate(
        (out / "events.jsonl").read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            malformed.append(number)
        else:
            if isinstance(row, dict):
                rows.append(row)
            else:
                malformed.append(number)
    policy_file = out / "server/server-policy.json"
    policy = json.loads(policy_file.read_text(encoding="utf-8")) if policy_file.exists() else {}
    summary = audit_native_events(rows, set(policy.get("tools", [])))
    summary.update(
        {
            "arm": args.arm,
            "model": args.model,
            "effort": args.effort,
            "exit_code": process.returncode if process is not None else None,
            "timeout": timed_out,
            "elapsed_s": time.monotonic() - started,
            "changed_inputs_after_run": check_frozen_inputs(frozen, ROOT),
            "server_policy": policy,
            "answer_exists": (out / "answer.json").exists(),
            "sample_status": "not_yet_evaluated",
            "launch_error": launch_error,
            "cleanup": cleanup,
            "malformed_event_lines": malformed,
        }
    )
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: summary[key] for key in ("arm", "exit_code", "timeout", "elapsed_s")}))


if __name__ == "__main__":
    main()
