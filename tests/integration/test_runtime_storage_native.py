"""Configured data/cache survive reconnect and remain isolated in real MCP/PoB."""

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from pok.pob.versions import find_luajit, resolve_snapshot


def _ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _ready(), reason="LuaJIT or pinned PoB unavailable")


def test_configured_storage_reconnect_index_and_native_cache(tmp_path):
    resource = Path(__file__).resolve().parents[2]
    data_a, data_b = tmp_path / "data-a", tmp_path / "data-b"
    cache_a, cache_b = tmp_path / "cache-a", tmp_path / "cache-b"

    def parameters(data, cache):
        return StdioServerParameters(
            command=sys.executable,
            args=["-m", "pok.mcp"],
            cwd=str(resource),
            env={
                **os.environ,
                "PYTHONPATH": str(resource / "src"),
                "PYTHONUTF8": "1",
                "POK_DATA_HOME": str(data),
                "POK_CACHE_HOME": str(cache),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": str(resource),
            },
        )

    async def call(session, name, arguments):
        response = await session.call_tool(name, arguments)
        assert not response.isError, response.content
        data = response.structuredContent
        if data is None:
            data = json.loads(response.content[0].text)
        if isinstance(data, dict) and set(data) == {"result"}:
            data = data["result"]
        if isinstance(data, dict) and data.get("stored_tool_result"):
            ref = data["result_ref"]
            chunks, offset = [], 0
            while True:
                page = await call(
                    session,
                    "get_tool_result",
                    {
                        "result_id": ref["$pok_result"],
                        "path": ref["path"],
                        "mode": "json",
                        "offset": offset,
                    },
                )
                chunks.append(page["chunk"])
                offset = page["next_offset"]
                if offset is None:
                    break
            data = json.loads("".join(chunks))
        return data

    spec = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 90,
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

    async def run():
        async with (
            stdio_client(parameters(data_a, cache_a)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            info = await call(session, "server_info", {})
            assert Path(info["runtime_paths"]["resource_root"]) == resource
            assert Path(info["runtime_paths"]["artifacts_root"]) == (data_a / "artifacts").resolve()
            assert Path(info["runtime_paths"]["cache_root"]) == cache_a.resolve()
            record = await call(
                session,
                "create_design_record",
                {"design_id": "storage-test", "goal": "Configured storage persistence"},
            )
            reference = record["record_ref"]
            await call(session, "search_kb", {"query": "Spark", "type": "Skill", "limit": 1})
            first = await call(
                session,
                "compute_pob",
                {"build_spec": spec, "stats": ["Life"], "input_policy": "explicit"},
            )
            assert first["meta"]["execution_inputs"]["cache"] == "miss"
        assert (data_a / "artifacts/builds" / reference["artifact_id"]).is_dir()
        assert (cache_a / "index.sqlite").is_file()
        assert list((cache_a / "pob-cache").glob("*.json"))
        async with (
            stdio_client(parameters(data_a, cache_a)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            restored = await call(session, "read_design_record", {"record_ref": reference})
            assert restored["record_ref"] == reference
            reused = await call(
                session,
                "compute_pob",
                {"build_spec": spec, "stats": ["Life"], "input_policy": "explicit"},
            )
            assert reused["meta"]["execution_inputs"]["cache"] == "hit"
            assert reused["stats"] == first["stats"]
        async with (
            stdio_client(parameters(data_b, cache_b)) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            missing = await session.call_tool("read_design_record", {"record_ref": reference})
            assert missing.isError
            separate = await call(
                session,
                "compute_pob",
                {"build_spec": spec, "stats": ["Life"], "input_policy": "explicit"},
            )
            assert separate["meta"]["execution_inputs"]["cache"] == "miss"
            assert separate["stats"] == first["stats"]
        assert not (data_b / "artifacts/builds" / reference["artifact_id"]).exists()

    asyncio.run(run())
