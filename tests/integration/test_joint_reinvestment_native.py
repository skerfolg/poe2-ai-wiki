"""Explicit packages can reopen equipment/support decisions after supply changes.

These small arithmetic fixtures do not establish general build quality.
"""

import asyncio
from copy import deepcopy

import pytest
from fastmcp import Client, FastMCP

from pok.artifacts import tool_results
from pok.engine.execution_requests import RequestManager
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


def ring(slot, *mods):
    return {
        "slot": slot,
        "text": "Rarity: RARE\nExample\nGold Ring\nItem Level: 80\nImplicits: 0\n"
        + "\n".join(mods),
    }


@pytest.mark.parametrize("scenario", ["mana_support", "resistance_reallocation"])
def test_supply_change_and_joint_reinvestment_are_separate_measured_candidates(
    tmp_path, monkeypatch, scenario
):
    api = FastMCP("joint-reinvestment")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", RequestManager())
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    server.tool(build.evaluate_delta)
    base = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 90,
        "items": [ring("Ring 1", "+10 to maximum Life")],
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
    if scenario == "mana_support":
        base["items"] = [ring("Ring 1", "+50 to Intelligence", "+10 to maximum Life")]
        base["skills"][0]["gems"][0]["level"] = 10
        base["skills"][0]["gems"].append(
            {
                "gem_id": "Metadata/Items/Gems/SkillGemEfficiencySupport",
                "name": "Efficiency I",
                "level": 1,
            }
        )
        supply = deepcopy(base)
        supply["items"] = [
            ring(
                "Ring 1",
                "+50 to Intelligence",
                "+100 to maximum Mana",
                "25% increased Mana Regeneration Rate",
            )
        ]
        package = deepcopy(supply)
        package["skills"][0]["gems"][1] = {
            "gem_id": "Metadata/Items/Gems/SkillGemRapidCastingSupport",
            "name": "Rapid Casting I",
            "level": 1,
        }
        premature = deepcopy(base)
        premature["skills"][0]["gems"][1] = deepcopy(package["skills"][0]["gems"][1])
        stats = ["Mana", "ManaRegen", "ManaCost", "Speed", "Life"]
    else:
        base["items"] = [
            ring("Ring 1", "+20% to Fire Resistance"),
            ring("Ring 2", "+10 to maximum Life"),
        ]
        supply = deepcopy(base)
        supply["items"][1] = ring("Ring 2", "+20% to Fire Resistance")
        package = deepcopy(supply)
        package["items"][0] = ring("Ring 1", "+20 to maximum Life")
        stats = ["Life", "FireResist"]
    original = deepcopy(base)
    variants = {"supply_only": supply, "joint_package": package}
    if scenario == "mana_support":
        variants["premature_swap"] = premature

    async def run():
        async with Client(api) as client:
            response = await client.call_tool(
                "evaluate_delta",
                {
                    "base_spec": base,
                    "variants": variants,
                    "stats": stats,
                },
            )
            assert not response.is_error
            payload, _ = tool_results.load_result(response.data["measurement_ref"]["$pok_result"])
            result = payload["result"]
            assert result["comparison"]["measurements_complete"], result["comparison"]
            before = result["base"]["stats"]
            supplied = result["variants"]["supply_only"]["stats"]
            after = result["variants"]["joint_package"]["stats"]
            if scenario == "mana_support":
                without_supply = result["variants"]["premature_swap"]["stats"]
                assert before["ManaRegen"] >= before["ManaCost"] * before["Speed"]
                assert (
                    without_supply["ManaRegen"]
                    < without_supply["ManaCost"] * without_supply["Speed"]
                )
                assert supplied["ManaRegen"] > before["ManaRegen"]
                assert after["Speed"] > supplied["Speed"]
                assert after["ManaCost"] > supplied["ManaCost"]
                assert after["ManaRegen"] >= after["ManaCost"] * after["Speed"]
            else:
                assert supplied["FireResist"] > before["FireResist"]
                assert after["FireResist"] == before["FireResist"]
                assert after["Life"] > before["Life"]
            assert base == original

    asyncio.run(run())
