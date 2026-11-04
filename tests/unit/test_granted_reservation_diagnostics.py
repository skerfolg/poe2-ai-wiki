"""Known #167 facts belong next to measurements, not only KB lookups."""
import xml.etree.ElementTree as ET

from pok.engine.integrity import (
    granted_reservation_diagnostics,
    xml_granted_reservation_diagnostics,
)


def amulet(base='Absent Amulet', slot='Amulet'):
    return {'slot': slot, 'text': f'Rarity: RARE\nExample\n{base}\n'
            'Grants Skill: Level 20 Eternal Rage'}


def test_known_free_grant_does_not_rewrite_or_excuse_all_negative_spirit():
    stats = {'SpiritUnreserved': -94}
    report = granted_reservation_diagnostics([amulet()], stats)
    fact = report['granted_skill_instances'][0]
    assert fact['granted_instance_spirit_reservation'] == 0
    assert fact['gem_instance_is_separate'] is True
    assert report['known_pob_limitations'][0]['native_spirit_unreserved'] == -94
    assert '재검증 요청하지 말 것' in report['known_pob_limitations'][0]['note']
    assert stats == {'SpiritUnreserved': -94}


def test_positive_spirit_still_reports_separate_free_instance_without_deficit_warning():
    report = granted_reservation_diagnostics([amulet('Lament Amulet')], {'SpiritUnreserved': 15})
    assert report['granted_skill_instances']
    assert 'known_pob_limitations' not in report


def test_unknown_grant_sources_and_wrong_slot_are_not_promoted_to_verified_fact():
    assert granted_reservation_diagnostics([amulet('Unknown Amulet')], {}) == {}
    assert granted_reservation_diagnostics([amulet(slot='Helmet')], {}) == {}


def test_raw_document_resolves_only_equipped_amulet_in_saved_active_set():
    root = ET.fromstring('''<PathOfBuilding2><Build level="98"/>
<Items activeItemSet="2"><Item id="1"/><Item id="2"/>
<ItemSet id="1"><Slot name="Amulet" itemId="1"/></ItemSet>
<ItemSet id="2"><Slot name="Amulet" itemId="2"/></ItemSet></Items>
</PathOfBuilding2>''')
    root.find('./Items/Item[@id="1"]').text = amulet()['text']
    root.find('./Items/Item[@id="2"]').text = amulet('Unknown Amulet')['text']
    xml = ET.tostring(root, encoding='unicode')
    assert xml_granted_reservation_diagnostics(xml, {'SpiritUnreserved': -94}) == {}
    root.find('Items').set('activeItemSet', '1')
    xml = ET.tostring(root, encoding='unicode')
    assert xml_granted_reservation_diagnostics(xml, {'SpiritUnreserved': -94})[
        'granted_skill_instances'
    ][0]['skill'] == 'Eternal Rage'
