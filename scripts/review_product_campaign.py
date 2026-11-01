"""Inventory frozen campaign outcomes without selecting partial builds or scoring quality."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from jsonschema import validate


def _read(path: Path, sources: dict[str, str], root: Path) -> Any:
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("Campaign file redirects outside its root")
    raw = path.read_bytes()
    sources[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw)


def inventory(root: Path) -> dict[str, Any]:
    sources: dict[str, str] = {}
    plan = _read(root / "plan.json", sources, root)
    campaign = _read(root / "campaign.json", sources, root)
    diagnostics: list[dict[str, Any]] = []
    identities = [item["id"] for item in campaign["trials"]]
    if len(set(identities)) != len(identities):
        diagnostics.append({"error": "DuplicateTrial"})
    declared = {item["id"]: item for item in campaign["trials"]}
    results: list[dict[str, Any]] = []
    for index, (task, version, repetition) in enumerate(plan["order"], 1):
        identity = f"{index:02d}-{task}-{version}-{repetition}"
        if Path(identity).name != identity or "\\" in identity or ":" in identity:
            raise ValueError("Invalid frozen trial identity")
        item: dict[str, Any] = {"id": identity, "recorded_state": "not_recorded", "phases": []}
        results.append(item)
        directory = root / identity
        if not (directory / "trial.json").exists():
            continue
        try:
            trial = _read(directory / "trial.json", sources, root)
            item["recorded_state"] = trial["state"]
            expected_phases = len(plan["tasks"][task]["phases"])
            phase_records = {phase["phase"]: phase for phase in trial["phases"]}
            if len(phase_records) != len(trial["phases"]) or set(phase_records) - set(
                range(1, expected_phases + 1)
            ):
                raise ValueError("Duplicate or unexpected phase record")
            for number in range(1, expected_phases + 1):
                phase = phase_records.get(number, {})
                execution = phase.get("execution", {})
                summary = {
                    "phase": number,
                    "recorded_state": execution.get("state", phase.get("state", "not_recorded")),
                    "cleanup": execution.get("cleanup", {}).get("status", "not_recorded"),
                    "answer_valid_recorded": execution.get("answer_valid", False),
                    "turn_completed_recorded": execution.get("turn_completed", False),
                    "wall_s_including_cleanup": execution.get("elapsed_s_including_cleanup"),
                }
                process_path = directory / f"phase-{number}" / "process.json"
                if not execution and process_path.exists():
                    process = _read(process_path, sources, root)
                    summary.update(
                        recorded_state="started_without_terminal_record",
                        start_receipt_present=True,
                        recorded_pid=process.get("pid"),
                        liveness="not_probed",
                    )
                audit_path = directory / f"phase-{number}" / "native-audit.json"
                if audit_path.exists():
                    audit = _read(audit_path, sources, root)
                    summary["tool_failures_recorded"] = len(audit.get("mcp_call_failures", []))
                    summary["usage_recorded"] = audit.get("usage_raw", [])
                item["phases"].append(summary)
            final = phase_records.get(expected_phases, {}).get("execution", {})
            # A valid earlier draft never substitutes for the task's last phase.
            eligible = (
                trial["state"] == "finished"
                and declared.get(identity, {}).get("state") == "collected"
                and final.get("state") == "completed"
                and final.get("answer_valid") is True
                and final.get("turn_completed") is True
                and final.get("cleanup", {}).get("status") == "confirmed"
            )
            item["final_submission_recorded"] = False
            if eligible:
                phase_root = directory / f"phase-{expected_phases}"
                answer = _read(phase_root / "answer.json", sources, root)
                validate(answer, _read(phase_root / "schema.json", sources, root))
                item.update(
                    final_submission_recorded=True,
                    answer_status=answer["status"],
                    final_answer_path=(phase_root / "answer.json").relative_to(root).as_posix(),
                )
            item["integrity_check_records"] = [
                {"stage": check["stage"], "status": check["result"].get("status")}
                for check in trial.get("checks", [])
            ]
        except Exception as exc:
            item["final_submission_recorded"] = False
            diagnostics.append(
                {"trial": identity, "error": type(exc).__name__, "reason": str(exc)[:600]}
            )
    expected_ids = {item["id"] for item in results}
    if set(declared) - expected_ids:
        diagnostics.append(
            {"error": "UnexpectedTrial", "ids": sorted(set(declared) - expected_ids)}
        )
    return {
        "format": "pok.campaign-outcome-inventory.v1",
        "scope": "record inventory, not liveness, input revalidation, build validity or quality",
        "recorded_campaign_state": campaign["state"],
        "expected_trials": len(results),
        "recorded_trial_states": dict(Counter(item["recorded_state"] for item in results)),
        "final_submissions_recorded": sum(
            item.get("final_submission_recorded", False) for item in results
        ),
        "quality_evaluated": False,
        "partial_build_substitution": False,
        "trials": results,
        "diagnostics": diagnostics,
        "source_sha256": sources,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign", type=Path)
    args = parser.parse_args()
    print(json.dumps(inventory(args.campaign), ensure_ascii=False, indent=2))
