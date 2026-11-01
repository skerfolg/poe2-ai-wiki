"""Spawn native work in an owned containment unit; report confirmed scope only.

Windows assigns a suspended child to a non-breakaway job before resuming it.
POSIX uses a new session/process group; deliberate group escape is not prevented.
"""

from __future__ import annotations

import ctypes
import math
import os
import signal
import subprocess
from contextlib import suppress
from threading import RLock
from time import monotonic, sleep
from typing import Any, cast

from pok.common.execution import checkpoint


class _Limits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", ctypes.c_uint32),
        ("min_working_set", ctypes.c_size_t),
        ("max_working_set", ctypes.c_size_t),
        ("active_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority", ctypes.c_uint32),
        ("scheduling", ctypes.c_uint32),
    ]


class _IO(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _Limits),
        ("io", _IO),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t),
        ("peak_job_memory", ctypes.c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_int64)
        for name in (
            "user_time",
            "kernel_time",
            "period_user_time",
            "period_kernel_time",
        )
    ] + [
        (name, ctypes.c_uint32)
        for name in (
            "page_faults",
            "total",
            "active",
            "terminated",
        )
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("usage", ctypes.c_uint32),
        ("thread_id", ctypes.c_uint32),
        ("process_id", ctypes.c_uint32),
        ("priority", ctypes.c_int32),
        ("delta_priority", ctypes.c_int32),
        ("flags", ctypes.c_uint32),
    ]


class _WindowsJob:
    def __init__(self) -> None:
        api = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
        handle, dword, boolean = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int32
        signatures = {
            "CreateJobObjectW": ([handle, ctypes.c_wchar_p], handle),
            "SetInformationJobObject": ([handle, ctypes.c_int32, handle, dword], boolean),
            "AssignProcessToJobObject": ([handle, handle], boolean),
            "TerminateJobObject": ([handle, dword], boolean),
            "QueryInformationJobObject": ([handle, ctypes.c_int32, handle, dword, handle], boolean),
            "CreateToolhelp32Snapshot": ([dword, dword], handle),
            "Thread32First": ([handle, ctypes.POINTER(_ThreadEntry)], boolean),
            "Thread32Next": ([handle, ctypes.POINTER(_ThreadEntry)], boolean),
            "OpenThread": ([dword, boolean, dword], handle),
            "ResumeThread": ([handle], dword),
            "CloseHandle": ([handle], boolean),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(api, name)
            function.argtypes, function.restype = arguments, result
        self.api = api
        self.handle = api.CreateJobObjectW(None, None)
        if not self.handle:
            self._error()
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway flags.
        if not api.SetInformationJobObject(
            self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
        ):
            error = cast(Any, ctypes).get_last_error()
            self.close()
            raise cast(Any, ctypes).WinError(error)

    @staticmethod
    def _error() -> Any:
        raise cast(Any, ctypes).WinError(cast(Any, ctypes).get_last_error())

    def assign_and_resume(self, process: subprocess.Popen[Any]) -> None:
        if not self.api.AssignProcessToJobObject(self.handle, int(cast(Any, process)._handle)):
            self._error()
        snapshot = self.api.CreateToolhelp32Snapshot(4, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            self._error()
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            threads = []
            present = self.api.Thread32First(snapshot, ctypes.byref(entry))
            while present:
                if entry.process_id == process.pid:
                    threads.append(entry.thread_id)
                present = self.api.Thread32Next(snapshot, ctypes.byref(entry))
            if len(threads) != 1:
                raise OSError("Cannot identify the suspended initial native thread")
            thread = self.api.OpenThread(2, False, threads[0])  # THREAD_SUSPEND_RESUME
            if not thread:
                self._error()
            try:
                checkpoint()
                if self.api.ResumeThread(thread) != 1:
                    raise OSError("Unexpected initial native thread suspend count")
            finally:
                self.api.CloseHandle(thread)
        finally:
            self.api.CloseHandle(snapshot)

    def active(self) -> int:
        counters = _Accounting()
        if not self.api.QueryInformationJobObject(
            self.handle, 1, ctypes.byref(counters), ctypes.sizeof(counters), None
        ):
            self._error()
        return int(counters.active)

    def members(self) -> list[int]:
        buffer = ctypes.create_string_buffer(65536)
        if not self.api.QueryInformationJobObject(self.handle, 3, buffer, len(buffer), None):
            self._error()
        count = ctypes.c_uint32.from_buffer(buffer, 4).value
        width = ctypes.sizeof(ctypes.c_size_t)
        if count > (len(buffer) - 8) // width:
            raise OSError("Owned job process inventory exceeds the response buffer")
        return [
            int(ctypes.c_size_t.from_buffer(buffer, 8 + index * width).value)
            for index in range(count)
        ]

    def terminate(self) -> None:
        if not self.api.TerminateJobObject(self.handle, 1):
            self._error()

    def close(self) -> None:
        if self.handle:
            self.api.CloseHandle(self.handle)
            self.handle = None

    def __del__(self) -> None:
        with suppress(Exception):
            self.close()


def spawn_owned(command: list[str], **kwargs: Any) -> subprocess.Popen[Any]:
    """Return a normal Popen carrying an owned job/group handle for later cleanup."""
    checkpoint()
    process: subprocess.Popen[Any] | None = None
    if os.name != "nt":
        kwargs["start_new_session"] = True
        process = subprocess.Popen(command, **kwargs)
        cast(Any, process)._pok_process_group = process.pid
        return process
    job = _WindowsJob()
    kwargs["creationflags"] = int(kwargs.get("creationflags", 0)) | 4 | 0x08000000
    process = None
    try:
        checkpoint()
        process = subprocess.Popen(command, **kwargs)
        job.assign_and_resume(process)
        cast(Any, process)._pok_windows_job = job
        return process
    except BaseException as exc:
        # A failed assignment must never leave the suspended child runnable.
        cleanup = {"status": "confirmed", "scope": "failed_spawn"}
        if process is not None:
            cast(Any, process)._pok_windows_job = job
            with suppress(OSError):
                job.terminate()
            with suppress(OSError):
                process.kill()
            try:
                process.wait(timeout=5)
                if job.active():
                    cleanup["status"] = "unconfirmed"
            except (OSError, subprocess.TimeoutExpired):
                cleanup["status"] = "unconfirmed"
        if cleanup["status"] == "confirmed":
            if process is not None:
                cast(Any, process)._pok_tree_confirmed = True
            job.close()
        if process is not None:
            cast(Any, exc).owned_process = process
        cast(Any, exc).owned_cleanup = cleanup
        exc.add_note(f"Owned native spawn cleanup: {cleanup['status']}")
        raise


def terminate_owned(process: subprocess.Popen[Any], *, timeout_s: float = 5) -> dict[str, Any]:
    """Terminate only this launch's job/group and verify the registered scope."""
    if not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("Cleanup timeout must be finite and positive")
    lock = process.__dict__.setdefault("_pok_cleanup_lock", RLock())
    started = monotonic()
    if not lock.acquire(timeout=timeout_s):
        return {"status": "unconfirmed", "scope": "cleanup_in_progress"}
    try:
        return _terminate_locked(process, timeout_s=max(timeout_s - (monotonic() - started), 0.001))
    finally:
        lock.release()


def _terminate_locked(process: subprocess.Popen[Any], *, timeout_s: float) -> dict[str, Any]:
    job = getattr(process, "_pok_windows_job", None)
    group = getattr(process, "_pok_process_group", None)
    scope = "windows_job" if job is not None else "posix_process_group" if group else "direct_child"
    if getattr(process, "_pok_tree_confirmed", False):
        return {"status": "confirmed", "scope": scope}
    deadline = monotonic() + timeout_s
    try:
        if job is not None:
            job.terminate()
        elif group is not None:
            if process.returncode is not None:
                try:
                    cast(Any, os).killpg(group, 0)
                except ProcessLookupError:
                    cast(Any, process)._pok_tree_confirmed = True
                    return {"status": "confirmed", "scope": scope}
                return {
                    "status": "unconfirmed",
                    "scope": scope,
                    "reason": "Reaped leader cannot prove ownership of a still-existing group",
                }
            with suppress(ProcessLookupError):
                cast(Any, os).killpg(group, cast(Any, signal).SIGKILL)
        else:
            with suppress(OSError):
                process.kill()
        process.wait(timeout=max(deadline - monotonic(), 0.001))
        while job is not None and job.active():
            if monotonic() >= deadline:
                raise TimeoutError("Owned job still has active processes")
            sleep(0.01)
        if group is not None:
            while True:
                try:
                    cast(Any, os).killpg(group, 0)
                except ProcessLookupError:
                    break
                if monotonic() >= deadline:
                    raise TimeoutError("Owned process group still exists")
                sleep(0.01)
    except (OSError, subprocess.TimeoutExpired, TimeoutError) as exc:
        return {"status": "unconfirmed", "scope": scope, "reason": str(exc)}
    cast(Any, process)._pok_tree_confirmed = True
    if job is not None:
        job.close()
    return {
        "status": "confirmed",
        "scope": scope,
        "deliberate_posix_group_escape": "not_prevented" if group else "not_applicable",
    }
