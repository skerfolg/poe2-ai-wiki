"""Public operations inspect actual evidence without mutating historical records."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP

from pok.artifacts.design_record import DesignRecordError, parse_record
from pok.artifacts.store import read_build_blob, record_immutable_build
from pok.engine import design_service
from pok.mcp import server


def test_list_filters_legacy_pages_and_preserves_branches(tmp_path):
    import json

    legacy = tmp_path / "artifacts/builds/000-legacy"
    legacy.mkdir(parents=True)
    (legacy / "manifest.json").write_text(json.dumps({"build_id": "legacy"}), encoding="utf-8")
    first = design_service.create_design("listed", "목록 검사", root=tmp_path)
    reference = first["record_ref"]
    child = design_service.update_design(
        reference,
        reference["revision"],
        [{"op": "merge_extensions", "value": {"branch": "child"}}],
        root=tmp_path,
    )
    empty_page = design_service.list_designs(limit=1, root=tmp_path)
    assert empty_page["records"] == []
    assert empty_page["next_offset"] == 1
    page = design_service.list_designs(offset=1, design_id="listed", root=tmp_path)
    assert {row["record_ref"]["revision"] for row in page["records"]} == {
        reference["revision"],
        child["record_ref"]["revision"],
    }
    assert page["current_head"] == "caller_owned_not_inferred"
    assert all(row["current_evidence_verification"] == "not_performed" for row in page["records"])
    assert design_service.list_designs(design_id="other", root=tmp_path)["records"] == []


def test_list_reports_corrupt_checkpoint_without_hiding_healthy_records(tmp_path):
    first = design_service.create_design("healthy", "정상", root=tmp_path)
    broken = design_service.create_design("broken", "손상", root=tmp_path)
    path = tmp_path / "artifacts/builds" / broken["record_ref"]["artifact_id"] / "design.md"
    path.write_text("modified", encoding="utf-8")
    page = design_service.list_designs(root=tmp_path)
    assert [row["record_ref"] for row in page["records"]] == [first["record_ref"]]
    assert len(page["diagnostics"]) == 1
    assert page["diagnostics"][0]["code"] == "CHECKPOINT_DISCOVERY_INVALID"


@pytest.mark.parametrize("kwargs", [{"offset": -1}, {"limit": 0}, {"limit": 101}])
def test_list_rejects_unbounded_or_invalid_pages(tmp_path, kwargs):
    with pytest.raises(ValueError):
        design_service.list_designs(root=tmp_path, **kwargs)


def test_import_preserves_exact_bytes_and_never_promotes_legacy_confirmation(tmp_path):
    import hashlib

    raw = b"\xef\xbb\xbf# Legacy\r\n\r\n## Confirmed\r\n- Unknown fixed choice\r\n"
    saved = record_immutable_build("legacy-source", {"source.md": raw}, {}, root=tmp_path)
    result = design_service.import_design(
        "import-service",
        source_ref={
            "artifact_id": saved["artifact_id"],
            "name": "source.md",
            "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        },
        root=tmp_path,
    )
    record = parse_record(result["record_json"])
    source = record["legacy_sources"][0]
    assert (
        read_build_blob(source["artifact_id"], source["name"], source["sha256"], root=tmp_path)
        == raw
    )
    assert not any(item["role"] == "user_fixed" for item in record["decisions"])
    assessment = design_service.inspect_design(result["record_ref"], root=tmp_path)
    assert assessment["current_assessment"] == result["current_assessment"]
    assert "record_json" not in assessment


def test_import_requires_one_source_and_checks_blob_hash(tmp_path):
    for kwargs in ({}, {"document_text": "text", "source_ref": {}}):
        with pytest.raises(DesignRecordError):
            design_service.import_design("invalid", root=tmp_path, **kwargs)
    with pytest.raises(DesignRecordError):
        design_service.import_design("invalid", source_ref={"path": "outside"}, root=tmp_path)


def test_revision_conflict_and_noop_preserve_checkpoint(tmp_path):
    first = design_service.create_design("service-test", "설계 목표", root=tmp_path)
    reference = first["record_ref"]
    same = design_service.update_design(reference, reference["revision"], [], root=tmp_path)
    assert same["no_change"]
    assert same["record_ref"] == reference
    assert same["record_json"] == first["record_json"]
    assert "current_assessment" in same
    assert same["change_summary"]["changed_decision_count"] == 0
    assert same["change_summary"]["checks"]["game_feasibility"] == "not_checked"
    assert same["assessment_is_current_evidence_verification"] is False
    with pytest.raises(DesignRecordError):
        design_service.update_design(reference, "sha256:" + "0" * 64, [], root=tmp_path)
    loaded = design_service.read_design(reference, root=tmp_path)
    assert loaded["record_json"] == first["record_json"]


def test_registered_mcp_create_read_update_inspect_automatically(monkeypatch, tmp_path):
    api = FastMCP("design-service-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    original_create = design_service.create_design
    original_read = design_service.read_design
    original_update = design_service.update_design
    monkeypatch.setattr(
        design_service,
        "create_design",
        lambda design_id, goal: original_create(design_id, goal, root=tmp_path),
    )
    # The service internally calls its public read operation with root.
    monkeypatch.setattr(
        design_service,
        "read_design",
        lambda reference, **kwargs: original_read(reference, root=tmp_path),
    )
    monkeypatch.setattr(
        design_service,
        "update_design",
        lambda reference, expected_revision, changes, **kwargs: original_update(
            reference, expected_revision, changes, root=tmp_path, **kwargs
        ),
    )
    server.tool(server.create_design_record.__wrapped__)
    server.tool(server.read_design_record.__wrapped__, literal_arguments=frozenset({"record_ref"}))
    server.tool(
        server.update_design_record.__wrapped__,
        literal_arguments=frozenset({"record_ref", "changes", "user_decisions"}),
    )

    async def exercise():
        async with Client(api) as client:
            created = (
                await client.call_tool(
                    "create_design_record", {"design_id": "wire-design", "goal": "한글 목표"}
                )
            ).data
            reference = created["record_ref"]
            read = (await client.call_tool("read_design_record", {"record_ref": reference})).data
            assert read["record_json"] == created["record_json"]
            updated = (
                await client.call_tool(
                    "update_design_record",
                    {
                        "record_ref": reference,
                        "expected_revision": reference["revision"],
                        "changes": [{"op": "merge_extensions", "value": {"note": "추적"}}],
                    },
                )
            ).data
            record = parse_record(updated["record_json"])
            assert record["parents"] == [reference["revision"]]
            assert record["extensions"]["note"] == "추적"
            assert "current_assessment" in updated

    asyncio.run(exercise())
