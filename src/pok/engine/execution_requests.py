"""Process-local request supervision; transport types and build policy stay outside.

Opaque refs address one server incarnation. Missing history is not completion.
Native adapters cooperate with ExecutionScope; arbitrary Python is not preempted.
"""

from __future__ import annotations

import asyncio
import math
import re
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from time import monotonic
from typing import Any
from uuid import uuid4

import anyio

from pok.common.execution import ExecutionScope, ExecutionStopped, bind_execution
from pok.engine import execution_journal


class RequestExecutionError(RuntimeError):
    def __init__(self, reference: dict[str, str], receipt: dict[str, Any]) -> None:
        self.reference = reference
        self.receipt = receipt
        super().__init__(f"Execution {reference['request_id']}: {receipt['state']}")


@dataclass
class _Entry:
    scope: ExecutionScope
    tool: str
    reference: dict[str, str]
    result: Any = None
    result_available: bool = False
    error: dict[str, Any] | None = None
    started_ref: dict[str, str] | None = None
    finished_ref: dict[str, str] | None = None
    persistence_error: str | None = None


class RequestManager:
    def __init__(
        self,
        *,
        capacity: int = 1024,
        cleanup_grace_s: float = 5,
        persist: bool = False,
        root: Path | None = None,
    ) -> None:
        if (
            type(capacity) is not int
            or capacity < 1
            or not math.isfinite(cleanup_grace_s)
            or (cleanup_grace_s < 0)
        ):
            raise ValueError("Execution capacity and cleanup grace are invalid")
        self.instance = uuid4().hex
        self.capacity = capacity
        self.cleanup_grace_s = cleanup_grace_s
        self.persist = persist
        self.root = root
        self._lock = RLock()
        self._entries: dict[str, _Entry] = {}
        self._issued_ids: set[str] = set()
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    def _lookup(self, reference: Mapping[str, Any]) -> _Entry:
        if set(reference) != {"format", "server_instance", "request_id"} or (
            reference.get("format") != "pok.execution-ref.v1"
            or reference.get("server_instance") != self.instance
        ):
            raise ValueError("Execution ref belongs to another server or has an unsupported format")
        with self._lock:
            entry = self._entries.get(reference["request_id"])
        if entry is None:
            raise ValueError("Execution is unavailable; absence does not prove completion")
        return entry

    def status(self, reference: Mapping[str, Any]) -> dict[str, Any]:
        entry = self._lookup(reference)
        receipt = entry.scope.snapshot()
        return {
            "execution_ref": dict(entry.reference),
            "tool": entry.tool,
            **receipt,
            "result_available": entry.result_available and receipt["state"] == "completed",
            "error": entry.error,
            "persistence": {
                "enabled": self.persist,
                "started_ref": entry.started_ref,
                "finished_ref": entry.finished_ref,
                "error": entry.persistence_error,
            },
        }

    def cancel(self, reference: Mapping[str, Any]) -> dict[str, Any]:
        entry = self._lookup(reference)
        entry.scope.request_cancel()
        return self.status(reference)

    def result(self, reference: Mapping[str, Any]) -> Any:
        entry = self._lookup(reference)
        if entry.scope.snapshot()["state"] != "completed" or not entry.result_available:
            raise ValueError("No completed result is available; inspect execution status")
        return entry.result

    async def run(
        self,
        operation: Callable[[], Any],
        *,
        owner: str,
        tool: str,
        timeout_s: float,
        request_id: str | None = None,
        input_revision: str | None = None,
        request_json: str | None = None,
        result_encoder: Callable[[Any, dict[str, str]], str] | None = None,
    ) -> tuple[Any, dict[str, str]]:
        identity = request_id or uuid4().hex
        if self.persist and (request_json is None or result_encoder is None):
            raise ValueError("Persistent requests require explicit input JSON and a result encoder")
        if not isinstance(identity, str) or not re.fullmatch(r"[a-f0-9]{32}", identity):
            raise ValueError("Execution request_id must be 32 lowercase hexadecimal characters")
        scope = ExecutionScope(owner, timeout_s, input_revision=input_revision, request_id=identity)
        reference = {
            "format": "pok.execution-ref.v1",
            "server_instance": self.instance,
            "request_id": identity,
        }
        entry = _Entry(scope, tool, reference)
        with self._lock:
            if identity in self._issued_ids:
                raise ValueError("Execution request_id already exists; inspect its original result")
            while len(self._entries) >= self.capacity:
                removable = next(
                    (
                        key
                        for key, value in self._entries.items()
                        if (
                            value.scope.snapshot()["worker_finished"]
                            and value.scope.snapshot()["state"] != "termination_unconfirmed"
                        )
                    ),
                    None,
                )
                if removable is None:
                    raise RuntimeError("Execution capacity is occupied by unfinished resources")
                del self._entries[removable]
            self._entries[identity] = entry
            self._issued_ids.add(identity)

        def work() -> Any:
            failed = False
            try:
                if self.persist:
                    assert request_json is not None
                    try:
                        entry.started_ref = execution_journal.start_execution(
                            reference,
                            tool=tool,
                            receipt=scope.snapshot(),
                            request_json=request_json,
                            root=self.root,
                        )
                    except Exception as exc:
                        entry.persistence_error = f"Start checkpoint unavailable: {exc}"
                        raise
                with bind_execution(scope):
                    value = operation()
                    scope.checkpoint()
                entry.result = value
                entry.result_available = True
                return value
            except ExecutionStopped as exc:
                failed = True
                entry.error = {
                    "type": "ExecutionStopped",
                    "reason": exc.reason,
                    "details": exc.details,
                    "notes": getattr(exc, "__notes__", []),
                }
                raise RequestExecutionError(reference, scope.snapshot()) from None
            except Exception as exc:
                failed = True
                entry.error = {"type": type(exc).__name__, "message": str(exc)}
                raise
            except BaseException:
                failed = True
                raise
            finally:
                receipt = scope.finish(failed=failed)
                if receipt["state"] != "completed":
                    entry.result_available = False
                if entry.started_ref is not None:
                    try:
                        serialized = (
                            result_encoder(entry.result, reference)
                            if entry.result_available and result_encoder is not None
                            else None
                        )
                        entry.finished_ref = execution_journal.finish_execution(
                            entry.started_ref,
                            receipt=receipt,
                            result_json=serialized,
                            error=entry.error,
                            root=self.root,
                        )
                    except Exception as exc:
                        entry.persistence_error = f"Terminal checkpoint unavailable: {exc}"

        # Existing adapters report progress with anyio.from_thread.run; retain
        # the framework's worker-thread context while supervising cancellation.
        task = asyncio.create_task(anyio.to_thread.run_sync(work, abandon_on_cancel=True))
        self._tasks[identity] = task

        def done(completed: asyncio.Task[Any]) -> None:
            self._tasks.pop(identity, None)
            if not completed.cancelled():
                completed.exception()  # Observe failures even after transport cancellation.

        task.add_done_callback(done)
        try:
            value = await asyncio.wait_for(
                asyncio.shield(task), timeout=max(scope.deadline - monotonic(), 1e-9)
            )
        except TimeoutError:
            if task.done() and not task.cancelled() and (error := task.exception()) is not None:
                raise error from None
            scope.snapshot()  # Record absolute expiry; never reset its deadline.
            await asyncio.wait({task}, timeout=self.cleanup_grace_s)
            raise RequestExecutionError(reference, scope.snapshot()) from None
        except asyncio.CancelledError:
            scope.request_cancel()
            # A repeated transport cancel does not cancel the native owner thread.
            with suppress(asyncio.CancelledError):
                await asyncio.shield(asyncio.wait({task}, timeout=self.cleanup_grace_s))
            raise
        except RequestExecutionError:
            raise RequestExecutionError(reference, scope.snapshot()) from None
        if scope.snapshot()["state"] != "completed":
            raise RequestExecutionError(reference, scope.snapshot())
        if entry.persistence_error is not None:
            raise RuntimeError(
                f"Execution {identity} finished, but durable checkpoint failed; "
                "inspect live status: " + entry.persistence_error
            )
        return value, reference

    def recover(self, reference: Mapping[str, Any]) -> dict[str, Any]:
        return execution_journal.recover_execution(reference, root=self.root)
