"""One explicit item/tree/gem patch preserves the original and inactive XML."""

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.design_service import capture_material
from pok.engine.pob_documents import (
    edit_document,
    inspect_document,
    load_document_measurement,
    measure_document,
    read_document,
)
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT or pinned PoB unavailable")


def test_native_item_passive_and_gem_bundle_preserves_original(tmp_path):
    graph = TreeGraph(knowledge_dir())
    start = graph.start_of("Sorceress")
    neighbor = next(
        node
        for node in sorted(graph.adj[start])
        if node in graph.nodes
        and not graph.nodes[node].ascendancy
        and graph.nodes[node].kind == "small"
    )
    old_item = "Rarity: RARE\nProbe\nGold Ring\nItem Level: 80\nImplicits: 0\n+10 to maximum Life"
    xml = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            tree_nodes=(start,),
            items=(ItemSpec(slot="Ring 1", text=old_item),),
            skills=(
                SkillGroupSpec(
                    gems=(
                        GemSpec(
                            gem_id="Metadata/Items/Gems/SkillGemSpark",
                            name="Spark",
                            level=1,
                        ),
                    )
                ),
            ),
        )
    )
    extra = '<!--preserve--><FutureSetting key="unknown"/>'
    xml = xml.replace("</PathOfBuilding2>", extra + "</PathOfBuilding2>")
    parent = capture_material(xml_text=xml, root=tmp_path)["material"]["xml"]
    before = measure_document(parent, stats=["Life"], use_cache=False, root=tmp_path)
    inspected = inspect_document(parent, limit=100, root=tmp_path)
    nodes = inspected["nodes"]
    item = next(node for node in nodes if node["tag"] == "Item")
    tree = next(node for node in nodes if node["tag"] == "Spec")
    gem = next(node for node in nodes if node["tag"] == "Gem")
    changes = [
        {
            "op": "set_text",
            "path": item["path"],
            "tag": "Item",
            "expected_raw_value": item["raw_text"],
            "value": old_item.replace("+10", "+110"),
        },
        {
            "path": tree["path"],
            "tag": "Spec",
            "attribute": "nodes",
            "expected_raw_value": tree["raw_attributes"]["nodes"],
            "value": f"{start},{neighbor}",
        },
        {
            "path": gem["path"],
            "tag": "Gem",
            "attribute": "level",
            "expected_raw_value": gem["raw_attributes"]["level"],
            "value": "2",
        },
    ]
    child = edit_document(parent, inspected["xml_revision"], changes, root=tmp_path)
    after = measure_document(child["xml_ref"], stats=["Life"], use_cache=False, root=tmp_path)
    assert after["stats"]["Life"] > before["stats"]["Life"]
    assert read_document(parent, root=tmp_path)["xml_text"] == xml
    assert extra in read_document(child["xml_ref"], root=tmp_path)["xml_text"]
    assert after["meta"]["nativeSelection"]["actual"]["effect_id"] == "SparkPlayer"
    full = load_document_measurement(
        after["document_measurement_ref"], child["xml_ref"], root=tmp_path
    )
    assert neighbor in full["measurement"]["allocated_nodes"]
    # Parent remains a usable, independently measurable restore target.
    restored = measure_document(parent, stats=["Life"], use_cache=False, root=tmp_path)
    assert restored["stats"]["Life"] == before["stats"]["Life"]
