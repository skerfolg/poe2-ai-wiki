"""Choose effects from document-bound observations, never infer from gem slots."""

import json
import xml.etree.ElementTree as ET

import pytest

from pok.artifacts.design import list_builds
from pok.artifacts.store import read_build_blob, record_immutable_build
from pok.engine.document_selection import plan_selection, select_effect
from pok.engine.pob_documents import measure_document, read_document
from pok.pob.runner import PobResult

SPARK = "Metadata/Items/Gems/SkillGemSpark"
XML = (
    '<PathOfBuilding2><Build mainSocketGroup="1"/><Tree><Spec/></Tree>'
    '<Skills><SkillSet id="1"><Skill mainActiveSkill="1">'
    '<Gem gemId="Metadata/Items/Gems/SkillGemUnleashSupport"/>'
    f'<Gem gemId="{SPARK}" nameSpec="Spark"><!--keep-->'
    '<StatSetCalcsIndex grantedEffect="SparkPlayer" index="1"/></Gem>'
    '</Skill></SkillSet></Skills><Unknown retained="yes"/></PathOfBuilding2>'
)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    from pok.pob import runner

    state = {"fail": False, "group": 1, "mismatch": False}

    def calculate(xml, **kwargs):
        if state["fail"]:
            raise RuntimeError("native test failure")
        mode_node = ET.fromstring(xml).find(".//StatSetIndex")
        mode = int(mode_node.get("index")) if mode_node is not None else 1
        if state["mismatch"]:
            mode = 1
        effect = {
            "group_index": state["group"],
            "active_index": 1,
            "gem_index": 2,
            "gem_id": SPARK,
            "effect_id": "SparkPlayer",
            "selected": True,
            "stat_set_index": mode,
            "stat_set_resolved": True,
            "stat_sets": [{"index": 1, "label": "Base"}, {"index": 2, "label": "Other"}],
        }
        return PobResult(
            {"Life": 100},
            {
                "nativeSelection": {
                    "format": "pok.native-selection.v1",
                    "status": "observed",
                    "actual": effect,
                    "groups": [{"group_index": state["group"], "effects": [effect]}],
                }
            },
            (),
            (),
            False,
        )

    monkeypatch.setattr(runner, "run_xml", calculate)
    stored = record_immutable_build(
        "selection-source", {"input.xml": XML.encode()}, {"kind": "pob-document"}, root=tmp_path
    )
    reference = {
        "artifact_id": stored["artifact_id"],
        "name": "input.xml",
        "sha256": stored["files"]["input.xml"]["sha256"],
    }
    return reference, state


def test_mode_is_edited_on_observed_gem_two_not_active_index_one(fixture, tmp_path):
    reference, _ = fixture
    before = measure_document(reference, stats=[], root=tmp_path)
    selected = select_effect(
        reference, before["xml_revision"], before["document_measurement_ref"], 1, 2, root=tmp_path
    )
    assert selected["status"] == "native_selection_matched"
    assert selected["plan"]["expected_native"]["gem_index"] == 2
    current = read_document(selected["candidate"]["xml_ref"], root=tmp_path)["xml_text"]
    root = ET.fromstring(current)
    gems = root.findall(".//Gem")
    assert gems[0].find("StatSetIndex") is None
    assert gems[1].find("StatSetIndex").get("index") == "2"
    assert gems[1].find("StatSetCalcsIndex").get("index") == "1"
    assert '<Unknown retained="yes"/>' in current and "<!--keep-->" in current
    assert read_document(reference, root=tmp_path)["xml_text"] == XML
    assert list_builds(root=tmp_path) == ()
    ref = selected["selection_ref"]
    stored = json.loads(
        read_build_blob(
            **{key: ref[key] for key in ("artifact_id", "name", "sha256")}, root=tmp_path
        )
    )
    assert stored["plan"]["document_measurement_ref"] == before["document_measurement_ref"]


@pytest.mark.parametrize("active,mode", [(2, 1), (1, 3), (True, 1), (1, 0)])
def test_unobserved_effect_or_mode_never_publishes_a_candidate(fixture, tmp_path, active, mode):
    reference, _ = fixture
    before = measure_document(reference, root=tmp_path)
    count = len(list((tmp_path / "artifacts/builds").iterdir()))
    with pytest.raises(ValueError):
        select_effect(
            reference,
            before["xml_revision"],
            before["document_measurement_ref"],
            active,
            mode,
            root=tmp_path,
        )
    assert len(list((tmp_path / "artifacts/builds").iterdir())) == count


def test_source_coordinate_mismatch_is_not_guessed(fixture, tmp_path):
    reference, state = fixture
    state["group"] = 2
    before = measure_document(reference, root=tmp_path)
    with pytest.raises(ValueError, match="coordinates"):
        plan_selection(
            reference,
            before["xml_revision"],
            before["document_measurement_ref"],
            1,
            2,
            root=tmp_path,
        )


def test_remeasurement_failure_or_mismatch_is_retained_not_marked_matched(fixture, tmp_path):
    reference, state = fixture
    before = measure_document(reference, root=tmp_path)
    state["fail"] = True
    failed = select_effect(
        reference, before["xml_revision"], before["document_measurement_ref"], 1, 2, root=tmp_path
    )
    assert failed["status"] == "measurement_failed"
    assert failed["selection_ref"] and failed["candidate"]["xml_ref"]
    state["fail"] = False
    state["mismatch"] = True
    mismatch = select_effect(
        reference, before["xml_revision"], before["document_measurement_ref"], 1, 2, root=tmp_path
    )
    assert mismatch["status"] == "native_selection_mismatch"
    assert read_document(reference, root=tmp_path)["xml_text"] == XML


def test_mcp_selection_keeps_the_bound_input_and_postmeasurement(monkeypatch, fixture, tmp_path):
    import asyncio

    from fastmcp import Client, FastMCP

    from pok.mcp import server

    reference, _ = fixture
    before = measure_document(reference, root=tmp_path)
    api = FastMCP("document-selection-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(
        server._document_selection,
        "select_effect",
        lambda *args, **kwargs: select_effect(*args, root=tmp_path, **kwargs),
    )
    server.tool(server.select_pob_document_effect.__wrapped__)

    async def exercise():
        async with Client(api) as client:
            result = (
                await client.call_tool(
                    "select_pob_document_effect",
                    {
                        "xml_ref": reference,
                        "expected_revision": before["xml_revision"],
                        "document_measurement_ref": before["document_measurement_ref"],
                        "active_index": 1,
                        "stat_set_index": 2,
                    },
                )
            ).data
            assert result["format"] == "pok.document-selection.v1"
            assert result["status"] == "native_selection_matched"
            assert result["plan"]["document_measurement_ref"] == before["document_measurement_ref"]
            assert result["measurement"]["document_measurement_ref"]
            assert result["selection_ref"]

    asyncio.run(exercise())
