"""The optional skill server preserves all normal PoK tools in a fresh process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE_SERVER = ROOT / "skills/build-generation/native_server.py"


def test_real_mcp_keeps_full_catalog_and_transports_detail():
    # A separate process prevents optional registration from changing other tests'
    # standard MCP catalog. No model turn or PoB build is involved.
    script = """
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from fastmcp import Client
from fastmcp.exceptions import ToolError
from pok.mcp import server

path = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("optional_native_server", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

async def run():
    async with Client(server.mcp) as client:
        before = {tool.name for tool in await client.list_tools()}
    module.register(server)
    async with Client(server.mcp) as client:
        after = {tool.name for tool in await client.list_tools()}
        query = {"query": "passive points", "type": "Mechanic", "limit": 3}
        original = await client.call_tool("search_kb", query)
        assert not original.is_error
        result = await client.call_tool("search_and_read", {
            "search": query,
            "max_entries": 1, "fields": ["id", "data"],
        })
        assert not result.is_error
        assert after == before | {"search_and_read"}
        assert {"assemble_pob", "optimize_items", "optimize_tree"} <= after
        value = result.data
        assert value["search_result"] == original.data
        assert value["details"][0]["ok"]
        assert value["details"][0]["record"]["data"]
        assert value["physical_queries"] == 2
        rejected = []
        for name, arguments in (
            ("search_kb", {"tags": "spell"}),
            ("search_and_read", {"search": {"tags": "spell"}}),
        ):
            try:
                await client.call_tool(name, arguments)
            except ToolError:
                rejected.append(name)
            else:
                raise AssertionError(f"{name} accepted invalid tags")
        print(json.dumps({
            "before": len(before), "after": len(after), "ok": True,
            "equal_search_results": True, "rejected": rejected,
        }))
asyncio.run(run())
"""
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONUTF8="1")
    result = subprocess.run(
        [sys.executable, "-c", script, str(NATIVE_SERVER)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    evidence = json.loads(result.stdout.strip().splitlines()[-1])
    assert evidence["ok"]
    assert evidence["after"] == evidence["before"] + 1
    assert evidence["equal_search_results"]
    assert evidence["rejected"] == ["search_kb", "search_and_read"]
