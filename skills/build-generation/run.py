"""CLI connecting skill design orchestration, the Codex provider, and real PoK.

No experiment files, answers, scoring rules, or game-selection policy are loaded.
Importing this module performs no network, model, MCP, or filesystem writes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from types import FrameType
from typing import Any

SKILL_DIR = Path(__file__).resolve().parent
REPO_ROOT = SKILL_DIR.parents[1]


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _modules() -> tuple[Any, Any]:
    session = _load_module(
        "_pok_build_generation_session",
        SKILL_DIR / "session.py",
    )
    runtime = _load_module(
        "_pok_build_generation_codex_provider",
        SKILL_DIR / "codex_runtime.py",
    )
    return session, runtime


def _client_factory() -> Any:
    # Skill orchestration is above MCP. Engine modules do not import this file.
    from fastmcp import Client

    from pok.mcp.server import mcp

    return Client(mcp)


def _model_dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


def response_envelope(response: Any) -> dict[str, Any]:
    """Preserve structured values (including null) and original MCP content."""
    return {
        "is_error": bool(response.is_error),
        "result": response.data,
        "content": [_model_dump(block) for block in response.content],
    }


def make_generator(
    runtime: Any, args: argparse.Namespace
) -> Callable[[str, dict[str, Any], Path, float], dict[str, Any]]:
    """A synchronous adapter; the provider owns process-tree timeout cleanup."""

    def generate(
        prompt: str, schema: dict[str, Any], outdir: Path, timeout_s: float
    ) -> dict[str, Any]:
        result = runtime.run_codex(
            prompt,
            schema,
            outdir,
            timeout_s,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            repo_root=REPO_ROOT,
            codex_exe=args.codex_exe,
        )
        return {
            "execution_ok": result.get("runtime_checks_passed") is True,
            "provider": result,
            # The session reads answer.json from this provider output directory.
            # No provider success value is treated as semantic design validation.
        }

    return generate


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description=__doc__)
    command.add_argument("--brief", type=Path, required=True)
    command.add_argument("--evidence", type=Path, required=True)
    command.add_argument("--method", type=Path, default=SKILL_DIR / "discovery.md")
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--model", required=True)
    command.add_argument(
        "--reasoning-effort",
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"),
        required=True,
    )
    command.add_argument("--codex-exe")
    command.add_argument("--allowed-tool", action="append")
    command.add_argument(
        "--lookup-mode", choices=("search-and-read", "plain"), default="search-and-read"
    )
    command.add_argument("--schema", type=Path)
    command.add_argument("--total-timeout-s", type=float, default=1800)
    command.add_argument("--model-timeout-s", type=float, default=600)
    command.add_argument("--tool-timeout-s", type=float, default=90)
    command.add_argument("--total-tool-requests", type=int, default=12)
    command.add_argument("--stage-tool-requests", type=int, default=6)
    command.add_argument("--stage-candidates", type=int, default=12)
    command.add_argument("--public-result-chars", type=int, default=18000)
    return command


async def run(
    args: argparse.Namespace,
    *,
    session_module: Any = None,
    runtime_module: Any = None,
    client_factory: Any = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    if session_module is None or runtime_module is None:
        session_module, runtime_module = _modules()
    limits = session_module.Limits(
        total_timeout_s=args.total_timeout_s,
        model_timeout_s=args.model_timeout_s,
        tool_timeout_s=args.tool_timeout_s,
        total_tool_requests=args.total_tool_requests,
        stage_tool_requests=args.stage_tool_requests,
        stage_candidates=args.stage_candidates,
        public_result_chars=args.public_result_chars,
    )
    limits.validate()
    # Validate basic model input before creating any artifacts or opening MCP.
    if not args.model.strip() or args.model.startswith("-"):
        raise ValueError("model must be an explicit, nonempty model identifier")
    allowed = frozenset(args.allowed_tool or session_module.READ_TOOLS)
    if not allowed <= session_module.READ_TOOLS:
        raise ValueError(f"not approved read-query tools: {sorted(allowed)}")
    inputs = {
        "brief.txt": args.brief.read_bytes(),
        "evidence.json": args.evidence.read_bytes(),
        "method.txt": args.method.read_bytes(),
    }
    brief = inputs["brief.txt"].decode("utf-8-sig")
    method = inputs["method.txt"].decode("utf-8-sig")
    evidence = json.loads(inputs["evidence.json"].decode("utf-8-sig"))
    if not brief.strip() or not method.strip():
        raise ValueError("brief and method must both contain text")
    schema = None
    if args.schema is not None:
        inputs["schema-input.json"] = args.schema.read_bytes()
        schema = json.loads(inputs["schema-input.json"].decode("utf-8-sig"))
    output = args.out.resolve()
    # Never overwrite/reuse a partial run. Each invocation needs a new directory.
    output.mkdir(parents=True, exist_ok=False)
    started = clock()
    deadline = started + limits.total_timeout_s
    for name, content in inputs.items():
        (output / name).write_bytes(content)
    manifest = {
        "scope": "design_only",
        "model": args.model,
        "reasoning_effort": args.reasoning_effort,
        "limits": asdict(limits),
        "allowed_tools": sorted(allowed),
        "lookup_mode_requested": args.lookup_mode,
        "input_sha256": {
            name: hashlib.sha256(content).hexdigest() for name, content in inputs.items()
        },
        "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "automatic_retry": False,
        "token_hard_cap": None,
        "model_count_unit": "provider CLI sessions, not remote sampling calls",
        "clock_scope": "bootstrap plus design session; process cleanup may extend wall time",
        "bootstrap_query_accounting": (
            "server_info and list_tools are recorded metadata calls; "
            "they do not consume the model-requested query quota"
        ),
    }
    _write_json(output / "cli-manifest.json", manifest)
    client = None
    entered = False
    summary: dict[str, Any] = {
        "scope": "design_only",
        "status": "initializing",
        "assembly_ready": False,
        "recommendation_ready": False,
    }

    def remaining_timeout() -> float:
        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("session deadline exhausted during MCP bootstrap")
        return float(min(limits.tool_timeout_s, remaining))

    try:
        client = (client_factory or _client_factory)()
        await asyncio.wait_for(client.__aenter__(), remaining_timeout())
        entered = True
        tools = await asyncio.wait_for(client.list_tools(), remaining_timeout())
        catalog = [_model_dump(tool) for tool in tools if tool.name in allowed]
        actual = {row["name"] for row in catalog}
        if actual != allowed:
            _write_json(output / "catalog.json", catalog)
            raise ValueError(f"registered read tools missing: {sorted(allowed - actual)}")
        if args.lookup_mode == "search-and-read" and {"search_kb", "get_entry"} <= allowed:
            catalog.extend(session_module.VIRTUAL_TOOL_CATALOG)
        _write_json(output / "catalog.json", catalog)
        info = await asyncio.wait_for(
            client.call_tool("server_info", {}, raise_on_error=False), remaining_timeout()
        )
        info_envelope = response_envelope(info)
        _write_json(output / "server-info.json", info_envelope)
        if info_envelope["is_error"]:
            raise RuntimeError("server_info returned an error; see preserved response")
        source_state = info_envelope["result"]
        stale = source_state.get("stale") if isinstance(source_state, dict) else None
        summary["source_freshness"] = (
            "stale" if stale is True else "current" if stale is False else "unknown"
        )
        if stale is True:
            raise RuntimeError("MCP loaded code is stale; restart it before generation")

        async def reader(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
            # The session also checks this allowlist before consuming a query.
            if tool not in allowed:
                raise ValueError(f"tool is outside the fixed read surface: {tool}")
            response = await client.call_tool(tool, arguments, raise_on_error=False)
            return response_envelope(response)

        remaining = deadline - clock()
        if remaining <= 0:
            raise TimeoutError("session deadline exhausted before generation")
        effective_limits = replace(limits, total_timeout_s=remaining)
        _write_json(output / "effective-limits.json", asdict(effective_limits))
        state = await session_module.run_generation_session(
            prompt=json.dumps(
                {"user_brief": brief, "generation_method": method}, ensure_ascii=False
            ),
            generator=make_generator(runtime_module, args),
            reader=reader,
            outdir=output / "session",
            allowed_tools=allowed,
            initial_evidence=evidence,
            tool_catalog=catalog,
            limits=effective_limits,
            schema=schema,
        )
        summary.update(
            status=state["status"],
            execution_status=state["execution_status"],
            structure_status=state["structure_status"],
            selection_status=state["selection_status"],
            session_summary="session/summary.json",
            diagnostic_count=len(state["diagnostics"]),
        )
        final_answer = state.get("final_answer")
        if final_answer is not None:
            _write_json(output / "design-draft.json", final_answer)
            (output / "design-draft.md").write_text(final_answer["report"], encoding="utf-8")
        _write_json(
            output / "handoff.json",
            {
                "scope": "design_only",
                "assembly_ready": False,
                "recommendation_ready": False,
                "semantic_quality_verified": False,
                "draft": "design-draft.json" if final_answer is not None else None,
                "candidate_and_evidence_history": "session/summary.json",
                "selected_candidate_id": (
                    final_answer.get("selection") if final_answer is not None else None
                ),
                "not_produced": [
                    "build_spec and optimization_contract",
                    "constraint-ledger validation",
                    "PoB measurements and optimization evidence",
                    "assemble_pob recommendation validation",
                ],
            },
        )
    except BaseException as exc:
        summary.update(
            status="interrupted"
            if isinstance(exc, KeyboardInterrupt | asyncio.CancelledError)
            else "failed",
            error={"type": type(exc).__name__, "message": str(exc)},
        )
        raise
    finally:
        if client is not None and entered:
            try:
                await asyncio.wait_for(client.__aexit__(None, None, None), timeout=10)
            except Exception as exc:
                summary["client_cleanup_error"] = {
                    "type": type(exc).__name__,
                    "message": str(exc),
                }
        summary["elapsed_s"] = clock() - started
        _write_json(output / "cli-summary.json", summary)
    return summary


def _interrupt_provider(_signal: int, _frame: FrameType | None) -> None:
    """Deliver the first CLI interrupt to a running synchronous provider."""
    raise KeyboardInterrupt


def main() -> int:
    args = parser().parse_args()
    # asyncio.Runner normally turns the first SIGINT into task.cancel(). A
    # synchronous provider blocks that task, so cancellation would wait until its
    # model call finished. This distinct handler raises into the provider now,
    # letting its existing KeyboardInterrupt cleanup stop the owned process.
    previous_sigint = signal.signal(signal.SIGINT, _interrupt_provider)
    try:
        summary = asyncio.run(run(args))
    finally:
        signal.signal(signal.SIGINT, previous_sigint)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
