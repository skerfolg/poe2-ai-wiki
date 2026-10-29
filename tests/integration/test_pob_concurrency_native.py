"""실제 PoB에서 XML 계산과 아이템 렌더 병렬 호출이 응답을 섞지 않는다."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Event

import pytest

from pok.engine.tree.deltas import TreeSwapMeasurer
from pok.pob import daemon as daemon_mod
from pok.pob import runner
from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

SPEC = BuildSpec(
    class_name="Sorceress",
    ascendancy="Sorceress1",
    level=90,
    tree_nodes=(4739, 22419),
    skills=(
        SkillGroupSpec(
            gems=(GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark", level=20),)
        ),
    ),
)
ITEM = (
    "Rarity: RARE\nConcurrent Boots\nDrakeskin Boots\nItem Level: 82\nCrafted: true\n"
    "Prefix: {range:0.5}IncreasedLife9\n"
)


def test_shared_protocol_matches_sequential_for_mixed_parallel_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_mod, "var_dir", lambda: tmp_path)
    specs = (SPEC, replace(SPEC, level=80))
    with daemon_mod.PobDaemon() as daemon:
        expected = [daemon.compute_build(spec) for spec in specs]
        crafted = daemon.build_item(ITEM)
        assert "+135 to maximum Life" in crafted
        barrier = Barrier(4)

        def compute(index: int):
            barrier.wait(timeout=5)
            return daemon.compute_build(specs[index])

        def craft():
            barrier.wait(timeout=5)
            return daemon.build_item(ITEM)

        with ThreadPoolExecutor(max_workers=4) as pool:
            calculations = [pool.submit(compute, i) for i in range(2)]
            items = [pool.submit(craft) for _ in range(2)]
            for future, baseline in zip(calculations, expected, strict=True):
                result = future.result(timeout=30)
                assert result.meta == baseline.meta
                assert result.stats == baseline.stats
                assert result.allocated_nodes == baseline.allocated_nodes
            assert [future.result(timeout=30) for future in items] == [crafted, crafted]
    assert not list((tmp_path / "pob-cache").iterdir())


def test_identical_native_driver_requests_publish_complete_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path)
    xml = to_xml(SPEC)
    barrier = Barrier(2)

    def compute():
        barrier.wait(timeout=5)
        return runner.run_xml(xml)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(compute) for _ in range(2)]
        first, second = [future.result(timeout=60) for future in futures]
    assert first.stats == second.stats
    assert first.meta == second.meta
    cached = runner.run_xml(xml)
    assert cached.cached
    assert cached.stats == first.stats
    files = list((tmp_path / "pob-cache").iterdir())
    assert len(files) == 1 and files[0].suffix == ".json"


FOREIGN = replace(
    SPEC,
    items=(
        ItemSpec(
            slot="Body Armour",
            text="Rarity: RARE\nOther Build\nAltar Robe\n+100 to maximum Life",
        ),
    ),
)


def test_raw_xml_invalidates_the_previous_tree_swap_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_mod, "var_dir", lambda: tmp_path)
    with daemon_mod.PobDaemon() as daemon:
        measurer = TreeSwapMeasurer(daemon, SPEC)
        baseline = measurer.base()
        foreign = daemon.compute(to_xml(FOREIGN))
        assert foreign.stats["Life"] != baseline.stats["Life"]
        assert daemon.loaded_spec is None
        actual = measurer.measure(SPEC)
        assert actual.stats == baseline.stats


def test_tree_state_check_and_measure_are_one_native_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon_mod, "var_dir", lambda: tmp_path)
    observed, checked, foreign_done = Event(), Event(), Event()
    competitor_owned: list[bool] = []

    class GatedDaemon(daemon_mod.PobDaemon):
        gate = False

        @property
        def loaded_spec(self):
            value = super().loaded_spec
            if self.gate:
                self.gate = False
                observed.set()
                assert checked.wait(5)
                if competitor_owned[0]:
                    assert foreign_done.wait(10)
            return value

    with GatedDaemon() as daemon:
        measurer = TreeSwapMeasurer(daemon, SPEC)
        baseline = measurer.base()
        daemon.gate = True

        def competitor():
            assert observed.wait(5)
            owns = daemon._lock.acquire(blocking=False)
            competitor_owned.append(owns)
            checked.set()
            try:
                return daemon.compute_build(FOREIGN)
            finally:
                if owns:
                    daemon._lock.release()
                foreign_done.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            other = pool.submit(competitor)
            measured = pool.submit(measurer.measure, SPEC)
            actual = measured.result(timeout=15)
            foreign = other.result(timeout=15)
        assert foreign.stats["Life"] != baseline.stats["Life"]
        assert actual.stats == baseline.stats
        assert competitor_owned == [False]
