"""Item socket acquisition, separate from PoB's representation ceiling (#192).

PoB base.socketLimit includes sockets that require an acquisition outcome. It
is not an ordinary crafting allowance. This module checks the supplied item,
its verified fixed socket modifiers, allocated grants and corruption budget.
It neither selects equipment nor treats a Corrupted marker as two outcomes.
"""

from __future__ import annotations

import functools
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir
from pok.engine.items import _active_lines, _kb_records
from pok.engine.tree.graph import TreeGraph
from pok.pob.runner import RUNE_CONTROL_SLOTS

_TAGS = re.compile(r"^(?:\{[^{}]*\})+")
_FIXED = re.compile(r"^Has (\d+) (?:Augment |Rune )?Sockets(?: \(Hidden\))?$", re.I)
_SLOT_GRANT = re.compile(r"^(\d+) (Helmet|Body Armour|Gloves|Boots) sockets?$", re.I)


@functools.lru_cache(maxsize=4)
def _rules(root: Path | None) -> dict[str, Any]:
    path = knowledge_dir(root) / "crafting-rules" / "board-rules.json"
    return dict(json.loads(path.read_text(encoding="utf-8")).get("socket_acquisition") or {})


@functools.lru_cache(maxsize=4)
def _graph(root: Path | None) -> TreeGraph:
    return TreeGraph(knowledge_dir(root))


@functools.lru_cache(maxsize=4)
def _catalog(root: Path | None) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    bases: dict[str, Any] = {}
    uniques: dict[str, Any] = {}
    corruptions: list[dict[str, Any]] = []
    for record in _kb_records(root).values():
        data = record.raw.get("data") or {}
        if record.type == "Item":
            target = uniques if data.get("rarity") == "unique" else bases
            key = record.name_en.casefold()
            # Cultivated copies share the name and may omit hidden socket text.
            # They must not overwrite the canonical unique's fixed capacity.
            if key not in target or data.get("class_group") != "cultivated":
                target[key] = record.raw
        elif record.type == "Modifier" and data.get("affix_type") == "corrupted":
            corruptions.append(record.raw)
    return bases, uniques, corruptions


def _plain(line: str) -> str:
    return _TAGS.sub("", line.strip()).strip()


@functools.lru_cache(maxsize=4)
def _augment_types(root: Path | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for record in _kb_records(root).values():
        data = record.raw.get("data") or {}
        types = set((data.get("per_slot_type") or {}).values())
        if data.get("affix_type") == "rune" and len(types) == 1:
            result[record.name_en.casefold()] = str(next(iter(types)))
    return result


def _lines(value: Any) -> list[str]:
    if isinstance(value, str):
        return value.splitlines()
    if isinstance(value, list):
        return [str(line) for line in value if isinstance(line, str)]
    return []


def _tree_grants(spec: Mapping[str, Any], root: Path | None) -> dict[str, list[dict[str, Any]]]:
    allocated = {int(n) for n in spec.get("tree_nodes") or ()}
    if not allocated:
        return {}
    graph = _graph(root)
    ascendancy = graph.resolve_ascendancy(spec.get("ascendancy"))
    grants: dict[str, list[dict[str, Any]]] = {}
    for node_id in sorted(allocated):
        node = graph.nodes.get(node_id)
        if node is None:
            continue
        if node.ascendancy and graph.resolve_ascendancy(node.ascendancy) != ascendancy:
            continue
        if node.locked_to and graph.resolve_ascendancy(node.locked_to) != ascendancy:
            continue
        if not set(node.requires_nodes) <= allocated:
            continue
        armed = False
        for line in node.stats_en:
            if "additional rune-only sockets" in line.casefold():
                armed = True
            elif armed and (match := _SLOT_GRANT.fullmatch(line.strip().lstrip("• "))):
                grants.setdefault(match[2].casefold(), []).append(
                    {
                        "node_id": node_id,
                        "name": node.name_en,
                        "count": int(match[1]),
                        "rune_only": True,
                    }
                )
            else:
                armed = False
    return grants


def _corruption_mods(
    text: str, base: dict[str, Any], innate: Sequence[str], root: Path | None
) -> list[str]:
    # Reuse the legality matcher's normalisation and base eligibility. A native
    # custom corruption is not an ordinary affix merely because Craft stores it
    # as {custom}. Conversely native base/unique effects must not consume a roll.
    from pok.engine.legality import _fits_base, _norm, _values_in_range

    _, _, records = _catalog(root)
    native = [_plain(line) for line in innate]
    matched_lines: dict[tuple[str, str], int] = {}
    implicit_left = 0
    for line in _active_lines(text):
        if match := re.fullmatch(r"Implicits:\s*(\d+)", line, re.I):
            implicit_left = int(match[1])
            continue
        in_implicit = implicit_left > 0
        if implicit_left:
            implicit_left -= 1
        prefix = _TAGS.match(line)
        tags = (prefix.group() if prefix else "").lower()
        if any(tag in tags for tag in ("{rune}", "{desecrated}", "{crafted}")):
            continue
        body = _plain(line)
        if not (in_implicit or "{custom}" in tags or "{corrupted}" in tags):
            continue
        if not any(tag in tags for tag in ("{custom}", "{corrupted}", "{enchant}")):
            native_match = next(
                (
                    index
                    for index, line in enumerate(native)
                    if _norm(body) == _norm(line) and _values_in_range(body, [line])[0]
                ),
                None,
            )
            if native_match is not None:
                native.pop(native_match)
                continue
        for record in records:
            data = record["data"]
            texts = data.get("texts") or []
            if (
                any(_norm(body) == _norm(str(candidate)) for candidate in texts)
                and _fits_base(data, base)
                and _values_in_range(body, texts)[0]
            ):
                key = (str(record["id"]), _norm(body))
                matched_lines[key] = matched_lines.get(key, 0) + 1
                break
    # Two distinct rows of one hybrid modifier consume one outcome. Repeating
    # the same row consumes another; set-based deduplication would mint free mods.
    counts: dict[str, int] = {}
    for (record_id, _), count in matched_lines.items():
        counts[record_id] = max(counts.get(record_id, 0), count)
    return [record_id for record_id, count in sorted(counts.items()) for _ in range(count)]


def audit_item_sockets(
    spec: Mapping[str, Any],
    root: Path | None = None,
    observed: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Check the whole supplied equipment without silently reducing its sockets.

    Unknown acquisition routes do not get a successful legality certificate.
    PoB observations supplement the report; they never manufacture a route.
    """
    rules = _rules(root)
    bases, uniques, _ = _catalog(root)
    grants = _tree_grants(spec, root)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    observations = {str(row.get("slot")): row for row in observed or ()}
    for item in spec.get("items") or ():
        slot = str(item.get("slot") or "")
        text = str(item.get("text") or "")
        lines = _active_lines(text)
        if len(lines) < 2:
            continue  # The item parser reports malformed input.
        rarity = lines[0].partition(":")[2].strip().casefold()
        name = lines[1]
        base_name = name if rarity == "normal" else (lines[2] if len(lines) > 2 else "")
        base = bases.get(base_name.casefold())
        if base is None and rarity == "magic" and name.casefold() in bases:
            base_name, base = name, bases[name.casefold()]
        # Native ParseRaw counts every 'S' character across every declaration,
        # including SSS and repeated Sockets headers. Match its semantics.
        sockets = sum(
            line.partition(":")[2].count("S")
            for line in lines
            if line.casefold().startswith("sockets:")
        )
        if base is None:
            if sockets:
                problems.append(
                    f"{slot}/{name}: 베이스가 확인되지 않아 룬 홈 획득 한도를 검증할 수 없다"
                )
            continue
        data = base.get("data") or {}
        category = str(data.get("category") or "")
        pob_limit = int(data.get("socket_limit") or 0)
        ordinary = (rules.get("ordinary_by_item_class") or {}).get(
            str(data.get("item_class") or "")
        )
        if ordinary is None:
            ordinary = (rules.get("ordinary_by_category") or {}).get(category)
        if ordinary is None and not pob_limit:
            ordinary = 0
        native = _lines(data.get("implicit"))
        unique = uniques.get(name.casefold()) if rarity == "unique" else None
        if unique and str(unique["data"].get("base_type") or "").casefold() != base_name.casefold():
            # Native GetUniqueDBItem resolves these cultivated bases through
            # their original base. Verify both KB bases and the actual tag so
            # a unique title on an unrelated base cannot inherit its sockets.
            original_name = re.sub(r"^(?:Runeforged|Runemastered) ", "", base_name, flags=re.I)
            original_base = bases.get(original_name.casefold())
            cultivated_match = (
                original_name != base_name
                and bool((data.get("spawn_tags") or {}).get("runeforged"))
                and original_name.casefold()
                == str(unique["data"].get("base_type") or "").casefold()
                and original_base is not None
                and (original_base.get("data") or {}).get("item_class") == data.get("item_class")
            )
            if not cultivated_match:
                unique = None
        if unique:
            native += _lines(unique["data"].get("implicits"))
        native_implicits = list(native)
        if unique:
            native += _lines(unique["data"].get("explicits"))
        # Fixed socket modifiers must occur in both the canonical record and the
        # actual selected text; a forged line/unused variant cannot buy sockets.
        supplied = {_plain(ln).casefold().removesuffix(" (hidden)") for ln in lines}
        fixed = [
            int(m[1])
            for ln in native
            if (m := _FIXED.fullmatch(_plain(ln)))
            and (
                _plain(ln).casefold().removesuffix(" (hidden)") in supplied
                or (unique and "(hidden)" in ln.lower())
            )
        ]
        for variant in data.get("implicit_variants") or []:
            for ln in _lines(variant):
                if (match := _FIXED.fullmatch(_plain(ln))) and _plain(ln).casefold() in supplied:
                    fixed.append(int(match[1]))
        exception = (rules.get("fixed_unique_sockets") or {}).get(str((unique or {}).get("id")))
        if unique and isinstance(exception, dict):
            fixed.append(int(exception["sockets"]))
        fixed_limit = max(fixed, default=0)
        ordinary_known = ordinary is not None or bool(fixed_limit)
        normal_budget = fixed_limit if fixed else int(ordinary or 0)
        declared_sources = item.get("socket_sources") or ()
        source_errors: list[str] = []
        if not isinstance(declared_sources, list | tuple) or any(
            not isinstance(source, str) for source in declared_sources
        ):
            source_errors.append("socket_sources는 획득 경로 문자열 목록이어야 한다")
            declared_sources = ()
        if len(set(declared_sources)) != len(declared_sources):
            source_errors.append("socket_sources 중복 선언은 추가 홈을 늘리지 않는다")
        unknown_sources = set(declared_sources) - {"exceptional", "exceptional_quality"}
        if unknown_sources:
            source_errors.append(f"검증되지 않은 홈 획득 경로: {sorted(unknown_sources)}")
        exceptional = (
            int(rules.get("exceptional_socket_gain") or 0)
            if "exceptional" in declared_sources
            else 0
        )
        if {"exceptional", "exceptional_quality"} <= set(declared_sources):
            source_errors.append("exceptional 추가 홈과 초과 품질은 서로 다른 드롭 결과다")
        if exceptional and not normal_budget:
            source_errors.append("홈이 없는 베이스에 exceptional 추가 홈을 선언할 수 없다")
            exceptional = 0
        sources = grants.get(slot.casefold(), [])
        tree_budget = sum(int(grant["count"]) for grant in sources)
        corrupted = any(ln.casefold() in {"corrupted", "twice corrupted"} for ln in lines)
        mods = _corruption_mods(text, base, native_implicits, root)
        outcome_limit = int(rules.get("corruption_outcome_limit") or 1)
        if any(ln.casefold() == "twice corrupted" for ln in lines):
            outcome_limit = int(rules.get("twice_corrupted_outcome_limit") or outcome_limit)
        available = max(0, outcome_limit - len(mods)) if corrupted else 0
        extra_limit = int(rules.get("corruption_socket_gain") or 1)
        corruption_budget = min(extra_limit, available) if normal_budget else 0
        budget = normal_budget + exceptional + tree_budget + corruption_budget
        failures: list[str] = source_errors
        if sockets and not ordinary_known:
            failures.append("일반 홈 획득 규칙 미확인: PoB socketLimit를 일반 예산으로 쓸 수 없다")
        if mods and not corrupted:
            failures.append("타락 옵션이 있으나 Corrupted 획득 표기가 없다")
        if len(mods) > outcome_limit:
            failures.append(f"타락 결과 {len(mods)}개 > 확인된 결과 예산 {outcome_limit}개")
        corruption_records = {str(record["id"]): record for record in _catalog(root)[2]}
        groups = [str(corruption_records[mod]["data"].get("group") or mod) for mod in mods]
        if len(set(groups)) != len(groups):
            failures.append("동일 타락 모드 그룹의 결과를 중복 사용할 수 없다")
        if ordinary_known and sockets > budget:
            failures.append(
                f"룬 홈 {sockets}칸 > 획득 가능한 {budget}칸 "
                f"(일반/고정 {normal_budget} + exceptional {exceptional} "
                f"+ 트리 {tree_budget} + 타락 홈 {corruption_budget}); "
                f"타락 옵션 {len(mods)}개가 결과 예산 {outcome_limit}개를 공유한다. "
                "홈 수를 줄이거나 다른 타락 결과와 공존 가능한 획득 경로를 검증할 것"
            )
        if sockets > RUNE_CONTROL_SLOTS:
            failures.append(f"PoB 편집창 표현 한도 {RUNE_CONTROL_SLOTS}칸 초과")
        if slot in observations and observations[slot].get("sockets") != sockets:
            failures.append(
                f"PoB가 읽은 홈 {observations[slot].get('sockets')}칸과 "
                f"입력 검사 {sockets}칸 불일치"
            )
        native_plain = {_plain(line).casefold() for line in native}
        allowed_types: list[str] | None = None
        if "only soul cores can be socketed in this item" in native_plain:
            allowed_types = ["SoulCore"]
        elif "only runes can be socketed in this item" in native_plain:
            allowed_types = ["Rune"]
        names = [
            line.partition(":")[2].strip() for line in lines if line.casefold().startswith("rune:")
        ]
        types = [
            _augment_types(root).get(name.casefold()) for name in names if name.casefold() != "none"
        ]
        if len(types) > sockets:
            failures.append(f"룬 선언 {len(types)}개 > 홈 {sockets}칸")
        if allowed_types is not None and any(kind not in allowed_types for kind in types):
            failures.append(f"이 고유 아이템의 홈에는 {allowed_types}만 장착할 수 있다")
        non_rune_capacity = normal_budget + exceptional + corruption_budget
        if tree_budget and sum(kind != "Rune" for kind in types) > non_rune_capacity:
            failures.append(
                "전직 추가 홈은 Rune 전용이다; 우상·영혼 핵·미분류 장착물을 넣을 수 없다"
            )
        # An imported text can omit its exceptional-drop provenance. Distinguish
        # that missing evidence from combinations that still exceed every known
        # declared route; neither is a completed acquisition verification.
        missing_exceptional = (
            sockets > budget
            and "exceptional" not in declared_sources
            and sockets <= budget + int(rules.get("exceptional_socket_gain") or 0)
        )
        status = "legal" if not failures else "illegal"
        if failures and (not ordinary_known or (missing_exceptional and len(failures) == 1)):
            status = "acquisition_unproven"
        row = {
            "slot": slot,
            "name": name,
            "base": base_name,
            "sockets": sockets,
            "ordinary_limit": ordinary,
            "fixed_limit": fixed_limit,
            "socket_sources": list(declared_sources),
            "exceptional_grant": exceptional,
            "tree_grant": tree_budget,
            "non_rune_capacity": non_rune_capacity,
            "allowed_augment_types": allowed_types,
            "grant_sources": sources,
            "corrupted": corrupted,
            "corruption_mods": mods,
            "corruption_outcome_limit": outcome_limit,
            "corruption_socket_allowance": corruption_budget,
            "budget": budget,
            "pob_base_limit": pob_limit,
            "pob_control_limit": RUNE_CONTROL_SLOTS,
            "legal": not failures,
            "status": status,
            "problems": failures,
        }
        if slot in observations:
            row["pob_observed_sockets"] = observations[slot].get("sockets")
        rows.append(row)
        problems += [f"{slot}/{name}: {failure}" for failure in failures]
    return {"legal": not problems, "items": rows, "problems": problems}
