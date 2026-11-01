"""Actual MCP comparison receipts support explicit recommendation assembly."""

import asyncio
from copy import deepcopy

import pytest
from fastmcp import Client, FastMCP

from pok.artifacts import store, tool_results
from pok.engine.execution_requests import RequestManager
from pok.mcp import server
from pok.mcp.tools import build
from pok.pob import codec
from pok.pob.versions import find_luajit, resolve_snapshot


def _ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _ready(), reason="LuaJIT or pinned PoB unavailable")


def test_saved_mcp_comparison_can_assemble_without_optimizer_or_autofill(tmp_path, monkeypatch):
    api = FastMCP("comparison-recommendation")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", RequestManager())
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    monkeypatch.setattr(store, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    server.tool(build.evaluate_delta)
    server.tool(build.assemble_pob)
    base = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 90,
        "items": [
            {
                "slot": "Ring 1",
                "text": (
                    "Rarity: RARE\nExample\nGold Ring\nItem Level: 80\n"
                    "Implicits: 0\n+10 to maximum Life"
                ),
            }
        ],
        "skills": [
            {
                "gems": [
                    {
                        "gem_id": "Metadata/Items/Gems/SkillGemSpark",
                        "name": "Spark",
                        "level": 1,
                        "stat_set_index": 1,
                    }
                ]
            }
        ],
    }
    alternative = deepcopy(base)
    alternative["items"][0]["text"] = base["items"][0]["text"].replace("+10", "+20")

    async def run():
        async with Client(api) as client:
            measured = await client.call_tool(
                "evaluate_delta",
                {"base_spec": base, "variants": {"more_life": alternative}, "stats": ["Life"]},
            )
            assert not measured.is_error
            data = measured.data
            reference = data["measurement_ref"]
            payload, _ = tool_results.load_result(reference["$pok_result"])
            assert payload["result"]["comparison"]["measurements_complete"], payload["result"]
            chosen = deepcopy(alternative)
            chosen["optimization_contract"] = {
                "version": 2,
                "required_components": ["items"],
                "comparisons": [
                    {
                        "result_id": reference["$pok_result"],
                        "selected": "more_life",
                        "reason": "Higher measured life with the same skill and scenario",
                    }
                ],
            }
            assembled = await client.call_tool(
                "assemble_pob",
                {
                    "build_spec": chosen,
                    "slug": "comparison-native",
                    "purpose": "recommendation",
                    "input_policy": "explicit",
                    "stats": ["Life"],
                },
            )
            assert not assembled.is_error
            result = assembled.data
            if "result_ref" in result:
                result = tool_results.resolve_references(result["result_ref"])
            assert result["ok"], result
            assert result["optimization_readiness"]["version"] == 2
            assert result["optimization_readiness"]["recommendation_ready"]
            assert "+20 to maximum Life" in codec.decode(result["build_code"])
            assert "autofilled" not in result

    asyncio.run(run())
