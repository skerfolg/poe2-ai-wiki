"""Document edits publish atomic children and keep parent/evidence untouched."""

import asyncio

import pytest
from fastmcp import Client, FastMCP

from pok.artifacts.design import list_builds
from pok.artifacts.store import read_build_blob, record_immutable_build
from pok.engine.pob_documents import edit_document, inspect_document, read_document
from pok.mcp import server

XML = (
    '\ufeff<PathOfBuilding2 mode="1">\r\n<!--keep--><Unknown/>'
    '<Inactive id="7"/>\r\n</PathOfBuilding2>'
)


@pytest.fixture
def document(tmp_path):
    saved = record_immutable_build(
        "source-doc", {"original.xml": XML.encode()}, {"kind": "pob-document"}, root=tmp_path
    )
    return {
        "artifact_id": saved["artifact_id"],
        "name": "original.xml",
        "sha256": saved["files"]["original.xml"]["sha256"],
    }


def change(value="2"):
    return {
        "path": [],
        "tag": "PathOfBuilding2",
        "attribute": "mode",
        "expected_raw_value": "1",
        "value": value,
    }


def raw(reference, root):
    return read_build_blob(
        **{key: reference[key] for key in ("artifact_id", "name", "sha256")}, root=root
    )


def test_published_child_preserves_parent_and_unknown_content(document, tmp_path):
    inspected = inspect_document(document, root=tmp_path)
    child = edit_document(document, inspected["xml_revision"], [change()], root=tmp_path)
    assert raw(document, tmp_path) == XML.encode()
    assert raw(child["xml_ref"], tmp_path) == XML.replace('mode="1"', 'mode="2"').encode()
    assert child["spec_and_metadata_rebinding"] == "not_performed"
    assert list_builds(root=tmp_path) == ()


def test_failed_batch_publishes_nothing_and_noop_reuses_reference(document, tmp_path):
    revision = inspect_document(document, root=tmp_path)["xml_revision"]
    noop = edit_document(document, revision, [change("1")], root=tmp_path)
    assert noop["no_change"] and noop["xml_ref"] == document
    with pytest.raises(ValueError):
        edit_document(document, revision, [change(), {**change(), "tag": "Wrong"}], root=tmp_path)
    assert len(list((tmp_path / "artifacts/builds").iterdir())) == 1
    assert raw(document, tmp_path) == XML.encode()


def test_inspection_filters_and_pages_without_rewriting(document, tmp_path):
    first = inspect_document(document, limit=1, root=tmp_path)
    assert first["nodes"][0]["path"] == []
    assert first["next_offset"] == 1
    second = inspect_document(document, offset=1, limit=1, root=tmp_path)
    assert second["nodes"][0]["tag"] == "Unknown"
    assert inspect_document(document, tag="Inactive", root=tmp_path)["nodes"][0][
        "raw_attributes"
    ] == {"id": "7"}


def test_text_and_attribute_batch_is_atomic_and_preserves_original(document, tmp_path):
    revision = inspect_document(document, root=tmp_path)["xml_revision"]
    text_change = {
        "op": "set_text",
        "path": [1],
        "tag": "Inactive",
        "expected_raw_value": "",
        "value": "new & text",
    }
    child = edit_document(document, revision, [change(), text_change], root=tmp_path)
    assert raw(document, tmp_path) == XML.encode()
    assert (
        raw(child["xml_ref"], tmp_path)
        == XML.replace('mode="1"', 'mode="2"')
        .replace('<Inactive id="7"/>', '<Inactive id="7">new &amp; text</Inactive>')
        .encode()
    )
    before = set((tmp_path / "artifacts/builds").iterdir())
    with pytest.raises(ValueError, match="value conflict"):
        edit_document(
            document,
            revision,
            [text_change, {**change(), "expected_raw_value": "wrong"}],
            root=tmp_path,
        )
    assert set((tmp_path / "artifacts/builds").iterdir()) == before


def test_mcp_inspection_to_explicit_edit_roundtrip(monkeypatch, document, tmp_path):
    api = FastMCP("document-service-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(
        server._pob_documents,
        "inspect_document",
        lambda reference, **kwargs: inspect_document(reference, root=tmp_path, **kwargs),
    )
    monkeypatch.setattr(
        server._pob_documents,
        "edit_document",
        lambda *args, **kwargs: edit_document(*args, root=tmp_path, **kwargs),
    )
    monkeypatch.setattr(
        server._pob_documents,
        "read_document",
        lambda reference: read_document(reference, root=tmp_path),
    )
    server.tool(server.inspect_pob_document.__wrapped__)
    server.tool(server.read_pob_document.__wrapped__)
    server.tool(server.edit_pob_document.__wrapped__, literal_arguments=frozenset({"changes"}))

    async def exercise():
        async with Client(api) as client:
            inspected = (
                await client.call_tool(
                    "inspect_pob_document", {"xml_ref": document, "tag": "PathOfBuilding2"}
                )
            ).data
            result = (
                await client.call_tool(
                    "edit_pob_document",
                    {
                        "xml_ref": document,
                        "expected_revision": inspected["xml_revision"],
                        "changes": [change()],
                    },
                )
            ).data
            assert result["no_change"] is False
            assert raw(result["xml_ref"], tmp_path) == XML.replace('mode="1"', 'mode="2"').encode()
            loaded = (
                await client.call_tool("read_pob_document", {"xml_ref": result["xml_ref"]})
            ).data
            assert loaded["xml_text"] == XML.replace('mode="1"', 'mode="2"')
            inserted = (
                await client.call_tool(
                    "edit_pob_document",
                    {
                        "xml_ref": result["xml_ref"],
                        "expected_revision": result["xml_revision"],
                        "changes": [
                            {
                                "op": "upsert_child_attribute",
                                "path": [],
                                "tag": "PathOfBuilding2",
                                "child_tag": "StatSetIndex",
                                "identity_attribute": "grantedEffect",
                                "identity_value": "SparkPlayer",
                                "attribute": "index",
                                "expected_raw_value": None,
                                "value": "2",
                            }
                        ],
                    },
                )
            ).data
            assert (
                '<StatSetIndex grantedEffect="SparkPlayer" index="2"/>'
                in raw(inserted["xml_ref"], tmp_path).decode()
            )

    asyncio.run(exercise())


def test_child_upsert_is_atomic_and_can_be_updated_in_a_following_edit(tmp_path):
    xml = '<PathOfBuilding2><Gem name="Spark"/><Unknown kept="yes"/></PathOfBuilding2>'
    stored = record_immutable_build(
        "gem-doc", {"source.xml": xml.encode()}, {"kind": "pob-document"}, root=tmp_path
    )
    reference = {
        "artifact_id": stored["artifact_id"],
        "name": "source.xml",
        "sha256": stored["files"]["source.xml"]["sha256"],
    }
    revision = inspect_document(reference, root=tmp_path)["xml_revision"]
    insert = {
        "op": "upsert_child_attribute",
        "path": [0],
        "tag": "Gem",
        "child_tag": "StatSetIndex",
        "identity_attribute": "grantedEffect",
        "identity_value": "SparkPlayer",
        "attribute": "index",
        "expected_raw_value": None,
        "value": "2",
    }
    with pytest.raises(ValueError):
        edit_document(reference, revision, [insert, insert], root=tmp_path)
    assert len(list((tmp_path / "artifacts/builds").iterdir())) == 1
    child = edit_document(reference, revision, [insert], root=tmp_path)
    assert (
        '<StatSetIndex grantedEffect="SparkPlayer" index="2"/>'
        in raw(child["xml_ref"], tmp_path).decode()
    )
    updated = edit_document(
        child["xml_ref"],
        child["xml_revision"],
        [{**insert, "expected_raw_value": "2", "value": "1"}],
        root=tmp_path,
    )
    assert '<Unknown kept="yes"/>' in raw(updated["xml_ref"], tmp_path).decode()
    assert raw(reference, tmp_path) == xml.encode()
