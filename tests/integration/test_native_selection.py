"""Native selection receipt: support ordering, clamping and daemon state changes.

Run at the pre-PR native gate. This tests calculator selection, not game legality.
"""

import pytest

from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.catalog import canonical_gem_id
from pok.pob.daemon import PobCommandTimeout, PobDaemon
from pok.pob.runner import run_build
from pok.pob.versions import find_luajit, resolve_snapshot


def ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not ready(), reason="LuaJIT or pinned PoB unavailable")
SPARK = GemSpec(
    gem_id="Metadata/Items/Gems/SkillGemSpark",
    name="Spark",
    level=20,
    stat_set_index=1,
)
SUPPORT = GemSpec(gem_id="Metadata/Items/Gems/SkillGemUnleashSupport", name="Unleash", level=1)


def spec(support_first=True, pointer=1):
    gems = (SUPPORT, SPARK) if support_first else (SPARK, SUPPORT)
    return BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        level=90,
        skills=(SkillGroupSpec(gems=gems, main_active_skill=pointer),),
    )


def actual(result):
    observation = result.meta["nativeSelection"]
    assert observation["format"] == "pok.native-selection.v1"
    assert observation["status"] == "observed"
    assert observation["actual"]["selected"] is True
    return observation["actual"]


def test_native_start_deadline_reaps_child_and_next_command_restarts():
    daemon = PobDaemon(command_timeout_s=0.001)
    try:
        with pytest.raises(PobCommandTimeout) as failure:
            daemon.start()
        # A source-observation deadline may expire before creating a child.
        assert failure.value.termination in {
            "no_process",
            "direct_child_confirmed",
            "owned_tree_confirmed",
        }
        assert daemon._proc is None
        daemon.command_timeout_s = 180.0
        recovered = actual(daemon.compute_build(spec()))
        assert recovered["effect_id"] == "SparkPlayer"
        assert recovered["stat_set_resolved"] is True
        assert daemon._proc is not None
    finally:
        daemon.close()


def test_live_owned_daemon_timeout_records_tree_cleanup_and_recovers():
    from pok.common.execution import ExecutionScope, bind_execution

    daemon = PobDaemon()
    xml = to_xml(spec())
    try:
        daemon.start()
        child = daemon._proc
        daemon.command_timeout_s = 0.001
        scope = ExecutionScope("native-daemon-timeout", 30)
        with bind_execution(scope), pytest.raises(PobCommandTimeout) as failure:
            daemon.compute(xml)
        assert failure.value.termination == "owned_tree_confirmed"
        assert child.poll() is not None
        receipt = scope.finish(failed=True)
        assert any(
            row["state"] == "terminated" and row["details"]["status"] == "confirmed"
            for row in receipt["resources"].values()
        )
        daemon.command_timeout_s = 180
        assert actual(daemon.compute_build(spec()))["effect_id"] == "SparkPlayer"
    finally:
        daemon.close()


def test_request_scope_tracks_actual_driver_and_daemon_resources():
    from pok.common.execution import ExecutionScope, bind_execution

    scope = ExecutionScope("native-request-scope", 180)
    with bind_execution(scope):
        assert actual(run_build(spec(), use_cache=False))["effect_id"] == "SparkPlayer"
        with PobDaemon() as daemon:
            assert actual(daemon.compute_build(spec()))["effect_id"] == "SparkPlayer"
    receipt = scope.finish()
    assert receipt["state"] == "completed"
    assert {row["kind"] for row in receipt["resources"].values()} == {
        "pob_driver",
        "pob_daemon_command",
    }
    assert all(row["state"] == "released" for row in receipt["resources"].values())


@pytest.mark.parametrize("support_first", [True, False])
def test_driver_reports_effect_ordinal_separately_from_gem_slot(support_first):
    selected = actual(run_build(spec(support_first), use_cache=False))
    assert selected["group_index"] == 1
    assert selected["active_index"] == 1
    assert selected["gem_index"] == (2 if support_first else 1)
    assert canonical_gem_id(selected["gem_id"]) == SPARK.gem_id
    assert selected["effect_id"] == "SparkPlayer"
    assert selected["stat_set_index"] == 1
    assert selected["stat_set_resolved"] is True


def test_native_clamp_is_observable_and_reported_as_a_request_difference():
    from dataclasses import asdict

    from pok.engine.integrity import spec_integrity

    source = spec(pointer=99)
    result = run_build(source, use_cache=False)
    assert actual(result)["active_index"] == 1
    problems = spec_integrity(asdict(source), native_selection=result.meta["nativeSelection"])
    assert any("main_active_skill=99" in problem for problem in problems)


def test_daemon_selection_follows_each_loaded_build_and_tree_recalculation():
    with PobDaemon() as daemon:
        assert actual(daemon.compute_build(spec(True)))["gem_index"] == 2
        assert actual(daemon.compute_build(spec(False)))["gem_index"] == 1
        assert actual(daemon.compute_tree(()))["gem_index"] == 1


@pytest.mark.parametrize("pointer", [1, 2])
def test_actual_meta_container_and_payload_have_distinct_native_diagnostics(pointer):
    from dataclasses import asdict

    from pok.engine.integrity import spec_integrity

    meta = GemSpec(
        gem_id="Metadata/Items/Gems/SkillGemCastOnElementalAilment",
        name="Cast on Elemental Ailment",
        level=20,
        stat_set_index=1,
    )
    source = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        level=90,
        skills=(SkillGroupSpec(gems=(meta, SPARK), main_active_skill=pointer),),
    )
    result = run_build(source, use_cache=False)
    selected = actual(result)
    assert selected["active_index"] == pointer
    assert selected["meta_container"] is (pointer == 1)
    problems = spec_integrity(asdict(source), native_selection=result.meta["nativeSelection"])
    assert any("메타 컨테이너" in problem for problem in problems) is (pointer == 1)


def test_native_inbuilt_effects_keep_distinct_active_and_gem_indices():
    wind = GemSpec(
        gem_id="Metadata/Items/Gems/SkillGemWindDancer",
        name="Wind Dancer",
        level=20,
        stat_set_index=1,
        stages=3,
    )
    source = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        level=90,
        skills=(SkillGroupSpec(gems=(wind,), main_active_skill=2),),
    )
    selected = actual(run_build(source, use_cache=False))
    assert selected["gem_index"] == 1
    assert selected["active_index"] == 2
    assert selected["effect_id"] == "TriggeredWindDancerPlayer"


def test_disabled_gem_does_not_become_a_fake_observed_first_skill():
    from dataclasses import replace

    source = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        level=90,
        skills=(SkillGroupSpec(gems=(replace(SPARK, enabled=False),)),),
    )
    observation = run_build(source, use_cache=False).meta["nativeSelection"]
    assert observation["status"] == "default_or_unmapped"
    assert observation["actual"]["gem_index"] is None
    assert observation["actual"]["active_index"] is None
