"""Absolute native deadlines, owned termination and clean daemon recovery."""

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Timer
from time import monotonic
from types import SimpleNamespace

import pytest

from pok.pob.daemon import PobCommandTimeout, PobDaemon
from pok.pob.versions import PobSnapshot


def test_heartbeats_do_not_extend_deadline_and_owned_child_is_reaped(tmp_path, monkeypatch):
    from pok.pob import daemon as module

    monkeypatch.setattr(module, "var_dir", lambda: tmp_path)
    daemon = PobDaemon(PobSnapshot("test", tmp_path, tmp_path), command_timeout_s=0.3)
    child = subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            "import time\nwhile True:\n print('heartbeat', flush=True)\n time.sleep(.02)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    daemon._proc = child
    before = monotonic()
    try:
        with pytest.raises(PobCommandTimeout) as failure:
            daemon.compute("<PathOfBuilding2/>")
        assert failure.value.phase == "native_response"
        assert failure.value.termination == "direct_child_confirmed"
        assert monotonic() - before < 6
        assert child.poll() is not None
        assert daemon._proc is None
        assert daemon.loaded_spec is None
        assert not list((tmp_path / "pob-cache").iterdir())
        assert daemon._reader is None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_lock_wait_timeout_never_terminates_other_owner(tmp_path):
    daemon = PobDaemon(PobSnapshot("test", tmp_path, tmp_path), command_timeout_s=0.05)
    killed = Event()
    daemon._proc = SimpleNamespace(kill=killed.set)
    with daemon._lock, ThreadPoolExecutor(max_workers=1) as executor:
        waiting = executor.submit(daemon.compute, "unused")
        with pytest.raises(PobCommandTimeout) as failure:
            waiting.result(timeout=2)
        assert failure.value.phase == "lock_wait"
        assert failure.value.termination == "not_owned"
        assert not killed.is_set()


def test_unconfirmed_child_is_retained_and_cannot_be_reused(tmp_path, monkeypatch):
    from pok.pob.runner import PobRunError

    daemon = PobDaemon(PobSnapshot("test", tmp_path, tmp_path), command_timeout_s=0.05)

    def cannot_wait(**kwargs):
        raise subprocess.TimeoutExpired("test", 5)

    child = SimpleNamespace(kill=lambda: None, wait=cannot_wait)
    daemon._proc = child
    with daemon._lock:
        assert daemon._abort_owned() == "unconfirmed"
    assert daemon._proc is child
    with pytest.raises(PobRunError, match="unconfirmed"):
        daemon.start()
    child.wait = lambda **kwargs: 0
    child.stdin = None
    daemon.close()
    assert daemon._proc is None
    assert not daemon._broken


def test_postprocessing_cannot_return_success_past_command_deadline(tmp_path, monkeypatch):
    from pok.pob import daemon as module

    daemon = PobDaemon(PobSnapshot("test", tmp_path, tmp_path), command_timeout_s=1)
    now = [0.0]
    monkeypatch.setattr(module, "monotonic", lambda: now[0])

    @module._exclusive
    def command(self):
        now[0] = 2.0
        return "too late"

    with pytest.raises(PobCommandTimeout) as failure:
        command(daemon)
    assert failure.value.termination == "no_process"
    assert "termination=no_process" in str(failure.value)


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_request_scope_stops_owned_native_command_and_confirms_cleanup(tmp_path, monkeypatch, stop):
    from pok.common.execution import ExecutionScope, ExecutionStopped, bind_execution
    from pok.pob import daemon as module

    monkeypatch.setattr(module, "var_dir", lambda: tmp_path)
    daemon = PobDaemon(PobSnapshot("test", tmp_path, tmp_path))
    child = subprocess.Popen(
        [sys.executable, "-u", "-c", "import time; time.sleep(10)"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
    )
    daemon._proc = child
    scope = ExecutionScope("test/request", 10 if stop == "cancel" else 0.2)
    cancel = Timer(0.2, scope.request_cancel)
    if stop == "cancel":
        cancel.start()
    try:
        with bind_execution(scope), pytest.raises(ExecutionStopped) as failure:
            daemon.compute("<test/>")
        assert failure.value.reason == (
            "cancel_requested" if stop == "cancel" else "deadline_exceeded"
        )
        assert child.poll() is not None
        assert scope.finish()["state"] == ("cancelled" if stop == "cancel" else "timed_out")
        assert all(row["state"] != "active" for row in scope.snapshot()["resources"].values())
        assert daemon._proc is None
    finally:
        cancel.cancel()
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
