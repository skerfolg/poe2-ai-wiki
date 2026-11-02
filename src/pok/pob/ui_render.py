"""UI selections to native PoB item specifications, never KB mod text."""

from __future__ import annotations

import math
import re
from typing import Any

from pok.pob.daemon import PobDaemon

_SELECTED = re.compile(r"^Selected( Alt)?( Variant)?( Two| Three| Four| Five)?:.*$", re.M)


def render_item(
    request: dict[str, Any], catalog: dict[str, Any], calculator: PobDaemon
) -> dict[str, Any]:
    """Render base/rare and one explicit unique variant through the native builder.

    Multiple unique variant selections remain an explicit unsupported operation;
    their raw text is retained by the catalog for direct PoB editing.
    """
    if set(request) - {"kind", "id", "name", "variants", "mods", "rolls", "quality"}:
        raise ValueError("Unsupported item render parameter")
    kind, identity = request.get("kind"), request.get("id")
    if (
        not isinstance(kind, str)
        or kind not in {"base", "rare", "unique"}
        or not isinstance(identity, str)
    ):
        raise ValueError("Expected an item kind and native catalog ID")
    entries = {(row["type"], row["id"]): row for row in catalog["entries"]}
    entry = entries.get(("base" if kind == "rare" else kind, identity))
    if entry is None or entry["type"] != ("base" if kind == "rare" else kind):
        raise ValueError("Item ID does not identify the requested native catalog kind")
    quality = request.get("quality")
    if quality is not None and (type(quality) is not int or not 0 <= quality <= 100):
        raise ValueError("Quality must be an integer in the editor's 0..100 range")
    mods, rolls, variants = (
        request.get("mods", []),
        request.get("rolls", {}),
        request.get("variants", []),
    )
    if not isinstance(mods, list) or any(not isinstance(value, str) for value in mods):
        raise ValueError("mods must be native mod IDs")
    if not isinstance(rolls, dict) or any(not isinstance(key, str) for key in rolls):
        raise ValueError("rolls must be keyed by native mod ID")
    if not isinstance(variants, list) or any(not isinstance(value, str) for value in variants):
        raise ValueError("variants must be native variant IDs")
    if kind == "unique":
        if mods or rolls or len(variants) > 1:
            raise ValueError("Use raw PoB text for multiple variants or unique mod edits")
        text = entry["raw"]["text"]
        if variants:
            choices = {row["id"]: index for index, row in enumerate(entry.get("variants", []), 1)}
            if variants[0] not in choices:
                raise ValueError("Unknown native unique variant ID")
            text = "\n".join(line for line in _SELECTED.sub("", text).splitlines() if line.strip())
            text += f"\nSelected Variant: {choices[variants[0]]}"
        if not text.lstrip().lower().startswith("rarity:"):
            text = "Rarity: UNIQUE\n" + text
        if quality is not None:
            lines = [line for line in text.splitlines() if not line.startswith("Quality:")]
            lines.insert(3, f"Quality: {quality}")
            text = "\n".join(lines)
        spec = text
    else:
        if variants or (kind == "base" and (mods or rolls)):
            raise ValueError("The selected base operation does not accept these modifiers")
        name = request.get("name", "New Item")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 256
            or any(c in name for c in "\r\n\0")
        ):
            raise ValueError("Item name must be a single bounded line")
        lines = ["Rarity: RARE" if kind == "rare" else "Rarity: NORMAL", name, entry["id"]]
        if kind == "rare":
            lines.append("Crafted: true")
        if quality is not None:
            lines.append(f"Quality: {quality}")
        if set(rolls) - set(mods):
            raise ValueError("A roll has no corresponding selected mod")
        for mod_id in mods:
            mod = entries.get(("mod", mod_id))
            category = (mod or {}).get("raw", {}).get("type")
            if mod is None or mod["type"] != "mod" or category not in {"Prefix", "Suffix"}:
                raise ValueError("Unknown native prefix/suffix ID")
            fraction = rolls.get(mod_id)
            marker = ""
            if fraction is not None:
                if (
                    isinstance(fraction, bool)
                    or not isinstance(fraction, int | float)
                    or not math.isfinite(fraction)
                    or not 0 <= fraction <= 1
                ):
                    raise ValueError("Native roll fractions must be finite in 0..1")
                marker = "{range:" + format(fraction, ".17g") + "}"
            lines.append(f"{category}: {marker}{mod_id}")
        spec = "\n".join(lines)
    rendered = calculator.build_item(spec)
    if not rendered:
        raise ValueError("Native PoB did not produce item text")
    return {
        "ok": True,
        "text": rendered,
        "id": identity,
        "kind": kind,
        "claim": "native_item_render_not_acquisition_validation",
        "limits": ["multiple_unique_variant_editing_requires_raw_text"],
    }
