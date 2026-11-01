"""Persistent manager recovery and storage failures preserve the actual outcome."""

import asyncio
import json

import pytest

from pok.engine import execution_journal as journal
from pok.engine.execution_requests import RequestManager


def encoder(value, reference):
    return json.dumps({"value": value, "execution_ref": reference})


def test_new_manager_recovers_completed_result_without_replaying(tmp_path):
    first = RequestManager(persist=True, root=tmp_path)
    calls = []

    async def exercise():
        value, reference = await first.run(
            lambda: calls.append("called") or 123,
            owner="test",
            tool="value",
            timeout_s=10,
            request_json='{"record_json":"{\\"large\\":9007199254740993}"}',
            result_encoder=encoder,
        )
        assert value == 123 and first.status(reference)["persistence"]["finished_ref"]
        restarted = RequestManager(persist=True, root=tmp_path)
        assert restarted.instance != reference["server_instance"]
        recovered = restarted.recover(reference)
        assert recovered["state"] == "completed"
        assert json.loads(recovered["result_json"])["value"] == 123
        assert calls == ["called"]
        with pytest.raises(ValueError, match="another server"):
            restarted.cancel(reference)

    asyncio.run(exercise())


def test_start_publication_failure_never_invokes_operation(tmp_path, monkeypatch):
    manager = RequestManager(persist=True, root=tmp_path)
    calls = []

    def unavailable(*args, **kwargs):
        raise OSError("start publication unavailable")

    monkeypatch.setattr(journal, "start_execution", unavailable)

    async def exercise():
        with pytest.raises(OSError, match="start publication"):
            await manager.run(
                lambda: calls.append("bad"),
                owner="test",
                tool="value",
                timeout_s=10,
                request_json="{}",
                result_encoder=encoder,
            )
        assert not calls

    asyncio.run(exercise())


def test_terminal_failure_preserves_start_and_live_completed_result(tmp_path, monkeypatch):
    manager = RequestManager(persist=True, root=tmp_path)
    identity = "1" * 32
    reference = {
        "format": "pok.execution-ref.v1",
        "server_instance": manager.instance,
        "request_id": identity,
    }

    def unavailable(*args, **kwargs):
        raise OSError("terminal publication unavailable")

    monkeypatch.setattr(journal, "finish_execution", unavailable)

    async def exercise():
        with pytest.raises(RuntimeError, match="durable checkpoint failed"):
            await manager.run(
                lambda: 42,
                owner="test",
                tool="value",
                timeout_s=10,
                request_id=identity,
                request_json="{}",
                result_encoder=encoder,
            )
        live = manager.status(reference)
        assert live["state"] == "completed" and live["result_available"]
        assert live["persistence"]["error"]
        assert manager.result(reference) == 42
        restarted = RequestManager(persist=True, root=tmp_path)
        recovered = restarted.recover(reference)
        assert recovered["state"] == "nonterminal_checkpoint"
        assert recovered["worker_finished"] == "unknown" and not recovered["result_eligible"]

    asyncio.run(exercise())
