"""Literal access to fixed raw sources for the R reference; no KB ranking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SUFFIXES = {".lua", ".json", ".ndjson", ".md", ".txt", ".html"}


def raw_source(
    pools: dict[str, Path],
    pool: str,
    action: str,
    path: str = "",
    query: str = "",
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """Page text or literal search hits; never select a build or an item."""
    if pool not in pools or action not in {"list", "read", "search"}:
        raise ValueError("Unknown raw pool or operation")
    if offset < 0 or not 1 <= limit <= 20000:
        raise ValueError("Expected nonnegative offset and limit between 1 and 20000")
    base = pools[pool].resolve()
    target = (base / path).resolve()
    if not target.is_relative_to(base) or any(part.startswith(".") for part in Path(path).parts):
        raise ValueError("Path escapes the frozen public source pool")
    if action == "read":
        if target.suffix.lower() not in SUFFIXES:
            raise ValueError("Unsupported raw text file")
        text = target.read_text(encoding="utf-8")
        chunk = text[offset : offset + limit]
        return {
            "pool": pool,
            "path": path,
            "text": chunk,
            "offset": offset,
            "next_offset": offset + len(chunk) if offset + len(chunk) < len(text) else None,
        }
    if not target.exists():
        return {"pool": pool, "path": path, "entries": [], "next_offset": None}
    files = sorted(
        p
        for p in (target.rglob("*") if target.is_dir() else [target])
        if p.is_file()
        and p.suffix.lower() in SUFFIXES
        and not any(part.startswith(".") for part in p.relative_to(base).parts)
        and p.resolve().is_relative_to(base)
    )
    if action == "list":
        entries = [p.relative_to(base).as_posix() for p in files[offset : offset + limit]]
        return {
            "pool": pool,
            "entries": entries,
            "next_offset": offset + len(entries) if offset + len(entries) < len(files) else None,
        }
    if not query:
        raise ValueError("Literal search requires a query")
    hits = []
    skipped = 0
    for source in files:
        with source.open(encoding="utf-8", errors="replace") as stream:
            for number, line in enumerate(stream, 1):
                at = line.casefold().find(query.casefold())
                if at < 0:
                    continue
                if skipped < offset:
                    skipped += 1
                    continue
                hits.append(
                    {
                        "path": source.relative_to(base).as_posix(),
                        "line": number,
                        "excerpt": line[max(0, at - 100) : at + 300],
                    }
                )
                if len(hits) == limit:
                    return {
                        "pool": pool,
                        "entries": hits,
                        "next_offset": offset + len(hits),
                        "complete": False,
                    }
    return {"pool": pool, "entries": hits, "next_offset": None, "complete": True}
