"""Cache identity follows actual bytes, not manual protocol/mtime discipline."""

import json
import os

import pytest

from pok.pob import runner
from pok.pob.versions import PobSnapshot


@pytest.fixture
def environment(tmp_path, monkeypatch):
    snapshot_root = tmp_path / "snapshot"
    src = snapshot_root / "src"
    runtime = snapshot_root / "runtime"
    scripts = tmp_path / "scripts"
    for directory in (src, runtime, scripts):
        directory.mkdir(parents=True)
    components = {
        "driver": scripts / "pob_driver.lua",
        "helper": scripts / "pob_selection.lua",
        "source": src / "HeadlessWrapper.lua",
        "runtime": runtime / "lua-library.dll",
        "executable": tmp_path / "luajit.exe",
    }
    for path in components.values():
        path.write_bytes(b"first")
    monkeypatch.setattr(runner, "project_root", lambda: tmp_path)
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path / "var")
    monkeypatch.setattr(runner, "find_luajit", lambda: str(components["executable"]))
    snapshot = PobSnapshot("unchanged-commit", snapshot_root, src)
    calls = []

    def calculate(*args):
        calls.append(args)
        return {"stats": {"Life": len(calls) * 100}, "meta": {"level": 90}, "alloc": []}

    monkeypatch.setattr(runner, "_run_driver", calculate)
    return snapshot, components, calls


@pytest.mark.parametrize("component", ["driver", "helper", "source", "runtime", "executable"])
def test_changed_bytes_invalidate_cache_even_with_same_size_and_mtime(environment, component):
    snapshot, files, calls = environment
    first = runner.run_xml("<input/>", snapshot=snapshot)
    hit = runner.run_xml("<input/>", snapshot=snapshot)
    assert hit.cached and hit.stats == first.stats
    path = files[component]
    stat = path.stat()
    path.write_bytes(b"other")
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    changed = runner.run_xml("<input/>", snapshot=snapshot)
    assert not changed.cached
    assert changed.stats["Life"] == 200
    assert len(calls) == 2
    assert (
        changed.meta["execution_inputs"]["observation"]["sha256"]
        != (first.meta["execution_inputs"]["observation"]["sha256"])
    )


def test_changed_inputs_during_calculation_are_reported_and_not_published(environment, monkeypatch):
    snapshot, files, _ = environment

    def changed(*args):
        files["helper"].write_bytes(b"changed")
        return {"stats": {"Life": 1}, "meta": {}, "alloc": []}

    monkeypatch.setattr(runner, "_run_driver", changed)
    result = runner.run_xml("<input/>", snapshot=snapshot)
    assert result.meta["execution_inputs"]["status"] == "changed_during_calculation"
    assert not list(runner.var_dir().glob("pob-cache/*.json"))


def test_unknown_identity_disables_cache_without_inventing_native_failure(environment):
    snapshot, files, calls = environment
    files["executable"].unlink()
    first = runner.run_xml("<input/>", snapshot=snapshot)
    second = runner.run_xml("<input/>", snapshot=snapshot)
    assert not first.cached and not second.cached and len(calls) == 2
    assert second.meta["execution_inputs"]["cache"] == "disabled"


def test_valid_json_corruption_and_wrong_input_cache_are_recomputed(environment):
    snapshot, _, calls = environment
    runner.run_xml("<one/>", snapshot=snapshot)
    first_path = runner._cache_path("<one/>", snapshot.commit, snapshot=snapshot)
    data = json.loads(first_path.read_text(encoding="utf-8"))
    data["result"]["stats"]["Life"] = 999
    first_path.write_text(json.dumps(data), encoding="utf-8")
    assert runner.run_xml("<one/>", snapshot=snapshot).stats["Life"] == 200
    other_path = runner._cache_path("<two/>", snapshot.commit, snapshot=snapshot)
    other_path.write_bytes(first_path.read_bytes())
    assert runner.run_xml("<two/>", snapshot=snapshot).stats["Life"] == 300
    assert len(calls) == 3


def test_unfingerprintable_adapter_disables_cache_but_can_still_calculate(environment, monkeypatch):
    from functools import partial

    snapshot, _, calls = environment
    monkeypatch.setattr(runner, "_run_driver", partial(runner._run_driver))
    result = runner.run_xml("<input/>", snapshot=snapshot)
    assert result.stats["Life"] == 100 and len(calls) == 1
    assert result.meta["execution_inputs"]["cache"] == "disabled"


def test_after_observation_failure_is_not_claimed_as_known_content_change(environment, monkeypatch):
    snapshot, _, _ = environment
    observations = iter(
        [
            {"status": "observed", "sha256": "before"},
            {"status": "unavailable", "diagnostics": [{"reason": "read failed"}]},
        ]
    )
    monkeypatch.setattr(runner, "_execution_observation", lambda *args: next(observations))
    result = runner.run_xml("<input/>", snapshot=snapshot)
    receipt = result.meta["execution_inputs"]
    assert receipt["status"] == "unverified_after_calculation"
    assert receipt["after_observation"]["diagnostics"] == [{"reason": "read failed"}]
    assert not list(runner.var_dir().glob("pob-cache/*.json"))


def test_selected_driver_and_lua_search_path_are_cache_inputs(environment, monkeypatch):
    snapshot, files, calls = environment
    (files["driver"].parent / "alternate.lua").write_bytes(b"alternate")
    runner.run_xml("<input/>", snapshot=snapshot)
    monkeypatch.setattr(runner, "_DRIVER", "scripts/alternate.lua")
    assert not runner.run_xml("<input/>", snapshot=snapshot).cached
    monkeypatch.setattr(runner, "_LUA_PATH", "different-module-search-path")
    assert not runner.run_xml("<input/>", snapshot=snapshot).cached
    assert len(calls) == 3
