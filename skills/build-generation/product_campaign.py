"""Fixed-budget trial orchestration; no build decisions or automatic retries."""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

from jsonschema import Draft202012Validator, SchemaError
from product_delivery import audit_submission
from product_integrity import relative_name
from product_run import build_product_command, execute_phase
from product_server import CONTROL_ROOT
from redesign_run import ANSWER_SCHEMA, audit_native_events


class CampaignIntegrityError(RuntimeError):
    """Stop rather than score a run whose inputs or execution ownership changed."""


REFERENCES = (
    "skills/build-generation/AGENTS.md",
    "skills/build-assembly/AGENTS.md",
    "skills/AGENTS.md",
    "docs/BUILD_DESIGN.md",
)


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def copy_verified(
    source: Path, destination: Path, names: list[str], checksums: Mapping[str, str]
) -> list[str]:
    """Validate the full batch before exposing any phase-specific input."""
    pending = []
    base, target = source.resolve(), destination.resolve()
    for name in names:
        relative = relative_name(name)
        origin = base.joinpath(*relative.parts)
        output = target.joinpath(*relative.parts)
        if not origin.resolve().is_relative_to(base) or not output.resolve().is_relative_to(target):
            raise CampaignIntegrityError("Phase input redirects outside its declared namespace")
        raw = origin.read_bytes()
        if hashlib.sha256(raw).hexdigest() != checksums.get(name):
            raise CampaignIntegrityError(f"Frozen input changed: {name}")
        if output.exists() and output.read_bytes() != raw:
            raise CampaignIntegrityError(f"Participant input already has different bytes: {name}")
        pending.append((output, raw))
    for output, raw in pending:
        output.parent.mkdir(parents=True, exist_ok=True)
        if not output.exists():
            with output.open("xb") as stream:
                stream.write(raw)
    return names


def read_answer_contract(
    name: str | None, source: Path, checksums: Mapping[str, str]
) -> dict[str, Any]:
    """Load one frozen, shared output contract without altering legacy trials."""
    if name is None:
        return {"schema": ANSWER_SCHEMA, "instruction": ""}
    if not isinstance(name, str):
        raise CampaignIntegrityError("Answer contract path must be a string")
    base = source.resolve()
    path = base.joinpath(*relative_name(name).parts).resolve()
    if not path.is_relative_to(base):
        raise CampaignIntegrityError("Answer contract redirects outside frozen inputs")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise CampaignIntegrityError("Answer contract is unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != checksums.get(name):
        raise CampaignIntegrityError("Answer contract changed or was not frozen")
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise CampaignIntegrityError("Answer contract is not valid JSON") from exc
    if (
        not isinstance(value, dict)
        or set(value) - {"format", "schema", "instruction"}
        or value.get("format") != "pok.trial-answer-contract.v1"
        or not isinstance(value.get("schema"), dict)
        or not isinstance(value.get("instruction", ""), str)
    ):
        raise CampaignIntegrityError("Invalid answer contract fields")
    try:
        Draft202012Validator.check_schema(value["schema"])
    except SchemaError as exc:
        raise CampaignIntegrityError("Invalid answer contract schema") from exc
    return {"schema": value["schema"], "instruction": value.get("instruction", "")}


def trial_prompt(
    scenario: str, files: list[str], phase: int, *, answer_instruction: str = ""
) -> str:
    prelude = (
        "PoK 제품의 실제 생성/조립 지침에 따라 수행하라. pok MCP만 사용하고 웹·거래·셸·"
        "추가 모델·다른 시험의 답안을 사용하지 마라. 필요한 작업은 자율적으로 진행하되 "
        "인게임 관측이나 실제 사용자 선택이 필요한 미해결을 허위 확정하지 마라.\n"
        "지침은 experiment_file의 reference/skills/build-generation/AGENTS.md, "
        "reference/skills/build-assembly/AGENTS.md, reference/skills/AGENTS.md, "
        "reference/docs/BUILD_DESIGN.md에서 읽을 수 있다. 지원되지 않는 새 API/양식을 "
        "흉내 내지 말고 현재 제품 계약을 확인하라. 일반 작업 메모/스펙 초안은 work/에 저장하고 "
        "기계 산출물은 제품 도구로 생성하라. 최종 JSON은 실제 build_id/PoB와 한글 설계·"
        "이득/대가·남은 일을 담고, 형식·호출 횟수로 품질을 주장하지 마라.\n"
        "이번 단계에 공개한 입력: " + ", ".join("inputs/" + name for name in files) + "\n"
    )
    if phase == 2:
        prelude += (
            "이전 대화와 이 시험 자체의 산출물에서 이어가라. "
            "운영자가 중간 최선안을 골라 제공하지 않는다.\n"
        )
    if answer_instruction:
        prelude += "\n모든 비교군의 공통 제출 계약:\n" + answer_instruction + "\n"
    return prelude + "\n사용자 시나리오 원문:\n" + scenario


def run_trial(
    trial_root: Path,
    *,
    task: Mapping[str, Any],
    input_root: Path,
    input_hashes: Mapping[str, str],
    product_root: Path,
    product_hashes: Mapping[str, str],
    model: str,
    effort: str,
    codex_exe: str,
    luajit_exe: str,
    verify: Callable[[], dict[str, Any]],
    control_root: Path = CONTROL_ROOT,
    phase_executor: Callable[..., dict[str, Any]] = execute_phase,
    audit: bool = True,
    answer_contract_file: str | None = None,
) -> dict[str, Any]:
    """H1 retains partial context, never transfers unused phase-1 model budget.

    Initial input verification precedes participant startup. Between-phase checks
    consume the trial's total budget. Final verification follows task termination
    and is reported separately, before another trial may start.
    """
    controller_started = time.monotonic()
    root = trial_root.resolve()
    if root == control_root.resolve() / "artifacts" or not root.is_relative_to(
        control_root.resolve() / "artifacts"
    ):
        raise ValueError("Trial must remain in controlled artifacts")
    root.mkdir(parents=True, exist_ok=False)
    result: dict[str, Any] = {
        "format": "pok.product-trial.v1",
        "state": "preflight",
        "phases": [],
        "checks": [],
        "build_quality_verified": False,
    }

    def save() -> None:
        write_json(root / "trial.json", result)

    def check(label: str) -> None:
        checked = verify()
        read_answer_contract(answer_contract_file, input_root, input_hashes)
        if answer_contract_file is not None:
            result["answer_contract"] = {
                "path": answer_contract_file,
                "sha256": input_hashes[answer_contract_file],
            }
        result["checks"].append({"stage": label, "result": checked})
        save()
        if checked.get("status") != "verified":
            raise CampaignIntegrityError("Frozen inputs/source did not verify")

    save()
    try:
        check("before_participant_start")
        result["preflight_elapsed_s"] = time.monotonic() - controller_started
        started = time.monotonic()
        total_deadline = started + float(task["total_budget_s"])
        result["state"] = "running"
        namespace = root / "server/artifacts"
        copy_verified(product_root, namespace / "reference", list(REFERENCES), product_hashes)
        context = None
        terminal_at = started
        for number, phase in enumerate(task["phases"], 1):
            if number > 1 and context is None:
                result["phases"].append(
                    {"phase": number, "state": "not_started", "reason": "no_exact_prior_session"}
                )
                break
            contract = read_answer_contract(answer_contract_file, input_root, input_hashes)
            phase_started = started if number == 1 else time.monotonic()
            phase_deadline = min(total_deadline, phase_started + float(phase["budget_s"]))
            files = list(phase["participant_files"])
            copy_verified(input_root, namespace / "inputs", files, input_hashes)
            prompt_name = phase["prompt"]
            relative_name(prompt_name)
            prompt_path = (input_root / prompt_name).resolve()
            if not prompt_path.is_relative_to(input_root.resolve()):
                raise CampaignIntegrityError("Scenario prompt redirects outside frozen inputs")
            raw = prompt_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != input_hashes.get(prompt_name):
                raise CampaignIntegrityError("Scenario prompt changed")
            write_json(
                root / f"phase-{number}-scenario-source.json",
                {"path": prompt_name, "sha256": input_hashes[prompt_name]},
            )
            command = build_product_command(
                root,
                phase=number,
                product_root=product_root,
                model=model,
                reasoning_effort=effort,
                codex_exe=codex_exe,
                luajit_exe=luajit_exe,
                session_id=context,
                control_root=control_root,
            )
            remaining = phase_deadline - time.monotonic()
            if remaining <= 0:
                terminal_at = time.monotonic()
                result["phases"].append(
                    {"phase": number, "state": "not_started", "reason": "budget_exhausted"}
                )
                break
            output = root / f"phase-{number}"
            execution = phase_executor(
                command,
                output,
                prompt=trial_prompt(
                    raw.decode("utf-8"),
                    files,
                    number,
                    answer_instruction=contract["instruction"],
                ),
                schema=contract["schema"],
                cwd=root / "workspace",
                timeout_s=remaining,
            )
            terminal_at = time.monotonic()
            answer_path = output / "answer.json"
            if (
                answer_contract_file is not None
                and execution.get("answer_valid")
                and answer_path.is_file()
            ):
                submitted = json.loads(answer_path.read_bytes())
                if isinstance(submitted, dict) and isinstance(submitted.get("artifacts"), list):
                    write_json(
                        output / "delivery-audit.json", audit_submission(submitted, namespace)
                    )
            result["phases"].append(
                {"phase": number, "execution": execution, "exposed_inputs": files}
            )
            save()
            if execution.get("cleanup", {}).get("status") != "confirmed":
                raise CampaignIntegrityError("Owned process termination is unconfirmed")
            if audit:
                audit_phase(root, output)
            context = execution.get("session_id")
            if number > 1 and context != result["phases"][0]["execution"].get("session_id"):
                raise CampaignIntegrityError("Resumed execution changed session identity")
            check(f"after_phase_{number}")
        result["participant_elapsed_s"] = terminal_at - started
        result["total_controller_elapsed_s"] = time.monotonic() - controller_started
        result["state"] = "finished"
        save()
        return result
    except BaseException as exc:
        result.update(state="stopped", error={"type": type(exc).__name__, "message": str(exc)})
        save()
        raise


def audit_phase(trial_root: Path, output: Path) -> None:
    from product_run import complete_events

    policies = [
        json.loads(path.read_bytes())
        for path in (trial_root / "server").glob("server-policy-*.json")
    ]
    if policies and any(p["tools"] != policies[0]["tools"] for p in policies):
        raise CampaignIntegrityError("Product tool surface changed")
    diagnostics: list[dict[str, Any]] = []
    rows = list(complete_events(output / "events.jsonl", diagnostics))
    report = audit_native_events(rows, set(policies[0]["tools"]) if policies else set())
    report["product_surface_observed"] = bool(policies)
    report["event_diagnostics"] = diagnostics
    write_json(output / "native-audit.json", report)
    if report["protocol_violations"]:
        raise CampaignIntegrityError("Trial used a forbidden native execution surface")


def run_campaign(
    output: Path,
    *,
    plan: Mapping[str, Any],
    input_root: Path,
    input_hashes: Mapping[str, str],
    products: Mapping[str, Mapping[str, Any]],
    codex_exe: str,
    luajit_exe: str,
    verify: Callable[[], dict[str, Any]],
    trial_runner: Callable[..., dict[str, Any]] = run_trial,
    control_root: Path | None = None,
) -> dict[str, Any]:
    """Run the frozen order once; retain failed/incomplete delivery as outcomes."""
    destination = output.resolve()
    control = (control_root or CONTROL_ROOT).resolve()
    if destination == control / "artifacts" or not destination.is_relative_to(
        control / "artifacts"
    ):
        raise ValueError("Campaign output must remain in private controlled artifacts")
    destination.mkdir(parents=True, exist_ok=False)
    state: dict[str, Any] = {
        "format": "pok.product-campaign.v1",
        "state": "running",
        "trials": [],
        "quality_evaluated": False,
    }
    write_json(destination / "plan.json", dict(plan))
    write_json(destination / "campaign.json", state)
    try:
        extra: dict[str, Any] = {}
        contract_file = plan.get("answer_contract")
        if contract_file is not None:
            read_answer_contract(contract_file, input_root, input_hashes)
            extra["answer_contract_file"] = contract_file
            state["answer_contract"] = {
                "path": contract_file,
                "sha256": input_hashes[contract_file],
            }
        for index, (task_name, version, repetition) in enumerate(plan["order"], 1):
            product = products[version]
            identity = f"{index:02d}-{task_name}-{version}-{repetition}"
            item = {
                "id": identity,
                "task": task_name,
                "version": version,
                "repetition": repetition,
                "state": "running",
            }
            state["trials"].append(item)
            write_json(destination / "campaign.json", state)
            result = trial_runner(
                destination / identity,
                task=plan["tasks"][task_name],
                input_root=input_root,
                input_hashes=input_hashes,
                product_root=Path(product["root"]),
                product_hashes=product["files"],
                model=plan["model"],
                effort=plan["effort"],
                codex_exe=codex_exe,
                luajit_exe=luajit_exe,
                verify=verify,
                control_root=control,
                **extra,
            )
            item.update(state="collected", result=result)
            write_json(destination / "campaign.json", state)
        state["state"] = "collected"
        write_json(destination / "campaign.json", state)
        return state
    except BaseException as exc:
        state.update(state="stopped", error={"type": type(exc).__name__, "message": str(exc)})
        write_json(destination / "campaign.json", state)
        raise
