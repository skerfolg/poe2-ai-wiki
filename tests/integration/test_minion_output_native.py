"""Selected minion axes survive both native transports and daemon reuse."""

import pytest

from pok.pob.buildxml import spec_from_dict
from pok.pob.daemon import PobDaemon
from pok.pob.runner import run_build
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="Native PoB unavailable")


def test_minion_axes_driver_daemon_and_actor_switch():
    spec = spec_from_dict(
        {
            "class_name": "Witch",
            "ascendancy": "Witch1",
            "level": 100,
            "skills": [
                {
                    "gems": [
                        {
                            "name": "Skeletal Arsonist",
                            "gem_id": "Metadata/Items/Gems/SkillGemSkeletalArsonist",
                            "level": 20,
                            "stat_set_indices": {"SummonSkeletalArsonistsPlayer": 1},
                        }
                    ]
                }
            ],
        }
    )
    direct = run_build(spec, use_cache=False)
    assert direct.stats["CombinedDPS"] == 0
    assert direct.stats["Minion.CombinedDPS"] > 0
    selected = direct.meta["nativeSelection"]["minion"]
    assert selected["actual"]["selected"] is True
    assert selected["actual"]["effect_id"]
    daemon = PobDaemon()
    try:
        repeated = daemon.compute_build(spec)
        assert repeated.stats == direct.stats
        assert repeated.meta["nativeSelection"]["minion"] == selected
        empty = daemon.compute_build(
            spec_from_dict({"class_name": "Witch", "ascendancy": "Witch1", "level": 100})
        )
        assert not any(key.startswith("Minion.") for key in empty.stats)
        assert empty.meta["nativeSelection"]["minion"]["actual"] is None
    finally:
        daemon.close()
