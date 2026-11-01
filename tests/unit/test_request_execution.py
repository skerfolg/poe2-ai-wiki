"""Actual MCP supervision and truthful pending/finished cancellation states."""

import asyncio
from threading import Event
from time import sleep
from uuid import uuid4

import pytest
from fastmcp import Client, Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.shared.exceptions import McpError
from mcp.types import CancelledNotification, CancelledNotificationParams, ClientNotification

from pok.common.execution import checkpoint
from pok.engine.execution_requests import RequestExecutionError, RequestManager
from pok.mcp import server


@pytest.fixture
def supervised(monkeypatch):
    api = FastMCP("execution-transport")
    manager = RequestManager(cleanup_grace_s=0.2)
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "_REQUESTS", manager)
    for function in (
        server.get_execution_status,
        server.cancel_execution,
        server.read_execution_result,
    ):
        server.tool(function.__wrapped__)
    entered = Event()

    @server.tool
    def slow() -> dict:
        entered.set()
        while True:
            checkpoint()
            sleep(0.01)

    @server.tool
    def quick() -> dict:
        return {"value": 123}

    return api, manager, entered


def reference(manager, identity):
    return {
        "format": "pok.execution-ref.v1",
        "server_instance": manager.instance,
        "request_id": identity,
    }


@pytest.mark.parametrize("stop", ["cancel", "deadline", "notification", "client_only"])
def test_mcp_stop_propagates_and_other_requests_remain_usable(supervised, stop):
    api, manager, entered = supervised

    async def exercise():
        async with Client(api) as client:
            identity = uuid4().hex
            ref = reference(manager, identity)
            task = asyncio.create_task(
                client.call_tool(
                    "slow",
                    {},
                    meta={
                        "pok_execution": {
                            "request_id": identity,
                            "timeout_s": 0.15 if stop == "deadline" else 10,
                        }
                    },
                )
            )
            assert await asyncio.to_thread(entered.wait, 3)
            if stop == "cancel":
                pending = (await client.call_tool("cancel_execution", {"execution_ref": ref})).data
                assert pending["state"] in {"cancel_requested", "cancelled"}
            if stop == "notification":
                status = (
                    await client.call_tool("get_execution_status", {"execution_ref": ref})
                ).data
                transport_id = int(status["owner"].rsplit("/", 1)[1])
                await client.session.send_notification(
                    ClientNotification(
                        CancelledNotification(
                            params=CancelledNotificationParams(
                                requestId=transport_id, reason="test stop"
                            )
                        )
                    )
                )
                with pytest.raises((McpError, ToolError)):
                    await task
            elif stop == "client_only":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
                # The installed SDK does not turn local task cancellation into
                # notifications/cancelled. Never claim the server stopped.
                status = (
                    await client.call_tool("get_execution_status", {"execution_ref": ref})
                ).data
                assert status["worker_finished"] is False
                assert status["stop_reason"] is None
                await client.call_tool("cancel_execution", {"execution_ref": ref})
            else:
                with pytest.raises(ToolError):
                    await task
            for _ in range(100):
                status = (
                    await client.call_tool("get_execution_status", {"execution_ref": ref})
                ).data
                if status["worker_finished"]:
                    break
                await asyncio.sleep(0.01)
            assert status["worker_finished"] is True
            assert status["state"] == ("timed_out" if stop == "deadline" else "cancelled")
            assert not status["result_available"]
            good = await client.call_tool("quick", {})
            assert good.data == {"value": 123}
            good_ref = good.meta["pok_execution"]
            saved = (
                await client.call_tool("read_execution_result", {"execution_ref": good_ref})
            ).data
            assert saved["execution"]["state"] == "completed"
            assert saved["wire_result"]["structuredContent"] == {"value": 123}

    asyncio.run(exercise())


def test_noncooperative_worker_is_pending_and_late_result_is_not_completed():
    manager = RequestManager(cleanup_grace_s=0.01)
    release = Event()

    async def exercise():
        identity = uuid4().hex
        ref = reference(manager, identity)
        try:
            with pytest.raises(RequestExecutionError):
                await manager.run(
                    lambda: release.wait(3),
                    owner="test",
                    tool="blocked",
                    timeout_s=0.03,
                    request_id=identity,
                )
            assert not manager.status(ref)["worker_finished"]
            assert manager.status(ref)["state"] == "deadline_exceeded"
            release.set()
            for _ in range(100):
                if manager.status(ref)["worker_finished"]:
                    break
                await asyncio.sleep(0.01)
            assert manager.status(ref)["state"] == "timed_out"
            with pytest.raises(ValueError, match="No completed result"):
                manager.result(ref)
        finally:
            release.set()

    asyncio.run(exercise())


def test_duplicate_request_does_not_replace_original_and_restart_ref_is_unknown():
    manager = RequestManager()

    async def exercise():
        identity = uuid4().hex
        _, ref = await manager.run(
            lambda: 1, owner="test", tool="value", timeout_s=1, request_id=identity
        )
        with pytest.raises(ValueError, match="already exists"):
            await manager.run(
                lambda: 2, owner="test", tool="value", timeout_s=1, request_id=identity
            )
        assert manager.result(ref) == 1
        with pytest.raises(ValueError, match="another server"):
            RequestManager().status(ref)

    asyncio.run(exercise())


def test_pruned_execution_id_cannot_alias_a_new_request():
    manager = RequestManager(capacity=1)

    async def exercise():
        identity = uuid4().hex
        _, original = await manager.run(
            lambda: 1, owner="test", tool="one", timeout_s=1, request_id=identity
        )
        await manager.run(lambda: 2, owner="test", tool="two", timeout_s=1)
        with pytest.raises(ValueError, match="unavailable"):
            manager.status(original)
        with pytest.raises(ValueError, match="already exists"):
            await manager.run(
                lambda: 3, owner="test", tool="three", timeout_s=1, request_id=identity
            )

    asyncio.run(exercise())


def test_existing_anyio_progress_reporter_works_under_supervision(supervised):
    from pok.mcp.tools.build import _progress_reporter

    api, _, _ = supervised

    @server.tool
    def progress_probe(ctx: Context) -> dict:
        report = _progress_reporter(ctx)
        assert report is not None
        report(1, 2, "progress under supervision")
        return {"done": True}

    async def exercise():
        events = []

        async def progress(done, total, message):
            events.append((done, total, message))

        async with Client(api) as client:
            result = await client.call_tool("progress_probe", {}, progress_handler=progress)
            assert result.data == {"done": True}
            assert events == [(1, 2, "progress under supervision")]

    asyncio.run(exercise())


def test_progress_notifications_cannot_extend_request_deadline(supervised):
    from pok.mcp.tools.build import _progress_reporter

    api, manager, _ = supervised

    @server.tool
    def progress_loop(ctx: Context) -> dict:
        report = _progress_reporter(ctx)
        while True:
            checkpoint()
            report(1, 2, "still running")
            sleep(0.01)

    async def exercise():
        events = []

        async def progress(*args):
            events.append(args)

        identity = uuid4().hex
        async with Client(api) as client:
            with pytest.raises(ToolError):
                await client.call_tool(
                    "progress_loop",
                    {},
                    progress_handler=progress,
                    meta={
                        "pok_execution": {"request_id": identity, "timeout_s": 0.2},
                    },
                )
            assert events
            assert manager.status(reference(manager, identity))["state"] == "timed_out"

    asyncio.run(exercise())
