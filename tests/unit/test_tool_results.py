"""Lossless bounded delivery, content binding, and explicit input references."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

import pytest

from pok.artifacts import tool_results as results


def save(tmp_path, result, inputs=None):
    return results.store_result("evaluate_delta", inputs or {}, result, root=tmp_path)


def test_store_binds_complete_result_inputs_and_source(tmp_path):
    inputs = {"variants": {"chosen": {"tree_nodes": [1, 2], "config": {"a": True}}}}
    original = {
        "variant_reviews": {"chosen": {"derived_from": {"tree": {"receipt": '한글\\"' * 10000}}}}
    }
    source = {"loaded_commit": "abc", "tool": "evaluate_delta"}
    manifest = results.store_result(
        "evaluate_delta", inputs, original, source=source, root=tmp_path
    )
    payload, loaded = results.load_result(manifest["id"], root=tmp_path)
    assert payload["inputs"] == inputs and payload["result"] == original
    assert loaded == manifest
    assert manifest["inputs_sha256"] == results.digest(inputs)
    assert manifest["result_sha256"] == results.digest(original)
    assert manifest["source_sha256"] == results.digest(source)
    assert len(results.encode(results.notice(manifest, original))) < 4096


@pytest.mark.parametrize("file_name", ["payload.json", "manifest.json"])
def test_tampering_fails_before_read_or_reference_use(tmp_path, file_name):
    stored = save(tmp_path, {"ok": True})
    path = tmp_path / "artifacts/sessions" / f"tool-result-{stored['id']}" / file_name
    payload = json.loads(path.read_bytes())
    payload["tool"] = "tampered"
    path.write_bytes(results.encode(payload))
    with pytest.raises(ValueError, match="hash mismatch"):
        results.read_page(stored["id"], root=tmp_path)
    with pytest.raises(ValueError, match="hash mismatch"):
        results.resolve_references({"$pok_result": stored["id"]}, root=tmp_path)


@pytest.mark.parametrize("bad_id", ["../elsewhere", "/tmp/path", "C:\\secret", "A" * 64, [], None])
def test_ids_are_not_paths(tmp_path, bad_id):
    with pytest.raises(ValueError, match="Invalid tool-result ID"):
        results.resolve_references({"$pok_result": bad_id}, root=tmp_path)


def test_missing_result_and_pointer_fail_explicitly(tmp_path):
    with pytest.raises(ValueError, match="missing or unreadable"):
        results.load_result("0" * 64, root=tmp_path)
    stored = save(tmp_path, {"a/b~c": [10]})
    assert results.read_page(stored["id"], "/result/a~1b~0c/0", root=tmp_path)["value"] == 10
    for pointer in (
        "result",
        "/result/no-key",
        "/result/a~2b",
        "/result/a~1b~0c/01",
        "/result/a~1b~0c/-1",
    ):
        with pytest.raises(ValueError):
            results.read_page(stored["id"], pointer, root=tmp_path)


def test_selected_spec_and_receipt_resolve_with_top_level_replacement(tmp_path):
    original_spec = {"tree_nodes": [1, 2], "derived_from": {"old": True}, "config": {"old": True}}
    receipt = {"tree": {"tool": "evaluate_delta", "context": "exact-selected-context"}}
    stored = save(
        tmp_path,
        {"variant_reviews": {"chosen": {"derived_from": receipt}}},
        {"variants": {"chosen": original_spec}},
    )
    reference = {
        "$pok_result": stored["id"],
        "path": "/inputs/variants/chosen",
        "overrides": {
            "derived_from": {
                "$pok_result": stored["id"],
                "path": "/result/variant_reviews/chosen/derived_from",
            },
            "config": {"new": True},
        },
    }
    actual = results.resolve_references(reference, root=tmp_path)
    assert actual == {"tree_nodes": [1, 2], "derived_from": receipt, "config": {"new": True}}
    actual["tree_nodes"].append(3)
    assert (
        results.load_result(stored["id"], root=tmp_path)[0]["inputs"]["variants"]["chosen"]
        == original_spec
    )
    assert original_spec["derived_from"] == {"old": True}


def test_reference_shape_override_type_and_recursion_limits(tmp_path):
    stored = save(tmp_path, {"base": {"nested": {}}, "scalar": 1})
    for reference in (
        {"$pok_result": stored["id"], "invented": True},
        {"$pok_result": stored["id"], "path": "/result/scalar", "overrides": {}},
        {"$pok_result": stored["id"], "overrides": []},
    ):
        with pytest.raises(ValueError):
            results.resolve_references(reference, root=tmp_path)
    nested = {"$pok_result": stored["id"], "path": "/result/base"}
    for _ in range(70):
        nested = {
            "$pok_result": stored["id"],
            "path": "/result/base",
            "overrides": {"nested": nested},
        }
    with pytest.raises(ValueError, match="limit exceeded"):
        results.resolve_references(nested, root=tmp_path)


def test_all_entries_can_be_recovered_without_truncation(tmp_path):
    original = [{"label": str(n), "value": n, "text": '한글\\"' * 40} for n in range(100)]
    stored = save(tmp_path, original)
    offset, reconstructed = 0, []
    while True:
        page = results.read_page(stored["id"], offset=offset, limit=100, root=tmp_path)
        assert len(results.encode(page)) <= results.PAGE_BYTES
        reconstructed.extend(row["value"] for row in page["entries"])
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    assert reconstructed == original


@pytest.mark.parametrize("mode", ["entries", "json"])
def test_huge_string_can_be_recovered_in_full_with_unicode_offsets(tmp_path, mode):
    original = '문자😀\\"\n' * 3000
    stored = save(tmp_path, original)
    offset, chunks = 0, []
    while True:
        page = results.read_page(stored["id"], offset=offset, mode=mode, root=tmp_path)
        assert len(results.encode(page)) <= results.PAGE_BYTES
        chunks.append(page["chunk"])
        if page["next_offset"] is None:
            break
        assert page["next_offset"] > offset
        offset = page["next_offset"]
    text = "".join(chunks)
    assert (json.loads(text) if mode == "json" else text) == original


def test_large_child_reference_and_giant_key_json_recovery(tmp_path):
    original = {"candidate": {"proof": "x" * 10000}, "k" * 10000: 2}
    stored = save(tmp_path, original)
    first = results.read_page(stored["id"], limit=1, root=tmp_path)
    child = first["entries"][0]
    assert "value_ref" in child
    assert results.resolve_references(child["value_ref"], root=tmp_path) == original["candidate"]
    oversized = results.read_page(stored["id"], offset=1, root=tmp_path)
    assert oversized["recovery"] == {"mode": "json", "offset": 0}
    chunks, offset = [], 0
    while True:
        page = results.read_page(stored["id"], mode="json", offset=offset, root=tmp_path)
        chunks.append(page["chunk"])
        if page["next_offset"] is None:
            break
        offset = page["next_offset"]
    assert json.loads("".join(chunks)) == original


@pytest.mark.parametrize("round_number", range(8))
def test_concurrent_writers_publish_identical_complete_results(tmp_path, round_number):
    value = {"data": "x" * 100000, "round": round_number}
    with ThreadPoolExecutor(max_workers=12) as pool:
        outputs = list(pool.map(lambda _: save(tmp_path, value), range(48)))
    assert len({result["id"] for result in outputs}) == 1
    assert results.load_result(outputs[0]["id"], root=tmp_path)[0]["result"] == value
    assert not list((tmp_path / "artifacts/sessions").glob(".publish-*"))


def test_symlink_escape_is_rejected(tmp_path):
    stored = save(tmp_path, {"ok": True})
    original = tmp_path / "artifacts/sessions" / f"tool-result-{stored['id']}" / "payload.json"
    outside = tmp_path / "outside.json"
    original.replace(outside)
    try:
        original.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Host does not allow symlinks: {exc}")
    with pytest.raises(ValueError, match="escapes"):
        results.load_result(stored["id"], root=tmp_path)


def test_first_publication_race_has_one_owner_and_complete_directory(tmp_path, monkeypatch):
    writers = 12
    gate = Barrier(writers)
    real_rename = results.os.rename
    published = []

    def simultaneous_rename(source, destination):
        assert {p.name for p in Path(source).iterdir()} == {"payload.json", "manifest.json"}
        gate.wait(timeout=15)
        real_rename(source, destination)
        published.append(destination)

    monkeypatch.setattr(results.os, "rename", simultaneous_rename)
    monkeypatch.setattr(results.os, "replace", lambda *a, **k: pytest.fail("no replacement"))
    value = {"data": "x" * 100000}
    with ThreadPoolExecutor(max_workers=writers) as pool:
        outputs = list(pool.map(lambda _: save(tmp_path, value), range(writers)))
    assert len(published) == 1
    assert all(output == outputs[0] for output in outputs)
    assert results.load_result(outputs[0]["id"], root=tmp_path)[0]["result"] == value


def test_readers_and_repeated_writers_never_replace_open_published_files(tmp_path, monkeypatch):
    value = {"data": "x" * 100000}
    stored = save(tmp_path, value)
    directory = tmp_path / "artifacts/sessions" / f"tool-result-{stored['id']}"
    gate = Barrier(12)
    monkeypatch.setattr(results.os, "rename", lambda *a, **k: pytest.fail("already published"))
    monkeypatch.setattr(results.os, "replace", lambda *a, **k: pytest.fail("no replacement"))

    def use(index):
        gate.wait(timeout=15)
        for _ in range(20):
            if index % 2:
                assert save(tmp_path, value) == stored
            else:
                payload, manifest = results.load_result(stored["id"], root=tmp_path)
                assert payload["result"] == value and manifest == stored

    with (
        (directory / "payload.json").open("rb") as payload_file,
        (directory / "manifest.json").open("rb") as manifest_file,
    ):
        before = payload_file.read(), manifest_file.read()
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(use, range(12)))
        payload_file.seek(0)
        manifest_file.seek(0)
        assert (payload_file.read(), manifest_file.read()) == before


def test_payload_and_manifest_become_visible_together(tmp_path, monkeypatch):
    payload_written, finish = Event(), Event()
    real_write = Path.write_bytes

    def pause_after_payload(path, data):
        count = real_write(path, data)
        if path.name == "payload.json":
            payload_written.set()
            assert finish.wait(timeout=15)
        return count

    monkeypatch.setattr(Path, "write_bytes", pause_after_payload)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(save, tmp_path, {"value": 1})
        try:
            assert payload_written.wait(timeout=15)
            sessions = tmp_path / "artifacts/sessions"
            assert not list(sessions.glob("tool-result-*"))
        finally:
            finish.set()
        stored = pending.result(timeout=15)
    assert results.load_result(stored["id"], root=tmp_path)[0]["result"] == {"value": 1}


def test_staging_failure_never_publishes_half_a_result(tmp_path, monkeypatch):
    real_write = Path.write_bytes

    def fail_manifest(path, data):
        if path.name == "manifest.json":
            raise OSError("controlled staging failure")
        return real_write(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_manifest)
    with pytest.raises(OSError, match="controlled staging failure"):
        save(tmp_path, {"value": 1})
    assert list((tmp_path / "artifacts/sessions").iterdir()) == []


@pytest.mark.parametrize("damage", ["payload.json", "manifest.json", "missing_manifest"])
def test_existing_modified_or_partial_result_is_never_repaired(tmp_path, damage):
    value = {"value": 1}
    stored = save(tmp_path, value)
    directory = tmp_path / "artifacts/sessions" / f"tool-result-{stored['id']}"
    if damage == "missing_manifest":
        (directory / "manifest.json").unlink()
    else:
        (directory / damage).write_bytes(b"modified")
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(ValueError, match=r"modified|incomplete"):
        save(tmp_path, value)
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


@pytest.mark.skipif(results.os.name != "nt", reason="Windows extended-path spelling")
@pytest.mark.parametrize("escape", [False, True])
def test_mixed_windows_extended_prefixes_preserve_path_boundary(tmp_path, monkeypatch, escape):
    stored = save(tmp_path, {"value": 1})
    real_resolve = Path.resolve

    def prefixed(path, *args, **kwargs):
        resolved = real_resolve(path, *args, **kwargs)
        if path.name.startswith("tool-result-") or path.name in {"payload.json", "manifest.json"}:
            if escape:
                resolved = tmp_path / "outside" / path.name
            text = str(resolved)
            return Path(text if text.startswith("\\\\?\\") else "\\\\?\\" + text)
        return resolved

    monkeypatch.setattr(Path, "resolve", prefixed)
    if escape:
        with pytest.raises(ValueError, match="escapes"):
            results.load_result(stored["id"], root=tmp_path)
    else:
        assert save(tmp_path, {"value": 1}) == stored
        assert results.load_result(stored["id"], root=tmp_path)[0]["result"] == {"value": 1}
