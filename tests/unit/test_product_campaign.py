"""Phase exposure and resume decisions without model calls or post-hoc repairs."""

import hashlib
import importlib
import json
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


def add_answer_contract(args, *, instruction="Actual file references are sufficient.", schema=None):
    value = {
        "format": "pok.trial-answer-contract.v1",
        "instruction": instruction,
        "schema": schema
        or {
            "type": "object",
            "properties": {"pob_code": {"type": ["string", "null"]}},
            "required": ["pob_code"],
            "additionalProperties": False,
        },
    }
    name = "shared/answer-contract.json"
    path = args["input_root"] / name
    path.write_text(json.dumps(value), encoding="utf-8")
    args["input_hashes"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    args["answer_contract_file"] = name
    return path, value


def test_frozen_file_delivery_contract_is_identical_across_both_phases(case):
    module, args = case
    _path, contract = add_answer_contract(args)
    schemas = []
    identity = str(uuid4())

    def run(*a, **k):
        schemas.append(k["schema"])
        assert contract["instruction"] in k["prompt"]
        return {"state": "completed", "cleanup": {"status": "confirmed"}, "session_id": identity}

    result = module.run_trial(**args, verify=lambda: {"status": "verified"}, phase_executor=run)
    assert schemas == [contract["schema"], contract["schema"]]
    assert result["answer_contract"]["sha256"] == args["input_hashes"][args["answer_contract_file"]]
    assert not result["build_quality_verified"]


def test_changed_answer_contract_never_starts_a_participant(case):
    module, args = case
    path, _ = add_answer_contract(args)
    path.write_text("{}", encoding="utf-8")
    calls = []
    with pytest.raises(module.CampaignIntegrityError, match="contract"):
        module.run_trial(
            **args,
            verify=lambda: {"status": "verified"},
            phase_executor=lambda *a, **k: calls.append(True),
        )
    assert not calls


def test_answer_contract_changed_after_first_phase_stops_before_followup(case):
    module, args = case
    path, _ = add_answer_contract(args)
    calls = []

    def run(*a, **k):
        calls.append(True)
        path.write_text("{}", encoding="utf-8")
        return {
            "state": "completed",
            "cleanup": {"status": "confirmed"},
            "session_id": str(uuid4()),
        }

    with pytest.raises(module.CampaignIntegrityError, match="contract"):
        module.run_trial(**args, verify=lambda: {"status": "verified"}, phase_executor=run)
    assert len(calls) == 1
    assert not (args["trial_root"] / "server/artifacts/inputs/phase2/item.txt").exists()


def test_invalid_frozen_schema_never_starts_a_participant(case):
    module, args = case
    add_answer_contract(args, schema={"type": 17})
    with pytest.raises(module.CampaignIntegrityError, match="contract"):
        module.run_trial(
            **args,
            verify=lambda: {"status": "verified"},
            phase_executor=lambda *a, **k: pytest.fail("must not run"),
        )


def test_answer_contract_path_cannot_escape_frozen_inputs(case):
    module, args = case
    args["answer_contract_file"] = "../answer.json"
    with pytest.raises((module.CampaignIntegrityError, ValueError)):
        module.run_trial(
            **args,
            verify=lambda: {"status": "verified"},
            phase_executor=lambda *a, **k: pytest.fail("must not run"),
        )


def test_campaign_forwards_one_frozen_answer_contract_to_every_trial(case):
    module, args = case
    add_answer_contract(args)
    seen = []
    plan = {
        "model": args["model"],
        "effort": args["effort"],
        "tasks": {"H1": args["task"]},
        "order": [["H1", "baseline", 1], ["H1", "improved", 1]],
        "answer_contract": args["answer_contract_file"],
    }

    def run(root, **kwargs):
        seen.append(kwargs["answer_contract_file"])
        return {"state": "finished", "build_quality_verified": False}

    result = module.run_campaign(
        args["trial_root"],
        plan=plan,
        input_root=args["input_root"],
        input_hashes=args["input_hashes"],
        products={
            v: {"root": args["product_root"], "files": args["product_hashes"]}
            for v in ["baseline", "improved"]
        },
        codex_exe=args["codex_exe"],
        luajit_exe=args["luajit_exe"],
        verify=lambda: {"status": "verified"},
        trial_runner=run,
        control_root=args["control_root"],
    )
    assert seen == [plan["answer_contract"], plan["answer_contract"]]
    assert result["answer_contract"]["sha256"] == args["input_hashes"][plan["answer_contract"]]
    assert not result["quality_evaluated"]


@pytest.mark.parametrize("answer_valid", [True, False])
def test_file_delivery_audit_runs_only_for_valid_new_contract_answer(case, answer_valid):
    module, args = case
    add_answer_contract(args)
    identity = str(uuid4())
    artifacts = args["trial_root"] / "server/artifacts"

    def run(command, output, **kwargs):
        output.mkdir()
        (artifacts / "final.xml").write_text("<PathOfBuilding/>", encoding="utf-8")
        answer = {
            "status": "complete",
            "pob_code": None,
            "artifacts": [{"format": "pob_xml", "reference": "final.xml"}],
        }
        (output / "answer.json").write_text(
            json.dumps(answer) if answer_valid else "invalid JSON", encoding="utf-8"
        )
        return {
            "state": "completed",
            "answer_valid": answer_valid,
            "cleanup": {"status": "confirmed"},
            "session_id": identity,
        }

    result = module.run_trial(**args, verify=lambda: {"status": "verified"}, phase_executor=run)
    assert result["state"] == "finished"
    for phase in [1, 2]:
        report = args["trial_root"] / f"phase-{phase}/delivery-audit.json"
        assert report.exists() == answer_valid
        if answer_valid:
            audit = json.loads(report.read_bytes())
            assert audit["transport_verified"]
            assert not audit["build_quality_verified"]
