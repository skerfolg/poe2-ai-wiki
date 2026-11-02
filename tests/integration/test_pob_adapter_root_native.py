"""Native raw XML and item daemon use explicit assets without project lookup."""

import shutil

import pytest

from pok.common.paths import project_root
from pok.pob import daemon, runner
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not ready(), reason="LuaJIT or pinned PoB unavailable")


@pytest.fixture
def assets(tmp_path, monkeypatch):
    target = tmp_path / "standalone-assets"
    scripts = target / "scripts"
    scripts.mkdir(parents=True)
    for source in (project_root() / "scripts").glob("*.lua"):
        shutil.copyfile(source, scripts / source.name)
    monkeypatch.setenv("POK_CACHE_HOME", str(tmp_path / "cache"))
    assert not (target / "knowledge").exists()
    assert not (target / "pyproject.toml").exists()
    return target


def xml():
    return to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(
                SkillGroupSpec(
                    gems=(
                        GemSpec(
                            gem_id="Metadata/Items/Gems/SkillGemSpark",
                            name="Spark",
                            stat_set_index=1,
                        ),
                    )
                ),
            ),
        )
    )


def forbidden():
    pytest.fail("standalone assets must not discover the engine project")


def test_run_xml_uses_actual_explicit_driver_without_project_markers(assets, monkeypatch):
    snap = resolve_snapshot()
    source = xml()
    monkeypatch.setattr(runner, "project_root", forbidden)
    monkeypatch.setattr(runner, "resolve_snapshot", forbidden)
    result = runner.run_xml(source, snapshot=snap, adapter_root=assets, use_cache=False)
    assert result.stats["Life"] > 0
    observation = result.meta["execution_inputs"]["observation"]
    assert observation["status"] == "observed"
    assert observation["launch_config"]["driver"] == str(
        (assets / "scripts/pob_driver.lua").resolve()
    )


def test_daemon_uses_actual_explicit_driver_without_project_markers(assets, monkeypatch):
    snap = resolve_snapshot()
    source = xml()
    monkeypatch.setattr(daemon, "project_root", forbidden)
    monkeypatch.setattr(daemon, "resolve_snapshot", forbidden)
    with daemon.PobDaemon(snap, adapter_root=assets) as calculator:
        result = calculator.compute(source)
        assert result.stats["Life"] > 0
        observed = calculator._observe_inputs()
        assert observed["status"] == "observed"
        assert observed["launch_config"]["driver"] == str(
            (assets / "scripts/pob_daemon.lua").resolve()
        )
