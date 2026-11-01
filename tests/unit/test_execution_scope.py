"""Request stop intent cannot masquerade as confirmed worker/resource completion."""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context

import pytest

from pok.common import execution


def test_cancel_intent_is_pending_until_worker_and_resources_finish():
    scope = execution.ExecutionScope("session/request", 10)
    scope.acquire_resource("native", kind="pob", identity="123")
    scope.request_cancel()
    assert scope.snapshot()["state"] == "cancel_requested"
    assert scope.snapshot()["worker_finished"] is False
    with pytest.raises(execution.ExecutionStopped):
        scope.checkpoint()
    assert scope.finish()["state"] == "termination_unconfirmed"


def test_confirmed_cancel_and_failed_cleanup_are_distinct():
    scope = execution.ExecutionScope("request", 10)
    scope.acquire_resource("native", kind="pob", identity="123")
    scope.request_cancel()
    scope.release_resource("native", state="terminated")
    assert scope.finish()["state"] == "cancelled"
    failed = execution.ExecutionScope("other-request", 10)
    failed.acquire_resource("native", kind="pob", identity="456")
    failed.release_resource("native", state="unconfirmed")
    failed.release_resource("native")
    assert failed.finish(failed=True)["state"] == "termination_unconfirmed"


def test_absolute_deadline_cannot_be_replaced_by_nested_scope(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(execution, "monotonic", lambda: now[0])
    scope = execution.ExecutionScope("request", 10)
    with execution.bind_execution(scope):
        now[0] = 9
        assert execution.remaining_timeout(180) == 1
        with execution.bind_execution(scope):
            assert execution.remaining_timeout(180) == 1
        with (
            pytest.raises(RuntimeError, match="nested request"),
            execution.bind_execution(execution.ExecutionScope("replacement", 100)),
        ):
            pass
        now[0] = 10
        with pytest.raises(execution.ExecutionStopped) as failure:
            execution.checkpoint()
        assert failure.value.reason == "deadline_exceeded"
    assert scope.snapshot()["worker_finished"] is False
    assert scope.finish()["state"] == "timed_out"


def test_worker_context_and_cancellation_do_not_cross_requests():
    first = execution.ExecutionScope("first", 10)
    second = execution.ExecutionScope("second", 10)
    first.request_cancel()
    with execution.bind_execution(second), ThreadPoolExecutor(max_workers=1) as pool:
        context = copy_context()
        result = pool.submit(context.run, execution.remaining_timeout, 1).result(timeout=2)
        assert result == 1
        assert execution.current_execution() is second
    assert execution.current_execution() is None
    assert second.finish()["state"] == "completed"
    first.finish()


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_request_deadlines_are_rejected(timeout):
    with pytest.raises(ValueError):
        execution.ExecutionScope("request", timeout)


def test_finished_scope_cannot_resume_and_stop_is_not_fallback_error():
    scope = execution.ExecutionScope("finished", 10)
    assert scope.finish() == scope.finish()
    with pytest.raises(RuntimeError, match="finished"):
        scope.checkpoint()
    assert not issubclass(execution.ExecutionStopped, Exception)


def test_cleanup_details_are_copied_and_terminal_facts_survive_generic_finally():
    scope = execution.ExecutionScope("owner", 10)
    scope.acquire_resource("native", kind="pob", identity="123")
    detail = {"status": "confirmed", "scope": "windows_job"}
    scope.release_resource("native", state="terminated", details=detail)
    detail["status"] = "caller-mutated"
    scope.release_resource("native")
    snapshot = scope.snapshot()
    assert snapshot["resources"]["native"]["state"] == "terminated"
    assert snapshot["resources"]["native"]["details"]["status"] == "confirmed"
    snapshot["resources"]["native"]["details"]["status"] = "another-mutation"
    assert scope.snapshot()["resources"]["native"]["details"]["status"] == "confirmed"
