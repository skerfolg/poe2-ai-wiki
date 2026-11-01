"""A live native daemon retains startup evidence after its source files change."""

import shutil

import pytest

from pok.pob import daemon as module
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT or pinned PoB unavailable")


def test_actual_daemon_startup_is_preserved_until_restart(tmp_path, monkeypatch):
    snapshot = resolve_snapshot()
    adapter = tmp_path / "adapter"
    source = module.project_root() / "scripts"
    for file in source.rglob("*.lua"):
        target = adapter / "scripts" / file.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
    monkeypatch.setattr(module, "project_root", lambda: adapter)
    monkeypatch.setattr(module, "var_dir", lambda: tmp_path / "var")
    spec = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        level=90,
        skills=(
            SkillGroupSpec(
                gems=(
                    GemSpec(
                        gem_id="Metadata/Items/Gems/SkillGemSpark",
                        name="Spark",
                        level=20,
                    ),
                )
            ),
        ),
    )
    daemon = module.PobDaemon(snapshot)
    try:
        first = daemon.compute_build(spec)
        original = first.meta["daemon_execution"]["startup"]
        assert original["status"] == "stable_observation"
        assert daemon.inspect_execution(observe_current=True)["current_matches_startup"] is True
        helper = adapter / "scripts/pob_selection.lua"
        helper.write_bytes(helper.read_bytes() + b"\n-- isolated daemon startup identity probe\n")
        current = daemon.inspect_execution(observe_current=True)
        assert current["current_matches_startup"] is False
        assert current["startup"] == original
        again = daemon.compute_tree(())
        assert again.meta["daemon_execution"]["startup"] == original
        assert again.meta["nativeSelection"]["actual"]["effect_id"] == "SparkPlayer"
        daemon.close()
        stopped = daemon.inspect_execution()
        assert stopped["last_startup"] == original
        assert stopped["last_cleanup"]["status"] == "confirmed"
        daemon.start()
        restarted = daemon.inspect_execution(observe_current=True)
        assert restarted["current_matches_startup"] is True
        assert restarted["startup"]["generation"] != original["generation"]
        assert restarted["startup"]["after"]["sha256"] != original["after"]["sha256"]
    finally:
        daemon.close()
