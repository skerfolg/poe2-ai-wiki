"""Exact XML preservation and atomic, revision-bound acquisition sidecars."""

import copy
import hashlib
import json
from xml.sax.saxutils import escape

import pytest

from pok.artifacts.design import list_builds
from pok.artifacts.design_record import canonical_bytes
from pok.artifacts.store import read_build_blob, record_immutable_build
from pok.engine import restore_fidelity as fidelity
from pok.engine.item_sockets import audit_item_sockets
from pok.pob.codec import encode
from pok.pob.restore import spec_from_pob


def xml(sockets=2):
    text = (
        "Rarity: RARE\nGloves\nAdorned Wraps\nItem Level: 80\nImplicits: 0\nSockets: "
        + " ".join(["S"] * sockets)
    )
    return (
        '<PathOfBuilding2><Build level="90" className="Monk" ascendClassName="Invoker"/>'
        '<Tree><Spec nodes="" ascendancyInternalId="Monk1"/></Tree><Skills/>'
        '<Items activeItemSet="1"><Item id="1">' + escape(text) + "</Item>"
        '<ItemSet id="1"><Slot name="Gloves" itemId="1"/></ItemSet>'
        '<ItemSet id="2" title="inactive-preserved"><UnknownItemTag/></ItemSet></Items>'
        '<Config/><UnknownSection value="retain-me"/></PathOfBuilding2>'
    )


@pytest.fixture(autouse=True)
def use_actual_rules_with_isolated_artifact_store(monkeypatch):
    # The optional root here isolates artifact publication. Rule evaluation
    # still uses the real fixed KB and checker, never a fake legal verdict.
    monkeypatch.setattr(
        fidelity, "audit_item_sockets", lambda spec, root=None: audit_item_sockets(spec)
    )


def test_missing_routes_are_unproven_without_inventing_exceptional():
    code = encode(xml())
    restored = spec_from_pob(code)
    result = fidelity.assess_restoration(code, restored)
    assert result["original_xml"] == xml()
    assert "inactive-preserved" in result["original_xml"]
    assert result["restore_fidelity"]["source_xml_preserved"] is True
    assert result["restore_fidelity"]["socket_metadata"] == "not_encoded_in_pob"
    assert result["socket_acquisition"]["items"][0]["status"] == "acquisition_unproven"
    assert any(
        row["code"] == "SOCKET_ACQUISITION_UNPROVEN"
        for row in result["restore_fidelity"]["diagnostics"]
    )
    assert "socket_sources" not in result["build_spec"]["items"][0]
    assert result["faithful_scope"] == "pob_calculation_projection_only"


@pytest.mark.parametrize("change", ["config", "comment", "item", "slot", "stale"])
def test_rebind_routes_requires_verified_original_and_unchanged_slot_item(tmp_path, change):
    from pok.engine.design_service import capture_material

    source = xml()
    source_code = encode(source)
    original = fidelity.create_socket_sidecar(
        source_code,
        fidelity.projection_revision(spec_from_pob(source_code).spec),
        {"Gloves": ["exceptional"]},
        root=tmp_path,
    )
    target = {
        "config": source.replace(
            "<Config/>", '<Config><Input name="enemyLevel" number="83"/></Config>'
        ),
        "comment": source.replace("<Config/>", "<Config/><!--changed-->"),
        "item": source.replace("Item Level: 80", "Item Level: 81"),
        "slot": source.replace('name="Gloves"', 'name="Boots"'),
        "stale": source,
    }[change]
    source_ref = capture_material(xml_text=source, root=tmp_path)["material"]["xml"]
    target_ref = capture_material(xml_text=target, root=tmp_path)["material"]["xml"]
    revision = fidelity.projection_revision(spec_from_pob(encode(target)).spec)
    if change == "stale":
        revision = "sha256:" + "0" * 64
    before = set((tmp_path / "artifacts/builds").iterdir())
    if change in {"item", "slot", "stale"}:
        with pytest.raises(ValueError):
            fidelity.rebind_socket_sidecar(
                source_ref, original["sidecar_ref"], target_ref, revision, root=tmp_path
            )
        assert set((tmp_path / "artifacts/builds").iterdir()) == before
        return
    rebound = fidelity.rebind_socket_sidecar(
        source_ref, original["sidecar_ref"], target_ref, revision, root=tmp_path
    )
    result = fidelity.assess_restoration(
        encode(target), spec_from_pob(encode(target)), rebound["sidecar_ref"], root=tmp_path
    )
    assert result["restore_fidelity"]["socket_metadata"] == "matched_socket_sidecar"
    assert result["build_spec"]["items"][0]["socket_sources"] == ["exceptional"]
    assert rebound["rebinding"]["source_sidecar_ref"] == original["sidecar_ref"]
    assert (
        fidelity.assess_restoration(
            source_code, spec_from_pob(source_code), original["sidecar_ref"], root=tmp_path
        )["restore_fidelity"]["socket_metadata"]
        == "matched_socket_sidecar"
    )


def test_ordinary_sockets_do_not_get_a_false_extra_route_warning():
    code = encode(xml(1))
    result = fidelity.assess_restoration(code, spec_from_pob(code))
    assert result["socket_acquisition"]["legal"] is True
    assert result["restore_fidelity"]["diagnostics"] == []
    assert result["restore_fidelity"]["socket_metadata"] == "not_encoded_in_pob"


def test_matching_sidecar_restores_declarations_and_keeps_original_projection(tmp_path):
    code = encode(xml())
    restored = spec_from_pob(code)
    before = copy.deepcopy(restored.spec)
    saved = fidelity.create_socket_sidecar(
        code, fidelity.projection_revision(before), {"Gloves": ["exceptional"]}, root=tmp_path
    )
    result = fidelity.assess_restoration(code, restored, saved["sidecar_ref"], root=tmp_path)
    assert restored.spec == before
    assert result["socket_acquisition"]["legal"] is True
    assert result["build_spec"]["items"][0]["socket_sources"] == ["exceptional"]
    assert result["restored_projection_revision"] != result["effective_spec_revision"]
    assert result["restore_fidelity"]["socket_metadata"] == "matched_socket_sidecar"
    assert result["socket_sidecar_ref"] == saved["sidecar_ref"]
    assert result["restore_fidelity"]["other_design_metadata"] == "not_reconstructed"
    assert list_builds(root=tmp_path) == ()
    assert (
        read_build_blob(
            saved["sidecar_ref"]["artifact_id"],
            "original.xml",
            saved["source_xml_sha256"],
            root=tmp_path,
        )
        == xml().encode()
    )


def test_other_xml_or_projection_cannot_reuse_sidecar(tmp_path):
    code = encode(xml())
    restored = spec_from_pob(code)
    saved = fidelity.create_socket_sidecar(
        code,
        fidelity.projection_revision(restored.spec),
        {"Gloves": ["exceptional"]},
        root=tmp_path,
    )
    changed_xml = encode(xml().replace("retain-me", "changed"))
    changed = copy.deepcopy(restored.spec)
    changed["level"] += 1
    for other_code, other in (
        (changed_xml, spec_from_pob(changed_xml)),
        (code, type(restored)(changed)),
    ):
        result = fidelity.assess_restoration(other_code, other, saved["sidecar_ref"], root=tmp_path)
        assert result["restore_fidelity"]["socket_metadata"] == "sidecar_not_applied"
        assert "socket_sources" not in result["build_spec"]["items"][0]


def test_stale_capture_and_unknown_slot_fail_before_publication(tmp_path):
    code = encode(xml())
    revision = fidelity.projection_revision(spec_from_pob(code).spec)
    for expected, routes in (("sha256:" + "0" * 64, {}), (revision, {"Boots": ["exceptional"]})):
        with pytest.raises(ValueError):
            fidelity.create_socket_sidecar(code, expected, routes, root=tmp_path)
    assert not (tmp_path / "artifacts/builds").exists()


def test_identical_values_in_another_set_still_need_the_correct_selection_binding(tmp_path):
    text = xml().replace("<UnknownItemTag/>", '<Slot name="Gloves" itemId="1"/>')
    code = encode(text)
    first = spec_from_pob(code)
    second = spec_from_pob(code, selection={"item_set": "2"})
    assert first.spec == second.spec
    assert first.selection != second.selection
    original = fidelity.create_socket_sidecar(
        code, fidelity.projection_revision(first.spec), {"Gloves": ["exceptional"]}, root=tmp_path
    )
    refused = fidelity.assess_restoration(code, second, original["sidecar_ref"], root=tmp_path)
    assert refused["restore_fidelity"]["socket_metadata"] == "sidecar_not_applied"
    matching = fidelity.create_socket_sidecar(
        code,
        fidelity.projection_revision(second.spec),
        {"Gloves": ["exceptional"]},
        selection={"item_set": "2"},
        root=tmp_path,
    )
    applied = fidelity.assess_restoration(code, second, matching["sidecar_ref"], root=tmp_path)
    assert applied["socket_acquisition"]["legal"] is True
    assert applied["selection_resolved"]["item_set"] == "2"


def test_explicit_current_main_group_keeps_default_sidecar_compatible(tmp_path):
    groups = (
        "<Skills>"
        + (
            '<Skill><Gem gemId="Metadata/Items/Gems/SkillGemSpark" '
            'nameSpec="Spark" level="20"/></Skill>'
        )
        * 2
        + "</Skills>"
    )
    text = (
        xml()
        .replace("<Skills/>", groups)
        .replace("<Build level=", '<Build mainSocketGroup="2.0" level=')
    )
    code = encode(text)
    default = spec_from_pob(code)
    explicit = spec_from_pob(code, selection={"main_group": 2})
    assert default.spec == explicit.spec
    captured = fidelity.create_socket_sidecar(
        code, fidelity.projection_revision(default.spec), {"Gloves": ["exceptional"]}, root=tmp_path
    )
    result = fidelity.assess_restoration(code, explicit, captured["sidecar_ref"], root=tmp_path)
    assert result["restore_fidelity"]["socket_metadata"] == "matched_socket_sidecar"


def test_sidecar_validation_is_atomic_and_hash_guarded(tmp_path):
    code = encode(xml())
    restored = spec_from_pob(code)
    saved = fidelity.create_socket_sidecar(
        code,
        fidelity.projection_revision(restored.spec),
        {"Gloves": ["exceptional"]},
        root=tmp_path,
    )
    reference = saved["sidecar_ref"]
    payload = json.loads(read_build_blob(**reference, root=tmp_path))
    payload["items"].append(copy.deepcopy(payload["items"][0]))
    raw = canonical_bytes(payload)
    record_immutable_build("duplicate-sidecar", {"sidecar.json": raw}, {}, root=tmp_path)
    bad = {
        "artifact_id": "duplicate-sidecar",
        "name": "sidecar.json",
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }
    payload["items"] = payload["items"][:1]
    payload["items"][0]["item_text_sha256"] = "sha256:" + "0" * 64
    wrong_item_raw = canonical_bytes(payload)
    record_immutable_build(
        "wrong-item-sidecar", {"sidecar.json": wrong_item_raw}, {}, root=tmp_path
    )
    wrong_item = {
        "artifact_id": "wrong-item-sidecar",
        "name": "sidecar.json",
        "sha256": "sha256:" + hashlib.sha256(wrong_item_raw).hexdigest(),
    }
    for ref in (bad, wrong_item, {**reference, "sha256": "sha256:" + "0" * 64}):
        result = fidelity.assess_restoration(code, restored, ref, root=tmp_path)
        assert result["restore_fidelity"]["socket_metadata"] == "sidecar_not_applied"
        assert "socket_sources" not in result["build_spec"]["items"][0]


@pytest.mark.parametrize("change", [None, "spec", "xml"])
def test_design_material_checks_sidecar_association_beyond_blob_hashes(tmp_path, change):
    from pok.artifacts.design_record import create_record, record_json, seal_record
    from pok.engine.design_evidence import inspect_evidence, value_sha256

    code = encode(xml())
    source = spec_from_pob(code).spec
    source["items"][0]["socket_sources"] = ["exceptional"]
    metadata_text, report = fidelity.socket_sidecar_for_export(code, source)
    assert report["status"] == "bound_declarations" and metadata_text is not None
    current_spec = copy.deepcopy(source)
    current_xml = xml()
    if change == "spec":
        current_spec["level"] += 1
    elif change == "xml":
        current_xml = current_xml.replace("retain-me", "changed")
    files = {
        "spec.json": canonical_bytes(current_spec),
        "build.xml": current_xml.encode("utf-8"),
        "socket-sidecar.json": metadata_text.encode("utf-8"),
    }
    saved = record_immutable_build("material-binding", files, {}, root=tmp_path)

    def blob(name):
        return {
            "artifact_id": saved["artifact_id"],
            "name": name,
            "sha256": "sha256:" + hashlib.sha256(files[name]).hexdigest(),
            "media_type": "application/xml" if name.endswith(".xml") else "application/json",
        }

    material = {
        "spec": blob("spec.json"),
        "xml": blob("build.xml"),
        "metadata": blob("socket-sidecar.json"),
        "selection": {},
    }
    material["revision"] = value_sha256(material)
    record = create_record("socket-material", "구성과 획득 선언 연결")
    record["material"] = material
    checked = inspect_evidence(record_json(seal_record(record)), root=tmp_path)
    assert checked["checks"]["material_integrity"] == "verified_blobs"
    assert checked["checks"]["socket_metadata_binding"] == (
        "verified_declared_binding" if change is None else "mismatch"
    )
    assert checked["material_assessment"]["spec_sha256"] == value_sha256(current_spec)
    assert checked["checks"]["xml_spec_consistency"] == "not_checked"
    if change is not None:
        assert any(
            row["code"] == "SOCKET_METADATA_BINDING_REQUIRES_REVIEW"
            for row in checked["diagnostics"]
        )


def test_rebind_rejects_wrong_original_before_publication(tmp_path):
    from pok.engine.design_service import capture_material

    code = encode(xml())
    saved = fidelity.create_socket_sidecar(
        code,
        fidelity.projection_revision(spec_from_pob(code).spec),
        {"Gloves": ["exceptional"]},
        root=tmp_path,
    )
    changed = xml().replace("retain-me", "different-original")
    reference = capture_material(xml_text=changed, root=tmp_path)["material"]["xml"]
    before = set((tmp_path / "artifacts/builds").iterdir())
    with pytest.raises(ValueError, match="Original socket sidecar"):
        fidelity.rebind_socket_sidecar(
            reference,
            saved["sidecar_ref"],
            reference,
            fidelity.projection_revision(spec_from_pob(encode(changed)).spec),
            root=tmp_path,
        )
    assert set((tmp_path / "artifacts/builds").iterdir()) == before


def test_rebind_registered_mcp_tool_preserves_reference_data(tmp_path, monkeypatch):
    import asyncio

    from fastmcp import Client, FastMCP

    from pok.engine.design_service import capture_material
    from pok.mcp import server

    source = xml()
    code = encode(source)
    original = fidelity.create_socket_sidecar(
        code,
        fidelity.projection_revision(spec_from_pob(code).spec),
        {"Gloves": ["exceptional"]},
        root=tmp_path,
    )
    reference = capture_material(xml_text=source, root=tmp_path)["material"]["xml"]
    target = source.replace("retain-me", "edited")
    target_ref = capture_material(xml_text=target, root=tmp_path)["material"]["xml"]
    original_rebind = fidelity.rebind_socket_sidecar
    monkeypatch.setattr(
        fidelity,
        "rebind_socket_sidecar",
        lambda *args, **kwargs: original_rebind(*args, **kwargs, root=tmp_path),
    )
    api = FastMCP("socket-rebind-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    server.tool(
        server.rebind_socket_sidecar.__wrapped__,
        literal_arguments=frozenset(
            {
                "source_xml_ref",
                "sidecar_ref",
                "target_xml_ref",
                "target_selection",
            }
        ),
    )

    async def exercise():
        async with Client(api) as client:
            result = (
                await client.call_tool(
                    "rebind_socket_sidecar",
                    {
                        "source_xml_ref": reference,
                        "sidecar_ref": original["sidecar_ref"],
                        "target_xml_ref": target_ref,
                        "expected_projection_revision": fidelity.projection_revision(
                            spec_from_pob(encode(target)).spec
                        ),
                    },
                )
            ).data
            assert result["transferred_slots"] == ["Gloves"]
            assert result["rebinding"]["source_xml_ref"] == reference
            assert result["sidecar_ref"] != original["sidecar_ref"]

    asyncio.run(exercise())
