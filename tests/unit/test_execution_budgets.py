"""Declared native/search budgets and shorter caller limits agree at the MCP boundary."""

import asyncio

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from pok.engine.execution_requests import RequestManager
from pok.mcp import server
from pok.mcp.tools import tree


@pytest.mark.parametrize(
    "tool,expected",
    [
        ("compute_pob", 180),
        ("compute_pob_document", 180),
        ("optimize_tree", 300),
        ("optimize_items", 300),
        ("evaluate_bundles", 300),
        ("read_design_record", 600),
    ],
)
def test_default_budgets(tool, expected):
    assert server._execution_budget(tool, {}, {}) == expected


def test_explicit_search_budget_and_shorter_caller_win():
    assert server._execution_budget("optimize_tree", {}, {"time_budget_s": 1000}) == 1000
    assert (
        server._execution_budget("optimize_tree", {"timeout_s": 50}, {"time_budget_s": 1000}) == 50
    )
    assert server._execution_budget("optimize_tree", {"timeout_s": 1200}, {}) == 1200
    assert tree.optimize_tree.__defaults__[-1] == 300


@pytest.mark.parametrize("invalid", [True, 0, -1, float("inf"), float("nan"), 1201])
def test_invalid_or_over_limit_search_budget_is_rejected(invalid):
    with pytest.raises(ValueError):
        server._execution_budget("optimize_tree", {"timeout_s": invalid}, {})


def test_actual_mcp_profile_accepts_search_1200_but_rejects_native_over_180(monkeypatch):
    api = FastMCP("budget-profiles")
    manager = RequestManager()
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", manager)
    calls = []

    def optimize_rare() -> dict:
        calls.append("search")
        return {"value": 1}

    def compute_pob() -> dict:
        calls.append("native")
        return {"value": 1}

    server.tool(optimize_rare)
    server.tool(compute_pob)

    async def exercise():
        async with Client(api) as client:
            result = await client.call_tool(
                "optimize_rare", {}, meta={"pok_execution": {"timeout_s": 1200}}
            )
            assert manager.status(result.meta["pok_execution"])["timeout_s"] == 1200
            with pytest.raises(ToolError, match="at most 180"):
                await client.call_tool(
                    "compute_pob", {}, meta={"pok_execution": {"timeout_s": 181}}
                )
            assert calls == ["search"]

    asyncio.run(exercise())
