"""The optional combined lookup preserves evidence and normal input validation."""

from __future__ import annotations

import asyncio
import functools
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated

import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, TypeAdapter, ValidationError

PATH = Path(__file__).resolve().parents[2] / "skills/build-generation/native_server.py"
SPEC = importlib.util.spec_from_file_location("native_generation_server_test", PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

type TagList = list[str]


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

    with pytest.raises(ValidationError, match="unexpected_keyword_argument"):
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


def test_invalid_nested_tags_fail_before_search_or_detail_execution():
    calls = []

    def search(tags: TagList | None = None) -> list[dict]:
        calls.append(("search", tags))
        return []

    def read(**kwargs):
        calls.append(("read", kwargs))
        return {}

    with pytest.raises(ValidationError, match="list_type"):
        MODULE.retrieve({"tags": "spell"}, 1, None, True, search_fn=search, read_fn=read)
    assert calls == []


def test_typed_alias_defaults_and_wrapper_execute_once_and_preserve_metadata():
    calls = []
    hits = [
        {
            "id": "one",
            "tags": ["spell"],
            "pob_gap": "modeling gap",
            "excluded_by_unlock": "different ascendancy",
        }
    ]
    record = {
        "id": "one",
        "data": {"rule": "original"},
        "narrative": "full original narrative",
        "granted_instance": {"free": True},
        "sources": [{"ref": "original-source"}],
    }

    def search(
        query: Annotated[str | None, Field(alias="term")] = None,
        tags: TagList | None = None,
        limit: int = 20,
    ) -> list[dict]:
        calls.append(("body", query, tags, limit))
        return hits

    @functools.wraps(search)
    def wrapped(*args, **kwargs):
        calls.append(("wrapper",))
        return search(*args, **kwargs)

    def read(**kwargs):
        calls.append(("read", kwargs))
        return record

    result = MODULE.retrieve(
        {"term": "rule", "tags": ["spell"]},
        1,
        ["id", "data"],
        True,
        search_fn=wrapped,
        read_fn=read,
    )
    assert calls == [
        ("wrapper",),
        ("body", "rule", ["spell"], 20),
        ("read", {"id": "one", "fields": ["id", "data"], "include_narrative": True}),
    ]
    assert result["search_result"] == hits
    assert result["details"] == [{"id": "one", "ok": True, "record": record}]
    assert result["physical_queries"] == 2
    assert result["complete_search_universe"] is False


def test_search_body_exception_propagates_without_retry_or_empty_relabel():
    calls = []

    def search(query: str | None = None) -> list[dict]:
        calls.append(query)
        raise RuntimeError("search backend unavailable")

    with pytest.raises(RuntimeError, match="search backend unavailable"):
        MODULE.retrieve({}, 1, None, True, search_fn=search, read_fn=lambda **kw: {})
    assert calls == [None]


def test_search_body_validation_error_is_not_relabeled_as_bad_input():
    calls = []
    error = None

    def search(query: str | None = None) -> list[dict]:
        nonlocal error
        calls.append(query)
        try:
            TypeAdapter(int).validate_python("backend-corrupt-value")
        except ValidationError as exc:
            error = exc
            raise
        pytest.fail("Fixture must raise a validation error inside the body")

    with pytest.raises(ValidationError) as failure:
        MODULE.retrieve({}, 1, None, True, search_fn=search, read_fn=lambda **kw: {})
    assert failure.value is error
    assert "backend-corrupt-value" in str(failure.value)
    assert calls == [None]


@pytest.mark.parametrize("strict_setting", [None, False, True])
def test_registration_passes_optional_strict_policy(monkeypatch, strict_setting):
    captured = []
    registered = {}

    def tool(fn):
        registered[fn.__name__] = fn
        return fn

    policy = SimpleNamespace()
    if strict_setting is not None:
        policy.strict_input_validation = strict_setting
    server = SimpleNamespace(
        tool=tool,
        mcp=policy,
        search_kb=lambda: [],
        get_entry=lambda **kw: {},
    )

    def retrieve(*args, **kwargs):
        captured.append(kwargs["strict_input_validation"])
        return {"sentinel": True}

    monkeypatch.setattr(MODULE, "retrieve", retrieve)
    MODULE.register(server)
    assert registered["search_and_read"]({}) == {"sentinel": True}
    assert captured == [strict_setting]


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize(
    ("arguments", "accepted"),
    [
        ({}, True),
        ({"term": "cold", "tags": ["spell"], "limit": 3}, True),
        ({"tags": "spell"}, False),
        ({"tags": [3]}, False),
        ({"limit": "3"}, "coerce_only"),
        ({"invented": 1}, False),
        ({"tags": None}, True),
        ({"query": "cold"}, False),
        ({"term": 3}, False),
    ],
    ids=[
        "defaults",
        "valid-alias",
        "invalid-tags",
        "invalid-tag-element",
        "integer-coercion",
        "unknown-key",
        "nullable",
        "non-alias-name",
        "invalid-string",
    ],
)
def test_combined_mcp_input_contract_matches_original(strict, arguments, accepted):
    body_calls = []

    def search(
        query: Annotated[str | None, Field(alias="term")] = None,
        tags: TagList | None = None,
        limit: int = 20,
    ) -> list[dict]:
        body_calls.append({"query": query, "tags": tags, "limit": limit})
        return [{"arguments": body_calls[-1]}]

    @functools.wraps(search)
    def wrapped(*args, **kwargs):
        return search(*args, **kwargs)

    def read(id: str, fields: list[str] | None = None, include_narrative: bool = False) -> dict:
        pytest.fail("This input-contract fixture deliberately returns no record ID")

    async def run():
        api = FastMCP("isolated-nested-search-validation", strict_input_validation=strict)
        api.tool(wrapped, name="search_kb")
        api.tool(read, name="get_entry")
        async with Client(api) as client:
            original_tools = {tool.name: tool.model_dump() for tool in await client.list_tools()}
            MODULE.register(
                SimpleNamespace(tool=api.tool, mcp=api, search_kb=wrapped, get_entry=read)
            )
            combined_tools = {tool.name: tool.model_dump() for tool in await client.list_tools()}
            assert set(combined_tools) == {
                "search_kb",
                "get_entry",
                "search_and_read",
            }
            assert {name: combined_tools[name] for name in original_tools} == original_tools
            outcomes = []
            for name, payload in (
                ("search_kb", arguments),
                ("search_and_read", {"search": arguments}),
            ):
                body_calls.clear()
                try:
                    response = await client.call_tool(name, payload)
                except ToolError:
                    outcomes.append({"ok": False, "body_calls": list(body_calls)})
                else:
                    value = response.data
                    if name == "search_and_read":
                        assert value["physical_queries"] == 1
                        assert value["details"] == value["unread_ids"] == []
                        value = value["search_result"]
                    outcomes.append(
                        {"ok": not response.is_error, "data": value, "body_calls": list(body_calls)}
                    )
            return outcomes

    original, combined = asyncio.run(run())
    assert combined == original
    expected = not strict if accepted == "coerce_only" else accepted
    assert combined["ok"] is expected
    assert len(combined["body_calls"]) == (1 if expected else 0)


@pytest.mark.parametrize("failure_kind", ["input", "body"])
def test_combined_mcp_preserves_validation_diagnostic_without_empty_result(failure_kind):
    calls = []

    def search(tags: TagList | None = None) -> list[dict]:
        calls.append(tags)
        TypeAdapter(int).validate_python("backend-corrupt-value")
        pytest.fail("Fixture must fail before returning a search result")

    async def run():
        api = FastMCP("isolated-validation-diagnostic")
        MODULE.register(
            SimpleNamespace(
                tool=api.tool,
                mcp=api,
                search_kb=search,
                get_entry=lambda **kw: pytest.fail("A failed search must not read details"),
            )
        )
        arguments = {"tags": "spell"} if failure_kind == "input" else {"tags": ["spell"]}
        async with Client(api) as client:
            with pytest.raises(ToolError) as failure:
                await client.call_tool("search_and_read", {"search": arguments})
            return str(failure.value)

    message = asyncio.run(run())
    if failure_kind == "input":
        assert "list_type" in message
        assert "tags" in message
        assert calls == []
    else:
        assert "backend-corrupt-value" in message
        assert "int_parsing" in message
        assert "Invalid input" not in message
        assert calls == [["spell"]]
