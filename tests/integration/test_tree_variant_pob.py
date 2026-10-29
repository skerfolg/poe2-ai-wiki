"""Normal MCP branch edit -> actual PoB comparison -> exploration share code."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client

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
    from pok.artifacts import store
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

    async def call(client: Client, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await client.call_tool(name, arguments)
        assert not result.is_error
        return result.data

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
            alternative["derived_from"] = compared["variant_reviews"]["branch-edit"]["derived_from"]
            exported = await call(
                client,
                "assemble_pob",
                {
                    "build_spec": alternative,
                    "slug": "tree-variant-regression",
                    "purpose": "exploration",
                    "stats": ["Life", "Mana"],
                },
            )
            assert exported["ok"], exported
            return prepared, compared, exported

    prepared, compared, exported = asyncio.run(run())
    assert base == original
    assert exported["purpose"] == "exploration"
    path = Path(exported["path"])
    xml = (path / "build.xml").read_text(encoding="utf-8")
    assert codec.decode(exported["build_code"]) == xml
    saved = json.loads((path / "spec.json").read_text(encoding="utf-8"))
    assert saved["tree_nodes"] == prepared["spec"]["tree_nodes"]
    assert saved["jewels"] == []
    assert compared["variant_reviews"]["branch-edit"]["measurements_complete"]
    (tmp_path / "comparison.json").write_text(
        json.dumps(compared, ensure_ascii=False, indent=2), encoding="utf-8"
    )
