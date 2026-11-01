"""A mechanism change can invalidate an old anchor and replace the whole supplied tree.

Small explicit alternatives, not an optimized level-100 build or model-quality eval.
"""

import asyncio
from copy import deepcopy

import pytest
from fastmcp import Client, FastMCP

from pok.artifacts import tool_results
from pok.common.paths import knowledge_dir
from pok.engine.execution_requests import RequestManager
from pok.engine.procedures import attribute_choice_nodes
from pok.engine.tree.graph import TreeGraph
from pok.mcp import server
from pok.mcp.tools import build
from pok.pob.versions import find_luajit, resolve_snapshot


def _ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _ready(), reason="LuaJIT or pinned PoB unavailable")


def test_critical_anchor_reopens_after_critical_hits_are_disabled(tmp_path, monkeypatch):
    graph = TreeGraph(knowledge_dir())
    old_nodes, _ = graph.connect_anchors("Sorceress", [61601], ascendancy="Sorceress1")
    new_nodes, _ = graph.connect_anchors("Sorceress", [51184], ascendancy="Sorceress1")
    choices = attribute_choice_nodes()

    def assign(spec, nodes):
        spec["tree_nodes"] = list(nodes)
        spec["attribute_choices"] = {str(node): "int" for node in nodes if node in choices}

    base = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 100,
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
    assign(base, old_nodes)
    changed = deepcopy(base)
    changed["skills"][0]["gems"].append(
        {
            "gem_id": "Metadata/Items/Gems/SkillGemControlledDestructionSupport",
            "name": "Controlled Destruction",
            "level": 1,
        }
    )
    without_dead_anchor = deepcopy(changed)
    assign(without_dead_anchor, [node for node in old_nodes if node != 61601])
    replacement = deepcopy(changed)
    assign(replacement, new_nodes)
    original = deepcopy(base)
    api = FastMCP("mechanism-tree-replacement")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", RequestManager())
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    server.tool(build.evaluate_delta)

    async def run():
        async with Client(api) as client:
            response = await client.call_tool(
                "evaluate_delta",
                {
                    "base_spec": base,
                    "variants": {
                        "mechanism_only": changed,
                        "remove_dead_anchor": without_dead_anchor,
                        "whole_tree_replacement": replacement,
                    },
                    "stats": ["CombinedDPS", "CritChance", "Life"],
                },
            )
            assert not response.is_error
            data = response.structured_content
            if set(data) == {"result"}:
                data = data["result"]
            payload, _ = tool_results.load_result(data["measurement_ref"]["$pok_result"])
            result = payload["result"]
            assert result["comparison"]["measurements_complete"], result["comparison"]
            assert result["base"]["stats"]["CritChance"] > 0
            variants = result["variants"]
            assert all(value["stats"]["CritChance"] == 0 for value in variants.values())
            assert variants["mechanism_only"]["stats"]["CombinedDPS"] == pytest.approx(
                variants["remove_dead_anchor"]["stats"]["CombinedDPS"]
            )
            assert (
                61601 not in payload["inputs"]["variants"]["whole_tree_replacement"]["tree_nodes"]
            )
            assert set(
                payload["inputs"]["variants"]["whole_tree_replacement"]["tree_nodes"]
            ) == set(new_nodes)
            assert len(new_nodes) < len(old_nodes)
            assert variants["whole_tree_replacement"]["stats"]["CombinedDPS"] > 0
            assert base == original

    asyncio.run(run())
