"""Measured non-adopted items must be reusable in caller-designed whole packages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from pok.engine import items
from pok.engine.valuation import utility_candidate_digest


def _apply(spec: dict[str, Any], replacement: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(spec)
    collection = replacement["collection"]
    key = replacement["identity_key"]
    value = replacement["value"]
    out[collection] = [row for row in out.get(collection, []) if row[key] != value[key]]
    out[collection].append(deepcopy(value))
    return out


def test_unselected_resistance_candidate_becomes_exact_package_input_without_more_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Rarity: UNIQUE\nUtility Belt\nBelt\n+45% to all Elemental Resistances"
    candidate = items.ItemCandidate("utility-belt", "Belt", text, "unique-kb")
    monkeypatch.setattr(items, "enumerate_slot_uniques", lambda *_: [candidate])
    base = {
        "items": [
            {"slot": "Belt", "text": "old", "active": False, "substitutes": ["old proxy"]},
            {"slot": "Ring 1", "text": "unchanged"},
        ]
    }
    calls: list[dict[str, Any]] = []

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        calls.append(deepcopy(spec))
        belt = next(row for row in spec["items"] if row["slot"] == "Belt")
        return {"TotalDPS": 100.0, "FireResistTotal": 120.0 if belt["text"] == text else 75.0}

    plain = items.optimize_items(base, ["Belt"], {"TotalDPS": 1}, compute=compute)
    plain_calls = deepcopy(calls)
    calls.clear()
    rich = items.optimize_items(
        base, ["Belt"], {"TotalDPS": 1}, compute=compute, include_candidate_items=True
    )
    assert calls == plain_calls
    assert not rich.steps and rich.spec == base
    assert "replacement" not in plain.unscored_candidates[0]
    report = rich.unscored_candidates[0]
    replacement = report["replacement"]
    assert replacement["value"] == {"slot": "Belt", "text": text, "active": False}
    assert replacement["candidate_sha256"] == report["candidate_sha256"]
    assert utility_candidate_digest(replacement["value"]) == report["candidate_sha256"]
    materialized = _apply(base, replacement)
    assert materialized == next(spec for spec in calls if spec != base)
    assert base["items"][0]["substitutes"] == ["old proxy"]
    assert rich.search_evidence == plain.search_evidence


def test_jewel_replacement_keeps_exact_socket_and_removes_old_allocates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Rarity: RARE\nMeasured Jewel\nEmerald\n+12% to Fire Resistance"
    base = {
        "tree_nodes": [7, 8],
        "jewels": [
            {"socket_node_id": 7, "text": "old", "allocates": [999]},
            {"socket_node_id": 8, "text": "keep"},
        ],
    }
    monkeypatch.setattr(items, "_jewel_slot_rejection", lambda *_: None)
    measured: list[dict[str, Any]] = []

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        measured.append(deepcopy(spec))
        return {"TotalDPS": 100.0}

    result = items.evaluate_slot(
        base,
        "Jewel@7",
        [items.ItemCandidate("jewel", "Jewel@7", text, "rare-template")],
        compute=compute,
    )[0]
    replacement = result.replacement
    assert replacement["collection"] == "jewels"
    assert replacement["identity_key"] == "socket_node_id"
    assert replacement["value"] == {"socket_node_id": 7, "text": text}
    assert _apply(base, replacement) == measured[1]
    assert len(_apply(base, replacement)["jewels"]) == 2


def test_conditional_replacement_excludes_synthetic_probe_and_keeps_floor_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Rarity: UNIQUE\nLife Scaler\nBelt\n1% increased Damage per 100 maximum Life"
    monkeypatch.setattr(
        items,
        "enumerate_slot_uniques",
        lambda *_: [items.ItemCandidate("life-scaler", "Belt", text, "unique-kb")],
    )

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        texts = [row["text"] for row in spec.get("items", [])]
        scaling = text in texts
        probed = any("Probe" in value for value in texts)
        return {
            "TotalDPS": 200.0 if scaling and probed else 100.0,
            "Life": 100.0 if scaling else 500.0,
        }

    result = items.optimize_items(
        {"items": []},
        ["Belt"],
        {"TotalDPS": 1},
        floors={"Life": 400.0},
        compute=compute,
        include_candidate_items=True,
    )
    assert not result.steps
    peak = result.conditional_peaks[0]
    assert peak.blocked and peak.floor_violations
    assert peak.replacement["value"] == {"slot": "Belt", "text": text}
    assert "Probe" not in str(peak.replacement)
    assert result.unscored_candidates[0]["blocked"]


def test_rare_template_keeps_original_text_without_rerendering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = "Rarity: RARE\nExact Roll\nBelt\n+43% to Fire Resistance\n"
    monkeypatch.setattr(items, "enumerate_slot_uniques", lambda *_: [])
    result = items.optimize_items(
        {"items": []},
        ["Belt"],
        {"TotalDPS": 1},
        rare_templates={"Belt": [text]},
        compute=lambda spec: {
            "TotalDPS": 100.0,
            "FireResistTotal": 118.0 if spec["items"] else 75.0,
        },
        include_candidate_items=True,
    )
    assert result.unscored_candidates[0]["replacement"]["value"]["text"] == text


def test_mcp_opt_in_exposes_exact_entries_for_visible_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pok.mcp.tools import tree

    candidate = items.ItemCandidate("conditional", "Belt", "exact", "unique-kb")
    replacement = items._candidate_replacement(
        {"items": [{"slot": "Belt", "text": "exact"}]}, "Belt"
    )
    measured = items.CandidateResult(
        candidate, {}, ("life",), {}, "synthetic", (), replacement=replacement
    )
    result = items.ItemOptimizeResult(
        spec={"items": []},
        steps=(),
        conditional_peaks=(measured,),
        notes=(),
        defensive_only=(measured,),
    )
    captured = {}

    def optimize(*_args: Any, **kwargs: Any) -> items.ItemOptimizeResult:
        captured.update(kwargs)
        return result

    monkeypatch.setattr(items, "optimize_items", optimize)
    plain = tree.optimize_items({"items": []}, ["Belt"], {"TotalDPS": 1})
    assert captured["include_candidate_items"] is False
    assert "replacement" not in plain["conditional_peaks"][0]
    rich = tree.optimize_items(
        {"items": []}, ["Belt"], {"TotalDPS": 1}, include_candidate_items=True
    )
    assert captured["include_candidate_items"] is True
    assert rich["conditional_peaks"][0]["replacement"] == replacement
    assert rich["defensive_only"][0]["replacement"] == replacement


def test_opt_in_keeps_existing_candidate_detail_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    candidates = [
        items.ItemCandidate(f"utility-{index:02}", "Belt", f"text-{index}", "unique-kb")
        for index in range(items._UNSCORED_CANDIDATE_LIMIT + 3)
    ]
    monkeypatch.setattr(items, "enumerate_slot_uniques", lambda *_: candidates)
    result = items.optimize_items(
        {"items": []},
        ["Belt"],
        {"TotalDPS": 1},
        compute=lambda spec: {"TotalDPS": 100.0, "Evasion": 200.0 if spec["items"] else 100.0},
        include_candidate_items=True,
    )
    assert len(result.unscored_candidates) == items._UNSCORED_CANDIDATE_LIMIT
    assert all(row["replacement"]["value"]["text"] for row in result.unscored_candidates)
    assert len(result.unscored_summary["omitted_candidates"]) == 3
    assert all("replacement" not in row for row in result.unscored_summary["omitted_candidates"])
    assert all(
        "replacement" not in row for row in result.unscored_summary["utility_gain_candidate_ids"]
    )
