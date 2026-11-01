"""Phase exposure and resume decisions without model calls or post-hoc repairs."""

import hashlib
import importlib
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def case(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills/build-generation")
    )
    module = importlib.import_module("product_campaign")
    monkeypatch.setattr(module, "CONTROL_ROOT", tmp_path)
    product = tmp_path / "artifacts/product"
    (product / "src/pok").mkdir(parents=True)
    (product / "knowledge").mkdir()
    (product / "pyproject.toml").write_text("", encoding="utf-8")
    references = {}
    for name in module.REFERENCES:
        path = product / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"Product reference")
        references[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    source = tmp_path / "artifacts/inputs"
    inputs = {
        "prompts/one.txt": b"first scenario",
        "prompts/two.txt": b"fixed followup",
        "shared/rules.json": b"{}",
        "phase2/item.txt": b"late item",
    }
    hashes = {}
    for name, raw in inputs.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    binary = tmp_path / "codex.exe"
    binary.write_bytes(b"construction only")
    task = {
        "total_budget_s": 5400,
        "phases": [
            {
                "budget_s": 2400,
                "prompt": "prompts/one.txt",
                "participant_files": ["shared/rules.json"],
            },
            {
                "budget_s": 3000,
                "prompt": "prompts/two.txt",
                "participant_files": ["phase2/item.txt"],
            },
        ],
    }
    return module, dict(
        trial_root=tmp_path / "artifacts/trial",
        task=task,
        input_root=source,
        input_hashes=hashes,
        product_root=product,
        product_hashes=references,
        model="gpt-6-astra",
        effort="ultra",
        codex_exe=str(binary),
        luajit_exe=str(binary),
        control_root=tmp_path,
        audit=False,
    )


def test_partial_first_phase_resumes_own_context_and_exposes_late_input_only_afterward(case):
    module, args = case
    identity = str(uuid4())
    calls, checks = [], []
    artifact = args["trial_root"] / "server/artifacts"

    def run(command, output, **kwargs):
        calls.append((command, kwargs["timeout_s"]))
        output.mkdir()
        if len(calls) == 1:
            assert not (artifact / "inputs/phase2/item.txt").exists()
            assert "late item" not in kwargs["prompt"] and "fixed followup" not in kwargs["prompt"]
            (artifact / "work").mkdir()
            (artifact / "work/partial.json").write_bytes(b"own partial draft")
            return {
                "state": "timed_out",
                "cleanup": {"status": "confirmed"},
                "session_id": identity,
            }
        assert command[-2:] == [identity, "-"]
        assert (artifact / "inputs/phase2/item.txt").read_bytes() == b"late item"
        assert (artifact / "work/partial.json").read_bytes() == b"own partial draft"
        assert "fixed followup" in kwargs["prompt"]
        return {"state": "completed", "cleanup": {"status": "confirmed"}, "session_id": identity}

    def verify():
        checks.append(True)
        return {"status": "verified"}

    result = module.run_trial(**args, verify=verify, phase_executor=run)
    assert result["state"] == "finished" and len(calls) == 2 and len(checks) == 3
    assert calls[0][1] <= 2400 and calls[1][1] <= 3000
    assert not result["build_quality_verified"]


def test_source_failure_after_first_phase_stops_before_exposing_followup(case):
    module, args = case
    checks, calls = [], []

    def verify():
        checks.append(True)
        return {"status": "verified" if len(checks) == 1 else "unverified"}

    def run(*a, **k):
        calls.append(True)
        return {
            "state": "completed",
            "cleanup": {"status": "confirmed"},
            "session_id": str(uuid4()),
        }

    with pytest.raises(module.CampaignIntegrityError):
        module.run_trial(**args, verify=verify, phase_executor=run)
    assert len(calls) == 1
    assert not (args["trial_root"] / "server/artifacts/inputs/phase2/item.txt").exists()


def test_unknown_termination_never_starts_next_phase(case):
    module, args = case
    calls = []

    def run(*a, **k):
        calls.append(True)
        return {
            "state": "termination_unconfirmed",
            "cleanup": {"status": "unconfirmed"},
            "session_id": str(uuid4()),
        }

    with pytest.raises(module.CampaignIntegrityError, match="termination"):
        module.run_trial(**args, verify=lambda: {"status": "verified"}, phase_executor=run)
    assert len(calls) == 1


def test_missing_session_is_not_replaced_with_fresh_trial(case):
    module, args = case
    calls = []

    def run(*a, **k):
        calls.append(True)
        return {"state": "failed", "cleanup": {"status": "confirmed"}, "session_id": None}

    result = module.run_trial(**args, verify=lambda: {"status": "verified"}, phase_executor=run)
    assert len(calls) == 1 and result["phases"][1]["reason"] == "no_exact_prior_session"


def test_input_batch_is_not_partially_exposed_when_a_file_changed(case, tmp_path):
    module, args = case
    (args["input_root"] / "phase2/item.txt").write_bytes(b"changed")
    destination = tmp_path / "exposure"
    with pytest.raises(module.CampaignIntegrityError):
        module.copy_verified(
            args["input_root"],
            destination,
            ["shared/rules.json", "phase2/item.txt"],
            args["input_hashes"],
        )
    assert not destination.exists()


def test_campaign_preserves_frozen_order_without_retrying_incomplete_delivery(case):
    module, args = case
    order = [
        ["H1", "baseline", 1],
        ["H1", "improved", 1],
        ["H2", "improved", 1],
        ["H2", "baseline", 1],
        ["H1", "improved", 2],
        ["H1", "baseline", 2],
        ["H2", "baseline", 2],
        ["H2", "improved", 2],
    ]
    plan = {
        "model": args["model"],
        "effort": args["effort"],
        "tasks": {"H1": args["task"], "H2": args["task"]},
        "order": order,
    }
    seen = []

    def runner(root, **kwargs):
        seen.append(root.name)
        return {"state": "finished", "delivery": "incomplete", "build_quality_verified": False}

    products = {
        version: {"root": args["product_root"], "files": args["product_hashes"]}
        for version in ("baseline", "improved")
    }
    state = module.run_campaign(
        args["trial_root"],
        plan=plan,
        input_root=args["input_root"],
        input_hashes=args["input_hashes"],
        products=products,
        codex_exe=args["codex_exe"],
        luajit_exe=args["luajit_exe"],
        verify=lambda: {"status": "verified"},
        trial_runner=runner,
    )
    assert seen == [
        f"{index:02d}-{task}-{version}-{rep}" for index, (task, version, rep) in enumerate(order, 1)
    ]
    assert state["state"] == "collected" and not state["quality_evaluated"]
    with pytest.raises(FileExistsError):
        module.run_campaign(
            args["trial_root"],
            plan=plan,
            input_root=args["input_root"],
            input_hashes=args["input_hashes"],
            products=products,
            codex_exe=args["codex_exe"],
            luajit_exe=args["luajit_exe"],
            verify=lambda: {"status": "verified"},
            trial_runner=runner,
        )
    assert len(seen) == 8


def test_campaign_integrity_failure_stops_the_remaining_order(case):
    module, args = case
    plan = {
        "model": args["model"],
        "effort": args["effort"],
        "tasks": {"H1": args["task"]},
        "order": [["H1", "baseline", 1], ["H1", "baseline", 2]],
    }
    seen = []

    def runner(*a, **kwargs):
        seen.append(True)
        raise module.CampaignIntegrityError("changed source")

    with pytest.raises(module.CampaignIntegrityError):
        module.run_campaign(
            args["trial_root"],
            plan=plan,
            input_root=args["input_root"],
            input_hashes=args["input_hashes"],
            products={"baseline": {"root": args["product_root"], "files": args["product_hashes"]}},
            codex_exe=args["codex_exe"],
            luajit_exe=args["luajit_exe"],
            verify=lambda: {"status": "verified"},
            trial_runner=runner,
        )
    assert len(seen) == 1
