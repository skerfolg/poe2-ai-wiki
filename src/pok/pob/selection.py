"""Resolve saved active XML sets without rewriting or discarding inactive data.

PoB uses IDs for item/skill/config sets and an ordinal for tree specs. Fallbacks
are reported rather than silently presenting a different set as an exact import.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class XmlSelection:
    tree: ET.Element | None
    items: ET.Element | None
    skills: ET.Element | None
    config: ET.Element | None
    resolved: dict[str, str | int]
    notes: tuple[str, ...]


def _integer(value: str) -> int:
    """Lua tonumber accepts integral decimal/exponent spellings as numeric IDs."""
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Set identity must be numeric") from exc
    if (
        not number.is_finite()
        or number < -9007199254740991
        or number > 9007199254740991
        or number != number.to_integral_value()
    ):
        raise ValueError("Set identity must be a finite integer")
    return int(number)


def _id_set(
    parent: ET.Element | None,
    child: str,
    attribute: str,
    key: str,
    resolved: dict[str, str | int],
    notes: list[str],
    overrides: Mapping[str, Any],
) -> ET.Element | None:
    if parent is None:
        if key in overrides:
            raise ValueError(f"Requested {key} section is absent")
        return None
    sets = parent.findall(child)
    if not sets:
        if key in overrides and _integer(overrides[key]) != 1:
            raise ValueError(f"Requested {key} is absent from the legacy single-set section")
        resolved[key] = "1"
        return parent  # Legacy format stores entries directly in the section.
    by_id = {}
    for index, element in enumerate(sets, 1):
        identity = element.get("id")
        if identity is None:
            if len(sets) != 1:
                raise ValueError(f"{child}: multiple sets without explicit IDs are ambiguous")
            identity = str(index)  # Preserve the historical single unnamed set.
        try:
            identity = str(_integer(identity))
        except ValueError as exc:
            raise ValueError(f"{child}: invalid numeric set ID") from exc
        if int(identity) < 1 or identity in by_id:
            raise ValueError(f"{child}: duplicate or nonpositive set ID")
        by_id[identity] = element
    raw = overrides[key] if key in overrides else parent.get(attribute)
    try:
        wanted = str(_integer(raw)) if raw is not None else "1"
    except ValueError:
        if key in overrides:
            raise ValueError(f"Explicit {key} must be an integral numeric ID") from None
        wanted = "1"
        notes.append(f"{attribute}={raw!r}는 유효한 ID가 아니어서 기본 세트를 선택했다")
    if wanted not in by_id:
        if key in overrides:
            raise ValueError(f"Explicit {key}={wanted} does not exist")
        selected = next(iter(by_id))
        notes.append(f"{attribute}={wanted} 세트가 없어 첫 세트 {selected}를 선택했다")
    else:
        selected = wanted
    resolved[key] = selected
    return by_id[selected]


def resolve_xml_selection(
    root: ET.Element, overrides: Mapping[str, Any] | None = None
) -> XmlSelection:
    overrides = dict(overrides or {})
    id_keys = {"tree_spec", "item_set", "skill_set", "config_set"}
    if set(overrides) - id_keys - {"weapon_set", "main_group"}:
        raise ValueError(
            "Unsupported explicit selection fields: "
            + ", ".join(sorted(set(overrides) - id_keys - {"weapon_set", "main_group"}))
        )
    if any(not isinstance(overrides[key], str) for key in id_keys & set(overrides)):
        raise ValueError("Explicit set IDs/tree ordinal must be strings")
    resolved: dict[str, str | int] = {}
    notes: list[str] = []
    tree = root.find("Tree")
    tree_specs = tree.findall("Spec") if tree is not None else []
    selected_tree = None
    if tree_specs:
        raw = overrides.get("tree_spec", tree.get("activeSpec") if tree is not None else None)
        try:
            ordinal = _integer(raw) if raw is not None else 1
        except ValueError:
            if "tree_spec" in overrides:
                raise ValueError("Explicit tree_spec must be an integral ordinal") from None
            ordinal = 1
            notes.append(f"activeSpec={raw!r}는 유효한 순번이 아니어서 첫 트리를 선택했다")
        if ordinal < 1:
            raise ValueError("activeSpec must be a positive ordinal")
        if ordinal > len(tree_specs):
            if "tree_spec" in overrides:
                raise ValueError("Explicit tree_spec does not exist")
            notes.append(f"activeSpec={ordinal}이 범위를 넘어 마지막 트리를 선택했다")
            ordinal = len(tree_specs)  # TreeTab.SetActiveSpec uses min(id, count).
        selected_tree = tree_specs[ordinal - 1]
        resolved["tree_spec"] = str(ordinal)
    elif "tree_spec" in overrides:
        raise ValueError("Requested tree_spec section is absent")
    items_parent = root.find("Items")
    items = _id_set(
        items_parent, "ItemSet", "activeItemSet", "item_set", resolved, notes, overrides
    )
    skills = _id_set(
        root.find("Skills"), "SkillSet", "activeSkillSet", "skill_set", resolved, notes, overrides
    )
    config = _id_set(
        root.find("Config"),
        "ConfigSet",
        "activeConfigSet",
        "config_set",
        resolved,
        notes,
        overrides,
    )
    raw_weapon = items.get("useSecondWeaponSet") if items is not None else None
    if raw_weapon is None and items_parent is not None:
        raw_weapon = items_parent.get("useSecondWeaponSet")
    resolved["weapon_set"] = 2 if raw_weapon == "true" else 1
    if "weapon_set" in overrides:
        value = overrides["weapon_set"]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("Explicit weapon_set must be 1 or 2")
        pointer = _integer(str(value))
        if pointer not in {1, 2}:
            raise ValueError("Explicit weapon_set must be 1 or 2")
        resolved["weapon_set"] = pointer
    if "main_group" in overrides:
        value = overrides["main_group"]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("Explicit main_group must be an integer")
        pointer = _integer(str(value))
        count = len(skills.findall("Skill")) if skills is not None else 0
        if not 1 <= pointer <= count:
            raise ValueError("Explicit main_group must name an existing XML Skill group (1-based)")
        resolved["main_group"] = pointer
    return XmlSelection(selected_tree, items, skills, config, resolved, tuple(notes))
