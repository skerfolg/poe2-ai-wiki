"""Cooperative request ownership and absolute deadlines, without build decisions.

Stopping a request and confirming its native resources stopped are separate facts.
The transport owns the scope; adapters report their actual resource disposition.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from time import monotonic, time
from typing import Any
from uuid import uuid4


class ExecutionStopped(BaseException):
    """Control flow must not be swallowed by ordinary calculator fallback handlers."""

    def __init__(self, request_id: str, reason: str) -> None:
        self.request_id = request_id
        self.reason = reason
        self.details: dict[str, Any] = {}
        super().__init__(f"Request {request_id} stopped: {reason}")


class ExecutionScope:
    def __init__(
        self,
        owner: str,
        timeout_s: float,
        *,
        input_revision: str | None = None,
        request_id: str | None = None,
    ) -> None:
        if not owner or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("An owner and a finite positive request timeout are required")
        self.request_id = request_id or uuid4().hex
        self.owner = owner
        self.input_revision = input_revision
        self.started = monotonic()
        self.started_at_unix_s = time()
        self.timeout_s = timeout_s
        self._deadline = self.started + timeout_s
        self._lock = RLock()
        self._reason: str | None = None
        self._finished = False
        self._outcome: str | None = None
        self._resources: dict[str, dict[str, Any]] = {}
        self._retained: dict[str, Any] = {}

    @property
    def deadline(self) -> float:
        return self._deadline

    def _expire(self) -> None:
        if self._reason is None and not self._finished and monotonic() >= self.deadline:
            self._reason = "deadline_exceeded"

    def request_cancel(self) -> None:
        with self._lock:
            self._expire()
            if not self._finished and self._reason is None:
                self._reason = "cancel_requested"

    def checkpoint(self) -> None:
        with self._lock:
            self._expire()
            if self._reason is not None:
                raise ExecutionStopped(self.request_id, self._reason)
            if self._finished:
                raise RuntimeError("A finished request cannot continue work")

    def acquire_resource(self, key: str, *, kind: str, identity: str, handle: Any = None) -> None:
        with self._lock:
            if self._finished:
                raise RuntimeError("A finished request cannot acquire resources")
            previous = self._resources.get(key)
            if previous and previous["state"] == "unconfirmed":
                raise RuntimeError("Cannot reuse a resource with unconfirmed termination")
            self._resources[key] = {"kind": kind, "identity": identity, "state": "active"}
            if handle is not None:
                self._retained[key] = handle

    def release_resource(
        self, key: str, *, state: str = "released", details: dict[str, Any] | None = None
    ) -> None:
        if state not in {"released", "terminated", "unconfirmed"}:
            raise ValueError("Unsupported resource disposition")
        with self._lock:
            resource = self._resources.get(key)
            if resource is not None:
                # A generic finally must not erase an explicit termination fact.
                if resource["state"] in {"unconfirmed", "terminated"} and state == "released":
                    return
                resource["state"] = state
                if details is not None:
                    resource["details"] = copy.deepcopy(details)
                if state != "unconfirmed":
                    self._retained.pop(key, None)

    def finish(self, *, failed: bool = False) -> dict[str, Any]:
        with self._lock:
            if not self._finished:
                self._expire()
                self._finished = True
                pending = any(
                    row["state"] in {"active", "unconfirmed"} for row in self._resources.values()
                )
                self._outcome = (
                    "termination_unconfirmed"
                    if pending
                    else "timed_out"
                    if self._reason == "deadline_exceeded"
                    else "cancelled"
                    if self._reason == "cancel_requested"
                    else "failed"
                    if failed
                    else "completed"
                )
            return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._expire()
            return {
                "format": "pok.execution-scope.v1",
                "request_id": self.request_id,
                "owner": self.owner,
                "input_revision": self.input_revision,
                "timeout_s": self.timeout_s,
                "started_at_unix_s": self.started_at_unix_s,
                "deadline_at_unix_s": self.started_at_unix_s + self.timeout_s,
                "worker_finished": self._finished,
                "stop_reason": self._reason,
                "state": self._outcome or self._reason or "running",
                "resources": copy.deepcopy(self._resources),
                "confirmation_scope": "registered_resources_only",
            }


_CURRENT: ContextVar[ExecutionScope | None] = ContextVar("pok_execution_scope", default=None)


def current_execution() -> ExecutionScope | None:
    return _CURRENT.get()


def checkpoint() -> None:
    if (scope := current_execution()) is not None:
        scope.checkpoint()


def remaining_timeout(limit: float) -> float:
    if not math.isfinite(limit) or limit <= 0:
        raise ValueError("Timeout must be finite and positive")
    if (scope := current_execution()) is None:
        return limit
    scope.checkpoint()
    return min(limit, max(scope.deadline - monotonic(), 1e-9))


@contextmanager
def bind_execution(scope: ExecutionScope) -> Iterator[ExecutionScope]:
    previous = current_execution()
    if previous is not None and previous is not scope:
        raise RuntimeError("A nested request cannot replace its owner's deadline")
    scope.checkpoint()
    token = _CURRENT.set(scope)
    try:
        yield scope
    finally:
        _CURRENT.reset(token)
