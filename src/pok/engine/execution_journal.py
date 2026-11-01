"""Immutable request checkpoints in the existing build artifact store.

Recovery retrieves evidence. It never replays an operation, adopts a build,
infers process death or kills a PID recorded by another server incarnation.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pok.artifacts.design_record import canonical_bytes, parse_json_data
from pok.artifacts.store import (
    ArtifactUnavailableError,
    open_immutable_build,
    read_immutable_build,
    record_immutable_build,
)

FORMAT = "pok.execution-checkpoint.v1"
REF_FORMAT = "pok.execution-checkpoint-ref.v1"
_HEX = re.compile(r"[a-f0-9]{32}\Z")


def _execution(reference: Mapping[str, Any]) -> dict[str, str]:
    if (
        set(reference) != {"format", "server_instance", "request_id"}
        or (reference.get("format") != "pok.execution-ref.v1")
        or any(
            not isinstance(reference[key], str) or not _HEX.fullmatch(reference[key])
            for key in ("server_instance", "request_id")
        )
    ):
        raise ValueError("Malformed execution reference")
    return dict(reference)


def _identity(reference: Mapping[str, Any], stage: str) -> str:
    checked = _execution(reference)
    return f"execution-{checked['server_instance']}-{checked['request_id']}-{stage}"


def _terminal_receipt(receipt: dict[str, Any], reference: Mapping[str, Any]) -> None:
    if (
        receipt.get("request_id") != reference["request_id"]
        or receipt.get("worker_finished") is not True
    ):
        raise ValueError("Terminal receipt must identify a matching finished worker")
    state = receipt.get("state")
    if state not in {"completed", "failed", "cancelled", "timed_out", "termination_unconfirmed"}:
        raise ValueError("Unsupported terminal worker state")
    resources = receipt.get("resources", {})
    if not isinstance(resources, dict) or any(
        not isinstance(row, dict)
        or row.get("state") not in {"active", "unconfirmed", "released", "terminated"}
        for row in resources.values()
    ):
        raise ValueError("Invalid terminal resource inventory")
    pending = any(row["state"] in {"active", "unconfirmed"} for row in resources.values())
    if pending and state != "termination_unconfirmed":
        raise ValueError("Unconfirmed resources cannot be declared completed or cancelled")
    if state == "completed" and receipt.get("stop_reason") is not None:
        raise ValueError("Stopped request cannot publish a completed result")


def _publish(record: dict[str, Any], files: dict[str, bytes], root: Path | None) -> dict[str, str]:
    raw = canonical_bytes(record)
    identity = _identity(record["execution_ref"], record["stage"])
    saved = record_immutable_build(
        identity,
        {"execution.json": raw, **files},
        {
            "kind": "execution-checkpoint",
            "stage": record["stage"],
            "execution_ref": record["execution_ref"],
        },
        root=root,
    )
    return {
        "format": REF_FORMAT,
        "artifact_id": identity,
        "manifest_sha256": saved["manifest_sha256"],
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }


def start_execution(
    execution_ref: Mapping[str, Any],
    *,
    tool: str,
    receipt: dict[str, Any],
    request_json: str,
    root: Path | None = None,
) -> dict[str, str]:
    reference = _execution(execution_ref)
    if not isinstance(parse_json_data(request_json), dict):
        raise ValueError("Request arguments must be a JSON object")
    if (
        receipt.get("request_id") != reference["request_id"]
        or receipt.get("worker_finished") is not False
    ):
        raise ValueError("Start receipt must identify an unfinished matching request")
    raw = request_json.encode("utf-8")
    return _publish(
        {
            "format": FORMAT,
            "stage": "started",
            "execution_ref": reference,
            "tool": tool,
            "receipt": receipt,
            "input_sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        },
        {"request.json": raw},
        root,
    )


def _load_ref(
    reference: Mapping[str, Any], root: Path | None
) -> tuple[dict[str, Any], dict[str, bytes]]:
    if set(reference) != {"format", "artifact_id", "manifest_sha256", "sha256"} or (
        reference.get("format") != REF_FORMAT
    ):
        raise ValueError("Malformed execution checkpoint reference")
    manifest, files = read_immutable_build(
        reference["artifact_id"], reference["manifest_sha256"], root=root
    )
    if "sha256:" + hashlib.sha256(files["execution.json"]).hexdigest() != reference["sha256"]:
        raise ValueError("Execution checkpoint record hash mismatch")
    record = parse_json_data(files["execution.json"].decode("utf-8"))
    if (
        not isinstance(record, dict)
        or record.get("format") != FORMAT
        or (manifest["metadata"].get("kind") != "execution-checkpoint")
    ):
        raise ValueError("Wrong execution checkpoint artifact kind or format")
    expected = _identity(record["execution_ref"], record["stage"])
    if (
        expected != reference["artifact_id"]
        or manifest["metadata"].get("stage") != record["stage"]
        or (manifest["metadata"].get("execution_ref") != record["execution_ref"])
    ):
        raise ValueError("Execution checkpoint identities disagree")
    receipt = record.get("receipt")
    if (
        not isinstance(receipt, dict)
        or receipt.get("request_id") != record["execution_ref"]["request_id"]
    ):
        raise ValueError("Execution receipt identity mismatch")
    if record["stage"] == "started":
        if receipt.get("worker_finished") is not False or "request.json" not in files:
            raise ValueError("Invalid started execution state")
        if record["input_sha256"] != "sha256:" + hashlib.sha256(files["request.json"]).hexdigest():
            raise ValueError("Started execution input hash mismatch")
    elif record["stage"] == "finished":
        _terminal_receipt(receipt, record["execution_ref"])
    else:
        raise ValueError("Unsupported execution checkpoint stage")
    return record, files


def finish_execution(
    started_ref: Mapping[str, Any],
    *,
    receipt: dict[str, Any],
    result_json: str | None = None,
    error: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, str]:
    started, _ = _load_ref(started_ref, root)
    _terminal_receipt(receipt, started["execution_ref"])
    if (
        started["stage"] != "started"
        or receipt.get("worker_finished") is not True
        or (receipt.get("request_id") != started["execution_ref"]["request_id"])
    ):
        raise ValueError("Terminal receipt must match an actually finished worker")
    if receipt.get("state") not in {
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "termination_unconfirmed",
    }:
        raise ValueError("Unsupported terminal worker state")
    if receipt["state"] == "completed" and result_json is None:
        raise ValueError("Completed checkpoint requires its exact serialized result")
    files = {}
    if result_json is not None:
        parse_json_data(result_json)
        files["result.json"] = result_json.encode("utf-8")
    return _publish(
        {
            "format": FORMAT,
            "stage": "finished",
            "execution_ref": started["execution_ref"],
            "tool": started["tool"],
            "started_ref": dict(started_ref),
            "receipt": receipt,
            "error": error,
            "result_eligible": receipt["state"] == "completed" and result_json is not None,
        },
        files,
        root,
    )


def _discover(reference: Mapping[str, Any], stage: str, root: Path | None) -> dict[str, str]:
    identity = _identity(reference, stage)
    _, files, manifest_sha = open_immutable_build(identity, root=root)
    return {
        "format": REF_FORMAT,
        "artifact_id": identity,
        "manifest_sha256": manifest_sha,
        "sha256": "sha256:" + hashlib.sha256(files["execution.json"]).hexdigest(),
    }


def recover_execution(
    execution_ref: Mapping[str, Any], *, root: Path | None = None
) -> dict[str, Any]:
    reference = _execution(execution_ref)
    started_ref = _discover(reference, "started", root)
    started, started_files = _load_ref(started_ref, root)
    if (
        started["stage"] != "started"
        or "sha256:" + hashlib.sha256(started_files["request.json"]).hexdigest()
        != started["input_sha256"]
    ):
        raise ValueError("Started execution input binding mismatch")
    result = {
        "execution_ref": reference,
        "started_ref": started_ref,
        "request_json": started_files["request.json"].decode("utf-8"),
        "tool": started["tool"],
        "state": "nonterminal_checkpoint",
        "worker_finished": "unknown",
        "result_eligible": False,
        "recovery_scope": "verified_saved_evidence_not_live_process_or_replay",
    }
    try:
        finished_ref = _discover(reference, "finished", root)
    except ArtifactUnavailableError as exc:
        result["terminal_checkpoint_status"] = "unavailable"
        result["terminal_checkpoint_diagnostic"] = str(exc)
        return result
    finished, files = _load_ref(finished_ref, root)
    if finished["stage"] != "finished" or finished["started_ref"] != started_ref:
        raise ValueError("Terminal checkpoint belongs to another start")
    receipt = finished["receipt"]
    _terminal_receipt(receipt, reference)
    eligible = receipt["state"] == "completed" and receipt["worker_finished"] is True
    if finished["result_eligible"] != eligible or (eligible and "result.json" not in files):
        raise ValueError("Terminal execution result eligibility mismatch")
    return {
        **result,
        "finished_ref": finished_ref,
        "state": receipt["state"],
        "worker_finished": receipt["worker_finished"],
        "receipt": receipt,
        "result_eligible": eligible,
        "error": finished["error"],
        "result_json": files["result.json"].decode("utf-8") if "result.json" in files else None,
    }
