"""Real PoK retrieval reaches the next design stage; no network/model/PoB.

The scripted provider tests evidence transport, not design quality. The source
is the registered in-process MCP server and its actual committed KB records.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MECHANIC_ID = "mechanic.crossbow-ammunition-skills"


def load_cli():
    path = ROOT / "skills/build-generation/run.py"
    spec = importlib.util.spec_from_file_location("generation_discovery_integration_cli", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def retrieved_stats(context):
    for row in context["public_history"]:
        if row["kind"] != "tool_result":
            continue
        value = row["value"]
        if value.get("truncated"):
            continue
        result = value.get("raw_response", {}).get("result")
        if isinstance(result, dict) and result.get("id") == MECHANIC_ID:
            stats = result.get("data", {}).get("stats")
            if stats:
                return stats
    return None


class ScriptedProvider:
    def __init__(self, mode):
        self.mode = mode
        self.contexts = []

    def run_codex(self, prompt, schema, outdir, timeout_s, **settings):
        context = json.loads(prompt)
        self.contexts.append(context)
        assert settings["model"] == "scripted-provider-no-model-call"
        stage = context["stage"]
        requests = []
        if stage == 1:
            search_args = {"query": "crossbow ammunition", "type": "Mechanic", "limit": 3}
            arguments = (
                {"search_args": search_args, "max_entries": 1, "fields": ["id", "data"]}
                if self.mode == "search-and-read"
                else search_args
            )
            requests = [
                {
                    "tool": "search_and_read" if self.mode == "search-and-read" else "search_kb",
                    "arguments_json": json.dumps(arguments),
                    "purpose": "Transport regression: fetch the full ammunition rule.",
                }
            ]
        elif stage == 2 and self.mode == "plain":
            hits = next(
                row["value"]["raw_response"]["result"]
                for row in context["public_history"]
                if row["kind"] == "tool_result"
            )
            assert hits[0]["id"] == MECHANIC_ID
            requests = [
                {
                    "tool": "get_entry",
                    "arguments_json": json.dumps({"id": hits[0]["id"], "fields": ["id", "data"]}),
                    "purpose": "Transport regression: read the record found in stage one.",
                }
            ]
        answer = {
            "report": "조회 전달 시험용 응답이며 빌드 추천이 아니다.",
            "candidates": [
                {
                    "id": "transport-fixture",
                    "label": "조회 전달 시험",
                    "status": "selected" if stage == 3 else "retained",
                    "components": [MECHANIC_ID],
                    "evidence_ids": [MECHANIC_ID],
                    "public_decision_reason": "원문 도착 단계와 실제 호출 수를 확인한다.",
                }
            ],
            "selection": "transport-fixture" if stage == 3 else "",
            "tool_requests": requests,
        }
        outdir.mkdir()
        (outdir / "answer.json").write_text(json.dumps(answer), encoding="utf-8")
        return {"runtime_checks_passed": True, "scripted_provider": True}


@pytest.mark.parametrize("mode", ["search-and-read", "plain"])
def test_real_mcp_search_detail_arrives_in_the_expected_stage(tmp_path, mode):
    cli = load_cli()
    session, _unused_real_provider = cli._modules()
    (tmp_path / "brief.txt").write_text("석궁 탄약 규칙의 조회 전달 시험", encoding="utf-8")
    (tmp_path / "method.txt").write_text("실제 MCP 응답 전달만 시험한다.", encoding="utf-8")
    (tmp_path / "evidence.json").write_text('{"records":[]}', encoding="utf-8")
    args = cli.parser().parse_args(
        [
            "--brief",
            str(tmp_path / "brief.txt"),
            "--evidence",
            str(tmp_path / "evidence.json"),
            "--method",
            str(tmp_path / "method.txt"),
            "--out",
            str(tmp_path / "run"),
            "--model",
            "scripted-provider-no-model-call",
            "--reasoning-effort",
            "low",
            "--allowed-tool",
            "search_kb",
            "--allowed-tool",
            "get_entry",
            "--total-tool-requests",
            "2",
            "--stage-tool-requests",
            "2",
            "--lookup-mode",
            mode,
        ]
    )
    scripted = ScriptedProvider(mode)
    result = asyncio.run(cli.run(args, session_module=session, runtime_module=scripted))
    assert result["execution_status"] == "complete"
    assert result["assembly_ready"] is False
    assert result["recommendation_ready"] is False
    assert retrieved_stats(scripted.contexts[0]) is None
    second_stage_stats = retrieved_stats(scripted.contexts[1])
    assert (second_stage_stats is not None) == (mode == "search-and-read")
    final_stats = retrieved_stats(scripted.contexts[2])
    assert final_stats
    assert any("only load it into your Crossbow" in line for line in final_stats)
    state = json.loads((args.out / "session/summary.json").read_text(encoding="utf-8"))
    assert state["tool_requests"] == state["reader_calls"] == 2
    assert state["operation_requests"] == (1 if mode == "search-and-read" else 0)
    queries = sorted((args.out / "session").glob("stage-*/queries/*.json"))
    assert len(queries) == 2
    raw = [json.loads(path.read_text(encoding="utf-8")) for path in queries]
    assert [row["request"]["tool"] for row in raw] == ["search_kb", "get_entry"]
    assert all(row["reader_called"] and not row["is_error"] for row in raw)
