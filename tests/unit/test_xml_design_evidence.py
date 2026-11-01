"""XML measurement refs are a distinct subject, not fabricated BuildSpec proof."""

import copy

import pytest

from pok.artifacts.design_record import DesignRecordError, create_record, record_json, seal_record
from pok.engine.design_evidence import inspect_evidence
from pok.engine.design_service import capture_material
from pok.engine.pob_documents import measure_document
from pok.pob.runner import PobResult

XML = (
    '<PathOfBuilding2><Build mainSocketGroup="1"/><Tree><Spec/></Tree>'
    '<Skills><SkillSet id="1"><Skill><Gem/></Skill></SkillSet></Skills>'
    '<Items><ItemSet id="1"/></Items><Config><ConfigSet id="1"/></Config>'
    "<!--original--></PathOfBuilding2>"
)


@pytest.fixture
def measured(tmp_path, monkeypatch):
    from pok.pob import runner

    actual = {"active_index": 1, "stat_set_index": 1, "stat_set_resolved": True, "selected": True}
    monkeypatch.setattr(
        runner,
        "run_xml",
        lambda *args, **kwargs: PobResult(
            {"Life": 100},
            {
                "nativeSelection": {
                    "format": "pok.native-selection.v1",
                    "status": "observed",
                    "actual": actual,
                }
            },
            (),
            (),
            False,
        ),
    )
    material = capture_material(xml_text=XML, root=tmp_path)["material"]
    result = measure_document(material["xml"], root=tmp_path)
    evidence = {
        "id": "xml-life",
        "kind": "measurement",
        "label": "Native XML Life",
        "scope": {
            "description": "Exact XML",
            "decision_ids": [],
            "usage": "current",
            "material_revision": material["revision"],
        },
        "source": {**result["design_evidence_source"], "path": "/stats/Life"},
    }
    return material, evidence


def document(material, evidence):
    record = create_record("xml-evidence", "XML 근거 연결")
    record["material"] = material
    record["evidence"] = [evidence]
    return record_json(seal_record(record))


def test_current_xml_subject_is_verified_without_game_or_execution_certificate(measured, tmp_path):
    material, evidence = measured
    result = inspect_evidence(
        document(material, evidence), root=tmp_path, expected_source={"loaded_commit": "host"}
    )
    row = result["evidence_assessments"][0]
    assert row["integrity"] == "verified" and row["application"] == "current_xml_verified"
    assert result["checks"]["current_evidence_application"] == "current_declared_inputs_verified"
    assert result["checks"]["measurement_source_compatibility"] == "needs_review"
    assert row["execution_identity"] == "not_verified"
    assert result["checks"]["game_feasibility"] == "not_checked"


def test_other_xml_is_not_current_but_comparison_remains_valid(measured, tmp_path):
    _, evidence = measured
    other = capture_material(xml_text=XML.replace("original", "changed"), root=tmp_path)["material"]
    checked = inspect_evidence(document(other, evidence), root=tmp_path)
    assert checked["evidence_assessments"][0]["application"] == "different_input"
    historical = copy.deepcopy(evidence)
    historical["scope"]["usage"] = "comparison"
    checked = inspect_evidence(document(other, historical), root=tmp_path)
    assert checked["evidence_assessments"][0]["integrity"] == "verified"
    assert checked["evidence_assessments"][0]["application"] == "comparison"


def test_same_xml_reuse_requires_explicit_material_mapping(measured, tmp_path):
    _, evidence = measured
    other = capture_material(xml_text=XML, root=tmp_path)["material"]
    result = inspect_evidence(document(other, evidence), root=tmp_path)
    assert result["evidence_assessments"][0]["application"] == "same_xml_reuse_requires_mapping"
    fixed = copy.deepcopy(evidence)
    fixed["scope"]["material_revision"] = other["revision"]
    assert (
        inspect_evidence(document(other, fixed), root=tmp_path)["evidence_assessments"][0][
            "application"
        ]
        == "current_xml_verified"
    )


@pytest.mark.parametrize("path", ["/source_xml_ref", "/stats/Missing"])
def test_receipt_claim_or_missing_value_is_not_a_native_measurement(measured, tmp_path, path):
    material, evidence = measured
    evidence["source"]["path"] = path
    assert (
        inspect_evidence(document(material, evidence), root=tmp_path)["evidence_assessments"][0][
            "integrity"
        ]
        == "unsupported"
    )


def test_current_selection_cannot_differ_from_native_observation(measured, tmp_path):
    _, evidence = measured
    current = capture_material(xml_text=XML, selection={"stat_set": 2}, root=tmp_path)["material"]
    evidence["scope"]["material_revision"] = current["revision"]
    result = inspect_evidence(document(current, evidence), root=tmp_path)
    assert result["evidence_assessments"][0]["application"] == "selection_requires_review"
    assert result["checks"]["current_evidence_application"] == "needs_review"


def test_mixed_xml_and_spec_claim_shape_is_rejected(measured):
    material, evidence = measured
    evidence["source"]["spec_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(DesignRecordError):
        document(material, evidence)


def test_link_helper_verifies_current_input_and_preserves_parent(measured, tmp_path):
    from pok.engine.design_checkpoints import save_checkpoint
    from pok.engine.design_service import link_document_measurement, read_design

    material, evidence = measured
    record = create_record("link-test", "연결")
    record["material"] = material
    parent = save_checkpoint(record_json(seal_record(record)), root=tmp_path)
    result = link_document_measurement(
        parent,
        parent["revision"],
        evidence["source"]["document_measurement_ref"],
        evidence_id="linked",
        label="Life",
        description="원문 계산",
        path="/stats/Life",
        root=tmp_path,
    )
    assert result["current_assessment"]["evidence_assessments"][0]["application"] == (
        "current_xml_verified"
    )
    assert read_design(parent, root=tmp_path)["record_json"] == record_json(seal_record(record))
    with pytest.raises(DesignRecordError, match="Expected revision"):
        link_document_measurement(
            parent,
            result["record_ref"]["revision"],
            evidence["source"]["document_measurement_ref"],
            evidence_id="stale",
            label="Life",
            description="stale",
            root=tmp_path,
        )


def test_link_helper_rejects_other_xml_and_requires_historical_revision(measured, tmp_path):
    from pok.engine.design_checkpoints import save_checkpoint
    from pok.engine.design_service import link_document_measurement

    _, evidence = measured
    record = create_record("other-input", "다른 입력")
    record["material"] = capture_material(xml_text=XML + "\n", root=tmp_path)["material"]
    parent = save_checkpoint(record_json(seal_record(record)), root=tmp_path)
    args = (parent, parent["revision"], evidence["source"]["document_measurement_ref"])
    kwargs = dict(evidence_id="linked", label="Life", description="비교", root=tmp_path)
    with pytest.raises(DesignRecordError, match="different_input"):
        link_document_measurement(*args, **kwargs)
    with pytest.raises(DesignRecordError, match="original material revision"):
        link_document_measurement(*args, **kwargs, usage="comparison")
    result = link_document_measurement(
        *args,
        **kwargs,
        usage="comparison",
        material_revision=evidence["scope"]["material_revision"],
    )
    assert result["current_assessment"]["evidence_assessments"][0]["application"] == "comparison"


def test_mcp_attachment_roundtrip_and_stale_revision(measured, tmp_path, monkeypatch):
    import asyncio

    from fastmcp import Client, FastMCP
    from fastmcp.exceptions import ToolError

    from pok.engine import design_service
    from pok.engine.design_checkpoints import save_checkpoint
    from pok.mcp import server

    material, evidence = measured
    record = create_record("wire-attachment", "MCP 연결")
    record["material"] = material
    parent = save_checkpoint(record_json(seal_record(record)), root=tmp_path)
    original = design_service.link_document_measurement
    monkeypatch.setattr(
        design_service,
        "link_document_measurement",
        lambda *args, **kwargs: original(*args, **kwargs, root=tmp_path),
    )
    api = FastMCP("xml-evidence-attachment")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    server.tool(
        server.attach_pob_document_measurement.__wrapped__,
        literal_arguments=frozenset({"record_ref", "document_measurement_ref"}),
    )

    async def exercise():
        async with Client(api) as client:
            arguments = {
                "record_ref": parent,
                "expected_revision": parent["revision"],
                "document_measurement_ref": evidence["source"]["document_measurement_ref"],
                "evidence_id": "wire-life",
                "label": "생명력",
                "description": "XML 측정",
                "path": "/stats/Life",
            }
            linked = (await client.call_tool("attach_pob_document_measurement", arguments)).data
            row = linked["current_assessment"]["evidence_assessments"][0]
            assert row["application"] == "current_xml_verified"
            arguments["expected_revision"] = linked["record_ref"]["revision"]
            with pytest.raises(ToolError, match="Expected revision"):
                await client.call_tool("attach_pob_document_measurement", arguments)

    asyncio.run(exercise())


@pytest.mark.parametrize("change", ["none", "unrelated", "node", "missing", "revision"])
def test_xml_provider_bindings_track_exact_nodes_without_game_claim(tmp_path, change):
    from pok.engine.pob_documents import inspect_document

    original = capture_material(xml_text=XML, root=tmp_path)["material"]
    node = inspect_document(original["xml"], tag="Gem", root=tmp_path)["nodes"][0]
    binding = {
        "material_revision": original["revision"],
        "representation": "pob_xml",
        "pointer": node["provider_binding_pointer"],
        "value_sha256": node["provider_binding_value_sha256"],
    }
    changed = {
        "none": XML,
        "unrelated": XML.replace("original", "new comment"),
        "node": XML.replace("<Gem/>", '<Gem level="2"/>'),
        "missing": XML.replace("<Gem/>", ""),
        "revision": XML,
    }[change]
    material = (
        original
        if change == "none"
        else capture_material(xml_text=changed, root=tmp_path)["material"]
    )
    record = create_record("provider-xml", "원문 공급자")
    record["material"] = material
    record["decisions"] = [
        {
            "id": "fixed-gem",
            "title": "보존할 젬",
            "role": "user_fixed",
            "domains": ["offence"],
            "condition": {
                "statement": "원문 젬 보존",
                "scope": {"description": "테스트", "decision_ids": []},
            },
            "adoption": "adopted",
            "belief": "user_reported",
            "confidence": "high",
            "providers": [{"id": "gem", "kind": "skill", "label": "젬", "binding": binding}],
            "depends_on": [],
            "alternatives": [],
            "evidence_ids": [],
            "costs": [],
        }
    ]
    result = inspect_evidence(record_json(seal_record(record)), root=tmp_path)
    row = result["provider_binding_assessments"][0]
    if change == "none":
        assert row["application"] == "current_xml_value_only"
    elif change in {"unrelated", "revision"}:
        assert row["application"] == "same_value_revalidated_at_new_material"
    else:
        assert row["application"] == "needs_review"
        assert row["integrity"] != "verified_value"
    assert result["checks"]["game_feasibility"] == "not_checked"
