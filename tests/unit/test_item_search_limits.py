"""Native jewel caps and actual chain budgets must survive the item search route."""

from __future__ import annotations

from typing import Any

import pytest

from pok.engine import items
from pok.engine.items import ItemCandidate, evaluate_slot, optimize_items
from pok.engine.optimization_readiness import optimization_readiness
from pok.engine.provenance import stamp

LIMITED = "Rarity: UNIQUE\nOne Only\nRuby\nLimited to: 1"
BASE = {"class_name": "Mercenary", "ascendancy": "Mercenary3", "level": 100}


@pytest.mark.parametrize("slots", [["Jewel"], ["Jewel@11", "Jewel@22"]])
def test_item_optimizer_never_measures_or_adopts_two_limited_copies(monkeypatch, slots):
    def oracle(spec):
        copies = sum("One Only" in j["text"] for j in spec.get("jewels", []))
        assert copies <= 1, "Illegal variants must be excluded before oracle evaluation"
        return {"Life": 100 + 10 * copies}

    monkeypatch.setattr(items, "enumerate_slot_uniques", lambda *args: [])
    spec = {
        **BASE,
        "tree_nodes": [11, 22],
        "jewels": [
            {"socket_node_id": 11, "text": "old ruby"},
            {"socket_node_id": 22, "text": "old ruby"},
        ],
    }
    out = optimize_items(
        spec,
        slots,
        {"Life": 1},
        rare_templates={"Jewel": [LIMITED]},
        jewel_sockets=(11, 22),
        max_rounds=3,
        compute=oracle,
    )
    assert len(out.steps) == 1
    assert sum("One Only" in j["text"] for j in out.spec["jewels"]) == 1
    evidence = out.search_evidence
    assert evidence["scope"]["candidate_counts"]["Jewel@22"]["rejected"] == 1
    assert evidence["scope"]["candidate_counts"]["Jewel@22"]["evaluated"] == 0
    assert "Limited to: 1" in evidence["rejected_candidates"]["Jewel@22"][0]["reasons"][0]
    assert evidence["unresolved"] == []  # A known illegal candidate is not a model gap.


def test_same_socket_replacement_and_unallocated_copy_are_allowed():
    spec = {
        **BASE,
        "tree_nodes": [11],
        "jewels": [
            {"socket_node_id": 11, "text": LIMITED},
            {"socket_node_id": 22, "text": LIMITED},
        ],
    }
    rows = evaluate_slot(
        spec,
        "Jewel@11",
        [ItemCandidate("limited", "Jewel@11", LIMITED, "unique")],
        compute=lambda s: {"Life": 100},
        stats=("Life",),
    )
    assert rows[0].delta_now == {"Life": 0}
    assert not rows[0].blocked


def test_chain_of_individually_legal_jewels_is_checked_as_a_whole():
    spec = {**BASE, "tree_nodes": [11, 22]}
    members = [
        evaluate_slot(
            spec,
            f"Jewel@{socket}",
            [ItemCandidate(f"limited-{socket}", f"Jewel@{socket}", LIMITED, "unique")],
            compute=lambda s: {"Life": 100},
            stats=("Life",),
        )[0]
        for socket in (11, 22)
    ]
    assert all(not m.blocked for m in members)

    def forbidden(spec):
        pytest.fail("The combined Limited-to violation must not reach the calculator")

    chain = items._measure_chain(
        spec,
        {"Life": 100},
        members,
        ["life"],
        stats=("Life",),
        floors=None,
        run=forbidden,
    )
    assert chain.blocked and chain.legality_violations
    assert chain.delta_chain == {}


def _search(monkeypatch, budget: int, *, suppliers: int = 1):
    scaler = "Rarity: UNIQUE\nScaler\nBase\n6% increased Damage per 100 maximum Life"
    supplier = "Rarity: RARE\nSupplier\nGold Ring\n+80 to maximum Life"

    def pool(slot, root=None):
        text = scaler if slot == "Weapon 2" else supplier
        return [ItemCandidate(slot, slot, text, "unit-fixture")]

    def oracle(spec):
        names = {row["text"].splitlines()[1] for row in spec.get("items", [])}
        value = 100.0
        if "Scaler" in names:
            value = 200.0 if names & {"Supplier", "Probe"} else 90.0
        return {"CombinedDPS": value}

    monkeypatch.setattr(items, "enumerate_slot_uniques", pool)
    return optimize_items(
        {**BASE, "items": []},
        ["Weapon 2", *[f"Ring {n + 1}" for n in range(suppliers)]],
        {"CombinedDPS": 1},
        max_rounds=2,
        max_chain=4,
        max_chain_measures_per_round=budget,
        compute=oracle,
    )


def _readiness(result: Any):
    spec = result.spec
    spec["derived_from"] = {
        "items": stamp(
            spec,
            "items",
            tool="optimize_items",
            search_evidence=result.search_evidence,
        )
    }
    spec["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "items": {
                "scope": {"slots": ["Weapon 2", "Ring 1"]},
                "require_converged": True,
                "allowed_termination_reasons": ["no_positive_candidate"],
            }
        },
    }
    return optimization_readiness(spec, purpose="recommendation")


def test_zero_chain_budget_does_not_claim_convergence_or_recommendation(monkeypatch):
    out = _search(monkeypatch, 0)
    evidence = out.search_evidence
    assert not out.steps and not out.chains
    assert evidence["settings"]["max_chain_measures_per_round"] == 0
    assert evidence["termination"]["reason"] == "chain_measurement_limit"
    assert evidence["termination"]["converged"] is False
    assert evidence["termination"]["chain_measurements"] == 0
    assert evidence["unresolved"][0]["code"] == "chain_measurement_limit"
    assert _readiness(out)["recommendation_ready"] is False


def test_sufficient_chain_budget_measures_package_and_retains_success_path(monkeypatch):
    out = _search(monkeypatch, 1)
    assert len(out.steps) == 2
    assert out.search_evidence["settings"]["max_chain_measures_per_round"] == 1
    assert out.search_evidence["termination"]["chain_measurements"] == 2
    assert out.search_evidence["termination"]["converged"] is True
    assert out.search_evidence["unresolved"] == []
    assert _readiness(out)["recommendation_ready"] is True


def test_positive_but_insufficient_chain_budget_records_remaining_extensions(monkeypatch):
    out = _search(monkeypatch, 1, suppliers=2)
    assert out.search_evidence["termination"]["chain_budget_limited"] is True
    assert out.search_evidence["termination"]["converged"] is False
    assert any(r["unmeasured_extensions"] for r in out.search_evidence["chain_rounds"])
    assert _readiness(out)["recommendation_ready"] is False


def test_zero_budget_without_chain_candidates_does_not_report_a_false_limit(monkeypatch):
    monkeypatch.setattr(items, "enumerate_slot_uniques", lambda *args: [])
    out = optimize_items(
        BASE,
        ["Helmet"],
        {"Life": 1},
        max_chain_measures_per_round=0,
        compute=lambda s: {"Life": 100},
    )
    assert out.search_evidence["termination"]["chain_budget_limited"] is False
    assert out.search_evidence["termination"]["converged"] is True


def test_zero_budget_with_only_illegal_pairs_does_not_report_a_false_limit(monkeypatch):
    text = LIMITED + "\n6% increased Damage per 100 maximum Life\n+80 to maximum Life"
    monkeypatch.setattr(
        items,
        "enumerate_slot_uniques",
        lambda slot, root=None: [ItemCandidate(slot, slot, text, "unique")],
    )

    def oracle(spec):
        copies = sum("One Only" in j["text"] for j in spec.get("jewels", []))
        assert copies <= 1
        probed = any("Probe" in row["text"] for row in spec.get("items", []))
        return {"CombinedDPS": 100 + copies * (10 if probed else -10)}

    out = optimize_items(
        {**BASE, "tree_nodes": [11, 22]},
        ["Jewel"],
        {"CombinedDPS": 1},
        jewel_sockets=(11, 22),
        max_chain_measures_per_round=0,
        compute=oracle,
    )
    assert out.search_evidence["termination"]["converged"] is True
    assert out.search_evidence["unresolved"] == []
    assert out.search_evidence["chain_rounds"][0]["rejected_extensions"]


def test_mcp_passes_explicit_chain_budget_to_engine(monkeypatch):
    from pok.mcp.tools import tree

    result = _search(monkeypatch, 0)
    captured = {}

    def run(*args, **kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(items, "optimize_items", run)
    output = tree.optimize_items(BASE, ["Helmet"], {"Life": 1}, max_chain_measures_per_round=0)
    assert captured["max_chain_measures_per_round"] == 0
    assert output["search_evidence"]["settings"]["max_chain_measures_per_round"] == 0
