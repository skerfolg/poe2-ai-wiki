"""Single-use driver timeouts do not drain descendant-owned output pipes."""

import json
import os
import subprocess
import sys
from threading import Timer
from time import monotonic, sleep

import pytest

from pok.pob import runner
from pok.pob.versions import PobSnapshot


def test_timeout_returns_before_descendant_closes_output_and_preserves_partial(
    tmp_path, monkeypatch
):
    original_run = runner._run_owned_driver
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path)
    monkeypatch.setattr(runner, "find_luajit", lambda: "unused-luajit")
    finished = tmp_path / "descendant-finished"
    ready = tmp_path / "parent-ready"
    descendant = (
        "import time; from pathlib import Path; time.sleep(15); "
        f"Path({str(finished)!r}).write_text('done')"
    )
    parent = (
        "import subprocess,sys,time; from pathlib import Path; "
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]); "
        "print('partial native output',flush=True); "
        "print('partial native error',file=sys.stderr,flush=True); "
        f"Path({str(ready)!r}).write_text('ready'); time.sleep(30)"
    )

    def injected_driver(args, **kwargs):
        kwargs["timeout"] = 0.7
        return original_run([sys.executable, "-c", parent], **kwargs)

    monkeypatch.setattr(runner, "_run_owned_driver", injected_driver)
    original_spawn = runner.spawn_owned
    ready_time = []

    def synchronize_startup(*args, **kwargs):
        child = original_spawn(*args, **kwargs)
        deadline = monotonic() + 5
        while not ready.exists() and monotonic() < deadline:
            sleep(0.02)
        if not ready.exists():
            runner.terminate_owned(child)
            raise AssertionError("Native helper did not reach its output marker")
        ready_time.append(monotonic())
        return child

    monkeypatch.setattr(runner, "spawn_owned", synchronize_startup)
    try:
        with pytest.raises(subprocess.TimeoutExpired) as failure:
            runner.run_xml("<test/>", snapshot=PobSnapshot("fixture", tmp_path, tmp_path))
        assert monotonic() - ready_time[0] < 7
        assert b"partial native output" in failure.value.output
        assert b"partial native error" in failure.value.stderr
        assert not list((tmp_path / "pob-cache").iterdir())
        assert failure.value.owned_cleanup["scope"] == (
            "windows_job" if os.name == "nt" else "posix_process_group"
        )
        if os.name == "nt":
            assert failure.value.owned_cleanup["status"] == "confirmed"
    finally:
        # Containment cleanup stops the descendant before its later write.
        assert not finished.exists()


@pytest.mark.parametrize("success", [True, False])
def test_file_output_keeps_utf8_protocol_and_native_errors(tmp_path, monkeypatch, success):
    original_run = runner._run_owned_driver
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path)
    monkeypatch.setattr(runner, "find_luajit", lambda: "unused-luajit")
    protocol = (
        "POK_META:"
        + json.dumps({"name": "한글 장비"}, ensure_ascii=False)
        + '\nPOK_ALLOC:[]\nPOK_JSON:{"Life":123}\nPOK_OK\n'
    )
    script = (
        f"import sys; sys.stdout.buffer.write({protocol.encode('utf-8')!r})"
        if success
        else "import sys; sys.stderr.buffer.write('한글 오류'.encode('utf-8')); sys.exit(2)"
    )

    def injected_driver(args, **kwargs):
        return original_run([sys.executable, "-c", script], **kwargs)

    monkeypatch.setattr(runner, "_run_owned_driver", injected_driver)
    if success:
        result = runner._run_driver("<test/>", PobSnapshot("fixture", tmp_path, tmp_path), 5)
        assert result["meta"] == {"name": "한글 장비"}
        assert result["stats"] == {"Life": 123}
    else:
        with pytest.raises(runner.PobRunError, match="한글 오류"):
            runner._run_driver("<test/>", PobSnapshot("fixture", tmp_path, tmp_path), 5)
    assert not list((tmp_path / "pob-cache").iterdir())


@pytest.mark.parametrize("stop", ["cancel", "deadline"])
def test_scoped_driver_stops_its_child_and_keeps_partial_output(tmp_path, monkeypatch, stop):
    from pok.common.execution import ExecutionScope, ExecutionStopped, bind_execution

    driver = tmp_path / "scoped-driver.py"
    ready = tmp_path / "driver-ready"
    driver.write_text(
        "import time\nfrom pathlib import Path\nprint('partial', flush=True)\n"
        f"Path({str(ready)!r}).write_text('ready')\ntime.sleep(10)\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path)
    monkeypatch.setattr(runner, "project_root", lambda: tmp_path)
    monkeypatch.setattr(runner, "_DRIVER", driver.name)
    monkeypatch.setattr(runner, "find_luajit", lambda: sys.executable)
    original_popen = subprocess.Popen
    children = []

    def observe_child(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child

    monkeypatch.setattr(runner.subprocess, "Popen", observe_child)
    scope = ExecutionScope("scoped-driver", 10 if stop == "cancel" else 0.4)

    def cancel_after_output():
        deadline = monotonic() + 5
        while not ready.exists() and monotonic() < deadline:
            sleep(0.02)
        scope.request_cancel()

    cancel = Timer(0.05, cancel_after_output)
    if stop == "cancel":
        cancel.start()
    try:
        with bind_execution(scope), pytest.raises(ExecutionStopped) as failure:
            runner.run_xml("<test/>", snapshot=PobSnapshot("fixture", tmp_path, tmp_path))
        # A startup deadline may legitimately fire before the child prints.
        if stop == "cancel":
            assert ready.exists()
            assert "partial" in failure.value.details["native_stdout"]
        assert len(children) == 1 and children[0].poll() is not None
        assert scope.finish()["state"] == ("cancelled" if stop == "cancel" else "timed_out")
        assert not list((tmp_path / "pob-cache").iterdir())
        assert not scope._retained
    finally:
        cancel.cancel()
        if stop == "cancel":
            cancel.join(timeout=6)
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


def test_scoped_driver_retains_unconfirmed_native_handle(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from pok.common.execution import ExecutionScope, bind_execution

    def cannot_wait(**kwargs):
        raise subprocess.TimeoutExpired("fake-child", 5)

    child = SimpleNamespace(pid=12345, wait=cannot_wait, kill=lambda: None)
    monkeypatch.setattr(runner, "spawn_owned", lambda *args, **kwargs: child)
    scope = ExecutionScope("unconfirmed-native", 10)
    with bind_execution(scope), pytest.raises(subprocess.TimeoutExpired):
        runner._run_owned_driver(["unused"], timeout=0.001)
    assert scope.finish(failed=True)["state"] == "termination_unconfirmed"
    assert list(scope._retained.values()) == [child]
