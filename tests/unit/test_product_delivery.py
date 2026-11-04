"""Submitted files remain evidence even when transport fails."""

import importlib
from pathlib import Path

import pytest

from pok.pob import codec


@pytest.fixture
def audit(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills/build-generation")
    )
    return importlib.import_module("product_delivery").audit_submission


def test_file_only_delivery_matches_code_without_mutation(tmp_path, audit):
    xml = "<PathOfBuilding>\r\n<Build/>\r\n</PathOfBuilding>"
    raw = xml.encode()
    (tmp_path / "final.xml").write_bytes(raw)
    (tmp_path / "final.pob").write_text(codec.encode(xml), encoding="utf-8")
    answer = {
        "status": "complete",
        "pob_code": None,
        "artifacts": [
            {"format": "pob_xml", "reference": "final.xml"},
            {"format": "pob_code", "reference": str(tmp_path / "final.pob")},
        ],
    }
    result = audit(answer, tmp_path)
    assert result["transport_verified"]
    assert not result["build_quality_verified"]
    assert len({x["sha256"] for x in result["xml_sources"]}) == 1
    assert (tmp_path / "final.xml").read_bytes() == raw


def test_answer_code_disagreement_preserves_both_sources(tmp_path, audit):
    (tmp_path / "final.xml").write_text("<PathOfBuilding/>", encoding="utf-8")
    answer = {
        "status": "complete",
        "pob_code": codec.encode("<PathOfBuilding><Build/></PathOfBuilding>"),
        "artifacts": [{"format": "pob_xml", "reference": "final.xml"}],
    }
    result = audit(answer, tmp_path)
    assert not result["transport_verified"]
    assert len(result["xml_sources"]) == 2
    assert any("disagree" in d["error"] for d in result["diagnostics"])


@pytest.mark.parametrize("reference", ["../secret.xml", "missing.xml"])
def test_escaping_or_missing_reference_is_not_replaced(tmp_path, audit, reference):
    (tmp_path / "unsubmitted.xml").write_text("<PathOfBuilding/>", encoding="utf-8")
    result = audit(
        {"status": "complete", "artifacts": [{"format": "pob_xml", "reference": reference}]},
        tmp_path,
    )
    assert not result["transport_verified"]
    assert not result["files"]
    assert not result["xml_sources"]


@pytest.mark.parametrize("content", ["<Other/>", "<PathOfBuilding>", "not XML"])
def test_invalid_submitted_xml_is_recorded(tmp_path, audit, content):
    path = tmp_path / "final.xml"
    path.write_text(content, encoding="utf-8")
    result = audit(
        {"status": "complete", "artifacts": [{"format": "pob_xml", "reference": "final.xml"}]},
        tmp_path,
    )
    assert not result["transport_verified"]
    assert len(result["files"]) == 1
    assert path.read_text(encoding="utf-8") == content


def test_incomplete_without_files_stays_incomplete(tmp_path, audit):
    result = audit({"status": "incomplete", "artifacts": [], "pob_code": None}, tmp_path)
    assert result["declared_status"] == "incomplete"
    assert not result["transport_verified"]
