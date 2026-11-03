"""Native invalid-mode failure retains context and a subsequent valid calculation works."""

from contextlib import nullcontext

import pytest

from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec, to_xml
from pok.pob.daemon import PobDaemon
from pok.pob.runner import PobRunError, run_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not ready(), reason="LuaJIT or pinned PoB unavailable")


def build(gem, ammo, attack, valid):
    skill = GemSpec(
        gem_id="Metadata/Items/Gems/SkillGem" + gem.replace(" ", ""),
        name=gem,
        level=20,
        stat_set_index=1 if valid else 2,
        stat_set_indices=((ammo, 1), (attack, 2)) if valid else None,
        stat_set_calcs_indices=((ammo, 1), (attack, 2)) if valid else None,
    )
    return to_xml(
        BuildSpec(
            class_name="Mercenary",
            ascendancy="Mercenary2",
            level=100,
            items=(ItemSpec(slot="Weapon 1", text="Rarity: Normal\nGemini Crossbow"),),
            skills=(SkillGroupSpec(gems=(skill,), main_active_skill=1),),
        )
    )


@pytest.mark.parametrize(
    "gem,ammo,attack",
    [
        ("Fragmentation Rounds", "FragmentationRoundsAmmoPlayer", "FragmentationRoundsPlayer"),
        ("High Velocity Rounds", "HighVelocityRoundsAmmoPlayer", "HighVelocityRoundsPlayer"),
    ],
)
@pytest.mark.parametrize("kind", ["one_shot", "daemon"])
def test_ammunition_error_lists_attack_modes_and_valid_input_recovers(gem, ammo, attack, kind):
    invalid = build(gem, ammo, attack, False)
    valid = build(gem, ammo, attack, True)
    with PobDaemon() if kind == "daemon" else nullcontext() as daemon:
        compute = (
            daemon.compute if kind == "daemon" else lambda text: run_xml(text, use_cache=False)
        )
        with pytest.raises(PobRunError) as failure:
            compute(invalid)
        message = str(failure.value)
        assert "POK_EFFECT_MODE_DIAGNOSTIC:" in message
        assert ammo in message and attack in message
        assert "Original native error:" in message and "statSet" in message
        assert failure.value.__cause__ is not None
        result = compute(valid)
        selected = result.meta["nativeSelection"]["actual"]
        assert selected["effect_id"] == attack
        assert selected["stat_set_index"] == 2
        assert selected["stat_set_resolved"] is True
