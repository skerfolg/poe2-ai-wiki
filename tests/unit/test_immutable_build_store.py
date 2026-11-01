"""Immutable publication, legacy coexistence, and byte/hash boundaries."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from pok.artifacts import store
from pok.artifacts.design import list_builds

ID = "20261101-설계-checkpoint"
DATA = {
    "design-record.json": b'{"opaque":1.0}\n',
    "original.md": "\ufeff# 원문\r\n<!-- keep -->\r\n".encode(),
    "design.md": "# 새 표현\n".encode(),
}
META = {"kind": "design-checkpoint", "audit": {"caller_reported_user_decision": "example"}}


def save(
    root: Path, files: dict[str, bytes] | None = None, metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    return store.record_immutable_build(
        ID,
        files if files is not None else DATA,
        metadata if metadata is not None else META,
        root=root,
    )


def test_exact_bytes_and_audit_are_verified(tmp_path: Path) -> None:
    result = save(tmp_path)
    manifest, files = store.read_immutable_build(ID, result["manifest_sha256"], root=tmp_path)
    assert files == DATA
    assert manifest["metadata"] == META
    assert manifest["format"] == store.IMMUTABLE_BUILD_FORMAT
    assert manifest["files"]["original.md"]["bytes"] == len(DATA["original.md"])


def test_identical_retry_does_not_rewrite_files(tmp_path: Path) -> None:
    result = save(tmp_path)
    directory = tmp_path / "artifacts/builds" / ID
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()}
    assert save(tmp_path) == result
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in directory.iterdir()} == before


@pytest.mark.parametrize("change", ["files", "audit"])
def test_same_id_different_content_cannot_overwrite(tmp_path: Path, change: str) -> None:
    result = save(tmp_path)
    with pytest.raises(ValueError):
        if change == "files":
            save(tmp_path, {"design-record.json": b"different"})
        else:
            save(tmp_path, metadata={"kind": "design-checkpoint", "audit": "changed"})
    assert store.read_immutable_build(ID, result["manifest_sha256"], root=tmp_path)[1] == DATA


def test_truncated_component_cannot_be_read_as_complete(tmp_path: Path) -> None:
    result = save(tmp_path)
    (tmp_path / "artifacts/builds" / ID / "original.md").write_bytes(b"truncated")
    with pytest.raises(ValueError, match=r"modified|truncated"):
        store.read_immutable_build(ID, result["manifest_sha256"], root=tmp_path)


def test_changed_audit_metadata_fails_the_original_manifest_reference(tmp_path: Path) -> None:
    result = save(tmp_path)
    path = tmp_path / "artifacts/builds" / ID / "manifest.json"
    manifest = json.loads(path.read_bytes())
    manifest["metadata"]["audit"] = "different acknowledgment"
    path.write_bytes(store._manifest_bytes(manifest))
    with pytest.raises(ValueError, match="manifest hash"):
        store.read_immutable_build(ID, result["manifest_sha256"], root=tmp_path)


def test_existing_empty_or_partial_directory_is_not_repaired(tmp_path: Path) -> None:
    directory = tmp_path / "artifacts/builds" / ID
    directory.mkdir(parents=True)
    with pytest.raises(ValueError, match=r"missing|incomplete"):
        save(tmp_path)
    assert list(directory.iterdir()) == []
    (directory / "original.md").write_bytes(b"partial")
    with pytest.raises(ValueError):
        save(tmp_path)
    assert (directory / "original.md").read_bytes() == b"partial"


def test_legacy_writer_cannot_replace_published_checkpoint(tmp_path: Path) -> None:
    result = save(tmp_path)
    with pytest.raises(ValueError, match="Legacy writes"):
        store.record_build(ID, {"design.md": "overwritten"}, {}, root=tmp_path)
    assert store.read_immutable_build(ID, result["manifest_sha256"], root=tmp_path)[1] == DATA


def test_immutable_writer_cannot_replace_a_legacy_build(tmp_path: Path) -> None:
    store.record_build(ID, {"build.xml": "<original/>"}, {}, root=tmp_path)
    path = tmp_path / "artifacts/builds" / ID / "build.xml"
    with pytest.raises(ValueError):
        save(tmp_path)
    assert path.read_text() == "<original/>"


def test_both_writers_honor_same_pending_claim_and_preserve_it(tmp_path: Path) -> None:
    directory = store._artifact_directory("builds", ID, tmp_path)
    with store._publication_lock(directory):
        token = store._lock_path(directory).read_bytes()
        for writer in [
            lambda: save(tmp_path),
            lambda: store.record_build(ID, {"x": "y"}, {}, root=tmp_path),
        ]:
            with pytest.raises(ValueError, match="publication pending"):
                writer()
        assert store._lock_path(directory).read_bytes() == token
        assert not directory.exists()
    assert not store._lock_path(directory).exists()


def test_id_allocation_skips_unconfirmed_claim_without_deleting_it(tmp_path: Path) -> None:
    when = datetime(2026, 11, 1, tzinfo=UTC)
    identity = store.new_build_id("draft", root=tmp_path, now=when)
    directory = store._artifact_directory("builds", identity, tmp_path)
    directory.parent.mkdir(parents=True)
    claim = store._lock_path(directory)
    claim.write_bytes(b"unknown owner; not proof of a live job")
    assert store.new_build_id("draft", root=tmp_path, now=when) == identity + "-2"
    assert claim.read_bytes().startswith(b"unknown owner")


def test_complete_stage_is_hidden_until_atomic_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rename = store.os.rename
    directory = tmp_path / "artifacts/builds" / ID
    observed = []

    def publish(source: Any, target: Any) -> None:
        assert not directory.exists()
        stage = Path(source)
        assert all((stage / name).read_bytes() == raw for name, raw in DATA.items())
        assert (stage / "manifest.json").is_file()
        assert list_builds(tmp_path) == ()
        observed.append(True)
        rename(source, target)

    monkeypatch.setattr(store.os, "rename", publish)
    save(tmp_path)
    assert observed == [True]


def test_failed_publication_keeps_originals_and_no_published_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store.record_build("20261101-original", {"build.xml": "<original/>"}, {}, root=tmp_path)

    def fail(source: Any, target: Any) -> None:
        raise OSError("injected publication failure")

    monkeypatch.setattr(store.os, "rename", fail)
    with pytest.raises(OSError, match="injected"):
        save(tmp_path)
    builds = tmp_path / "artifacts/builds"
    assert not (builds / ID).exists()
    assert not list(builds.glob(".publish-*"))
    assert not store._lock_path(builds / ID).exists()
    assert (builds / "20261101-original/build.xml").read_text() == "<original/>"


def test_legacy_listing_does_not_expose_design_only_or_staging_directories(tmp_path: Path) -> None:
    save(tmp_path)
    store.record_build("20261101-real-build", {"build.xml": "<x/>"}, {}, root=tmp_path)
    stage = tmp_path / "artifacts/builds/.publish-unfinished"
    stage.mkdir()
    (stage / "design.md").write_text("# unfinished")
    assert [row.build_id for row in list_builds(tmp_path)] == ["20261101-real-build"]


@pytest.mark.parametrize("identity", ["../outside", "a/b", "..", "CON", "name.", "x\n"])
def test_invalid_artifact_identity_does_not_escape_store(tmp_path: Path, identity: str) -> None:
    with pytest.raises(ValueError):
        store.record_immutable_build(identity, DATA, META, root=tmp_path)


@pytest.mark.parametrize(
    "name",
    [
        "../outside",
        "/outside",
        "a/../outside",
        "D:/outside",
        "a\\b",
        "manifest.json",
        "Manifest.JSON",
        "a.",
        "nul.txt",
    ],
)
def test_invalid_component_paths_are_rejected_before_publication(tmp_path: Path, name: str) -> None:
    with pytest.raises(ValueError):
        save(tmp_path, {name: b"bad"})
    assert not (tmp_path / "artifacts/builds" / ID).exists()


@pytest.mark.parametrize("files", [{"a.txt": b"a", "A.txt": b"b"}, {"a": b"a", "a/b": b"b"}])
def test_case_alias_or_file_parent_conflicts_are_rejected(
    tmp_path: Path, files: dict[str, bytes]
) -> None:
    with pytest.raises(ValueError):
        save(tmp_path, files)


def test_nested_component_bytes_are_verified(tmp_path: Path) -> None:
    files = {"tiers/high/원문.md": b"\xef\xbb\xbfopaque\r\n"}
    result = save(tmp_path, files)
    assert store.read_immutable_build(ID, result["manifest_sha256"], root=tmp_path)[1] == files


def test_symlink_component_is_not_followed(tmp_path: Path) -> None:
    result = save(tmp_path)
    path = tmp_path / "artifacts/builds" / ID / "original.md"
    outside = tmp_path / "outside.md"
    outside.write_bytes(DATA["original.md"])
    path.unlink()
    try:
        path.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Host does not allow symlinks: {exc}")
    with pytest.raises(ValueError, match="escapes"):
        store.read_immutable_build(ID, result["manifest_sha256"], root=tmp_path)
    assert outside.read_bytes() == DATA["original.md"]
