"""Stored design detail does not hide change/review counts or unchecked claims."""

import asyncio
import json

from fastmcp import Client, FastMCP

from pok.artifacts import tool_results
from pok.engine.execution_requests import RequestManager
from pok.mcp import server


def test_large_design_change_keeps_bounded_semantic_summary(monkeypatch, tmp_path):
    api = FastMCP("design-summary")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", RequestManager())
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    summary = {
        "changed_decision_count": 1,
        "review_required_count": 100,
        "diagnostic_count": 2,
        "checks": {"game_feasibility": "not_checked"},
    }
    result = {
        "record_json": "x" * 100000,
        "change_summary": summary,
        "changed_decision_ids": ["changed"],
        "review_required_ids": [str(i) for i in range(100)],
        "current_assessment": {"diagnostics": [{"code": "UNVERIFIED"}]},
    }

    def update_design_record() -> dict:
        return result

    server.tool(update_design_record)

    async def exercise():
        async with Client(api) as client:
            response = await client.call_tool("update_design_record", {})
            envelope = response.data
            assert envelope["stored_tool_result"] is True
            assert envelope["change_summary"] == summary
            assert len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) <= 8192
            payload, _ = tool_results.load_result(envelope["result_ref"]["$pok_result"])
            assert payload["result"] == result
            assert (
                envelope["change_details"]["review_required_ids"]["path"]
                == "/result/review_required_ids"
            )

    asyncio.run(exercise())
