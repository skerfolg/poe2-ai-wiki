"""Utility must remain visible even when the caller's score does not value it."""

from __future__ import annotations

from typing import Any

import pytest

from pok.engine import items


def _run(
    monkeypatch: pytest.MonkeyPatch,
    variants: dict[str, dict[str, float]],
    *,
    weights: dict[str, float] | None = None,
    floors: dict[str, float] | None = None,
    base: dict[str, float] | None = None,
    max_rounds: int = 1,
) -> items.ItemOptimizeResult:
    baseline = {
        "IgniteDPS": 100.0,
        "TotalEHP": 1000.0,
        "Life": 500.0,
        "Evasion": 100.0,
        "MovementSpeedMod": 1.3,
        "FireResist": 75.0,
        "FireResistTotal": 75.0,
    }
    if base is not None:
        baseline = base
    candidates = [items.ItemCandidate(name, "Belt", name, "unique-kb") for name in variants]
    monkeypatch.setattr(items, "enumerate_slot_uniques", lambda *_args: candidates)

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        equipped = spec.get("items", [])
        return variants[equipped[0]["text"]] if equipped else baseline

    return items.optimize_items(
        {"items": []},
        ["Belt"],
        weights if weights is not None else {"IgniteDPS": 1.0},
        floors=floors,
        max_rounds=max_rounds,
        compute=compute,
    )


def _stats(**changes: float) -> dict[str, float]:
    return {
        "IgniteDPS": 100.0,
        "TotalEHP": 1000.0,
        "Life": 500.0,
        "Evasion": 100.0,
        "MovementSpeedMod": 1.3,
        "FireResist": 75.0,
        "FireResistTotal": 75.0,
        **changes,
    }


def test_zero_score_utility_survives_without_ehp_gain(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _run(
        monkeypatch,
        {"utility": _stats(MovementSpeedMod=1.6, Evasion=1100.0, FireResistTotal=125.0)},
    )
    assert not result.steps
    assert not result.defensive_only  # Existing EHP-only field keeps its meaning.
    report = result.unscored_candidates[0]
    assert report["label"] == "utility"
    assert report["weighted_score"] == 0
    assert report["utility_gains"] == pytest.approx(
        {"MovementSpeedMod": 0.3, "Evasion": 1000.0, "FireResistTotal": 50.0}
    )
    assert result.search_evidence["termination"]["converged"] is True
    assert result.search_evidence["termination"]["convergence_scope"] == (
        "supplied_weights_and_search_scope"
    )
    assert result.search_evidence["termination"]["unscored_utility_gains_observed"] is True
    assert result.search_evidence["utility_review"] == result.unscored_summary


def test_every_candidate_uses_full_stats_not_only_first_or_last_adopted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run(
        monkeypatch,
        {
            "damage": _stats(IgniteDPS=120.0),
            "speed": _stats(MovementSpeedMod=1.6),
            "resistance": _stats(FireResistTotal=125.0),
        },
    )
    assert result.steps[0].adopted == "damage"
    reports = {row["label"]: row for row in result.unscored_candidates}
    assert set(reports) == {"speed", "resistance"}
    assert reports["resistance"]["utility_gains"] == {"FireResistTotal": 50.0}
    assert result.unscored_summary["last_round_matches_returned_spec"] is False


def test_missing_stats_are_not_zero_and_other_positive_changes_are_not_claimed_as_gains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run(
        monkeypatch,
        {"cost": {"IgniteDPS": 100.0, "ManaCost": 15.0, "Evasion": 1000.0}},
        base={"IgniteDPS": 100.0, "ManaCost": 10.0, "FireResistTotal": 75.0},
    )
    report = result.unscored_candidates[0]
    assert report["utility_gains"] == {}
    assert report["unscored_axis_count"] == 1
    assert report["axes"][0]["axis"] == "ManaCost"
    assert report["axes"][0]["delta"] == 5
    assert not result.search_evidence["termination"]["unscored_utility_gains_observed"]


def test_blocked_utility_is_reported_but_not_counted_as_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run(
        monkeypatch,
        {"fragile": _stats(Life=100.0, MovementSpeedMod=1.6)},
        floors={"Life": 400.0},
    )
    assert result.unscored_candidates[0]["blocked"]
    assert result.unscored_candidates[0]["floor_violations"]
    assert result.unscored_summary["utility_gain_candidate_count"] == 0
    assert not result.steps


def test_zero_weight_is_unscored_and_nonzero_weight_still_selects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    variants = {"evasion": _stats(Evasion=1100.0)}
    unscored = _run(monkeypatch, variants, weights={"IgniteDPS": 1, "Evasion": 0})
    assert unscored.unscored_candidates[0]["utility_gains"] == {"Evasion": 1000.0}
    assert not unscored.steps
    selected = _run(monkeypatch, variants, weights={"Evasion": 1})
    assert selected.steps[0].adopted == "evasion"
    assert not selected.unscored_candidates


def test_candidate_truncation_keeps_all_omitted_identities_and_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    count = items._UNSCORED_CANDIDATE_LIMIT + 3
    variants = {f"utility-{index:02}": _stats(Evasion=200.0 + index) for index in range(count)}
    result = _run(monkeypatch, variants)
    summary = result.unscored_summary
    assert summary["candidate_count"] == count
    assert summary["returned_count"] == items._UNSCORED_CANDIDATE_LIMIT
    assert summary["utility_gain_candidate_count"] == count
    assert summary["truncated"]
    returned = {row["label"] for row in result.unscored_candidates}
    omitted = {row["label"] for row in summary["omitted_candidates"]}
    assert returned.isdisjoint(omitted)
    assert returned | omitted == set(variants)
    assert all(row["utility_gains"] for row in summary["omitted_candidates"])


def test_family_truncation_preserves_utility_and_reports_omitted_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _stats(**{f"Other{index}": 1.0 for index in range(10)})
    variant = {**baseline, **{f"Other{index}": 100.0 for index in range(10)}}
    variant["MovementSpeedMod"] = 1.6
    result = _run(monkeypatch, {"many": variant}, base=baseline)
    report = result.unscored_candidates[0]
    assert report["family_count"] == 11
    assert report["families_truncated"]
    assert len(report["axes"]) == items._UNSCORED_FAMILY_LIMIT
    assert len(report["omitted_families"]) == 3
    assert report["utility_gains"]["MovementSpeedMod"] == pytest.approx(0.3)


def test_latest_round_does_not_present_prior_context_gain_as_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run(
        monkeypatch,
        {"adopted": _stats(IgniteDPS=120.0, Evasion=200.0)},
        max_rounds=2,
    )
    assert len(result.steps) == 1
    assert not result.unscored_candidates
    assert result.unscored_summary["candidate_count"] == 0
    assert result.unscored_summary["last_round_matches_returned_spec"]
    assert not result.search_evidence["termination"]["unscored_utility_gains_observed"]


def test_observed_delta_ignores_nonfinite_or_non_numeric_values() -> None:
    assert items._observed_delta(
        {"finite": 2.0, "inf": float("inf"), "flag": True},
        {"finite": 1.0, "inf": 1.0, "flag": False},
    ) == {"finite": 1.0}


def test_zero_baseline_change_is_json_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    result = _run(
        monkeypatch,
        {"evasion": _stats(Evasion=1000.0)},
        base=_stats(Evasion=0.0),
    )
    report = result.unscored_candidates[0]
    assert report["axes"][0]["relative"] is None
    assert report["axes"][0]["delta"] == 1000.0
    json.dumps(result.unscored_candidates, allow_nan=False)


def test_later_legality_rejection_clears_old_utility_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        items,
        "_jewel_slot_rejection",
        lambda spec, _slot, text: "now illegal" if spec["items"] and text == "utility" else None,
    )
    result = _run(
        monkeypatch,
        {"damage": _stats(IgniteDPS=120.0), "utility": _stats(Evasion=1000.0)},
        max_rounds=2,
    )
    assert result.steps[0].adopted == "damage"
    assert not result.unscored_candidates
    assert result.unscored_summary["utility_gain_candidate_count"] == 0
