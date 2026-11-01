"""Saved active IDs and tree ordinals select actual restored input, not first sets."""

import xml.etree.ElementTree as ET

import pytest

from pok.pob.parse import parse_pob_xml
from pok.pob.restore import spec_from_pob_xml
from pok.pob.selection import resolve_xml_selection

XML = """<PathOfBuilding2>
<Build className="Monk" ascendClassName="Invoker" level="90" mainSocketGroup="1"/>
<Tree activeSpec="2">
 <Spec nodes="13828" ascendancyInternalId="Monk1" treeVersion="first"/>
 <Spec nodes="10131" ascendancyInternalId="Monk1" treeVersion="second"/>
</Tree>
<Items activeItemSet="7">
 <Item id="1">Rarity: RARE
First Ring
Iron Ring</Item>
 <Item id="2">Rarity: RARE
Selected Ring
Iron Ring</Item>
 <ItemSet id="3"><Slot name="Ring 1" itemId="1"/></ItemSet>
 <ItemSet id="7"><Slot name="Ring 1" itemId="2"/></ItemSet>
</Items>
<Skills activeSkillSet="9">
 <SkillSet id="4"><Skill enabled="true">
  <Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="10"/>
 </Skill></SkillSet>
 <SkillSet id="9"><Skill enabled="true">
  <Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="19"/>
 </Skill></SkillSet>
</Skills>
<Config activeConfigSet="8">
 <ConfigSet id="2"><Input name="conditionStationary" number="4"/></ConfigSet>
 <ConfigSet id="8"><Input name="conditionStationary" number="1.5"/>
  <Input name="enemyLevel" number="82"/></ConfigSet>
</Config>
</PathOfBuilding2>"""


def test_nonconsecutive_ids_and_tree_ordinal_restore_the_selected_values():
    restored = spec_from_pob_xml(XML)
    assert restored.spec["tree_nodes"] == [10131]
    assert "Selected Ring" in restored.spec["items"][0]["text"]
    assert restored.spec["skills"][0]["gems"][0]["level"] == 19
    assert dict(restored.spec["config"])["conditionStationary"] == 1.5
    assert dict(restored.spec["config"])["enemyLevel"] == 82
    assert restored.selection == {
        "tree_spec": "2",
        "item_set": "7",
        "skill_set": "9",
        "config_set": "8",
        "weapon_set": 1,
    }
    summary = parse_pob_xml(XML)
    assert summary.tree_nodes == (10131,)
    assert summary.tree_version == "second"
    assert summary.selection == restored.selection


def test_fractional_config_survives_restore_spec_and_xml_export():
    from pok.pob.buildxml import spec_from_dict, to_xml

    first = spec_from_pob_xml(XML)
    rebuilt = to_xml(spec_from_dict(first.spec))
    item = ET.fromstring(rebuilt).find("./Config/Input[@name='conditionStationary']")
    assert item.get("number") == "1.5"
    assert item.get("string") is None
    assert dict(spec_from_pob_xml(rebuilt).spec["config"])["conditionStationary"] == 1.5


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_config_cannot_be_exported_as_a_number(value):
    from pok.pob.buildxml import BuildSpec, to_xml

    with pytest.raises(ValueError, match="finite"):
        to_xml(BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", config=(("x", value),)))


def test_default_id_one_is_not_the_first_list_entry():
    root = ET.fromstring(
        XML.replace('activeItemSet="7"', "").replace('<ItemSet id="7">', '<ItemSet id="1">')
    )
    selected = resolve_xml_selection(root)
    assert selected.resolved["item_set"] == "1"
    assert selected.items.find("Slot").get("itemId") == "2"


def test_integral_decimal_and_exponent_ids_use_numeric_identity():
    text = (
        XML.replace('activeItemSet="7"', 'activeItemSet="7e0"')
        .replace('<ItemSet id="7">', '<ItemSet id="7.0">')
        .replace('activeSpec="2"', 'activeSpec="2.0"')
    )
    selected = resolve_xml_selection(ET.fromstring(text))
    assert selected.resolved["item_set"] == "7"
    assert selected.resolved["tree_spec"] == "2"
    assert selected.notes == ()


def test_explicit_selection_overrides_saved_active_sets_without_rewriting_xml():
    requested = {"item_set": "3", "skill_set": "4", "config_set": "2", "tree_spec": "1"}
    restored = spec_from_pob_xml(XML, selection=requested)
    assert "First Ring" in restored.spec["items"][0]["text"]
    assert restored.spec["skills"][0]["gems"][0]["level"] == 10
    assert restored.spec["tree_nodes"] == [13828]
    assert dict(restored.spec["config"])["conditionStationary"] == 4
    assert all(restored.selection[key] == value for key, value in requested.items())
    assert 'activeItemSet="7"' in XML


@pytest.mark.parametrize(
    "selection",
    [
        {"item_set": "99"},
        {"tree_spec": "99"},
        {"tree_spec": "0"},
        {"config_set": "7.5"},
        {"weapon_set": True},
        {"item_set": 7},
        {"main_active_skill": 1},
    ],
)
def test_invalid_or_unsupported_explicit_choice_never_falls_back(selection):
    with pytest.raises(ValueError):
        spec_from_pob_xml(XML, selection=selection)


def test_explicit_weapon_set_is_reported():
    restored = spec_from_pob_xml(XML, selection={"weapon_set": 2})
    assert restored.selection["weapon_set"] == 2


def test_json_integral_numeric_pointer_is_normalized_without_boolean_coercion():
    selected = resolve_xml_selection(ET.fromstring(XML), {"main_group": 1.0, "weapon_set": 2.0})
    assert type(selected.resolved["main_group"]) is int
    assert selected.resolved["main_group"] == 1
    assert selected.resolved["weapon_set"] == 2
    with pytest.raises(ValueError):
        resolve_xml_selection(ET.fromstring(XML), {"main_group": True})
    with pytest.raises(ValueError):
        resolve_xml_selection(ET.fromstring(XML), {"main_group": 1.5})


def test_explicit_main_group_uses_xml_group_ordinal_and_remaps_dropped_groups():
    import copy

    root = ET.fromstring(XML)
    selected = root.find("./Skills/SkillSet[@id='9']")
    second = copy.deepcopy(selected.find("Skill"))
    second.find("Gem").set("level", "17")
    selected.append(second)
    selected.insert(0, ET.fromstring('<Skill source="Item"><Gem nameSpec="item skill"/></Skill>'))
    text = ET.tostring(root, encoding="unicode")
    result = spec_from_pob_xml(text, selection={"main_group": 3})
    assert result.selection["main_group"] == 3
    assert result.spec["main_socket_group"] == 2
    assert result.spec["skills"][1]["gems"][0]["level"] == 17
    with pytest.raises(ValueError, match="dropped"):
        spec_from_pob_xml(text, selection={"main_group": 1})
    with pytest.raises(ValueError):
        spec_from_pob_xml(text, selection={"main_group": 4})


def test_oversized_numeric_identity_is_rejected_without_expanding_the_integer():
    with pytest.raises(ValueError):
        resolve_xml_selection(ET.fromstring(XML), {"item_set": "1e999999999"})


def test_selected_item_set_controls_weapon_swap_and_preserves_source():
    root = ET.fromstring(
        XML.replace('<ItemSet id="3">', '<ItemSet id="3" useSecondWeaponSet="false">').replace(
            '<ItemSet id="7">', '<ItemSet id="7" useSecondWeaponSet="true">'
        )
    )
    before = ET.tostring(root)
    selected = resolve_xml_selection(root)
    assert selected.resolved["weapon_set"] == 2
    assert ET.tostring(root) == before


def test_missing_ids_and_out_of_range_tree_fallback_are_reported():
    text = XML.replace('activeItemSet="7"', 'activeItemSet="99"').replace(
        'activeSpec="2"', 'activeSpec="99"'
    )
    restored = spec_from_pob_xml(text)
    assert "First Ring" in restored.spec["items"][0]["text"]
    assert restored.selection["tree_spec"] == "2"
    assert any("activeItemSet" in note for note in restored.notes)
    assert any("activeSpec" in note for note in restored.notes)
    assert restored.faithful is False


@pytest.mark.parametrize(
    "text",
    [
        XML.replace('<ItemSet id="7">', '<ItemSet id="3">'),
        XML.replace('activeSpec="2"', 'activeSpec="0"'),
        XML.replace('<SkillSet id="4">', "<SkillSet>"),
    ],
)
def test_ambiguous_or_invalid_selections_are_not_silently_certified(text):
    with pytest.raises(ValueError):
        spec_from_pob_xml(text)


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_config_values_are_not_silently_replaced(value):
    with pytest.raises(ValueError, match="Nonfinite config"):
        spec_from_pob_xml(XML.replace('number="1.5"', f'number="{value}"'))
