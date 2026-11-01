"""Real MCP cancellation reaches the actual single-use PoB child process."""

import asyncio
from threading import Event
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

from pok.artifacts import tool_results
from pok.engine import pob_documents
from pok.engine.design_service import capture_material
from pok.engine.execution_requests import RequestManager
from pok.mcp import server
from pok.pob import runner
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT or pinned PoB unavailable")


def test_mcp_cancel_reaps_actual_pob_and_next_request_computes(tmp_path, monkeypatch):
    api = FastMCP("native-execution")
    manager = RequestManager(persist=True, root=tmp_path)
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", manager)
    server.tool(server.get_execution_status.__wrapped__)
    server.tool(server.cancel_execution.__wrapped__)
    started = Event()
    children = []
    original_popen = runner.subprocess.Popen

    def observe(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        command = args[0]
        if len(command) > 1 and str(command[1]).endswith("pob_driver.lua"):
            children.append(child)
            started.set()
        return child

    monkeypatch.setattr(runner.subprocess, "Popen", observe)
    spec = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        level=90,
        skills=(
            SkillGroupSpec(
                gems=(
                    GemSpec(
                        gem_id="Metadata/Items/Gems/SkillGemSpark",
                        name="Spark",
                        level=20,
                    ),
                )
            ),
        ),
    )

    @server.tool
    def native_scope_probe() -> dict[str, Any]:
        result = runner.run_build(spec, use_cache=False)
        return {"Life": result.stats["Life"], "native": result.meta["nativeSelection"]}

    async def exercise():
        async with Client(api) as client:
            identity = uuid4().hex
            ref = {
                "format": "pok.execution-ref.v1",
                "server_instance": manager.instance,
                "request_id": identity,
            }
            task = asyncio.create_task(
                client.call_tool(
                    "native_scope_probe",
                    {},
                    meta={
                        "pok_execution": {"request_id": identity, "timeout_s": 120},
                    },
                )
            )
            assert await asyncio.to_thread(started.wait, 60)
            await client.call_tool("cancel_execution", {"execution_ref": ref})
            with pytest.raises(ToolError):
                await task
            status = (await client.call_tool("get_execution_status", {"execution_ref": ref})).data
            assert status["state"] == "cancelled" and status["worker_finished"] is True
            assert any(row["state"] == "terminated" for row in status["resources"].values())
            assert all(
                row["details"]["status"] == "confirmed" for row in status["resources"].values()
            )
            assert children[0].poll() is not None
            recovered = RequestManager(persist=True, root=tmp_path).recover(ref)
            assert recovered["state"] == "cancelled"
            assert recovered["result_eligible"] is False
            assert recovered["error"]["reason"] == "cancel_requested"
            good = await client.call_tool("native_scope_probe", {})
            assert good.data["Life"] > 0
            assert good.data["native"]["actual"]["effect_id"] == "SparkPlayer"
            assert all(child.poll() is not None for child in children)

    try:
        asyncio.run(exercise())
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def test_actual_measurement_receipt_keeps_disk_and_loaded_memory_observations(
    tmp_path, monkeypatch
):
    api = FastMCP("native-loaded-observations")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", RequestManager())
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path / "var")
    original = pob_documents.measure_document
    monkeypatch.setattr(
        pob_documents,
        "measure_document",
        lambda *args, **kwargs: original(*args, **kwargs, root=tmp_path),
    )
    server.tool(server.compute_pob_document.__wrapped__, literal_arguments=frozenset({"xml_ref"}))
    xml = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(
                SkillGroupSpec(
                    gems=(
                        GemSpec(
                            gem_id="Metadata/Items/Gems/SkillGemSpark",
                            name="Spark",
                            level=20,
                        ),
                    )
                ),
            ),
        )
    )
    material = capture_material(xml_text=xml, root=tmp_path)["material"]

    async def exercise():
        async with Client(api) as client:
            response = await client.call_tool(
                "compute_pob_document",
                {
                    "xml_ref": material["xml"],
                    "stats": ["Life"],
                    "use_cache": False,
                },
            )
            payload, _ = tool_results.load_result(response.data["measurement_ref"]["$pok_result"])
            memory = payload["source"]["loaded_execution_observation"]
            assert memory["before"]["python"]["status"] == "observed_code_objects"
            assert memory["after"]["entrypoint"] == "observed_code_object"
            assert memory["after"]["native_process"] == "not_verified"
            assert payload["source"]["source_observation"]["execution_identity"] == (
                "not_verified_disk_observation_only"
            )
            assert payload["result"]["stats"]["Life"] > 0
            assert payload["result"]["meta"]["execution_inputs"]["status"] == "stable_observation"

    asyncio.run(exercise())
