"""Native item-editor regression for late rune declarations (#193).

This executes PoB's real dropdown callback and ParseRaw/BuildRaw/Craft. It is a
headless regression of the editor code, not a claim of a visible GUI click test.
The three-socket original is intentionally preserved as an invalid-item repro;
socket acquisition legality is an independent check.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any

import pytest

from pok.engine.runes import RuneOption, render_runed
from pok.pob.runner import _LUA_PATH
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 PoB 스냅샷 없음")

_GLOVES = """Rarity: RARE
Engineered Gloves
Adorned Wraps
Evasion: 315
Energy Shield: 102
Crafted: true
Prefix: {range:0.5}LocalBaseEvasionRatingAndEnergyShield4
Prefix: {range:0.5}LocalIncreasedEvasionAndEnergyShield7
Prefix: {range:0.5}AddedPhysicalDamage9
Suffix: {range:0.5}AlloyDamagingAilmentDuration1
Suffix: {range:0.5}CriticalMultiplier5
Suffix: {range:0.5}FireResist8
Quality: 20
LevelReq: 65
Implicits: 0
+72 to Evasion Rating
+24 to maximum Energy Shield
96% increased Evasion and Energy Shield
Adds 16 to 27 Physical Damage to Attacks
32% increased Critical Damage Bonus
+43% to Fire Resistance
23% increased Duration of Damaging Ailments on Enemies
{custom}{range:0.5}(15-25)% increased Evasion and Energy Shield
Corrupted"""
_RUNES = (
    RuneOption(
        "cruelty",
        "Courtesan Mannan's Rune of Cruelty",
        ("20% increased Magnitude of Damaging Ailments you inflict",),
    ),
    RuneOption("sirrius", "Idol of Sirrius", ("8% increased Attack Speed",)),
    RuneOption("iron", "Perfect Iron Rune", ("20% increased Armour, Evasion and Energy Shield",)),
)

_SCRIPT = r"""
package.preload['lua-utf8'] = function() return setmetatable({}, { __index = string }) end
local input = assert(io.open(arg[1], 'rb')):read('*a')
dofile('HeadlessWrapper.lua')
local json = require('dkjson')
local items = json.decode(input)
local results = {}
local function snapshot(item)
    item:BuildModList()
    local shown, mods, numericMods = {}, {}, {}
    for i = 1, 6 do
        if build.itemsTab.controls['displayItemRune'..i]:IsShown() then
            shown[#shown + 1] = i
        end
    end
    for _, line in ipairs(item.runeModLines) do mods[#mods + 1] = line.line end
    for _, mod in ipairs(item.baseModList) do
        if type(mod.value) == 'number' then
            numericMods[#numericMods + 1] = {mod.name, mod.type, mod.flags, mod.value}
        end
    end
    return {base=item.baseName, sockets=item.itemSocketCount,
        runes=copyTable(item.runes), shown=shown,
        mods=mods, numericMods=numericMods, armour=copyTable(item.armourData or {}),
        raw=item:BuildRaw()}
end
for name, raw in pairs(items) do
    local states = {}
    results[name] = states
    local item = new('Item', raw)
    build.itemsTab:SetDisplayItem(item)
    states.initial = snapshot(item)
    for pass = 1, 3 do
        local dropdown = build.itemsTab.controls.displayItemRune1
        dropdown.selFunc(dropdown.selIndex, dropdown.list[dropdown.selIndex])
        states['edited'..pass] = snapshot(item)
        item = new('Item', item:BuildRaw())
        local ok, why = pcall(function() build.itemsTab:SetDisplayItem(item) end)
        if not ok then
            states.failure = tostring(why)
            states.failed_sockets = item.itemSocketCount
            break
        end
        states['reimported'..pass] = snapshot(item)
    end
    if not states.failure and item.crafted then
        item:Craft()
        build.itemsTab:SetDisplayItem(item)
        states.crafted = snapshot(item)
    end
end
local output = assert(io.open(arg[2], 'wb'))
output:write(json.encode(results))
output:close()
print('POK_OK')
"""


@pytest.fixture(scope="module")
def editor_paths(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    try:
        snapshot = resolve_snapshot()
        lua = find_luajit()
    except (FileNotFoundError, RuntimeError) as exc:
        pytest.skip(str(exc))
    directory = tmp_path_factory.mktemp("rune-editor")
    late = "\n".join(
        [
            _GLOVES,
            "Sockets: S S S",
            *(f"Rune: {rune.name}" for rune in _RUNES),
            *(f"{{rune}}{line}" for rune in _RUNES for line in rune.lines),
        ]
    )
    wand = (
        "Rarity: RARE\nAmplification Probe\nAttuned Wand\n200% increased effect of Socketed Runes"
    )
    spell_rune = RuneOption("spell", "Greater Iron Rune", ("30% increased Spell Damage",))
    cases = {
        "late-original": late,
        "fixed-three": render_runed(late, _RUNES),
        "fixed-two": render_runed(_GLOVES, _RUNES[:2]),
        "amplified": render_runed(wand, [spell_rune]),
        "normal-header": render_runed("Rarity: NORMAL\nAttuned Wand", [spell_rune]),
        "magic-header": render_runed("Rarity: MAGIC\nAttuned Wand", [spell_rune]),
    }
    source, script, output = (directory / name for name in ("input.json", "probe.lua", "out.json"))
    source.write_text(json.dumps(cases), encoding="utf-8")
    script.write_text(_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [lua, str(script), str(source), str(output)],
        cwd=snapshot.src_dir,
        env={**os.environ, "LUA_PATH": _LUA_PATH},
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        input="",
        timeout=180,
    )
    assert proc.returncode == 0 and "POK_OK" in proc.stdout, proc.stderr + proc.stdout[-2000:]
    return json.loads(output.read_text(encoding="utf-8"))


def test_original_duplicates_on_real_editor_callback(editor_paths: dict[str, Any]) -> None:
    path = editor_paths["late-original"]
    assert path["initial"]["sockets"] == 3
    assert len(path["initial"]["runes"]) == 3
    assert path["edited1"]["sockets"] == 6
    assert path["edited1"]["runes"] == path["initial"]["runes"] * 2
    assert path["edited1"]["shown"] == [1, 2, 3, 4, 5, 6]
    assert "8% increased Attack Speed" in path["initial"]["mods"]
    assert "16% increased Attack Speed" in path["edited1"]["mods"]
    assert path["edited1"]["armour"]["EnergyShield"] > path["initial"]["armour"]["EnergyShield"]
    assert path["edited1"]["armour"]["Evasion"] > path["initial"]["armour"]["Evasion"]
    assert path["failed_sockets"] == 9
    assert "nil value" in path["failure"]


@pytest.mark.parametrize(
    "case,count",
    [
        ("fixed-three", 3),
        ("fixed-two", 2),
        ("amplified", 1),
        ("normal-header", 1),
        ("magic-header", 1),
    ],
)
def test_fixed_edit_save_reimport_preserves_runes_and_calculations(
    editor_paths: dict[str, Any], case: str, count: int
) -> None:
    path = editor_paths[case]
    assert "failure" not in path
    baseline = path["initial"]
    for state in path.values():
        assert state["sockets"] == count
        assert len(state["runes"]) == count
        assert state["shown"] == list(range(1, count + 1))
        for field in ("base", "runes", "mods", "armour", "numericMods"):
            assert state[field] == baseline[field], (case, field)
        assert state["raw"].count("Sockets:") == 1
        assert state["raw"].count("Rune:") == count
    if case == "amplified":
        # Native mod lists keep the 30 base + 60 amplified contribution separate.
        assert (
            sum(mod[3] for mod in baseline["numericMods"] if mod[:3] == ["Damage", "INC", 2]) == 90
        )
        assert "{enchant}{rune}90% increased Spell Damage" in baseline["raw"]
    if case.endswith("header"):
        assert baseline["base"] == "Attuned Wand"
