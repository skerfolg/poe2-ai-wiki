"""Actual native containment: descendants, separate owners and failed assignment."""

import os
import subprocess
import sys
from time import monotonic, sleep

import pytest

from pok.common import owned_process as module


def wait_file(path):
    deadline = monotonic() + 10
    while not path.exists() and monotonic() < deadline:
        sleep(0.02)
    assert path.exists(), "Owned helper did not reach its ready marker"


def test_owned_root_termination_and_retry_are_confirmed():
    process = module.spawn_owned(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        result = module.terminate_owned(process)
        assert result["status"] == "confirmed"
        assert process.poll() is not None
        assert module.terminate_owned(process)["status"] == "confirmed"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_concurrent_cleanup_of_same_owner_is_idempotent():
    from concurrent.futures import ThreadPoolExecutor

    process = module.spawn_owned(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(module.terminate_owned, process)
            second = executor.submit(module.terminate_owned, process)
            assert first.result(timeout=10)["status"] == "confirmed"
            assert second.result(timeout=10)["status"] == "confirmed"
    finally:
        module.terminate_owned(process)


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object containment")
def test_windows_job_contains_grandchildren_and_does_not_stop_other_owner(tmp_path):
    marker = tmp_path / "child.json"
    ready = tmp_path / "grandchild.json"
    child = (
        "import subprocess,sys,time; from pathlib import Path; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"Path({str(ready)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    first = module.spawn_owned(
        [sys.executable, "-c", parent],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    other = module.spawn_owned(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        wait_file(marker)
        wait_file(ready)
        assert int(marker.read_text()) > 0 and int(ready.read_text()) > 0
        assert first._pok_windows_job.active() >= 3
        members = first._pok_windows_job.members()
        assert int(marker.read_text()) in members and int(ready.read_text()) in members
        assert not set(members).intersection(other._pok_windows_job.members())
        result = module.terminate_owned(first)
        assert result == {
            "status": "confirmed",
            "scope": "windows_job",
            "deliberate_posix_group_escape": "not_applicable",
        }
        assert other.poll() is None
        assert other._pok_windows_job.active() > 0
    finally:
        module.terminate_owned(first)
        assert module.terminate_owned(other)["status"] == "confirmed"


@pytest.mark.skipif(os.name != "nt", reason="Windows suspended assignment")
def test_assignment_failure_does_not_execute_child_code(tmp_path, monkeypatch):
    marker = tmp_path / "must-not-run"
    original = module._WindowsJob.assign_and_resume
    children = []

    def rejected(self, process):
        children.append(process)
        raise OSError("injected job assignment failure")

    monkeypatch.setattr(module._WindowsJob, "assign_and_resume", rejected)
    with pytest.raises(OSError, match="injected job assignment") as failure:
        module.spawn_owned(
            [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('bad')",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    assert failure.value.owned_cleanup["status"] == "confirmed"
    assert children[0].poll() is not None
    assert not marker.exists()
    monkeypatch.setattr(module._WindowsJob, "assign_and_resume", original)


@pytest.mark.skipif(os.name != "nt", reason="Windows kill-on-job-close")
def test_owner_process_exit_closes_job_and_stops_its_child(tmp_path):
    import ctypes
    from pathlib import Path

    marker = tmp_path / "owned-child-pid"
    executable = getattr(sys, "_base_executable", sys.executable)
    source = str(Path(__file__).resolve().parents[2] / "src")
    script = (
        f"import sys; sys.path.insert(0,{source!r}); "
        "import time,subprocess; from pathlib import Path; "
        "from pok.common.owned_process import spawn_owned; "
        f"p=spawn_owned([{executable!r},'-c','import time; time.sleep(30)'],"
        "stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL); "
        f"Path({str(marker)!r}).write_text(str(p.pid)); time.sleep(30)"
    )
    owner = subprocess.Popen(
        [executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=0x08000000,
    )
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint32]
    api.OpenProcess.restype = ctypes.c_void_p
    api.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.WaitForSingleObject.restype = ctypes.c_uint32
    api.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    api.TerminateProcess.restype = ctypes.c_int32
    api.CloseHandle.argtypes = [ctypes.c_void_p]
    api.CloseHandle.restype = ctypes.c_int32
    child = None
    try:
        wait_file(marker)
        child = api.OpenProcess(0x100001, False, int(marker.read_text()))
        assert child
        owner.kill()
        owner.wait(timeout=5)
        assert api.WaitForSingleObject(child, 5000) == 0
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=5)
        if child:
            if api.WaitForSingleObject(child, 0) != 0:
                api.TerminateProcess(child, 1)
                api.WaitForSingleObject(child, 5000)
            api.CloseHandle(child)
