"""Large-result notices expose navigation without changing or ranking evidence."""

import copy

import pytest

from pok.artifacts import tool_results as results


def notice_for(tmp_path, value):
    manifest = results.store_result("evaluate_delta", {}, value, root=tmp_path)
    return results.notice(manifest, value), manifest


def test_comparison_fields_are_visible_and_references_recover_exact_values(tmp_path):
    original = {
        "base": {"stats": {"Life": 100}},
        "variants": {"alternative": {"stats": {"Life": 200}}},
        "comparison": {"failures": []},
        "deltas": {"alternative": {"Life": 100}},
        "variant_reviews": {"alternative": {"proof": "근거" * 100000}},
    }
    unchanged = copy.deepcopy(original)
    notice, manifest = notice_for(tmp_path, original)
    summary = notice["summary"]
    assert summary["fields_complete"] is True
    assert summary["fields_total"] == len(original)
    assert [row["key"] for row in summary["fields"]] == list(original)
    assert notice["read"]["mode"] == "entries"
    for row in summary["fields"]:
        assert results.resolve_references(row["value_ref"], root=tmp_path) == original[row["key"]]
        assert "value" not in row
    assert original == unchanged
    assert manifest["result_sha256"] == results.digest(original)
    assert results.load_result(manifest["id"], root=tmp_path)[0]["result"] == original
    assert len(results.encode(notice)) < results.PAGE_BYTES
    assert "best" not in notice


def test_escaped_keys_and_arrays_have_correct_reference_paths(tmp_path):
    for original in ({'cold/~피해"': [1, 2]}, [{"x": 1}, {"x": 2}]):
        notice, _ = notice_for(tmp_path, original)
        assert notice["summary"]["fields_complete"]
        for row in notice["summary"]["fields"]:
            assert (
                results.resolve_references(row["value_ref"], root=tmp_path) == original[row["key"]]
            )


def test_json_object_key_normalization_preserves_exact_pointer_targets(tmp_path):
    original = {None: "null key", True: "boolean key", 2.5: "number key"}
    notice, manifest = notice_for(tmp_path, original)
    saved = results.load_result(manifest["id"], root=tmp_path)[0]["result"]
    assert notice["summary"]["fields_complete"]
    for row in notice["summary"]["fields"]:
        assert results.resolve_references(row["value_ref"], root=tmp_path) == saved[row["key"]]


@pytest.mark.parametrize("value", [None, False, 17, "text", {}, []])
def test_leaf_or_empty_result_does_not_invent_child_fields(tmp_path, value):
    notice, _ = notice_for(tmp_path, value)
    assert notice["summary"]["fields"] == []
    assert notice["summary"]["fields_total"] == 0
    assert notice["summary"]["fields_complete"]


def test_bounded_overview_reports_omission_without_changing_saved_result(tmp_path):
    original = {f"field-{n}": {"text": "한글" * 100} for n in range(100)}
    notice, manifest = notice_for(tmp_path, original)
    summary = notice["summary"]
    assert summary["fields_total"] == len(original)
    assert 0 < len(summary["fields"]) < len(original)
    assert summary["fields_complete"] is False
    assert len(results.encode(notice)) < results.PAGE_BYTES
    assert results.load_result(manifest["id"], root=tmp_path)[0]["result"] == original


def test_unrepresentable_key_is_explicitly_omitted_and_root_remains_recoverable(tmp_path):
    original = {"한글" * 10000: 3, "stats": {"Life": 100}}
    notice, _ = notice_for(tmp_path, original)
    assert notice["summary"]["fields_complete"] is False
    assert notice["summary"]["fields_total"] == 2
    assert len(results.encode(notice)) < results.PAGE_BYTES
    assert results.resolve_references(notice["result_ref"], root=tmp_path) == original
