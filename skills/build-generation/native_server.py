"""Optional skill-level search/read operation alongside the complete PoK MCP.

Unlike the fixed-stage experiment runner, this entry point does not schedule
model turns, restrict the existing tools, or decide when generation must stop.
It is an experimental interface, not the default registered PoK server.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any


def retrieve(
    search: dict[str, Any],
    max_entries: int,
    fields: list[str] | None,
    include_narrative: bool,
    *,
    search_fn: Callable[..., list[dict[str, Any]]],
    read_fn: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Preserve all search hits, detail failures and unread IDs, without ranking."""
    if (
        isinstance(max_entries, bool)
        or not isinstance(max_entries, int)
        or not 1 <= max_entries <= 20
    ):
        raise ValueError("max_entries must be between 1 and 20")
    inspect.signature(search_fn).bind(**search)
    hits = search_fn(**search)
    identifiers = list(dict.fromkeys(row["id"] for row in hits if isinstance(row.get("id"), str)))
    details = []
    for identifier in identifiers[:max_entries]:
        try:
            value = read_fn(id=identifier, fields=fields, include_narrative=include_narrative)
        except Exception as exc:
            details.append({"id": identifier, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        else:
            details.append({"id": identifier, "ok": True, "record": value})
    return {
        "search_result": hits,
        "details": details,
        "unread_ids": identifiers[max_entries:],
        "physical_queries": 1 + len(details),
        "selection_policy": "Search order only; not a build recommendation.",
        "complete_search_universe": False,
    }


def register(server: Any) -> None:
    """Add one operation to the real server; leave every existing tool available."""

    @server.tool
    def search_and_read(
        search: dict[str, Any],
        max_entries: int = 3,
        fields: list[str] | None = None,
        include_narrative: bool = True,
    ) -> dict[str, Any]:
        """Run search_kb and read up to max_entries of its returned IDs immediately.

        search contains normal search_kb arguments, including query/type/limit and
        category/sub_type filters. All search hits and empty-result diagnostics
        remain visible. Unread IDs and detail errors remain explicit. Search order
        is not recommendation order; change the search or use ordinary get_entry
        when different records matter. This operation counts each actual query.
        No stage or total-query limit is imposed by this optional entry point.
        """
        return retrieve(
            search,
            max_entries,
            fields,
            include_narrative,
            search_fn=server.search_kb,
            read_fn=server.get_entry,
        )


def main() -> None:
    from pok.common.stdio import force_utf8_stdio
    from pok.mcp import server

    force_utf8_stdio()
    register(server)
    server.main()


if __name__ == "__main__":
    main()
