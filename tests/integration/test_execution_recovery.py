"""Restart real stdio servers and recover a verified result without replaying it."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import McpError


def test_real_stdio_server_restart_recovers_completed_wire_result(tmp_path):
    source = str(Path(__file__).resolve().parents[2] / "src")
    root = str(tmp_path)
    script = f"""
from pathlib import Path
from pok.mcp import server
from pok.engine.execution_requests import RequestManager
server._REQUESTS = RequestManager(persist=True, root=Path({root!r}))
@server.tool
def recovery_probe(value: str) -> dict:
    path = Path({root!r}) / "operation-count.txt"
    count = int(path.read_text()) if path.exists() else 0
    path.write_text(str(count + 1))
    return {{"value": value, "design_json": '{{"number":1e+01,"large":9007199254740993}}'}}
server.main()
"""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", script],
        env={**os.environ, "PYTHONPATH": source},
    )

    async def exercise():
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            original = await session.call_tool("recovery_probe", {"value": "원문 유지"})
            wire = original.model_dump(by_alias=True, exclude_none=True)
            reference = wire["_meta"]["pok_execution"]
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            recovered = await session.call_tool("recover_execution", {"execution_ref": reference})
            assert not recovered.isError
            value = recovered.structuredContent
            assert value["state"] == "completed" and value["result_eligible"]
            saved_wire = json.loads(value["result_json"])
            assert saved_wire == wire
            assert saved_wire["structuredContent"]["design_json"] == (
                '{"number":1e+01,"large":9007199254740993}'
            )
            rejected = await session.call_tool("cancel_execution", {"execution_ref": reference})
            assert rejected.isError  # A historical server reference is not live control authority.
        assert (tmp_path / "operation-count.txt").read_text() == "1"

    asyncio.run(exercise())


def test_real_server_crash_keeps_started_checkpoint_nonterminal(tmp_path):
    source = str(Path(__file__).resolve().parents[2] / "src")
    root = str(tmp_path)
    script = f"""
import os,json
from pathlib import Path
from pok.mcp import server
from pok.common.execution import current_execution
from pok.engine.execution_requests import RequestManager
server._REQUESTS = RequestManager(persist=True, root=Path({root!r}))
@server.tool
def crash_probe() -> dict:
    scope = current_execution()
    ref = {{"format":"pok.execution-ref.v1","server_instance":server._REQUESTS.instance,
           "request_id":scope.request_id}}
    (Path({root!r}) / "crashed-reference.json").write_text(json.dumps(ref))
    os._exit(77)
server.main()
"""
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-c", script],
        env={**os.environ, "PYTHONPATH": source},
    )

    async def exercise():
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            with pytest.raises(McpError):
                await session.call_tool("crash_probe", {})
        reference = json.loads((tmp_path / "crashed-reference.json").read_text())
        async with stdio_client(parameters) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            response = await session.call_tool("recover_execution", {"execution_ref": reference})
            assert not response.isError
            saved = response.structuredContent
            assert saved["state"] == "nonterminal_checkpoint"
            assert saved["worker_finished"] == "unknown" and saved["result_eligible"] is False

    asyncio.run(exercise())
