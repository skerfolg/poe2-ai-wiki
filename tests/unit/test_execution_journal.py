"""Durable checkpoint evidence never implies live process control or replay."""

import json

import pytest

from pok.artifacts.design import list_builds
from pok.artifacts.design_record import canonical_bytes
from pok.artifacts.store import record_immutable_build
from pok.common.execution import ExecutionScope
from pok.engine import execution_journal as journal


def setup_execution(tmp_path, instance="2" * 32):
    reference = {
        "format": "pok.execution-ref.v1",
        "server_instance": instance,
        "request_id": "1" * 32,
    }
    scope = ExecutionScope("owner", 100, request_id=reference["request_id"])
    request = json.dumps(
        {"record_json": '{"number":1e+01,"large":9007199254740993}', "unknown": "유지"}
    )
    started = journal.start_execution(
        reference, tool="test", receipt=scope.snapshot(), request_json=request, root=tmp_path
    )
    return reference, scope, request, started


def test_completed_checkpoint_recovers_exact_json_and_never_lists_as_build(tmp_path):
    reference, scope, request, started = setup_execution(tmp_path)
    result = '{"number":1e+01,"large":9007199254740993,"future":{"kept":true}}'
    finished = journal.finish_execution(
        started, receipt=scope.finish(), result_json=result, root=tmp_path
    )
    recovered = journal.recover_execution(reference, root=tmp_path)
    assert recovered["state"] == "completed" and recovered["result_eligible"]
    assert recovered["request_json"] == request and recovered["result_json"] == result
    assert recovered["finished_ref"] == finished
    assert list_builds(root=tmp_path) == ()
    assert (
        journal.finish_execution(started, receipt=scope.finish(), result_json=result, root=tmp_path)
        == finished
    )


def test_start_without_terminal_does_not_infer_worker_or_process_death(tmp_path):
    reference, _, request, _ = setup_execution(tmp_path)
    recovered = journal.recover_execution(reference, root=tmp_path)
    assert recovered["state"] == "nonterminal_checkpoint"
    assert recovered["worker_finished"] == "unknown"
    assert recovered["result_eligible"] is False
    assert recovered["request_json"] == request


def test_unconfirmed_native_cleanup_keeps_partial_result_ineligible(tmp_path):
    reference, scope, _, started = setup_execution(tmp_path)
    scope.acquire_resource("native", kind="pob", identity="123")
    scope.request_cancel()
    scope.release_resource("native", state="unconfirmed")
    journal.finish_execution(
        started, receipt=scope.finish(), result_json='{"partial":true}', root=tmp_path
    )
    recovered = journal.recover_execution(reference, root=tmp_path)
    assert recovered["state"] == "termination_unconfirmed"
    assert not recovered["result_eligible"] and recovered["result_json"] == '{"partial":true}'


@pytest.mark.parametrize("state", ["completed", "cancelled", "failed", "timed_out"])
def test_active_resources_cannot_be_published_as_finished_cleanly(tmp_path, state):
    _, scope, _, started = setup_execution(tmp_path)
    receipt = scope.snapshot()
    receipt.update(worker_finished=True, state=state, resources={"native": {"state": "active"}})
    with pytest.raises(ValueError, match="Unconfirmed resources"):
        journal.finish_execution(started, receipt=receipt, result_json="{}", root=tmp_path)


def test_tampered_result_and_wrong_start_link_are_rejected(tmp_path):
    reference, scope, _, started = setup_execution(tmp_path)
    finished = journal.finish_execution(
        started, receipt=scope.finish(), result_json="{}", root=tmp_path
    )
    file = tmp_path / "artifacts/builds" / finished["artifact_id"] / "result.json"
    file.write_bytes(b"forged")
    with pytest.raises(ValueError):
        journal.recover_execution(reference, root=tmp_path)
    other, other_scope, _, other_start = setup_execution(tmp_path, "3" * 32)
    forged = {
        "format": journal.FORMAT,
        "stage": "finished",
        "execution_ref": other,
        "tool": "test",
        "started_ref": started,
        "receipt": other_scope.finish(),
        "error": None,
        "result_eligible": True,
    }
    record_immutable_build(
        other_start["artifact_id"].removesuffix("started") + "finished",
        {"execution.json": canonical_bytes(forged), "result.json": b"{}"},
        {"kind": "execution-checkpoint", "stage": "finished", "execution_ref": other},
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="another start"):
        journal.recover_execution(other, root=tmp_path)


def test_missing_reference_is_not_reported_as_completed(tmp_path):
    reference = {
        "format": "pok.execution-ref.v1",
        "server_instance": "2" * 32,
        "request_id": "1" * 32,
    }
    with pytest.raises(ValueError):
        journal.recover_execution(reference, root=tmp_path)
