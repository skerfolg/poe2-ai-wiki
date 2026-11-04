"""Prepare caller-selected unique configurations from the pinned native catalogue."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from pok.engine.items import resolve_rolls
from pok.kb.pob_pin import POB_COMMIT, pob_src_dir
from pok.pob.uniques import _configuration_of, describe_configuration, render_configuration


def prepare_unique_item(
    name: str,
    selections: dict[str, Any] | None = None,
    roll_policy: str = "native",
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Return the native choices and a directly calculable item input; make no build choice."""
    if roll_policy not in {"native", "min", "mid", "max"}:
        raise ValueError("roll_policy must be native, min, mid or max")
    source = {
        "kind": "pinned_native_unique_catalogue",
        "configured_pob_commit": POB_COMMIT,
        "identity_scope": "native_name_template_not_kb_alias_or_cultivated_binding",
    }
    if not (pob_src_dir(root) / "Data" / "Uniques").is_dir():
        return {
            "format": "pok.unique-item-configuration.v1",
            "ok": False,
            "status": "native_catalogue_unavailable",
            "source": source,
        }
    schema = describe_configuration(name, root)
    if schema is None:
        return {
            "format": "pok.unique-item-configuration.v1",
            "ok": False,
            "status": "native_template_missing",
            "name": name,
            "source": source,
            "next_route": (
                "Inspect the KB entry and sources or an existing PoB document for concrete "
                "item text, then use explicit calculation. Template absence is not proof "
                "that the instantiated item cannot be calculated."
            ),
        }
    raw = render_configuration(name, selections, root)
    if raw is None:
        raise ValueError("Native template disappeared during preparation")
    configured = _configuration_of(raw)
    text = "Rarity: UNIQUE\n" + (
        raw if roll_policy == "native" else resolve_rolls(raw, roll_policy)
    )
    return {
        "format": "pok.unique-item-configuration.v1",
        "ok": True,
        "item_text": text,
        "item_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source": {**source, "raw_sha256": schema["raw_sha256"]},
        "available_configuration": schema,
        "configured_selectors": [
            {
                **row,
                "origin": "caller_selected" if row["key"] in (selections or {}) else row["origin"],
            }
            for row in configured["selectors"]
        ],
        "requested_selectors": dict(selections or {}),
        "roll_policy": roll_policy,
        "preserved_unspecified_selectors": True,
        "claim": "native_item_input_not_game_availability_or_build_quality_validation",
        "calculation_performed": False,
    }
