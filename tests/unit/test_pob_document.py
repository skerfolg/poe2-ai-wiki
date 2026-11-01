"""XML edits change selected tokens while preserving all other source bytes."""

import pytest

from pok.pob.document import (
    inspect_xml,
    select_xml_node,
    set_xml_attribute,
    set_xml_text,
    upsert_xml_child_attribute,
    xml_node_pointer,
    xml_revision,
)

XML = (
    '\ufeff<?xml version="1.0"?>\r\n<PathOfBuilding2 future="한글 &amp; extra">\r\n'
    '<!-- <Skill mainActiveSkill="88"/> -->\r\n'
    '<Unknown><![CDATA[<Skill mainActiveSkill="99"/>]]></Unknown>\r\n'
    '<Skills activeSkillSet="2"><SkillSet id="2">'
    "<Skill label='a > b' mainActiveSkill = '1'><Gem nameSpec=\"Spark\"/></Skill>"
    "</SkillSet></Skills>\r\n"
    '<Items><ItemSet id="7" note="inactive preserved"/></Items>\r\n</PathOfBuilding2>'
)


def test_binding_pointer_selects_exact_unicode_subtree_not_filtered_index():
    assert xml_node_pointer((1, 0, 0, 0)) == "/nodes/1.0.0.0"
    assert select_xml_node(XML, "/nodes/1.0.0.0") == '<Gem nameSpec="Spark"/>'
    assert select_xml_node(XML, "/nodes/0") == (
        '<Unknown><![CDATA[<Skill mainActiveSkill="99"/>]]></Unknown>'
    )
    assert "<!-- <Skill" in select_xml_node(XML, "/nodes/root")
    assert select_xml_node(XML, "/nodes/root").endswith("</PathOfBuilding2>")


@pytest.mark.parametrize("pointer", ["/nodes/01", "/nodes/-1", "/nodes/999", "/items/0"])
def test_binding_pointer_rejects_aliases_and_missing_nodes(pointer):
    with pytest.raises(ValueError):
        select_xml_node(XML, pointer)


def test_leaf_text_edit_preserves_all_outside_bytes_and_escapes_new_text():
    xml = (
        '\ufeff<Root future="한글">\r\n<!--keep-->'
        '<Item id="1">old &amp; raw</Item><Inactive/></Root>'
    )
    changed = set_xml_text(xml, xml_revision(xml), (0,), "old &amp; raw", "new <text> & value")
    assert changed.xml == xml.replace("old &amp; raw", "new &lt;text&gt; &amp; value")
    assert changed.changed
    with pytest.raises(ValueError, match="value conflict"):
        set_xml_text(changed.xml, changed.revision, (0,), "old &amp; raw", "wrong")


def test_cdata_and_empty_leaf_text_edits_are_valid_without_rewriting_neighbors():
    import xml.etree.ElementTree as ET

    xml = '<Root><Item><![CDATA[old <raw>]]></Item><Empty future="keep"/></Root>'
    changed = set_xml_text(xml, xml_revision(xml), (0,), "<![CDATA[old <raw>]]>", "new ]]> & raw")
    assert ET.fromstring(changed.xml).find("Item").text == "new ]]> & raw"
    assert '<Empty future="keep"/>' in changed.xml
    filled = set_xml_text(changed.xml, changed.revision, (1,), "", "value")
    assert '<Empty future="keep">value</Empty>' in filled.xml
    assert not set_xml_text(xml, xml_revision(xml), (1,), "", "").changed


@pytest.mark.parametrize("body", ["<!--keep-->old", "<?keep value?>old", "<Unknown/>old"])
def test_text_edit_refuses_to_delete_mixed_or_unknown_markup(body):
    xml = f"<Root><Item>{body}</Item></Root>"
    with pytest.raises(ValueError):
        set_xml_text(xml, xml_revision(xml), (0,), body, "new")


def test_utf8_offsets_comments_cdata_and_unknown_sections_are_preserved():
    result = set_xml_attribute(XML, xml_revision(XML), (1, 0, 0), "mainActiveSkill", "1", "2")
    assert result.xml == XML.replace("mainActiveSkill = '1'", "mainActiveSkill = '2'")
    assert result.parent_revision == xml_revision(XML)
    assert result.revision == xml_revision(result.xml)
    assert result.changed is True
    node = next(node for node in inspect_xml(result.xml) if node.path == (1, 0, 0))
    assert node.attributes["mainActiveSkill"] == "2"
    assert node.attributes["label"] == "a > b"


def test_add_to_self_closing_element_keeps_unrecognized_unicode_attribute():
    source = "<PathOfBuilding2 注='main=\"shadow\"' />"
    result = set_xml_attribute(source, xml_revision(source), (), "main", None, "2")
    assert result.xml == '<PathOfBuilding2 注=\'main="shadow"\'  main="2"/>'


def test_numeric_entity_is_not_mistaken_for_a_literal_noop():
    source = '<PathOfBuilding2 index="&#x32;" />'
    node = inspect_xml(source)[0]
    assert node.attributes["index"] == "2"
    assert node.raw_attributes["index"] == "&#x32;"
    result = set_xml_attribute(source, xml_revision(source), (), "index", "&#x32;", "2")
    assert result.changed
    assert result.xml == '<PathOfBuilding2 index="2" />'
    noop = set_xml_attribute(result.xml, result.revision, (), "index", "2", "2")
    assert noop.changed is False
    assert noop.xml == result.xml
    assert noop.revision == result.revision


def test_literal_multiline_attribute_value_is_not_normalized_by_rewriting():
    source = '<PathOfBuilding2 customMods="first\r\nsecond" mode="1"/>'
    result = set_xml_attribute(source, xml_revision(source), (), "mode", "1", "2")
    assert result.xml == source.replace('mode="1"', 'mode="2"')
    changed = set_xml_attribute(
        source, xml_revision(source), (), "customMods", "first\r\nsecond", "a\nb"
    )
    assert 'customMods="a\nb"' in changed.xml
    assert "&#10;" not in changed.xml


def test_quote_encoding_uses_existing_delimiter_and_named_entities():
    source = "<PathOfBuilding2 label='old'/>"
    result = set_xml_attribute(source, xml_revision(source), (), "label", "old", "a'b & <c>\"d")
    assert result.xml == "<PathOfBuilding2 label='a&apos;b &amp; &lt;c&gt;\"d'/>"


@pytest.mark.parametrize(
    "path,attribute,expected",
    [
        ((9,), "mode", None),
        ((), "future", "wrong"),
        ((True,), "mode", None),
        ((), "bad name", None),
    ],
)
def test_conflicting_or_invalid_targets_do_not_produce_an_edit(path, attribute, expected):
    with pytest.raises(ValueError):
        set_xml_attribute(XML, xml_revision(XML), path, attribute, expected, "2")


def test_revision_conflict_and_invalid_replacement_fail():
    with pytest.raises(ValueError, match="revision"):
        set_xml_attribute(XML, "sha256:" + "0" * 64, (), "future", "old", "new")
    with pytest.raises(ValueError):
        set_xml_attribute(XML, xml_revision(XML), (), "future", "한글 &amp; extra", "bad\x00value")


def test_unsupported_or_malformed_source_is_not_partially_edited():
    for source in ('<!DOCTYPE r [<!ENTITY x "1">]><r/>', '<r a="1" a="2"/>', "<r>"):
        with pytest.raises(ValueError):
            inspect_xml(source)


@pytest.mark.parametrize("parent", ['<Gem name="한글" />', '<Gem name="한글"></Gem>'])
def test_insert_mode_child_preserves_surrounding_source(parent):
    source = "\ufeff<R>\r\n<!--keep-->" + parent + "<Unknown/>\r\n</R>"
    changed = upsert_xml_child_attribute(
        source,
        xml_revision(source),
        (0,),
        "StatSetIndex",
        "grantedEffect",
        "SparkPlayer",
        "index",
        None,
        "2",
    )
    expected_parent = (
        '<Gem name="한글" ><StatSetIndex grantedEffect="SparkPlayer" index="2"/></Gem>'
        if parent.endswith("/>")
        else '<Gem name="한글"><StatSetIndex grantedEffect="SparkPlayer" index="2"/></Gem>'
    )
    assert changed.xml == source.replace(parent, expected_parent)
    nodes = inspect_xml(changed.xml)
    for node in nodes:
        raw = changed.xml.encode("utf-8")
        assert raw[node.start : node.end].startswith(b"<")
        assert raw[node.start : node.end].endswith(b">")


def test_existing_child_value_changes_without_touching_other_modes():
    source = (
        "<R><Gem><!--kept--><StatSetIndex grantedEffect=\"SparkPlayer\" index='1'/>"
        '<StatSetCalcsIndex grantedEffect="SparkPlayer" index="1"/>'
        "<Unknown><![CDATA[</Gem>]]></Unknown></Gem></R>"
    )
    changed = upsert_xml_child_attribute(
        source,
        xml_revision(source),
        (0,),
        "StatSetIndex",
        "grantedEffect",
        "SparkPlayer",
        "index",
        "1",
        "2",
    )
    assert changed.xml == source.replace("index='1'", "index='2'")


def test_nested_unknown_child_is_not_mistaken_for_direct_mode_binding():
    source = (
        '<R><Gem><Unknown><StatSetIndex grantedEffect="SparkPlayer" index="9"/></Unknown></Gem></R>'
    )
    changed = upsert_xml_child_attribute(
        source,
        xml_revision(source),
        (0,),
        "StatSetIndex",
        "grantedEffect",
        "SparkPlayer",
        "index",
        None,
        "2",
    )
    assert changed.xml == source.replace(
        "</Gem>", '<StatSetIndex grantedEffect="SparkPlayer" index="2"/></Gem>'
    )


@pytest.mark.parametrize(
    "children,expected",
    [
        ('<StatSetIndex grantedEffect="SparkPlayer" index="1"/>' * 2, "1"),
        ("", "1"),
    ],
)
def test_duplicate_or_missing_expected_child_is_rejected(children, expected):
    source = f"<R><Gem>{children}</Gem></R>"
    with pytest.raises(ValueError):
        upsert_xml_child_attribute(
            source,
            xml_revision(source),
            (0,),
            "StatSetIndex",
            "grantedEffect",
            "SparkPlayer",
            "index",
            expected,
            "2",
        )
