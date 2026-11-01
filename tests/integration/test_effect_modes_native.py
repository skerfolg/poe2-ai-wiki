"""Mode transport matches native input; this does not establish infusion upkeep."""

import xml.etree.ElementTree as ET

import pytest

from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, spec_from_dict, to_xml
from pok.pob.catalog import gem_aliases
from pok.pob.restore import spec_from_pob_xml
from pok.pob.runner import run_build, run_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not ready(), reason="LuaJIT or pinned PoB unavailable")
SPARK = "Metadata/Items/Gems/SkillGemSpark"


def selected(result):
    return result.meta["nativeSelection"]["actual"]


def test_main_mode_two_and_calcs_mode_one_survive_native_projection_roundtrip():
    gem = GemSpec(
        gem_id=SPARK,
        name="Spark",
        stat_set_index=2,
        stat_set_indices=(("SparkPlayer", 2),),
        stat_set_calcs_indices=(("SparkPlayer", 1),),
    )
    original = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(SkillGroupSpec(gems=(gem,)),),
            config=(("conditionStationary", 1.5),),
        )
    )
    rebuilt = to_xml(spec_from_dict(spec_from_pob_xml(original).spec))
    for xml in (original, rebuilt):
        actual = selected(run_xml(xml, use_cache=False))
        assert actual["effect_id"] == "SparkPlayer"
        assert actual["stat_set_index"] == 2
        assert actual["stat_set_resolved"] is True
        assert ET.fromstring(xml).find(".//StatSetCalcsIndex").get("index") == "1"


def test_game_id_alias_selects_the_primary_effect_mode_in_native_output():
    canonical = "Metadata/Items/Gems/SkillGemFrostBolt"
    alias = next(key for key, value in gem_aliases().items() if value == canonical)
    result = run_build(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(
                SkillGroupSpec(gems=(GemSpec(gem_id=alias, name="Frostbolt", stat_set_index=2),)),
            ),
        ),
        use_cache=False,
    )
    assert selected(result)["stat_set_index"] == 2
    assert selected(result)["stat_set_resolved"] is True


def test_legacy_attribute_is_not_revived_into_an_active_native_mode():
    original = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(SkillGroupSpec(gems=(GemSpec(gem_id=SPARK, name="Spark"),)),),
        )
    ).replace('nameSpec="Spark"/>', 'nameSpec="Spark" statSetIndex="2"/>')
    assert 'statSetIndex="2"' in original
    rebuilt = to_xml(spec_from_dict(spec_from_pob_xml(original).spec))
    assert selected(run_xml(original, use_cache=False))["stat_set_index"] == 1
    assert selected(run_xml(rebuilt, use_cache=False))["stat_set_index"] == 1


def test_source_preserving_child_insertion_changes_the_actual_native_mode():
    from pok.pob.document import inspect_xml, upsert_xml_child_attribute, xml_revision

    original = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(SkillGroupSpec(gems=(GemSpec(gem_id=SPARK, name="Spark"),)),),
        )
    )
    gem = next(node for node in inspect_xml(original) if node.tag == "Gem")
    changed = upsert_xml_child_attribute(
        original,
        xml_revision(original),
        gem.path,
        "StatSetIndex",
        "grantedEffect",
        "SparkPlayer",
        "index",
        None,
        "2",
    )
    assert selected(run_xml(original, use_cache=False))["stat_set_index"] == 1
    actual = selected(run_xml(changed.xml, use_cache=False))
    assert actual["effect_id"] == "SparkPlayer"
    assert actual["stat_set_index"] == 2
    assert actual["stat_set_resolved"] is True
    assert ET.fromstring(changed.xml).find(".//StatSetCalcsIndex") is None
