"""Actual PoB cache reuse and content invalidation without editing pinned sources."""

import json
import shutil
from time import perf_counter

import pytest

from pok.pob import runner
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT or pinned PoB unavailable")


def test_actual_cache_reuse_and_lua_content_invalidation(tmp_path, monkeypatch):
    snapshot = resolve_snapshot()
    source = runner.project_root() / "scripts"
    adapter = tmp_path / "adapter"
    for path in source.rglob("*.lua"):
        target = adapter / "scripts" / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    monkeypatch.setattr(runner, "project_root", lambda: adapter)
    monkeypatch.setattr(runner, "var_dir", lambda: tmp_path / "var")
    xml = to_xml(
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
                            level=20,
                        ),
                    )
                ),
            ),
        )
    )
    timings = {}
    started = perf_counter()
    first = runner.run_xml(xml, snapshot=snapshot)
    timings["fresh_s"] = perf_counter() - started
    started = perf_counter()
    cached = runner.run_xml(xml, snapshot=snapshot)
    timings["cache_hit_s"] = perf_counter() - started
    assert not first.cached and cached.cached
    assert json.dumps(first.stats, sort_keys=True) == json.dumps(cached.stats, sort_keys=True)
    assert first.meta["execution_inputs"]["status"] == "stable_observation"
    assert cached.meta["execution_inputs"]["status"] == "stable_at_lookup"
    old_files = {path: path.read_bytes() for path in (tmp_path / "var/pob-cache").glob("*.json")}
    helper = adapter / "scripts/pob_selection.lua"
    helper.write_bytes(helper.read_bytes() + b"\n-- isolated cache identity probe\n")
    started = perf_counter()
    changed = runner.run_xml(xml, snapshot=snapshot)
    timings["content_invalidated_s"] = perf_counter() - started
    assert not changed.cached
    assert changed.meta["nativeSelection"]["actual"]["effect_id"] == "SparkPlayer"
    assert changed.stats["Life"] == first.stats["Life"]
    assert (
        changed.meta["execution_inputs"]["observation"]["sha256"]
        != (first.meta["execution_inputs"]["observation"]["sha256"])
    )
    assert all(path.read_bytes() == raw for path, raw in old_files.items())
    assert len(list((tmp_path / "var/pob-cache").glob("*.json"))) == 2
    (tmp_path / "native-timings.json").write_text(
        json.dumps(
            {
                "format": "pok.cache-timing-observation.v1",
                "timings": timings,
                "scope": "single_host_observation_not_baseline_improvement_proof",
                "execution_observation": first.meta["execution_inputs"]["observation"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
