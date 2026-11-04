"""Actor output transport must not merge owners or invent missing values."""

import subprocess

import pytest

from pok.common.paths import project_root
from pok.pob.versions import find_luajit


def test_selected_minion_axes_preserve_player_and_missing_values(tmp_path):
    try:
        binary = find_luajit()
    except (FileNotFoundError, RuntimeError):
        pytest.skip("LuaJIT unavailable")
    script = tmp_path / "actor.lua"
    script.write_text(
        """local capture = dofile(arg[1])
local native = {CombinedDPS=0, Life=1500, Minion={CombinedDPS=63.5,
 Life=1232, Missing=false, Invalid=0/0, Infinite=math.huge, Nested={Life=999}}}
local result = capture(native)
assert(result.CombinedDPS == 0 and result.Life == 1500)
assert(result["Minion.CombinedDPS"] == 63.5 and result["Minion.Life"] == 1232)
assert(result["Minion.Missing"] == nil and result["Minion.Invalid"] == nil)
assert(result["Minion.Infinite"] == nil and result["Minion.Nested"] == nil)
assert(native["Minion.Life"] == nil)
assert(capture({Life=1500})["Minion.Life"] == nil)
assert(next(capture(nil)) == nil)
local ok = pcall(capture, {["Minion.Life"]=1, Minion={Life=2}})
assert(not ok)
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [binary, str(script), str(project_root() / "scripts/pob_actor_output.lua")],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_minion_power_request_cannot_silently_return_zero(monkeypatch):
    from pok.pob.daemon import PobDaemon
    from pok.pob.runner import PobRunError

    daemon = PobDaemon()
    monkeypatch.setattr(daemon, "start", lambda: pytest.fail("must reject before startup"))
    with pytest.raises(PobRunError, match="full XML or TREE"):
        daemon.node_power(("Minion.CombinedDPS",))
