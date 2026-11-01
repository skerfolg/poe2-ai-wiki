"""MAIN/CALCS mode maps retain each effect instead of borrowing another's index."""

import xml.etree.ElementTree as ET

import pytest

from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, spec_from_dict, to_xml
from pok.pob.restore import spec_from_pob_xml

WIND = "Metadata/Items/Gems/SkillGemWindDancer"
BUFF = "WindDancerPlayer"
ATTACK = "TriggeredWindDancerPlayer"


def source(main, calcs, group_calcs=1):
    def tags(tag, values):
        return "".join(
            f'<{tag} grantedEffect="{key}" index="{value}"/>' for key, value in values.items()
        )

    return (
        '<PathOfBuilding2><Build className="Monk" ascendClassName="Invoker" level="90"/>'
        '<Tree><Spec nodes="" ascendancyInternalId="Monk1"/></Tree><Items/><Config/>'
        f'<Skills><Skill mainActiveSkill="2" mainActiveSkillCalcs="{group_calcs}">'
        f'<Gem gemId="{WIND}" nameSpec="Wind Dancer" enabled="true">'
        + tags("StatSetIndex", main)
        + tags("StatSetCalcsIndex", calcs)
        + "</Gem></Skill></Skills></PathOfBuilding2>"
    )


def assignments(xml, tag):
    return {
        node.get("grantedEffect"): int(node.get("index"))
        for node in ET.fromstring(xml).findall(f".//Gem/{tag}")
    }


def test_multiple_effect_and_environment_modes_survive_projection_roundtrip():
    xml = source({BUFF: 1, ATTACK: 3}, {BUFF: 2, ATTACK: 1}, group_calcs=2)
    restored = spec_from_pob_xml(xml)
    gem = restored.spec["skills"][0]["gems"][0]
    assert gem["stat_set_index"] == 1
    assert gem["stat_set_indices"] == {BUFF: 1, ATTACK: 3}
    assert gem["stat_set_calcs_indices"] == {BUFF: 2, ATTACK: 1}
    rebuilt = to_xml(spec_from_dict(restored.spec))
    assert assignments(rebuilt, "StatSetIndex") == {BUFF: 1, ATTACK: 3}
    assert assignments(rebuilt, "StatSetCalcsIndex") == {BUFF: 2, ATTACK: 1}
    assert ET.fromstring(rebuilt).find(".//Skill").get("mainActiveSkillCalcs") == "2"


def test_secondary_only_index_does_not_become_the_primary_index():
    restored = spec_from_pob_xml(source({ATTACK: 3}, {}))
    gem = restored.spec["skills"][0]["gems"][0]
    assert gem["stat_set_index"] == 1
    rebuilt = to_xml(spec_from_dict(restored.spec))
    assert assignments(rebuilt, "StatSetIndex") == {ATTACK: 3}
    assert assignments(rebuilt, "StatSetCalcsIndex") == {}


def test_legacy_primary_shorthand_stays_compact_and_mirrored():
    restored = spec_from_pob_xml(source({BUFF: 1}, {BUFF: 1}))
    gem = restored.spec["skills"][0]["gems"][0]
    assert "stat_set_indices" not in gem
    assert "stat_set_calcs_indices" not in gem
    rebuilt = to_xml(spec_from_dict(restored.spec))
    assert assignments(rebuilt, "StatSetIndex") == {BUFF: 1}
    assert assignments(rebuilt, "StatSetCalcsIndex") == {BUFF: 1}


def test_explicit_empty_calcs_map_does_not_inherit_main_choice():
    restored = spec_from_pob_xml(source({BUFF: 2}, {}))
    rebuilt = to_xml(spec_from_dict(restored.spec))
    assert assignments(rebuilt, "StatSetIndex") == {BUFF: 2}
    assert assignments(rebuilt, "StatSetCalcsIndex") == {}


def test_new_main_map_does_not_silently_edit_calcs():
    spec = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        skills=(
            SkillGroupSpec(
                gems=(
                    GemSpec(
                        gem_id=WIND,
                        name="Wind Dancer",
                        stat_set_indices=((BUFF, 2),),
                    ),
                )
            ),
        ),
    )
    rebuilt = to_xml(spec)
    assert assignments(rebuilt, "StatSetIndex") == {BUFF: 2}
    assert assignments(rebuilt, "StatSetCalcsIndex") == {}


def test_redundant_main_map_keeps_existing_legacy_calcs_choice():
    spec = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        skills=(
            SkillGroupSpec(
                gems=(
                    GemSpec(
                        gem_id=WIND,
                        name="Wind Dancer",
                        stat_set_index=2,
                        stat_set_indices=((BUFF, 2), (ATTACK, 3)),
                    ),
                )
            ),
        ),
    )
    rebuilt = to_xml(spec)
    assert assignments(rebuilt, "StatSetIndex") == {BUFF: 2, ATTACK: 3}
    assert assignments(rebuilt, "StatSetCalcsIndex") == {BUFF: 2}


@pytest.mark.parametrize("value", [{BUFF: True}, {BUFF: 1.5}, [[BUFF, 1], [BUFF, 2]], {"": 1}])
def test_malformed_or_ambiguous_map_is_rejected(value):
    with pytest.raises(ValueError):
        spec_from_dict(
            {
                "class_name": "Monk",
                "ascendancy": "Monk1",
                "skills": [
                    {
                        "gems": [
                            {
                                "gem_id": WIND,
                                "name": "Wind Dancer",
                                "stat_set_indices": value,
                            }
                        ]
                    }
                ],
            },
            validate_catalog=False,
        )


def test_conflicting_primary_shorthand_is_not_silently_ignored():
    spec = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        skills=(
            SkillGroupSpec(
                gems=(
                    GemSpec(
                        gem_id=WIND,
                        name="Wind Dancer",
                        stat_set_index=1,
                        stat_set_indices=((BUFF, 2),),
                    ),
                )
            ),
        ),
    )
    with pytest.raises(ValueError, match="conflicts"):
        to_xml(spec)


def test_ignored_legacy_attribute_is_not_reinterpreted_as_a_child_assignment():
    xml = source({}, {}).replace('enabled="true"', 'enabled="true" statSetIndex="3"')
    restored = spec_from_pob_xml(xml)
    assert restored.spec["skills"][0]["gems"][0]["stat_set_index"] == 1
    assert any("구형 statSetIndex" in message for message in restored.needs_decision)


@pytest.mark.parametrize("value", [0, True, 1.5])
def test_calcs_pointer_must_be_a_positive_integer(value):
    spec = BuildSpec(
        class_name="Monk",
        ascendancy="Monk1",
        skills=(
            SkillGroupSpec(
                gems=(GemSpec(gem_id=WIND, name="Wind Dancer", stat_set_index=1),),
                main_active_skill_calcs=value,
            ),
        ),
    )
    with pytest.raises(ValueError, match="main_active_skill_calcs"):
        to_xml(spec)
