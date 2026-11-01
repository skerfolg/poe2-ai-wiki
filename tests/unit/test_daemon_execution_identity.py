"""Startup evidence belongs to one process, not the newest files on disk."""

import copy
from io import StringIO

from pok.pob import daemon as module
from pok.pob.versions import PobSnapshot


class Child:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None
        self.stdin = StringIO()
        self.stdout = StringIO(
            'POK_READY\nPOK_META:{"level":90}\nPOK_ALLOC:[]\nPOK_JSON:{"Life":100}\nPOK_DONE\n'
        )

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9

    def wait(self, **kwargs):
        self.returncode = self.returncode if self.returncode is not None else 0
        return self.returncode


def test_disk_changes_do_not_relabel_live_startup_and_restart_gets_new_evidence(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(module, "var_dir", lambda: tmp_path)
    monkeypatch.setattr(module, "find_luajit", lambda: "unused")
    current = {"status": "observed", "sha256": "original"}
    daemon = module.PobDaemon(PobSnapshot("test", tmp_path, tmp_path))
    monkeypatch.setattr(daemon, "_observe_inputs", lambda: current)
    children = []

    def spawn(*args, **kwargs):
        child = Child(len(children) + 1)
        children.append(child)
        return child

    monkeypatch.setattr(module, "spawn_owned", spawn)
    daemon.start()
    initial = daemon.inspect_execution()
    assert initial["startup"]["status"] == "stable_observation"
    assert initial["process_state"] == "running"
    original = copy.deepcopy(initial["startup"])
    current["sha256"] = "new-disk"
    inspected = daemon.inspect_execution(observe_current=True)
    assert inspected["current_matches_startup"] is False
    assert inspected["startup"] == original
    inspected["startup"]["before"]["sha256"] = "caller-mutated"
    assert daemon.inspect_execution()["startup"] == original
    computed = daemon.compute("<input/>")
    assert computed.meta["daemon_execution"]["startup"] == original
    assert computed.meta["daemon_execution"]["current_disk"] == "not_sampled"
    daemon.close()
    stopped = daemon.inspect_execution()
    assert stopped["process_state"] == "stopped"
    assert stopped["last_startup"] == original
    daemon.start()
    restarted = daemon.inspect_execution()
    assert restarted["startup"]["after"]["sha256"] == "new-disk"
    assert restarted["startup"]["generation"] != original["generation"]
    daemon.close()


def test_inspection_does_not_initialize_shared_process(monkeypatch):
    monkeypatch.setattr(module, "_SHARED", None)

    def forbidden_start():
        raise AssertionError("Inspection must not create a native process")

    monkeypatch.setattr(module, "shared_daemon", forbidden_start)
    result = module.inspect_shared_execution(observe_current=True)
    assert result["status"] == "not_started"
    assert result["started_by_inspection"] is False


def test_exited_process_is_restarted_instead_of_reusing_old_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "find_luajit", lambda: "unused")
    daemon = module.PobDaemon(PobSnapshot("test", tmp_path, tmp_path))
    monkeypatch.setattr(daemon, "_observe_inputs", lambda: {"status": "observed", "sha256": "same"})
    children = []

    def spawn(*args, **kwargs):
        child = Child(len(children) + 1)
        children.append(child)
        return child

    monkeypatch.setattr(module, "spawn_owned", spawn)
    daemon.start()
    old = daemon.inspect_execution()["startup"]["generation"]
    children[0].kill()
    assert daemon.inspect_execution()["process_state"] == "exited"
    daemon.start()
    assert len(children) == 2
    assert daemon.inspect_execution()["startup"]["generation"] != old
    daemon.close()


def test_registered_runtime_inspection_does_not_create_a_process(monkeypatch):
    import asyncio

    from fastmcp import Client, FastMCP

    from pok.mcp import server

    api = FastMCP("inspect-existing-runtime")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(module, "_SHARED", None)
    server.tool(server.inspect_pob_runtime.__wrapped__)

    async def exercise():
        async with Client(api) as client:
            result = await client.call_tool("inspect_pob_runtime", {"observe_current": True})
            assert result.data["status"] == "not_started"
            assert result.data["started_by_inspection"] is False

    asyncio.run(exercise())


def test_shared_inspection_does_not_wait_for_another_command_owner(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    daemon = module.PobDaemon(PobSnapshot("test", tmp_path, tmp_path))
    monkeypatch.setattr(module, "_SHARED", daemon)
    entered, release = Event(), Event()

    def owner():
        with daemon._lock:
            entered.set()
            assert release.wait(3)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(owner)
        try:
            assert entered.wait(2)
            result = module.inspect_shared_execution(observe_current=True)
            assert result["status"] == "busy"
            assert result["started_by_inspection"] is False
        finally:
            release.set()
        future.result(timeout=2)
