"""Native observations remain bound to complete, exact document snapshots."""

import pytest

from pok.artifacts.design import list_builds
from pok.artifacts.store import record_immutable_build
from pok.engine.pob_documents import load_document_measurement, measure_document
from pok.pob.runner import PobResult

XML = '\ufeff<PathOfBuilding2>\r\n<!--keep--><Unknown value="한글"/>\r\n</PathOfBuilding2>'


def document(root, identity="source", xml=XML):
    stored = record_immutable_build(
        identity, {"original.xml": xml.encode()}, {"kind": "pob-document"}, root=root
    )
    return {
        "artifact_id": identity,
        "name": "original.xml",
        "sha256": stored["files"]["original.xml"]["sha256"],
    }


@pytest.fixture
def calculator(monkeypatch):
    from pok.pob import runner

    calls = []

    def run(xml, **kwargs):
        calls.append((xml, kwargs))
        return PobResult(
            {"Life": 100, "CombinedDPS": 200},
            {
                "nativeSelection": {
                    "format": "pok.native-selection.v1",
                    "status": "unavailable",
                }
            },
            (1, 2),
            (),
            False,
        )

    monkeypatch.setattr(runner, "run_xml", run)
    return calls


def test_measurement_uses_exact_xml_and_keeps_unfiltered_native_result(tmp_path, calculator):
    reference = document(tmp_path)
    result = measure_document(
        reference, stats=["Life", "Missing"], native_timeout_s=37, use_cache=False, root=tmp_path
    )
    assert calculator == [(XML, {"timeout": 37, "use_cache": False})]
    assert result["stats"] == {"Life": 100}
    assert result["missing_stats"] == ["Missing"]
    loaded = load_document_measurement(result["document_measurement_ref"], reference, root=tmp_path)
    assert loaded["measurement"]["stats"] == {"Life": 100, "CombinedDPS": 200}
    assert loaded["binding"] == "verified_exact_xml_subject"
    assert loaded["execution_identity"] == "not_verified"
    assert list_builds(root=tmp_path) == ()


def test_equal_bytes_in_a_new_snapshot_match_but_any_xml_edit_does_not(tmp_path, calculator):
    reference = document(tmp_path)
    result = measure_document(reference, root=tmp_path)
    copied = document(tmp_path, "same-bytes")
    assert (
        load_document_measurement(result["document_measurement_ref"], copied, root=tmp_path)[
            "binding"
        ]
        == "verified_exact_xml_subject"
    )
    other = document(tmp_path, "changed", XML.replace("keep", "changed"))
    with pytest.raises(ValueError, match="another XML"):
        load_document_measurement(result["document_measurement_ref"], other, root=tmp_path)


def test_complete_bundle_tamper_is_rejected(tmp_path, calculator):
    reference = document(tmp_path)
    result = measure_document(reference, root=tmp_path)
    typed = result["document_measurement_ref"]
    path = tmp_path / "artifacts/builds" / typed["artifact_id"] / "measurement.json"
    path.write_bytes(b"{}")
    with pytest.raises(ValueError):
        load_document_measurement(typed, reference, root=tmp_path)


def test_wrong_kind_and_incomplete_reference_are_not_measurements(tmp_path):
    reference = document(tmp_path)
    with pytest.raises(ValueError):
        load_document_measurement(reference, reference, root=tmp_path)


@pytest.mark.parametrize("timeout", [0, -1, 181, float("nan")])
def test_invalid_native_timeout_never_starts_calculation(tmp_path, calculator, timeout):
    reference = document(tmp_path)
    with pytest.raises(ValueError):
        measure_document(reference, native_timeout_s=timeout, root=tmp_path)
    assert calculator == []


def test_mcp_keeps_document_and_tool_receipts_distinct(monkeypatch, tmp_path, calculator):
    import asyncio

    from fastmcp import Client, FastMCP

    from pok.artifacts import tool_results
    from pok.mcp import server

    reference = document(tmp_path)
    api = FastMCP("document-measurement-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "observe_sources", lambda: {})
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    monkeypatch.setattr(
        server._pob_documents,
        "measure_document",
        lambda ref, **kwargs: measure_document(ref, root=tmp_path, **kwargs),
    )
    monkeypatch.setattr(
        server._pob_documents,
        "load_document_measurement",
        lambda *args: load_document_measurement(*args, root=tmp_path),
    )
    server.tool(server.compute_pob_document.__wrapped__)
    server.tool(server.read_pob_document_measurement.__wrapped__)

    async def exercise():
        async with Client(api) as client:
            measured = (
                await client.call_tool(
                    "compute_pob_document", {"xml_ref": reference, "stats": ["Life"]}
                )
            ).data
            assert measured["measurement_ref"]["$pok_result"]
            assert (
                measured["document_measurement_ref"]["format"] == "pok.document-measurement-ref.v1"
            )
            read = (
                await client.call_tool(
                    "read_pob_document_measurement",
                    {
                        "document_measurement_ref": measured["document_measurement_ref"],
                        "xml_ref": reference,
                    },
                )
            ).data
            assert read["binding"] == "verified_exact_xml_subject"
            assert read["measurement"]["stats"]["CombinedDPS"] == 200
            assert measured["stats"] == {"Life": 100}

    asyncio.run(exercise())
