"""Native mode failures explain effect identity without repairing raw documents."""

import json
from types import SimpleNamespace

import pytest

from pok.pob import runner

AMMO = "FragmentationRoundsAmmoPlayer"
ATTACK = "FragmentationRoundsPlayer"
GEM = "Metadata/Items/Gems/SkillGemFragmentationRounds"


def xml(index=2, effect=AMMO, tag="StatSetIndex", active="1", enabled="true"):
    return (
        '<PathOfBuilding2><Skills activeSkillSet="' + active + '">'
        '<SkillSet id="1"><Skill enabled="true"><Gem gemId="' + GEM + '" '
        'nameSpec="Fragmentation Rounds" enabled="' + enabled + '">'
        "<" + tag + ' grantedEffect="' + effect + '" index="' + str(index) + '"/>'
        "</Gem></Skill></SkillSet></Skills></PathOfBuilding2>"
    )


@pytest.fixture
def facts(monkeypatch):
    from pok.kb import skill_facts

    monkeypatch.setattr(skill_facts, "gem_effects", lambda: {GEM: (AMMO, ATTACK)})
    monkeypatch.setattr(
        skill_facts,
        "skill_gates",
        lambda: {
            AMMO: SimpleNamespace(stat_sets=("Ammunition",)),
            ATTACK: SimpleNamespace(stat_sets=("Projectile", "Vs Frozen")),
        },
    )


def test_invalid_ammunition_mode_points_to_the_distinct_attack_effect(facts):
    source = xml()
    hint = runner.native_mode_error_hint(source, "attempt to index local 'statSet' (a nil value)")
    assert hint is not None
    payload = json.loads(hint.split(":", 1)[1])
    issue = payload["bindings"][0]
    assert issue["effect_id"] == AMMO
    assert issue["requested_index"] == "2"
    assert issue["available_modes"] == [{"index": 1, "label": "Ammunition"}]
    assert issue["gem_effect_modes"][ATTACK][1] == {"index": 2, "label": "Vs Frozen"}
    assert "stat_set_indices" in payload["input_route"]
    assert payload["input_rewritten"] is False
    assert source == xml()


@pytest.mark.parametrize(
    "source",
    [xml(1), xml(2, ATTACK), xml(active="2"), xml(enabled="false"), xml(effect="FutureEffect")],
)
def test_valid_inactive_disabled_or_unknown_bindings_are_not_rejected(facts, source):
    assert runner.native_mode_error_hint(source, "statSet nil") is None


def test_calcs_environment_is_identified_separately(facts):
    hint = runner.native_mode_error_hint(xml(tag="StatSetCalcsIndex"), "statSet nil")
    assert json.loads(hint.split(":", 1)[1])["bindings"][0]["environment"] == "CALCS"


def test_unrelated_errors_do_not_read_kb(monkeypatch):
    from pok.kb import skill_facts

    def forbidden():
        raise AssertionError("A successful or unrelated path must not scan KB")

    monkeypatch.setattr(skill_facts, "gem_effects", forbidden)
    assert runner.native_mode_error_hint(xml(), "unrelated native failure") is None


def test_diagnostic_failure_does_not_replace_the_native_error(facts):
    assert runner.native_mode_error_hint("<broken>", "statSet nil") is None


def test_one_shot_preserves_native_cause_and_does_not_rewrite_input(facts, monkeypatch, tmp_path):
    from pok.pob.versions import PobSnapshot

    original = runner.PobRunError("attempt to index local 'statSet' (a nil value)")

    def failing(*args, **kwargs):
        raise original

    monkeypatch.setattr(runner, "_run_driver", failing)
    monkeypatch.setattr(runner, "_execution_observation", lambda *a, **k: {"status": "unavailable"})
    monkeypatch.setattr(runner, "_cache_path", lambda *a, **k: tmp_path / "cache.json")
    source = xml()
    with pytest.raises(runner.PobRunError) as raised:
        runner.run_xml(source, snapshot=PobSnapshot("test", tmp_path, tmp_path), use_cache=False)
    assert raised.value.__cause__ is original
    assert "POK_EFFECT_MODE_DIAGNOSTIC:" in str(raised.value)
    assert "Original native error:" in str(raised.value)
    assert str(original) in str(raised.value)
    assert source == xml()


def test_successful_calculation_does_not_invoke_diagnostic(monkeypatch, tmp_path):
    from pok.pob.versions import PobSnapshot

    def forbidden(*args):
        raise AssertionError("Successful calculation must not inspect effect modes")

    monkeypatch.setattr(runner, "native_mode_error_hint", forbidden)
    monkeypatch.setattr(runner, "_execution_observation", lambda *a, **k: {"status": "unavailable"})
    monkeypatch.setattr(runner, "_cache_path", lambda *a, **k: tmp_path / "cache.json")
    monkeypatch.setattr(
        runner, "_run_driver", lambda *a, **k: {"stats": {"Life": 100}, "meta": {}, "alloc": []}
    )
    assert (
        runner.run_xml(
            xml(), snapshot=PobSnapshot("test", tmp_path, tmp_path), use_cache=False
        ).stats["Life"]
        == 100
    )


def test_daemon_error_is_explained_and_next_frame_is_not_reused(facts, monkeypatch, tmp_path):
    from io import StringIO

    from pok.pob import daemon as module
    from pok.pob.versions import PobSnapshot

    daemon = module.PobDaemon(PobSnapshot("test", tmp_path, tmp_path))
    monkeypatch.setattr(daemon, "start", lambda: None)
    monkeypatch.setattr(daemon, "_xml_file", lambda text: tmp_path / "input.xml")
    daemon._proc = SimpleNamespace(stdin=StringIO(), pid=1, poll=lambda: None)
    frames = iter(["POK_ERR:attempt to index local 'statSet' (a nil value)\n", "POK_DONE\n"])
    monkeypatch.setattr(daemon, "_readline", lambda: next(frames))
    try:
        with pytest.raises(runner.PobRunError, match="POK_EFFECT_MODE_DIAGNOSTIC") as raised:
            daemon.compute(xml())
        assert "statSet" in str(raised.value.__cause__)
        assert daemon._last_xml == ""
        frames = iter(
            ['POK_META:{"level": 90}\n', "POK_ALLOC:[]\n", 'POK_JSON:{"Life": 123}\n', "POK_DONE\n"]
        )
        assert daemon.compute(xml(1)).stats["Life"] == 123
        assert daemon._last_xml == xml(1)
    finally:
        daemon._proc = None


@pytest.mark.parametrize("index", ["2.0", "2e0", "+2", "0x2"])
def test_native_numeric_spellings_are_not_falsely_diagnosed(facts, index):
    assert runner.native_mode_error_hint(xml(index, ATTACK), "statSet nil") is None


def test_missing_kb_does_not_conceal_original_failure(monkeypatch):
    from pok.kb import skill_facts

    def unavailable():
        raise ValueError("KB unavailable")

    monkeypatch.setattr(skill_facts, "gem_effects", unavailable)
    assert runner.native_mode_error_hint(xml(), "statSet nil") is None
