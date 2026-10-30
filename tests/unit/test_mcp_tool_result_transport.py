"""Exercise the real FastMCP boundary, including its duplicate result encoding."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastmcp import Client, FastMCP
from mcp.types import CallToolResult

from pok.artifacts import tool_results
from pok.mcp import server


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    api = FastMCP("tool-result-transport-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    server.tool(server.get_tool_result.__wrapped__)
    return api


def wire_bytes(response) -> int:
    wire = CallToolResult(
        content=response.content,
        structured_content=response.structured_content,
        is_error=response.is_error,
        _meta=response.meta,
    )
    return len(wire.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))


@pytest.mark.parametrize("value", [{"ok": True, "text": "한글"}, [{"id": "one"}], "normal text"])
def test_small_mcp_and_direct_python_returns_match_original(isolated, value):
    if isinstance(value, list):

        def original() -> list[dict[str, Any]]:
            return value
    elif isinstance(value, str):

        def original() -> str:
            return value
    else:

        def original() -> dict[str, Any]:
            return value

    direct = server.tool(original)
    assert direct() is value
    normal = FastMCP("tool-result-transport-test")
    normal.tool(original)

    async def compare():
        async with Client(normal) as plain, Client(isolated) as bounded:
            before = await plain.call_tool("original", {})
            after = await bounded.call_tool("original", {})
            assert after.content == before.content
            assert after.structured_content == before.structured_content
            assert after.data == before.data
            assert after.meta == before.meta

    asyncio.run(compare())


@pytest.mark.parametrize("as_list", [False, True])
def test_large_response_is_valid_bounded_json_and_original_is_lossless(isolated, as_list):
    huge = {"proof": '한글😀\\"' * 100000, "candidate": {"value": 17}}
    value = [huge] if as_list else huge
    if as_list:

        def produce() -> list[dict[str, Any]]:
            return value
    else:

        def produce() -> dict[str, Any]:
            return value

    direct = server.tool(produce)
    assert direct() is value

    async def inspect():
        async with Client(isolated) as client:
            reply = await client.call_tool("produce", {})
            assert wire_bytes(reply) <= 16000
            notice = json.loads(reply.content[0].text)
            assert notice["stored_tool_result"] is True
            result_id = notice["result_ref"]["$pok_result"]
            payload, _ = tool_results.load_result(result_id)
            assert payload["result"] == value
            page = await client.call_tool(
                "get_tool_result",
                {
                    "result_id": result_id,
                    "path": "/result/0/candidate" if as_list else "/result/candidate",
                },
            )
            assert wire_bytes(page) <= 16000
            assert page.data["entries"] == [{"key": "value", "value": 17}]

    asyncio.run(inspect())


def test_saved_candidate_and_selected_receipt_flow_into_followup_call(isolated):
    calls = []
    receipt = {"tree": {"context": "chosen-context", "history": "evidence" * 100000}}

    @server.tool
    def evaluate(
        base_spec: dict[str, Any], variants: dict[str, dict[str, Any]], flag: bool = True
    ) -> dict[str, Any]:
        calls.append(("evaluate", base_spec, variants, flag))
        return {"variant_reviews": {"chosen": {"derived_from": receipt}}}

    @server.tool
    def consume(build_spec: dict[str, Any]) -> dict[str, Any]:
        calls.append(("consume", build_spec))
        return {"received": build_spec, "large": "x" * 20000}

    async def run():
        async with Client(isolated) as client:
            base = {"tree_nodes": [1], "derived_from": {"old": True}}
            chosen = {"tree_nodes": [1, 2], "derived_from": {"old": True}}
            first = await client.call_tool(
                "evaluate", {"base_spec": base, "variants": {"chosen": chosen}}
            )
            result_id = first.data["result_ref"]["$pok_result"]
            reference = {
                "$pok_result": result_id,
                "path": "/inputs/variants/chosen",
                "overrides": {
                    "derived_from": {
                        "$pok_result": result_id,
                        "path": "/result/variant_reviews/chosen/derived_from",
                    }
                },
            }
            second = await client.call_tool("consume", {"build_spec": reference})
            assert wire_bytes(first) <= 16000 and wire_bytes(second) <= 16000
            expected = {"tree_nodes": [1, 2], "derived_from": receipt}
            assert calls == [("evaluate", base, {"chosen": chosen}, True), ("consume", expected)]
            followup_id = second.data["result_ref"]["$pok_result"]
            payload, manifest = tool_results.load_result(followup_id)
            assert payload["inputs"] == {"build_spec": expected}
            assert manifest["inputs_sha256"] == tool_results.digest({"build_spec": expected})
            assert payload["result"]["received"] == expected

    asyncio.run(run())


def test_large_string_chunks_stay_bounded_on_actual_mcp_wire(isolated):
    text = '😀한글\\"\n' * 1200

    @server.tool
    def produce() -> dict[str, Any]:
        return {"huge_string": text}

    async def run():
        chunks, offset = [], 0
        async with Client(isolated) as client:
            response = await client.call_tool("produce", {})
            result_id = response.data["result_ref"]["$pok_result"]
            while True:
                reply = await client.call_tool(
                    "get_tool_result",
                    {"result_id": result_id, "path": "/result/huge_string", "offset": offset},
                )
                assert wire_bytes(reply) <= 16000
                page = json.loads(reply.content[0].text)
                chunks.append(page["chunk"])
                if page["next_offset"] is None:
                    break
                assert page["next_offset"] > offset
                offset = page["next_offset"]
        assert "".join(chunks) == text

    asyncio.run(run())


def test_saved_inputs_are_before_tool_mutation(isolated):
    @server.tool
    def mutate(build_spec: dict[str, Any]) -> dict[str, Any]:
        build_spec["tree_nodes"].append(2)
        return {"mutated": build_spec, "proof": "x" * 20000}

    async def run():
        async with Client(isolated) as client:
            reply = await client.call_tool("mutate", {"build_spec": {"tree_nodes": [1]}})
            payload, _ = tool_results.load_result(reply.data["result_ref"]["$pok_result"])
            assert payload["inputs"] == {"build_spec": {"tree_nodes": [1]}}
            assert payload["result"]["mutated"]["tree_nodes"] == [1, 2]

    asyncio.run(run())


def test_real_compute_adapter_accepts_resolved_spec_and_preserves_receipt(isolated, monkeypatch):
    from pok.mcp.tools import build
    from pok.pob.runner import PobResult

    server.tool(build.compute_pob)
    called = []
    stamp = {"tree": {"tool": "manual", "why": "transport fixture"}}
    chosen = {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "level": 100,
        "derived_from": stamp,
    }
    stored = tool_results.store_result("fixture", {"variants": {"chosen": chosen}}, {})
    monkeypatch.setattr(
        build,
        "_compute",
        lambda spec: called.append(spec) or PobResult({"Life": 123}, {}, (), (), False),
    )
    monkeypatch.setattr(
        build,
        "_pick",
        lambda result, stats, spec: {"stats": result.stats, "received_stamp": spec["derived_from"]},
    )
    monkeypatch.setattr(build, "_points", lambda *args: {})
    monkeypatch.setattr(build, "_stat_scalers", lambda *args: {})
    monkeypatch.setattr(build, "_unset_config", lambda *args: {})
    monkeypatch.setattr(build, "_config_upkeep", lambda *args: {})

    async def run():
        async with Client(isolated) as client:
            reply = await client.call_tool(
                "compute_pob",
                {
                    "build_spec": {"$pok_result": stored["id"], "path": "/inputs/variants/chosen"},
                    "stats": ["Life"],
                },
            )
            assert reply.data["stats"] == {"Life": 123}
            assert reply.data["received_stamp"] == stamp
            assert len(called) == 1
            assert called[0].class_name == "Mercenary" and called[0].level == 100

    asyncio.run(run())


def test_real_assembly_gate_is_not_bypassed_by_result_reference(isolated):
    from pok.mcp.tools import build

    server.tool(build.assemble_pob)
    chosen = {"class_name": "Mercenary", "level": 100}
    stored = tool_results.store_result("fixture", {"variants": {"chosen": chosen}}, {})

    async def run():
        async with Client(isolated) as client:
            inline = await client.call_tool(
                "assemble_pob",
                {"build_spec": chosen, "slug": "reference-fixture", "purpose": "recommendation"},
            )
            referenced = await client.call_tool(
                "assemble_pob",
                {
                    "build_spec": {"$pok_result": stored["id"], "path": "/inputs/variants/chosen"},
                    "slug": "reference-fixture",
                    "purpose": "recommendation",
                },
            )
            assert referenced.data == inline.data
            assert referenced.data["ok"] is False
            assert referenced.data["optimization_readiness"]["recommendation_ready"] is False
            assert "build_code" not in referenced.data

    asyncio.run(run())


@pytest.mark.parametrize("shape", ["dict", "list", "string", "untyped-list"])
@pytest.mark.parametrize("padding", [0, 20000])
def test_nonfinite_values_preserve_existing_mcp_json_contract(isolated, shape, padding):
    import math

    numbers = [float("inf"), float("-inf"), float("nan"), 1.25]
    record = {"unscored_axes": [{"relative": n} for n in numbers], "padding": "x" * padding}
    if shape == "dict":
        value = record

        def original() -> dict[str, Any]:
            return value
    elif shape == "list":
        value = [record]

        def original() -> list[dict[str, Any]]:
            return value
    elif shape == "untyped-list":
        value = [record]

        def original() -> Any:
            return value
    else:
        # Text spelling NaN/Infinity is ordinary text, including JSON-looking text.
        value = '{"relative":NaN,"negative":-Infinity,"positive":Infinity}' + "x" * padding

        def original() -> str:
            return value

    direct = server.tool(original)
    assert direct() is value
    assert math.isinf(numbers[0]) and math.isinf(numbers[1]) and math.isnan(numbers[2])
    normal = FastMCP("tool-result-transport-test")
    normal.tool(original)
    observed = []

    @server.tool
    def consume(payload: dict[str, Any]) -> dict[str, Any]:
        observed.append(payload)
        return {"received": payload, "large": "x" * 20000}

    async def full_json(client, result_id, path):
        chunks, offset = [], 0
        while True:
            reply = await client.call_tool(
                "get_tool_result",
                {"result_id": result_id, "path": path, "mode": "json", "offset": offset},
            )
            assert wire_bytes(reply) <= 16000
            page = reply.data
            chunks.append(page["chunk"])
            if page["next_offset"] is None:
                break
            assert page["next_offset"] > offset
            offset = page["next_offset"]
        return json.loads("".join(chunks), parse_constant=lambda value: pytest.fail(value))

    async def compare():
        async with Client(normal) as plain, Client(isolated) as bounded:
            before = await plain.call_tool("original", {})
            after = await bounded.call_tool("original", {})
            # The unstructured Any/list result has no .data; its logical JSON is text.
            expected = (
                json.loads(before.content[0].text) if shape == "untyped-list" else before.data
            )
            if not padding:
                assert after.content == before.content
                assert after.structured_content == before.structured_content
                assert after.data == before.data
                assert after.meta == before.meta
                return
            assert wire_bytes(after) <= 16000
            notice = json.loads(after.content[0].text)
            result_id = notice["result_ref"]["$pok_result"]
            assert await full_json(bounded, result_id, "/result") == expected
            payload, manifest = tool_results.load_result(result_id)
            assert payload["result"] == expected
            assert manifest["result_sha256"] == tool_results.digest(expected)
            followup = await bounded.call_tool(
                "consume",
                {"payload": {"value": {"$pok_result": result_id, "path": "/result"}}},
            )
            assert wire_bytes(followup) <= 16000
            followup_id = followup.data["result_ref"]["$pok_result"]
            assert observed == [{"value": expected}]
            assert await full_json(bounded, followup_id, "/inputs/payload") == {"value": expected}

    asyncio.run(compare())
