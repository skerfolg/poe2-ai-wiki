"""Read native selection objects with LuaJIT, without booting PoB."""

import json
import subprocess
from pathlib import Path

import pytest

from pok.common.paths import project_root
from pok.pob import runner


def capture(tmp_path: Path, body: str):
    from pok.pob.versions import find_luajit

    try:
        binary = find_luajit()
    except (FileNotFoundError, RuntimeError):
        pytest.skip("LuaJIT unavailable; helper test does not require a PoB snapshot")
    script = tmp_path / "selection.lua"
    script.write_text("local capture = dofile(arg[1])\n" + body, encoding="utf-8")
    result = subprocess.run(
        [binary, str(script), str(project_root() / "scripts/pob_selection.lua")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def test_active_ordinal_is_not_the_source_gem_slot(tmp_path):
    result = capture(
        tmp_path,
        """
local support = {gemId="support", nameSpec="Support"}
local gem = {gemId="spark", nameSpec="Spark"}
local stat = {label="Projectile"}
local group = {gemList={support,gem}, mainActiveSkill=1}
local skill = {socketGroup=group, skillTypes={}, activeEffect={
  srcInstance=gem, grantedEffect={id="SparkPlayer",name="Spark",statSets={stat}},
  statSet={index=1,statSet=stat}}}
group.displaySkillList={skill}
local build={skillsTab={socketGroupList={group}},calcsTab={mainEnv={player={
  activeSkillList={skill},mainSkill=skill}}}}
print(capture(build,{Meta=7}))
assert(group.mainActiveSkill==1 and #group.gemList==2)
""",
    )
    assert result["status"] == "observed"
    selected = result["actual"]
    assert selected["active_index"] == 1
    assert selected["gem_index"] == 2
    assert selected["gem_id"] == "spark"
    assert selected["effect_id"] == "SparkPlayer"
    assert selected["stat_set_resolved"] is True
    assert selected["stat_sets"] == [{"index": 1, "label": "Projectile"}]
    assert selected["meta_container"] is False


def test_multiple_effects_share_a_gem_and_stale_objects_are_not_reported(tmp_path):
    result = capture(
        tmp_path,
        """
local gem={gemId="multi",nameSpec="Multi"}
local group={gemList={gem},label="line\\n\\\"quoted\\\"",slot="Weapon 1"}
local first={skillTypes={[7]=true},activeEffect={srcInstance=gem,
  grantedEffect={id="Buff",statSets={}},statSet={index=99}}}
local second={skillTypes={},activeEffect={srcInstance=gem,
  grantedEffect={id="Attack",statSets={}},statSet={index=1}}}
local stale={activeEffect={grantedEffect={id="Old"}}}
group.displaySkillList={first,second,stale}
print(capture({skillsTab={socketGroupList={group}},calcsTab={mainEnv={player={
  activeSkillList={first,second},mainSkill=second}}}},{Meta=7}))
""",
    )
    effects = result["groups"][0]["effects"]
    assert len(effects) == 2
    assert [effect["gem_index"] for effect in effects] == [1, 1]
    assert [effect["active_index"] for effect in effects] == [1, 2]
    assert effects[0]["meta_container"] is True
    assert effects[0]["stat_set_resolved"] is False
    assert result["actual"]["effect_id"] == "Attack"
    assert result["groups"][0]["label"] == 'line\n"quoted"'


def test_missing_environment_is_unknown_not_a_fake_first_skill(tmp_path):
    result = capture(tmp_path, "print(capture(nil,nil))")
    assert result["status"] == "unavailable"
    assert result["actual"] is None
    assert result["groups"] == []


def test_native_default_is_identified_without_inventing_a_gem_slot(tmp_path):
    result = capture(
        tmp_path,
        """
local skill={activeEffect={grantedEffect={id="DefaultAttack",statSets={}}}}
print(capture({skillsTab={socketGroupList={}},calcsTab={mainEnv={player={
  activeSkillList={skill},mainSkill=skill}}}},{}))
""",
    )
    assert result["status"] == "default_or_unmapped"
    assert result["actual"]["effect_id"] == "DefaultAttack"
    assert result["actual"]["gem_index"] is None
    assert result["actual"]["active_index"] is None


def test_protocol_parses_nested_selection_and_invalidates_older_cache(monkeypatch):
    _, meta, _ = runner.parse_lines(
        [
            'POK_META:{"nativeSelection":{"format":"pok.native-selection.v1","actual":{"gem_index":2}}}',
            "POK_ALLOC:[]",
            'POK_JSON:{"Life":10}',
        ]
    )
    assert meta["nativeSelection"]["actual"]["gem_index"] == 2
    assert runner._META_PROTOCOL >= 6
    current = runner._cache_path("<xml/>", "commit")
    monkeypatch.setattr(runner, "_META_PROTOCOL", 5)
    assert current != runner._cache_path("<xml/>", "commit")


def test_both_drivers_use_the_same_selection_observer():
    for name in ("pob_driver.lua", "pob_daemon.lua"):
        text = (project_root() / "scripts" / name).read_text(encoding="utf-8")
        assert 'dofile(adapterDir .. "pob_selection.lua")' in text
        assert '"nativeSelection":%s' in text
        assert "nativeSelection(build, SkillType)" in text
