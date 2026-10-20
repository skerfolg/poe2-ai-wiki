"""The optional combined lookup preserves the evidence needed for later choices."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "skills/build-generation/native_server.py"
SPEC = importlib.util.spec_from_file_location("native_generation_server_test", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_partial_reads_preserve_search_hits_unread_ids_and_failures():
    calls = []
    hits = [{"id": "one"}, {"id": "two"}, {"id": "three"}]

    def search(query):
        calls.append(("search", query))
        return hits

    def read(**kwargs):
        calls.append(("read", kwargs))
        if kwargs["id"] == "two":
            raise ValueError("detail unavailable")
        return {"id": kwargs["id"], "data": {"rule": "original text"}}

    result = MODULE.retrieve(
        {"query": "rule"}, 2, ["id", "data"], True, search_fn=search, read_fn=read
    )
    assert result["search_result"] == hits
    assert result["unread_ids"] == ["three"]
    assert result["details"][0]["record"]["data"]["rule"] == "original text"
    assert result["details"][1] == {
        "id": "two",
        "ok": False,
        "error": "ValueError: detail unavailable",
    }
    assert result["physical_queries"] == len(calls) == 3
    assert calls[1][1]["fields"] == ["id", "data"]
    assert calls[1][1]["include_narrative"] is True


def test_empty_diagnostic_is_not_discarded_or_counted_as_detail():
    diagnostic = [{"empty": True, "other_types": [{"type": "Support", "count": 1}]}]

    def read(**kwargs):
        pytest.fail("No ID was returned; a detail query would be invented")

    result = MODULE.retrieve({}, 3, None, True, search_fn=lambda: diagnostic, read_fn=read)
    assert result["search_result"] == diagnostic
    assert result["details"] == result["unread_ids"] == []
    assert result["physical_queries"] == 1


@pytest.mark.parametrize("limit", [0, 21, True, 1.5])
def test_bad_limit_fails_before_any_query(limit):
    def search():
        pytest.fail("Invalid operation must not consume queries")

    with pytest.raises(ValueError):
        MODULE.retrieve({}, limit, None, True, search_fn=search, read_fn=lambda: {})


def test_unknown_search_argument_fails_before_query():
    def search(query=None):
        pytest.fail("Unknown arguments must be caught before executing search")

    with pytest.raises(TypeError):
        MODULE.retrieve({"invented": "field"}, 1, None, True, search_fn=search, read_fn=lambda: {})


def test_registration_keeps_original_tools_and_only_adds_one():
    class Server:
        def __init__(self):
            self.names = ["search_kb", "get_entry", "assemble_pob", "optimize_tree"]

        def tool(self, fn):
            self.names.append(fn.__name__)
            return fn

    server = Server()
    MODULE.register(server)
    assert server.names == [
        "search_kb",
        "get_entry",
        "assemble_pob",
        "optimize_tree",
        "search_and_read",
    ]
