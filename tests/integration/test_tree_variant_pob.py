"""Normal MCP branch edit -> actual PoB comparison -> exploration share code."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from mcp.types import CallToolResult

from pok.common.paths import knowledge_dir
from pok.engine.tree.graph import TreeGraph
from pok.pob import codec
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


def test_branch_variant_reaches_measurement_and_exploration_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pok.artifacts import store, tool_results
    from pok.mcp.server import mcp

    # These are the existing Spark/Raw Power/socket topology regression fixtures,
    # not a newly selected build or a claim of improved gameplay performance.
    graph = TreeGraph(knowledge_dir())
    allocated, _ = graph.connect_anchors("Sorceress", [51184, 61419], ascendancy="Sorceress1")
    base = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 100,
        "tree_nodes": allocated,
        "attribute_choices": {"18407": "int", "22419": "int"},
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
        "jewels": [
            {
                "socket_node_id": 61419,
                "text": (
                    "Rarity: RARE\nPok Jewel\nSapphire\nItem Level: 81\n"
                    "15% increased Spell Damage\n15% increased Critical Hit Chance for Spells"
                ),
            }
        ],
    }
    original = deepcopy(base)
    monkeypatch.setattr(store, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    result_refs = {}
    page_counts = {}

    async def raw_call(client: Client, name: str, arguments: dict[str, Any]):
        result = await client.call_tool(name, arguments)
        assert not result.is_error
        wire = CallToolResult(
            content=result.content,
            structured_content=result.structured_content,
            is_error=result.is_error,
            _meta=result.meta,
        ).model_dump_json(by_alias=True, exclude_none=True)
        assert len(wire.encode("utf-8")) <= 16000
        return result.data

    async def call(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        data = await raw_call(client, name, arguments)
        if not data.get("stored_tool_result"):
            return data
        reference = data["result_ref"]
        result_refs[name] = reference
        chunks, offset = [], 0
        while True:
            page = await raw_call(
                client,
                "get_tool_result",
                {
                    "result_id": reference["$pok_result"],
                    "path": reference["path"],
                    "mode": "json",
                    "offset": offset,
                },
            )
            chunks.append(page["chunk"])
            if page["next_offset"] is None:
                break
            assert page["next_offset"] > offset
            offset = page["next_offset"]
        page_counts[name] = len(chunks)
        return json.loads("".join(chunks), parse_constant=lambda value: pytest.fail(value))

    async def run() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        async with Client(mcp) as client:
            prepared = await call(
                client,
                "prepare_tree_variant",
                {
                    "build_spec": base,
                    "remove_nodes": [47555],
                    "add_anchors": [18845],
                    "point_budget": 11,
                },
            )
            assert prepared["ok"], prepared
            alternative = prepared["spec"]
            assert 51184 in prepared["changes"]["disconnected_removed"]
            assert 61419 in prepared["changes"]["disconnected_removed"]
            assert alternative["jewels"] == []
            compared = await call(
                client,
                "evaluate_delta",
                {
                    "base_spec": base,
                    "variants": {"branch-edit": alternative},
                    "stats": ["Life", "Mana"],
                    "review_components": ["tree", "jewels"],
                    "include_variant_reviews": True,
                },
            )
            assert compared["comparison"]["measurements_complete"], compared
            assert compared["variants"]["branch-edit"]["tree_connected"] is True
            # Consume the exact measured candidate and selected receipt through
            # the public reference route; do not transcribe them into another spec.
            result_id = result_refs["evaluate_delta"]["$pok_result"]
            candidate_reference = {
                "$pok_result": result_id,
                "path": "/inputs/variants/branch-edit",
                "overrides": {
                    "derived_from": {
                        "$pok_result": result_id,
                        "path": "/result/variant_reviews/branch-edit/derived_from",
                    }
                },
            }
            exported = await call(
                client,
                "assemble_pob",
                {
                    "build_spec": candidate_reference,
                    "slug": "tree-variant-regression",
                    "purpose": "exploration",
                    "stats": ["Life", "Mana"],
                },
            )
            assert exported["ok"], exported
            return prepared, compared, exported

    prepared, compared, exported = asyncio.run(run())
    assert base == original
    assert page_counts["evaluate_delta"] > 1
    assert exported["purpose"] == "exploration"
    path = Path(exported["path"])
    xml = (path / "build.xml").read_text(encoding="utf-8")
    assert codec.decode(exported["build_code"]) == xml
    saved = json.loads((path / "spec.json").read_text(encoding="utf-8"))
    assert saved["tree_nodes"] == prepared["spec"]["tree_nodes"]
    assert saved["jewels"] == []
    assert saved["derived_from"] == compared["variant_reviews"]["branch-edit"]["derived_from"]
    assert compared["variant_reviews"]["branch-edit"]["measurements_complete"]
    (tmp_path / "comparison.json").write_text(
        json.dumps(compared, ensure_ascii=False, indent=2), encoding="utf-8"
    )
