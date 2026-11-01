"""Outcome inventory must not turn an earlier partial draft into a final submission."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

MODULE = Path(__file__).parents[2] / "scripts" / "review_product_campaign.py"
SPEC = importlib.util.spec_from_file_location("campaign_inventory", MODULE)
assert SPEC and SPEC.loader
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def put(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def fixture(root: Path, final_state: str = "timed_out") -> Path:
    identity = "01-H1-baseline-1"
    put(
        root / "plan.json",
        {"order": [["H1", "baseline", 1]], "tasks": {"H1": {"phases": [{}, {}]}}},
    )
    put(
        root / "campaign.json",
        {"state": "collected", "trials": [{"id": identity, "state": "collected"}]},
    )
    phases = []
    for phase, state in [(1, "completed"), (2, final_state)]:
        phases.append(
            {
                "phase": phase,
                "execution": {
                    "state": state,
                    "answer_valid": state == "completed",
                    "turn_completed": state == "completed",
                    "cleanup": {"status": "confirmed"},
                },
            }
        )
        put(root / identity / f"phase-{phase}" / "answer.json", {"status": "incomplete"})
        put(
            root / identity / f"phase-{phase}" / "schema.json",
            {"type": "object", "required": ["status"]},
        )
    put(root / identity / "trial.json", {"state": "finished", "phases": phases, "checks": []})
    return root / identity


def test_earlier_valid_draft_never_substitutes_for_final_timeout(tmp_path: Path) -> None:
    fixture(tmp_path)
    result = REPORT.inventory(tmp_path)
    assert result["final_submissions_recorded"] == 0
    assert result["partial_build_substitution"] is False
    assert result["quality_evaluated"] is False


def test_schema_valid_incomplete_answer_is_delivery_not_quality(tmp_path: Path) -> None:
    fixture(tmp_path, "completed")
    result = REPORT.inventory(tmp_path)
    assert result["final_submissions_recorded"] == 1
    assert result["trials"][0]["answer_status"] == "incomplete"
    assert result["quality_evaluated"] is False
    assert len(result["source_sha256"]) == 5


def test_invalid_final_answer_is_explicit_diagnostic(tmp_path: Path) -> None:
    directory = fixture(tmp_path, "completed")
    # A schema-invalid current answer cannot cause selection of phase-1/answer.json.
    put(directory / "phase-2" / "answer.json", {"wrong": True})
    result = REPORT.inventory(tmp_path)
    assert result["final_submissions_recorded"] == 0
    assert result["diagnostics"][0]["error"] == "ValidationError"


def test_active_record_is_not_reported_as_live_or_final(tmp_path: Path) -> None:
    fixture(tmp_path, "completed")
    put(tmp_path / "campaign.json", {"state": "running", "trials": []})
    result = REPORT.inventory(tmp_path)
    assert result["final_submissions_recorded"] == 0
    assert "not liveness" in result["scope"]


def test_unconfirmed_cleanup_never_counts_as_final_delivery(tmp_path: Path) -> None:
    directory = fixture(tmp_path, "completed")
    trial = json.loads((directory / "trial.json").read_text())
    trial["phases"][-1]["execution"]["cleanup"]["status"] = "unknown"
    put(directory / "trial.json", trial)
    assert REPORT.inventory(tmp_path)["final_submissions_recorded"] == 0


def test_process_start_receipt_is_not_proof_of_a_live_process(tmp_path: Path) -> None:
    directory = fixture(tmp_path)
    trial = json.loads((directory / "trial.json").read_text())
    trial["phases"] = trial["phases"][:1]
    put(directory / "trial.json", trial)
    put(directory / "phase-2" / "process.json", {"pid": 123})
    result = REPORT.inventory(tmp_path)
    phase = result["trials"][0]["phases"][1]
    assert phase["recorded_state"] == "started_without_terminal_record"
    assert phase["liveness"] == "not_probed"
    assert result["final_submissions_recorded"] == 0
