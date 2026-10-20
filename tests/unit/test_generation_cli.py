"""Adapter tests use a fake provider/client; no model or real game queries."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cli = load("generation_cli_test_subject", ROOT / "skills/build-generation/run.py")
session = load("generation_session_cli_test", ROOT / "skills/build-generation/session.py")


def args(tmp_path, extra=()):
    (tmp_path / "brief.txt").write_text("새 컨셉의 운용 목표", encoding="utf-8")
    (tmp_path / "method.txt").write_text("구조가 다른 구성을 비교한다.", encoding="utf-8")
    (tmp_path / "evidence.json").write_text('{"source": "fixture"}', encoding="utf-8")
    return cli.parser().parse_args(
        [
            "--brief",
            str(tmp_path / "brief.txt"),
            "--evidence",
            str(tmp_path / "evidence.json"),
            "--method",
            str(tmp_path / "method.txt"),
            "--out",
            str(tmp_path / "output"),
            "--model",
            "explicit-model",
            "--reasoning-effort",
            "high",
            "--allowed-tool",
            "search_kb",
            *extra,
        ]
    )


class Tool:
    name = "search_kb"

    def model_dump(self, mode):
        assert mode == "json"
        return {"name": self.name, "description": "fixture", "inputSchema": {"type": "object"}}


def response(data, error=False):
    return SimpleNamespace(is_error=error, data=data, content=[])


class FakeClient:
    def __init__(self, *, info_error=False):
        self.calls = []
        self.closed = False
        self.info_error = info_error

    async def __aenter__(self):
        return self

    async def __aexit__(self, *unused):
        self.closed = True

    async def list_tools(self):
        return [Tool()]

    async def call_tool(self, name, arguments, *, raise_on_error):
        assert raise_on_error is False
        self.calls.append((name, arguments))
        if name == "server_info":
            return response({"fixture": True}, self.info_error)
        return response({"hits": [], "unknown": None})


class FakeRuntime:
    def __init__(self, success=True):
        self.calls = []
        self.success = success

    def run_codex(self, prompt, schema, outdir, timeout_s, **kwargs):
        self.calls.append((prompt, schema, outdir, timeout_s, kwargs))
        context = json.loads(prompt)
        stage = context["stage"]
        answer = {
            "report": f"단계 {stage} 설계 초안",
            "candidates": [
                {
                    "id": "candidate-a",
                    "label": "구성 A",
                    "status": "selected" if stage == 3 else "retained",
                    "components": ["fixture"],
                    "evidence_ids": ["fixture"],
                    "public_decision_reason": "사용자 목표와 조건을 비교한 결과",
                }
            ],
            "selection": "candidate-a" if stage == 3 else "",
            "tool_requests": [
                {"tool": "search_kb", "arguments_json": '{"query":"fixture"}', "purpose": "확인"}
            ]
            if stage < 3
            else [],
        }
        outdir.mkdir(parents=True)
        (outdir / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
        return {"runtime_checks_passed": self.success, "usage": {"total": 123}}


def test_required_model_and_effort():
    with pytest.raises(SystemExit):
        cli.parser().parse_args([])


def test_default_method_keeps_provider_settings_explicit():
    arguments = [
        "--brief",
        "brief.txt",
        "--evidence",
        "evidence.json",
        "--out",
        "new-output",
        "--model",
        "caller-selected-model",
        "--reasoning-effort",
        "medium",
    ]
    options = cli.parser().parse_args(arguments)
    assert options.method == ROOT / "skills/build-generation/discovery.md"
    assert options.model == "caller-selected-model"
    assert options.reasoning_effort == "medium"
    assert options.lookup_mode == "search-and-read"
    with pytest.raises(SystemExit):
        cli.parser().parse_args(arguments[:-4] + arguments[-2:])
    with pytest.raises(SystemExit):
        cli.parser().parse_args(arguments[:-2])


def test_full_adapter_preserves_inputs_calls_and_handoff(tmp_path):
    options = args(tmp_path)
    client = FakeClient()
    provider = FakeRuntime()
    summary = asyncio.run(
        cli.run(
            options,
            session_module=session,
            runtime_module=provider,
            client_factory=lambda: client,
        )
    )
    assert summary["status"] == "complete"
    assert summary["assembly_ready"] is False
    assert summary["recommendation_ready"] is False
    assert summary["source_freshness"] == "unknown"
    assert client.closed is True
    assert len(provider.calls) == 3
    assert [call[0] for call in client.calls] == ["server_info", "search_kb", "search_kb"]
    for prompt, _, _, timeout_s, settings in provider.calls:
        assert timeout_s <= 600
        assert settings["model"] == "explicit-model"
        assert settings["reasoning_effort"] == "high"
        assert json.loads(prompt)["initial_evidence"] == {"source": "fixture"}
    manifest = json.loads((options.out / "cli-manifest.json").read_text(encoding="utf-8"))
    assert (
        manifest["input_sha256"]["brief.txt"]
        == hashlib.sha256(options.brief.read_bytes()).hexdigest()
    )
    assert (options.out / "brief.txt").read_bytes() == options.brief.read_bytes()
    handoff = json.loads((options.out / "handoff.json").read_text(encoding="utf-8"))
    assert handoff["selected_candidate_id"] == "candidate-a"
    assert handoff["semantic_quality_verified"] is False
    assert "build_spec and optimization_contract" in handoff["not_produced"]
    raw = json.loads((options.out / "session/stage-1/queries/00.json").read_text(encoding="utf-8"))
    assert raw["raw_response"]["result"]["unknown"] is None
    context = json.loads(provider.calls[1][0])
    assert context["public_history"][-1]["kind"] == "tool_result"


def test_provider_success_is_not_inferred_from_other_keys(tmp_path):
    options = args(tmp_path)
    provider = FakeRuntime(success=False)
    summary = asyncio.run(
        cli.run(
            options,
            session_module=session,
            runtime_module=provider,
            client_factory=FakeClient,
        )
    )
    assert summary["status"] == "incomplete"
    assert len(provider.calls) == 1
    assert not (options.out / "design-draft.json").exists()


def test_mutating_tool_refused_before_output_or_mcp(tmp_path):
    options = args(tmp_path, ("--allowed-tool", "store_insight"))
    with pytest.raises(ValueError, match="not approved"):
        asyncio.run(cli.run(options, session_module=session, runtime_module=FakeRuntime()))
    assert not options.out.exists()


def test_existing_output_refused_even_empty(tmp_path):
    options = args(tmp_path)
    options.out.mkdir()
    with pytest.raises(FileExistsError):
        asyncio.run(cli.run(options, session_module=session, runtime_module=FakeRuntime()))


def test_invalid_evidence_fails_before_output_or_mcp(tmp_path):
    options = args(tmp_path)
    options.evidence.write_text("bad json", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        asyncio.run(cli.run(options, session_module=session, runtime_module=FakeRuntime()))
    assert not options.out.exists()


def test_missing_tool_catalog_stops_before_model(tmp_path):
    options = args(tmp_path, ("--allowed-tool", "get_entry"))
    provider = FakeRuntime()
    client = FakeClient()
    with pytest.raises(ValueError, match="registered read tools missing"):
        asyncio.run(
            cli.run(
                options,
                session_module=session,
                runtime_module=provider,
                client_factory=lambda: client,
            )
        )
    assert not provider.calls
    assert client.closed
    summary = json.loads((options.out / "cli-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert (options.out / "catalog.json").is_file()


def test_server_info_error_is_preserved_and_stops_model(tmp_path):
    options = args(tmp_path)
    provider = FakeRuntime()
    client = FakeClient(info_error=True)
    with pytest.raises(RuntimeError, match="server_info returned an error"):
        asyncio.run(
            cli.run(
                options,
                session_module=session,
                runtime_module=provider,
                client_factory=lambda: client,
            )
        )
    assert not provider.calls
    assert client.closed
    raw = json.loads((options.out / "server-info.json").read_text(encoding="utf-8"))
    assert raw == {"is_error": True, "result": {"fixture": True}, "content": []}


def test_stale_loaded_server_stops_before_any_model_call(tmp_path):
    class StaleClient(FakeClient):
        async def call_tool(self, name, arguments, *, raise_on_error):
            assert name == "server_info"
            return response(
                {"stale": True, "loaded_commit": "old-fixture", "source_commit": "new-fixture"}
            )

    options = args(tmp_path)
    provider = FakeRuntime()
    client = StaleClient()
    with pytest.raises(RuntimeError, match="loaded code is stale"):
        asyncio.run(
            cli.run(
                options,
                session_module=session,
                runtime_module=provider,
                client_factory=lambda: client,
            )
        )
    assert provider.calls == []
    assert client.closed
    summary = json.loads((options.out / "cli-summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "failed"
    assert summary["source_freshness"] == "stale"
    original = json.loads((options.out / "server-info.json").read_text(encoding="utf-8"))
    assert original["result"]["stale"] is True


def test_null_structured_result_and_content_remain_distinct():
    block = SimpleNamespace(model_dump=lambda **unused: {"type": "text", "text": "unknown"})
    raw = cli.response_envelope(SimpleNamespace(is_error=False, data=None, content=[block]))
    assert raw == {
        "is_error": False,
        "result": None,
        "content": [{"type": "text", "text": "unknown"}],
    }


def test_custom_schema_and_limits_are_preserved(tmp_path):
    options = args(tmp_path, ("--stage-candidates", "4", "--total-tool-requests", "1"))
    custom_schema = json.loads(json.dumps(session.OUTPUT_SCHEMA))
    custom_schema["properties"]["candidates"]["maxItems"] = 3
    options.schema = tmp_path / "custom-schema.json"
    options.schema.write_text(json.dumps(custom_schema), encoding="utf-8")
    provider = FakeRuntime()
    client = FakeClient()
    summary = asyncio.run(
        cli.run(
            options,
            session_module=session,
            runtime_module=provider,
            client_factory=lambda: client,
        )
    )
    assert summary["execution_status"] == "complete"
    assert len(client.calls) == 2  # metadata + one allowed model query
    assert provider.calls[0][1]["properties"]["candidates"]["maxItems"] == 3
    assert (options.out / "schema-input.json").read_bytes() == options.schema.read_bytes()


class SearchAndReadClient(FakeClient):
    async def list_tools(self):
        detail = Tool()
        detail.name = "get_entry"
        return [Tool(), detail]

    async def call_tool(self, name, arguments, *, raise_on_error):
        self.calls.append((name, arguments))
        assert raise_on_error is False
        if name == "search_kb":
            return response([{"id": "fixture-a", "name": "A"}])
        return response({"id": arguments.get("id"), "fixture": True})


class SearchAndReadRuntime(FakeRuntime):
    def run_codex(self, prompt, schema, outdir, timeout_s, **kwargs):
        result = super().run_codex(prompt, schema, outdir, timeout_s, **kwargs)
        answer_path = outdir / "answer.json"
        answer = json.loads(answer_path.read_text(encoding="utf-8"))
        if json.loads(prompt)["stage"] < 3:
            answer["tool_requests"] = [
                {
                    "tool": "search_and_read",
                    "arguments_json": json.dumps(
                        {"search_args": {"query": "fixture"}, "max_entries": 1}
                    ),
                    "purpose": "검색한 레코드 원문 확인",
                }
            ]
        answer_path.write_text(json.dumps(answer), encoding="utf-8")
        return result


def test_virtual_catalog_expands_only_to_real_budgeted_calls(tmp_path):
    options = args(tmp_path, ("--allowed-tool", "get_entry"))
    client = SearchAndReadClient()
    provider = SearchAndReadRuntime()
    summary = asyncio.run(
        cli.run(
            options,
            session_module=session,
            runtime_module=provider,
            client_factory=lambda: client,
        )
    )
    assert summary["execution_status"] == "complete"
    assert [call[0] for call in client.calls] == [
        "server_info",
        "search_kb",
        "get_entry",
        "search_kb",
        "get_entry",
    ]
    state = json.loads((options.out / "session/summary.json").read_text(encoding="utf-8"))
    assert state["reader_calls"] == state["tool_requests"] == 4
    assert state["operation_requests"] == 2
    assert {tool["name"] for tool in json.loads(provider.calls[0][0])["tool_catalog"]} == {
        "search_kb",
        "get_entry",
        "search_and_read",
    }
    assert client.calls[2][1] == {"id": "fixture-a", "include_narrative": True}


def test_plain_catalog_does_not_silently_enable_virtual_lookup(tmp_path):
    options = args(tmp_path, ("--allowed-tool", "get_entry", "--lookup-mode", "plain"))
    client = SearchAndReadClient()
    provider = SearchAndReadRuntime()
    summary = asyncio.run(
        cli.run(
            options,
            session_module=session,
            runtime_module=provider,
            client_factory=lambda: client,
        )
    )
    assert summary["execution_status"] == "complete"
    assert [call[0] for call in client.calls] == ["server_info"]
    assert {tool["name"] for tool in json.loads(provider.calls[0][0])["tool_catalog"]} == {
        "search_kb",
        "get_entry",
    }
    state = json.loads((options.out / "session/summary.json").read_text(encoding="utf-8"))
    assert state["operation_history"][0]["error"]["code"] == "operation_not_advertised"


def test_cli_first_sigint_reaches_sync_provider_before_it_finishes():
    # Use a separate Python process so a real SIGINT never reaches pytest. Its
    # only substituted dependency is run(): main() and asyncio.run() are real.
    # No Codex process, model, MCP, or network is involved.
    script = f"""
import argparse, asyncio, importlib.util, json, signal, threading, time
path = {str(ROOT / "skills/build-generation/run.py")!r}
spec = importlib.util.spec_from_file_location("generation_cli_sigint_probe", path)
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
previous = signal.getsignal(signal.SIGINT)
observed = {{"provider_interrupted": False, "provider_completed": False}}
async def scripted_run(_args):
    timer = threading.Timer(0.1, lambda: signal.raise_signal(signal.SIGINT))
    timer.start()
    try:
        deadline = time.monotonic() + 4
        try:
            while time.monotonic() < deadline:
                time.sleep(0.02)
            observed["provider_completed"] = True
        except KeyboardInterrupt:
            observed["provider_interrupted"] = True
            raise
        await asyncio.sleep(0)
        return {{"status": "complete"}}
    finally:
        timer.cancel()
        timer.join()
cli.run = scripted_run
cli.parser = lambda: argparse.ArgumentParser()
started = time.monotonic()
try:
    cli.main()
except KeyboardInterrupt:
    observed["elapsed_s"] = time.monotonic() - started
    observed["handler_restored"] = signal.getsignal(signal.SIGINT) is previous
    print(json.dumps(observed))
"""
    child = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=True,
    )
    result = json.loads(child.stdout)
    assert result["provider_interrupted"] is True
    assert result["provider_completed"] is False
    assert result["handler_restored"] is True
