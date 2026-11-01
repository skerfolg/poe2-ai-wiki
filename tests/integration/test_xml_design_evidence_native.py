"""Actual raw-XML measurement connects to design evidence without a spec fiction."""

import pytest

from pok.artifacts.design_record import create_record, record_json, seal_record
from pok.engine.design_evidence import inspect_evidence
from pok.engine.design_service import capture_material
from pok.engine.pob_documents import measure_document
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not ready(), reason="LuaJIT or pinned PoB unavailable")


def test_native_xml_statistics_are_current_only_on_their_linked_material(tmp_path):
    xml = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(
                SkillGroupSpec(
                    gems=(
                        GemSpec(
                            gem_id="Metadata/Items/Gems/SkillGemSpark",
                            name="Spark",
                            stat_set_index=1,
                        ),
                    )
                ),
            ),
        )
    )
    material = capture_material(xml_text=xml, root=tmp_path)["material"]
    measured = measure_document(material["xml"], stats=[], use_cache=False, root=tmp_path)
    record = create_record("native-xml-evidence", "원문 측정 근거 연결")
    record["material"] = material
    record["evidence"] = [
        {
            "id": "native-life",
            "kind": "measurement",
            "label": "Actual XML Life",
            "scope": {
                "description": "Native subject",
                "decision_ids": [],
                "usage": "current",
                "material_revision": material["revision"],
            },
            "source": {**measured["design_evidence_source"], "path": "/stats/Life"},
        }
    ]
    checked = inspect_evidence(record_json(seal_record(record)), root=tmp_path)
    assert checked["evidence_assessments"][0]["application"] == "current_xml_verified"
    assert checked["checks"]["current_evidence_application"] == "current_declared_inputs_verified"
    assert checked["checks"]["game_feasibility"] == "not_checked"
    assert checked["evidence_assessments"][0]["execution_identity"] == "not_verified"
