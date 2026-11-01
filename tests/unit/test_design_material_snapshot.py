"""Snapshot inputs into linked immutable blobs without manual hash transcription."""

import copy
import json

import pytest

from pok.artifacts.design import list_builds
from pok.artifacts.design_record import DesignRecordError, parse_record
from pok.artifacts.store import read_build_blob, record_immutable_build
from pok.engine.design_evidence import value_sha256
from pok.engine.design_service import capture_material, create_design, update_design
from pok.pob.codec import encode


def blob_bytes(reference, root):
    return read_build_blob(
        **{key: reference[key] for key in ("artifact_id", "name", "sha256")}, root=root
    )


def test_snapshot_preserves_spec_values_and_exact_original_xml(tmp_path):
    spec = {"unknown": {"integer": 9007199254740993, "float": 1.0, "text": "한글"}}
    original = copy.deepcopy(spec)
    xml = (
        '\ufeff<?xml version="1.0"?>\r\n'
        '<PathOfBuilding2><Unknown value="keep"/></PathOfBuilding2>\r\n'
    )
    result = capture_material(
        build_spec=spec, xml_text=xml, selection={"item_set": "2"}, root=tmp_path
    )
    material = result["material"]
    assert json.loads(blob_bytes(material["spec"], tmp_path)) == spec
    assert blob_bytes(material["xml"], tmp_path) == xml.encode("utf-8")
    assert material["revision"] == value_sha256(
        {key: value for key, value in material.items() if key != "revision"}
    )
    assert material["spec"]["media_type"] == "application/json"
    assert material["xml"]["media_type"] == "application/xml"
    assert result["selection_verification"] == "not_checked"
    assert result["material_assessment"]["status"] == "verified_blobs"
    assert spec == original
    assert list_builds(root=tmp_path) == ()


def test_returned_material_attaches_to_design_without_manual_fields(tmp_path):
    first = create_design("captured", "스냅샷 연결", root=tmp_path)
    snapshot = capture_material(build_spec={"level": 90}, root=tmp_path)
    changed = update_design(
        first["record_ref"],
        first["record_ref"]["revision"],
        [{"op": "set_material", "value": snapshot["material"]}],
        root=tmp_path,
    )
    assert parse_record(changed["record_json"])["material"] == snapshot["material"]
    assert changed["current_assessment"]["material_assessment"]["status"] == "verified_blobs"
    assert parse_record(first["record_json"])["material"] is None


@pytest.mark.parametrize("with_media_type", [False, True])
def test_metadata_is_copied_exactly_from_verified_reference(tmp_path, with_media_type):
    raw = b'{"opaque": [1, 2], "future-field": true}\n'
    stored = record_immutable_build("metadata-source", {"original.json": raw}, {}, root=tmp_path)
    reference = {
        "artifact_id": stored["artifact_id"],
        "name": "original.json",
        "sha256": stored["files"]["original.json"]["sha256"],
    }
    if with_media_type:
        reference["media_type"] = "application/json"
    snapshot = capture_material(build_spec={"level": 90}, metadata_ref=reference, root=tmp_path)
    assert blob_bytes(snapshot["material"]["metadata"], tmp_path) == raw
    assert snapshot["material"]["metadata"]["artifact_id"] != reference["artifact_id"]


def test_build_code_preserves_decoded_original_without_a_fake_spec(tmp_path):
    xml = "<PathOfBuilding2>\r\n<Unknown/><InactiveSet/>\r\n</PathOfBuilding2>"
    snapshot = capture_material(build_code=encode(xml), root=tmp_path)
    assert "spec" not in snapshot["material"]
    assert blob_bytes(snapshot["material"]["xml"], tmp_path) == xml.encode()


@pytest.mark.parametrize(
    "arguments",
    [
        {},
        {"build_code": "code", "xml_text": "xml"},
        {"build_spec": {}, "selection": {"unknown-selection": "bad"}},
        {"build_spec": {"bad": float("nan")}},
        {"build_spec": {}, "metadata_ref": {"path": "outside"}},
    ],
)
def test_invalid_snapshot_inputs_do_not_publish(tmp_path, arguments):
    with pytest.raises((ValueError, DesignRecordError)):
        capture_material(root=tmp_path, **arguments)
    assert not list((tmp_path / "artifacts/builds").glob("*/manifest.json"))


def test_mcp_snapshot_resolves_actual_spec_reference_and_attaches_without_transcription(
    monkeypatch, tmp_path
):
    import asyncio

    from fastmcp import Client, FastMCP

    from pok.artifacts import tool_results
    from pok.engine import design_service
    from pok.mcp import server

    api = FastMCP("material-capture-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    monkeypatch.setattr(
        design_service,
        "capture_material",
        lambda **kwargs: capture_material(root=tmp_path, **kwargs),
    )
    monkeypatch.setattr(
        design_service,
        "update_design",
        lambda *args, **kwargs: update_design(*args, root=tmp_path, **kwargs),
    )
    server.tool(
        server.capture_design_material.__wrapped__,
        literal_arguments=frozenset({"metadata_ref", "selection"}),
    )
    server.tool(
        server.update_design_record.__wrapped__,
        literal_arguments=frozenset({"record_ref", "changes", "user_decisions"}),
    )
    spec = {"unknown": {"large_integer": 9007199254740993}}
    stored = tool_results.store_result("fixture", {}, {"spec": spec})
    original = create_design("mcp-material", "명시 스냅샷", root=tmp_path)

    async def exercise():
        async with Client(api) as client:
            snapshot = (
                await client.call_tool(
                    "capture_design_material",
                    {
                        "build_spec": {"$pok_result": stored["id"], "path": "/result/spec"},
                    },
                )
            ).data
            assert json.loads(blob_bytes(snapshot["material"]["spec"], tmp_path)) == spec
            changed = (
                await client.call_tool(
                    "update_design_record",
                    {
                        "record_ref": original["record_ref"],
                        "expected_revision": original["record_ref"]["revision"],
                        "changes": [{"op": "set_material", "value": snapshot["material"]}],
                    },
                )
            ).data
            assert parse_record(changed["record_json"])["material"] == snapshot["material"]
            assert changed["current_assessment"]["checks"]["material_integrity"] == "verified_blobs"

    asyncio.run(exercise())
