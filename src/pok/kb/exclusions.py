"""Read approved gem exclusions as patch-scoped evidence, never infer from absence."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir

GEM_CATEGORIES = ("unobtainable_gems", "superseded", "removed_from_game", "poe1_remnant_pob")


def fold_gem_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name.replace("_", " ").replace("’", "'"))  # noqa: RUF001
    return "".join(char for char in normalized.casefold() if char.isalnum())


def gem_exclusion_ledger(root: Path | None = None) -> dict[str, Any]:
    """Return ledger evidence and its exact bytes hash, including historical entries."""
    directory = knowledge_dir(root) / "ingest"
    raw = (directory / "exclusions.json").read_bytes()
    ledger = json.loads(raw)
    manifest = json.loads((directory / "manifest.json").read_bytes())
    if not isinstance(ledger, dict) or ledger.get("version") != 1 or not isinstance(manifest, dict):
        raise ValueError("Unsupported gem exclusion ledger or ingest manifest")
    entries = []
    for category in GEM_CATEGORIES:
        rows = ledger.get(category, [])
        if not isinstance(rows, list):
            raise ValueError("Gem exclusion category must be a list")
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError("Gem exclusion entry must be an object")
            aliases = [row.get("slug"), row.get("pob_name"), *row.get("slugs", [])]
            aliases = [value for value in aliases if isinstance(value, str) and value]
            entries.append(
                {
                    "category": category,
                    "aliases": aliases,
                    "entry": row,
                    "source_path": f"/{category}/{index}",
                }
            )
    return {
        "patch": manifest.get("patch"),
        "source": "knowledge/ingest/exclusions.json",
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
        "entries": entries,
    }
