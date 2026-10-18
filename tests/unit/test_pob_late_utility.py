"""Late utility extraction without booting PoB; missing values must not become zero."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pok.common.paths import project_root
from pok.pob import runner
from pok.pob.daemon import PobDaemon
from pok.pob.versions import find_luajit


def _lua(tmp_path: Path, body: str) -> None:
    try:
        lua = find_luajit()
    except (FileNotFoundError, RuntimeError):
        pytest.skip("LuaJIT unavailable; no PoB snapshot is required")
    script = tmp_path / "late-utility-test.lua"
    script.write_text("local capture = dofile(arg[1])\n" + body, encoding="utf-8")
    proc = subprocess.run(
        [lua, str(script), str(project_root() / "scripts/pob_late_utility.lua")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_native_queries_preserve_original_output(tmp_path: Path) -> None:
    _lua(
        tmp_path,
        """
local original = { EffectiveLootRarityMod = 1 }
local mods = {}
function mods:Sum(kind, cfg, stat)
  assert(kind == 'INC' and cfg == nil and stat == 'LootRarity')
  return 62
end
function mods:More(cfg, stat)
  assert(cfg == nil and stat == 'LootRarity')
  return 1.25
end
calcLib = { mod = function(db, cfg, stat)
  assert(db == mods and cfg == nil and stat == 'LootRarity')
  return 2.025
end }
local env = { player = { modDB = mods, output = original } }
local out = capture(env)
assert(out.LateLootRarityInc == 62)
assert(out.LateLootRarityMore == 1.25)
assert(out.LateLootRarityMod == 2.025)
assert(original.EffectiveLootRarityMod == 1)
assert(original.LateLootRarityMod == nil)
assert(out.EffectiveLootRarityMod == nil)
""",
    )


@pytest.mark.parametrize("env", ["nil", "{}", "{player={}}", "{player={modDB={}}}"])
def test_unavailable_environment_omits_keys(tmp_path: Path, env: str) -> None:
    _lua(tmp_path, f"assert(next(capture({env})) == nil)\n")


@pytest.mark.parametrize("value", ["nil", "'62'", "0/0", "math.huge", "-math.huge"])
def test_nonfinite_or_nonnumeric_values_are_not_serialized(tmp_path: Path, value: str) -> None:
    _lua(
        tmp_path,
        f"""
local function invalid() return {value} end
calcLib = {{mod=invalid}}
local out = capture({{player={{modDB={{Sum=invalid, More=invalid}}}}}})
assert(next(out) == nil)
""",
    )


def test_query_failure_does_not_invent_other_axes(tmp_path: Path) -> None:
    _lua(
        tmp_path,
        """
local mods = { Sum = function() return 0 end,
  More = function() error('unavailable') end }
calcLib = { mod = function() error('unavailable') end }
local out = capture({player={modDB=mods}})
assert(out.LateLootRarityInc == 0)
assert(out.LateLootRarityMore == nil and out.LateLootRarityMod == nil)
""",
    )


def test_protocol_preserves_early_and_late_values() -> None:
    stats, _, _ = runner.parse_lines(
        [
            'POK_META:{"class":"Sorceress"}',
            "POK_ALLOC:[]",
            'POK_JSON:{"EffectiveLootRarityMod":1,"LateLootRarityInc":62,'
            '"LateLootRarityMore":1,"LateLootRarityMod":1.62}',
        ]
    )
    assert stats["EffectiveLootRarityMod"] == 1
    assert stats["LateLootRarityMod"] == 1.62


def test_late_axes_invalidate_previous_cached_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    assert runner._META_PROTOCOL >= 5
    current = runner._cache_path("<xml/>", "same-pob-commit")
    monkeypatch.setattr(runner, "_META_PROTOCOL", 4)
    assert current != runner._cache_path("<xml/>", "same-pob-commit")


@pytest.mark.parametrize("axis", ["LateLootRarityInc", "LateLootRarityMore", "LateLootRarityMod"])
def test_power_rejects_late_axes_before_start_or_send(axis: str) -> None:
    # No initialized snapshot/process: rejection must precede any daemon access.
    daemon = object.__new__(PobDaemon)
    with pytest.raises(runner.PobRunError, match="unavailable in POWER"):
        daemon.node_power(("TotalDPS", axis))
