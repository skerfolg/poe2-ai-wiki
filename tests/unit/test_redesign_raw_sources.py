"""Raw reference access preserves source text and cannot leave its pools."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "skills/build-generation/redesign_raw.py"
SPEC = importlib.util.spec_from_file_location("redesign_raw_sources", PATH)
assert SPEC is not None and SPEC.loader is not None
RAW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RAW)


def test_literal_search_is_not_a_build_ranker_and_read_preserves_text(tmp_path):
    text = "첫 줄\nStorm Wave raw text\nlast line\n"
    source = tmp_path / "sample.txt"
    source.write_text(text, encoding="utf-8")
    pools = {"raw": tmp_path}
    found = RAW.raw_source(pools, "raw", "search", query="storm wave")
    assert found["entries"][0]["path"] == "sample.txt"
    assert found["entries"][0]["line"] == 2
    first = RAW.raw_source(pools, "raw", "read", path="sample.txt", limit=5)
    second = RAW.raw_source(pools, "raw", "read", path="sample.txt", offset=5, limit=200)
    assert first["text"] + second["text"] == text
    assert RAW.raw_source(pools, "raw", "list")["entries"] == ["sample.txt"]


@pytest.mark.parametrize("action", ["read", "list", "search"])
def test_raw_source_rejects_traversal_and_hidden_metadata(tmp_path, action):
    with pytest.raises(ValueError):
        RAW.raw_source({"raw": tmp_path}, "raw", action, "../outside", query="anything")
    with pytest.raises(ValueError):
        RAW.raw_source({"raw": tmp_path}, "raw", action, ".git/config", query="anything")
