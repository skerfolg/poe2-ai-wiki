"""PoB 요청·파생 캐시의 파일 소유권과 응답 경계를 보존한다."""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Event, RLock
from types import SimpleNamespace

import pytest

from pok.pob import daemon as daemon_mod
from pok.pob import runner
from pok.pob.buildxml import BuildSpec
from pok.pob.versions import PobSnapshot

STDOUT = 'POK_META:{"level":90}\nPOK_ALLOC:[]\nPOK_JSON:{"Life":1187}\nPOK_OK\n'


def test_identical_driver_requests_do_not_delete_each_others_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path)
    monkeypatch.setattr(runner, "find_luajit", lambda: "fake-luajit")
    first_reading, second_reading, release_second = Event(), Event(), Event()
    paths: list[Path] = []

    def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        path = Path(args[-1])
        paths.append(path)
        if len(paths) == 1:
            first_reading.set()
            assert second_reading.wait(5)
        else:
            second_reading.set()
            assert release_second.wait(5)
        assert path.read_text(encoding="utf-8") == "<same-input/>"
        return subprocess.CompletedProcess(args, 0, STDOUT, "")

    monkeypatch.setattr(runner.subprocess, "run", run)
    snapshot = PobSnapshot("fixture", tmp_path, tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(runner._run_driver, "<same-input/>", snapshot, 10)
        assert first_reading.wait(5)
        second = pool.submit(runner._run_driver, "<same-input/>", snapshot, 10)
        try:
            assert first.result(timeout=5)["stats"] == {"Life": 1187}
        finally:
            release_second.set()
        assert second.result(timeout=5)["stats"] == {"Life": 1187}
    assert len(set(paths)) == 2
    assert not any(path.exists() for path in paths)


def test_cache_reader_never_observes_an_unfinished_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path)
    snapshot = PobSnapshot("fixture", tmp_path, tmp_path)
    payload = {"meta": {"level": 90}, "alloc": [], "stats": {"Life": 1187}}
    monkeypatch.setattr(runner, "_run_driver", lambda *args: payload)
    original_write = Path.write_text
    halfway, finish_write = Event(), Event()
    write_paths: list[Path] = []

    def slow_write(path: Path, data: str, **kwargs: object) -> int:
        write_paths.append(path)
        if len(write_paths) == 1:
            original_write(path, data[: len(data) // 2], encoding="utf-8")
            halfway.set()
            assert finish_write.wait(5)
        return original_write(path, data, **kwargs)

    monkeypatch.setattr(Path, "write_text", slow_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        writer = pool.submit(runner.run_xml, "<same-input/>", snapshot=snapshot)
        try:
            assert halfway.wait(5)
            observed = runner.run_xml("<same-input/>", snapshot=snapshot)
            assert observed.stats == {"Life": 1187}
        finally:
            finish_write.set()
        assert writer.result(timeout=5).stats == observed.stats
    cache = runner._cache_path("<same-input/>", snapshot.commit)
    assert json.loads(cache.read_text(encoding="utf-8")) == payload
    assert list(cache.parent.iterdir()) == [cache]


def test_corrupt_legacy_cache_is_recomputed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path)
    snapshot = PobSnapshot("fixture", tmp_path, tmp_path)
    cache = runner._cache_path("<input/>", snapshot.commit)
    cache.parent.mkdir()
    cache.write_text('{"meta":', encoding="utf-8")
    payload = {"meta": {"level": 90}, "alloc": [], "stats": {"Life": 1187}}
    monkeypatch.setattr(runner, "_run_driver", lambda *args: payload)
    assert not runner.run_xml("<input/>", snapshot=snapshot).cached
    assert runner.run_xml("<input/>", snapshot=snapshot).cached
    assert json.loads(cache.read_text(encoding="utf-8")) == payload


def test_independent_daemons_own_distinct_input_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_mod, "var_dir", lambda: tmp_path)
    snapshot = PobSnapshot("fixture", tmp_path, tmp_path)
    first = daemon_mod.PobDaemon(snapshot)
    second = daemon_mod.PobDaemon(snapshot)
    assert first._xml_file("same") != second._xml_file("same")


def test_compute_and_item_requests_keep_their_complete_response_frame(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_mod, "var_dir", lambda: tmp_path)
    first_reading, other_write = Event(), Event()
    lines: list[str] = []
    commands: list[str] = []

    def write(command: str) -> None:
        if commands:
            other_write.set()
        assert not lines, "새 요청이 아직 읽는 중인 응답 프레임을 침범했다"
        commands.append(command)
        if command.startswith("ITEM\t"):
            lines.extend(["POK_RAW:rendered item\n", "POK_DONE\n"])
        else:
            lines.extend(STDOUT.replace("POK_OK", "POK_DONE").splitlines(keepends=True))

    def readline() -> str:
        if not first_reading.is_set():
            first_reading.set()
            # 구 구현이면 두 번째 요청이 쓰기를 진행한다. 수정 후에는 첫 응답을
            # 끝낼 때까지 기다린다. PoB 부팅 없이 같은 요청 겹침을 고정한다.
            assert not other_write.wait(0.1)
        return lines.pop(0)

    daemon = daemon_mod.PobDaemon(PobSnapshot("fixture", tmp_path, tmp_path))
    daemon._proc = SimpleNamespace(
        stdin=SimpleNamespace(write=write, flush=lambda: None),
        stdout=SimpleNamespace(readline=readline),
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        compute = pool.submit(daemon.compute, "<input/>")
        assert first_reading.wait(5)
        item = pool.submit(daemon.build_item, "item")
        assert compute.result(timeout=5).stats == {"Life": 1187}
        assert item.result(timeout=5) == "rendered item"
    assert len(commands) == 2
    assert not list((tmp_path / "pob-cache").iterdir())


def test_shared_daemon_initialization_has_one_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    constructed: list[object] = []
    entered, duplicate = Event(), Event()

    class FakeDaemon:
        def __init__(self) -> None:
            constructed.append(self)
            if len(constructed) > 1:
                duplicate.set()

        def start(self) -> None:
            entered.set()
            assert not duplicate.wait(0.1)

        def close(self) -> None:
            pass

    monkeypatch.setattr(daemon_mod, "PobDaemon", FakeDaemon)
    monkeypatch.setattr(daemon_mod, "_SHARED", None)
    monkeypatch.setattr(daemon_mod.atexit, "register", lambda fn: None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(daemon_mod.shared_daemon)
        assert entered.wait(5)
        second = pool.submit(daemon_mod.shared_daemon)
        assert first.result(timeout=5) is second.result(timeout=5)
    assert len(constructed) == 1


def test_close_can_interrupt_a_blocked_response_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """요청 잠금이 기존의 강제 종료 복구 경로를 막아서는 안 된다."""
    monkeypatch.setattr(daemon_mod, "var_dir", lambda: tmp_path)
    reading, killed = Event(), Event()

    def readline() -> str:
        reading.set()
        assert killed.wait(5)
        return ""

    daemon = daemon_mod.PobDaemon(PobSnapshot("fixture", tmp_path, tmp_path))
    daemon._proc = SimpleNamespace(
        stdin=SimpleNamespace(write=lambda command: None, flush=lambda: None),
        stdout=SimpleNamespace(readline=readline),
        kill=killed.set,
        wait=lambda **kwargs: 0,
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        compute = pool.submit(daemon.compute, "<input/>")
        assert reading.wait(5)
        pool.submit(daemon.close).result(timeout=5)
        with pytest.raises(runner.PobRunError, match="POK_DONE"):
            compute.result(timeout=5)
    assert daemon._proc is None
    assert daemon.loaded_spec is None
    assert not list((tmp_path / "pob-cache").iterdir())


def test_power_error_consumes_frame_before_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_mod, "var_dir", lambda: tmp_path)
    lines: list[str] = []

    def write(command: str) -> None:
        if command.startswith("POWER\t"):
            lines.extend(["POK_ERR:injected power failure\n", "POK_DONE\n"])
        else:
            lines.extend(STDOUT.replace("POK_OK", "POK_DONE").splitlines(keepends=True))

    daemon = daemon_mod.PobDaemon(PobSnapshot("fixture", tmp_path, tmp_path))
    daemon._proc = SimpleNamespace(
        stdin=SimpleNamespace(write=write, flush=lambda: None),
        stdout=SimpleNamespace(readline=lambda: lines.pop(0)),
    )
    with pytest.raises(runner.PobRunError, match="injected power failure"):
        daemon.node_power(("Life",))
    assert daemon.compute("<input/>").stats == {"Life": 1187}
    assert not lines


def test_power_ranking_loads_its_base_and_holds_it_until_measurement() -> None:
    from pok.engine.tree.optimize import _power_ranked

    current = BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", level=90)
    foreign = replace(current, level=80)
    loaded, checked, foreign_done = Event(), Event(), Event()
    competitor_owned: list[bool] = []

    class Probe:
        transaction = daemon_mod.PobDaemon.transaction

        def __init__(self):
            self._lock = RLock()
            self.loaded = None

        def compute_build(self, spec):
            with self._lock:
                self.loaded = spec
            # Pause *after* the per-method lock releases. Only a transaction
            # around load + POWER can keep the other request out here.
            if spec == current:
                loaded.set()
                assert checked.wait(5)
                if competitor_owned[0]:
                    assert foreign_done.wait(5)

        def node_power(self, stats):
            with self._lock:
                return {2 if self.loaded == current else 3: {"CombinedDPS": 10}}, {}

    daemon = Probe()
    graph = SimpleNamespace(nodes={2: object(), 3: object()}, shortest_path=lambda a, n, **k: [n])

    def competitor():
        assert loaded.wait(5)
        owns = daemon._lock.acquire(blocking=False)
        competitor_owned.append(owns)
        checked.set()
        try:
            daemon.compute_build(foreign)
        finally:
            if owns:
                daemon._lock.release()
            foreign_done.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        other = pool.submit(competitor)
        ranked = pool.submit(_power_ranked, daemon, graph, current, set(), 10, set(), 5)
        assert ranked.result(timeout=10) == [2]
        other.result(timeout=10)
    assert competitor_owned == [False]
