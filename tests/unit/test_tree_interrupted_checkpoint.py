"""Interrupted tree search must retain measured choices without claiming completion."""

import asyncio
import dataclasses
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from pok.common import execution
from pok.engine import execution_requests
from pok.engine.execution_requests import RequestExecutionError, RequestManager
from pok.engine.tree import optimize
from pok.pob.buildxml import BuildSpec
from pok.pob.runner import PobResult


@pytest.fixture
def interrupted_search(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(execution, "monotonic", lambda: clock[0])
    monkeypatch.setattr(execution_requests, "monotonic", lambda: clock[0])
    graph = SimpleNamespace(point_split=lambda *args: {"general": 1})
    spec = BuildSpec(class_name="fixture", ascendancy="", tree_nodes=(101,))
    measured = PobResult({"Life": 42.0}, {"fixture": True}, (101,), (), False)
    state = {"calls": 0, "interrupt_at": 2, "cancel": False}

    class Oracle:
        transaction = staticmethod(nullcontext)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def compute_build(self, candidate):
            state["calls"] += 1
            if state["calls"] == state["interrupt_at"]:
                if state["cancel"]:
                    execution.current_execution().request_cancel()
                else:
                    clock[0] = 101.0
                execution.checkpoint()
            return measured

    monkeypatch.setattr(optimize, "PobDaemon", Oracle)
    monkeypatch.setattr(optimize, "_timeless_notes", lambda *args: ())
    monkeypatch.setattr(
        optimize,
        "_seed_anchors",
        lambda spec, *args, **kwargs: (spec, (), SimpleNamespace(general=0, ascendancy=0)),
    )
    # An unmeasured in-progress edit must not inherit the preceding measurement.
    monkeypatch.setattr(
        optimize,
        "_prune_dead_branches",
        lambda original, current, *args: (
            dataclasses.replace(current, tree_nodes=(202,)),
            (),
            0,
            [],
        ),
    )

    def run():
        return optimize.optimize_tree(
            spec,
            graph,
            optimize.Objective(weights={"Life": 1.0}),
            point_budget=1,
            time_budget_s=100,
        )

    return run, state


def test_request_timeout_retains_exact_last_measured_input_as_incomplete(interrupted_search):
    run, state = interrupted_search
    manager = RequestManager()

    async def exercise():
        with pytest.raises(RequestExecutionError) as stopped:
            await manager.run(run, owner="fixture", tool="optimize_tree", timeout_s=100)
        status = manager.status(stopped.value.reference)
        assert status["state"] == "timed_out"
        assert status["result_available"] is False
        with pytest.raises(ValueError, match="No completed result"):
            manager.result(stopped.value.reference)
        saved = status["error"]["details"]["tree_search_checkpoint"]
        assert saved["claim"] == "measured_partial_not_complete_or_recommended"
        assert saved["build_spec"]["tree_nodes"] == [101]
        assert saved["stats"] == {"Life": 42.0}
        assert saved["allocated_nodes"] == [101]
        assert saved["search_complete"] is False
        assert state["calls"] == 2

    asyncio.run(exercise())


def test_failure_before_any_measurement_does_not_invent_a_checkpoint(interrupted_search):
    run, state = interrupted_search
    state["interrupt_at"] = 1
    manager = RequestManager()

    async def exercise():
        with pytest.raises(RequestExecutionError) as stopped:
            await manager.run(run, owner="fixture", tool="optimize_tree", timeout_s=100)
        status = manager.status(stopped.value.reference)
        assert status["state"] == "timed_out"
        assert "tree_search_checkpoint" not in status["error"]["details"]

    asyncio.run(exercise())


def test_actual_mcp_timeout_keeps_error_and_exposes_measured_recovery(
    monkeypatch, interrupted_search
):
    from fastmcp import Client, FastMCP

    from pok.mcp import server

    run, _state = interrupted_search
    api = FastMCP("tree-checkpoint")
    manager = RequestManager()
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", manager)

    def optimize_tree(time_budget_s: float = 100) -> dict:
        run()
        return {}

    server.tool(optimize_tree)
    server.tool(server.get_execution_status.__wrapped__)

    async def exercise():
        async with Client(api) as client:
            reply = await client.call_tool("optimize_tree", {}, raise_on_error=False)
            assert reply.is_error
            assert reply.structured_content["ok"] is False
            assert reply.structured_content["state"] == "timed_out"
            assert reply.structured_content["result_available"] is False
            ref = reply.structured_content["execution_ref"]
            assert reply.structured_content["partial_checkpoint"]["status_arguments"] == {
                "execution_ref": ref
            }
            recovered = await client.call_tool("get_execution_status", {"execution_ref": ref})
            assert recovered.data["error"]["details"]["tree_search_checkpoint"]["build_spec"][
                "tree_nodes"
            ] == [101]
            with pytest.raises(ValueError, match="No completed result"):
                manager.result(ref)

    asyncio.run(exercise())


def test_explicit_cancellation_retains_measurement_without_completed_result(interrupted_search):
    run, state = interrupted_search
    state["cancel"] = True
    manager = RequestManager()

    async def exercise():
        with pytest.raises(RequestExecutionError) as stopped:
            await manager.run(run, owner="fixture", tool="optimize_tree", timeout_s=100)
        status = manager.status(stopped.value.reference)
        assert status["state"] == "cancelled"
        assert status["result_available"] is False
        saved = status["error"]["details"]["tree_search_checkpoint"]
        assert saved["build_spec"]["tree_nodes"] == [101]
        assert saved["stats"] == {"Life": 42.0}
        with pytest.raises(ValueError, match="No completed result"):
            manager.result(stopped.value.reference)

    asyncio.run(exercise())


def test_saved_checkpoint_survives_manager_restart_as_ineligible_evidence(
    interrupted_search, tmp_path
):
    run, _state = interrupted_search
    manager = RequestManager(persist=True, root=tmp_path)

    async def exercise():
        with pytest.raises(RequestExecutionError) as stopped:
            await manager.run(
                run,
                owner="fixture",
                tool="optimize_tree",
                timeout_s=100,
                request_json='{"fixture":true}',
                result_encoder=lambda value, ref: "{}",
            )
        restarted = RequestManager(persist=True, root=tmp_path)
        recovered = restarted.recover(stopped.value.reference)
        assert recovered["state"] == "timed_out"
        assert recovered["result_eligible"] is False
        assert recovered["result_json"] is None
        saved = recovered["error"]["details"]["tree_search_checkpoint"]
        assert saved["build_spec"]["tree_nodes"] == [101]
        assert saved["stats"] == {"Life": 42.0}

    asyncio.run(exercise())
