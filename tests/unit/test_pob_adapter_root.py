"""Explicit calculator assets do not require a PoK project/KB lookup."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from pok.pob import daemon, execution_identity, runner
from pok.pob.versions import PobSnapshot


def snapshot(tmp_path):
    base = tmp_path / "pob"
    return PobSnapshot("f" * 40, base, base / "src")


def forbidden():
    pytest.fail("explicit assets must not discover a PoK project")


def test_runner_observation_uses_explicit_lua_asset_root(monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    calls = []
    monkeypatch.setattr(runner, "project_root", forbidden)
    monkeypatch.setattr(runner, "find_luajit", lambda: str(tmp_path / "luajit"))

    def observe(snap, **kwargs):
        calls.append(kwargs)
        return {"status": "observed"}

    monkeypatch.setattr(execution_identity, "observe_execution_inputs", observe)
    assert (
        runner._execution_observation(snapshot(tmp_path), adapter_root=assets)["status"]
        == "observed"
    )
    assert calls[0]["adapter_root"] == assets.resolve()
    assert calls[0]["launch_config"]["driver"] == str((assets / "scripts/pob_driver.lua").resolve())


def test_native_driver_uses_explicit_path_and_exact_input(monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    captured = []
    xml = "<PathOfBuilding2>\r\n<!--keep-->\r\n</PathOfBuilding2>"
    monkeypatch.setattr(runner, "project_root", forbidden)
    monkeypatch.setattr(runner, "find_luajit", lambda: str(tmp_path / "luajit"))
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path / "cache")

    def capture(command, **kwargs):
        assert Path(command[1]) == assets.resolve() / "scripts/pob_driver.lua"
        assert Path(command[2]).read_bytes() == xml.encode()
        captured.append(Path(command[2]))
        return SimpleNamespace(returncode=0, stdout="native", stderr="")

    monkeypatch.setattr(runner, "run_native_capture", capture)
    monkeypatch.setattr(runner, "_parse", lambda _: ({"Life": 123}, {}, ()))
    assert runner._run_driver(xml, snapshot(tmp_path), 7, adapter_root=assets)["stats"] == {
        "Life": 123
    }
    assert not captured[0].exists()


def test_run_xml_forwards_explicit_assets_before_and_after_calculation(monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    calls = []
    monkeypatch.setattr(runner, "project_root", forbidden)
    monkeypatch.setattr(runner, "resolve_snapshot", forbidden)

    def observe(snap, *, adapter_root):
        calls.append(("observe", adapter_root))
        return {"status": "observed", "sha256": "f" * 64}

    def calculate(xml, snap, timeout, *, adapter_root):
        calls.append(("calculate", adapter_root))
        return {"stats": {"Life": 123}, "meta": {}, "alloc": []}

    monkeypatch.setattr(runner, "_execution_observation", observe)
    monkeypatch.setattr(runner, "_run_driver", calculate)
    monkeypatch.setattr(runner, "_cache_path", lambda *args, **kwargs: tmp_path / "cache.json")
    result = runner.run_xml(
        "<PathOfBuilding2/>", snapshot=snapshot(tmp_path), adapter_root=assets, use_cache=False
    )
    assert result.stats["Life"] == 123
    assert calls == [
        ("observe", assets.resolve()),
        ("calculate", assets.resolve()),
        ("observe", assets.resolve()),
    ]


def test_daemon_observation_has_the_same_explicit_asset_root(monkeypatch, tmp_path):
    assets = tmp_path / "assets"
    calls = []
    monkeypatch.setattr(daemon, "project_root", forbidden)
    monkeypatch.setattr(daemon, "find_luajit", lambda: str(tmp_path / "luajit"))

    def observe(snap, **kwargs):
        calls.append(kwargs)
        return {"status": "observed"}

    monkeypatch.setattr(daemon, "observe_execution_inputs", observe)
    worker = daemon.PobDaemon(snapshot(tmp_path), adapter_root=assets)
    assert worker._observe_inputs()["status"] == "observed"
    assert calls[0]["adapter_root"] == assets.resolve()
    assert calls[0]["launch_config"]["driver"] == str((assets / "scripts/pob_daemon.lua").resolve())
