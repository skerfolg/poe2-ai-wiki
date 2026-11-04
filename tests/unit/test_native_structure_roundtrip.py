"""Native socket/set identity must survive a calculation projection."""

import xml.etree.ElementTree as ET

import pytest

from pok.pob.buildxml import BuildSpec, JewelSpec, spec_from_dict, to_xml
from pok.pob.restore import spec_from_pob_xml


def source():
    return '''<PathOfBuilding2>
<Build className="Mercenary" level="98" mainSocketGroup="1"/>
<Tree><Spec ascendancyInternalId="Mercenary3" nodes="21984,10131,13828">
<WeaponSet1 nodes="10131"/><WeaponSet2 nodes="13828"/>
<Sockets><Socket nodeId="21984" itemId="1"/><Socket nodeId="11184" itemId="2"/></Sockets>
</Spec></Tree>
<Items><Item id="1">Rarity: UNIQUE
Voices
Sapphire
Allocates 3 Sinister Jewel sockets</Item>
<Item id="2">Rarity: RARE
Retained Jewel
Diamond
+3 to Maximum Rage</Item>
<Item id="3">Rarity: RARE
Main Bow
Warmonger Bow</Item>
<Item id="4">Rarity: UNIQUE
Hysseg's Claw
Familial Talisman
Grants Skill: Level 18 Cackling Companions</Item>
<ItemSet id="1" useSecondWeaponSet="true">
<Slot name="Weapon 1" itemId="3"/><Slot name="Weapon 1 Swap" itemId="4"/>
</ItemSet></Items>
<Skills><SkillSet><Skill mainActiveSkill="1" slot="Weapon 1 Swap">
<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20"
enabled="true" enableGlobal1="false" enableGlobal2="true"/>
</Skill></SkillSet></Skills></PathOfBuilding2>'''


def test_restore_preserves_native_sets_and_item_allocated_socket_without_paid_point():
    restored = spec_from_pob_xml(source(), assume_first_stat_set=False)
    spec = spec_from_dict(restored.spec, validate_catalog=False)
    tree = ET.fromstring(to_xml(spec))
    assert tree.find('./Items/ItemSet').get('useSecondWeaponSet') == 'true'
    assert {n.get('name') for n in tree.findall('./Items/ItemSet/Slot')} == {
        'Weapon 1', 'Weapon 1 Swap'
    }
    assert tree.find('./Tree/Spec/WeaponSet1').get('nodes') == '10131'
    assert tree.find('./Tree/Spec/WeaponSet2').get('nodes') == '13828'
    assert {n.get('nodeId') for n in tree.findall('./Tree/Spec/Sockets/Socket')} == {
        '21984', '11184'
    }
    assert '11184' not in tree.find('./Tree/Spec').get('nodes').split(',')
    group = tree.find('./Skills/SkillSet/Skill')
    assert group.get('slot') == 'Weapon 1 Swap'
    gem = group.find('Gem')
    assert gem.get('enableGlobal1') == 'false'
    assert gem.get('enableGlobal2') == 'true'
    # No new scalar choice is invented when the original leaves native defaults.
    assert gem.findall('StatSetIndex') == []
    assert restored.spec['skills'][0]['gems'][0]['stat_set_indices'] == {}


def test_normal_new_spec_still_requires_paid_socket_or_explicit_saved_mapping():
    jewel = JewelSpec(11184, 'Rarity: RARE\nSaved\nDiamond')
    with pytest.raises(ValueError, match='tree_nodes'):
        to_xml(BuildSpec('Mercenary', 'Mercenary3', jewels=(jewel,)))


@pytest.mark.parametrize('value', [0, 3, True, '2', 1.5])
def test_invalid_weapon_selector_is_rejected(value):
    with pytest.raises(ValueError, match='weapon_set'):
        spec_from_dict({'class_name': 'Mercenary', 'ascendancy': 'Mercenary3',
                        'weapon_set': value}, validate_catalog=False)


def test_explicit_empty_effect_map_is_native_fallback_not_unresolved_omission():
    from pok.pob.catalog import canonical_gem_id
    gem_id = canonical_gem_id('Metadata/Items/Gem/SkillGemIceShot')
    data = {'class_name': 'Mercenary', 'ascendancy': 'Mercenary3', 'skills': [{
        'gems': [{'gem_id': gem_id, 'name': 'Ice Shot', 'stat_set_indices': {},
                  'stat_set_calcs_indices': {}}]}]}
    spec_from_dict(data)
    del data['skills'][0]['gems'][0]['stat_set_indices']
    with pytest.raises(ValueError, match='stat_set_index'):
        spec_from_dict(data)


@pytest.mark.parametrize('value', ['false', 1, None])
def test_saved_socket_mapping_flag_must_be_boolean(value):
    jewel = JewelSpec(11184, 'Rarity: RARE\nSaved\nDiamond', preserve_socket_mapping=value)
    with pytest.raises(ValueError, match='preserve_socket_mapping'):
        to_xml(BuildSpec('Mercenary', 'Mercenary3', jewels=(jewel,)))
