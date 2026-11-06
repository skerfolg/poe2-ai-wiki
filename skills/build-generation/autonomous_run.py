"""Persisted 1..5 skill orchestration with scoped human gates and real product tools.

No model starts at import time. State stores execution refs, not build decisions.
The existing immutable design record is the only source of design content.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from autonomous_contract import ANSWER_SCHEMA, check_stage, claim_fingerprint, digest
from product_run import build_product_command, complete_events, execute_phase
from product_server import CONTROL_ROOT
from source_policy import POK_PRIMARY, WEB_REFERENCE


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}-{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def seed_user_request(saved: dict[str, Any], brief: str) -> dict[str, Any]:
    """Preserve the verbatim request, without guessing agent-selected requirements."""
    from pok.engine.design_service import update_design

    return update_design(
        saved["record_ref"],
        saved["record_ref"]["revision"],
        [
            {
                "op": "upsert_decision",
                "value": {
                    "id": "user.request",
                    "title": "사용자 원문 요구",
                    "role": "user_fixed",
                    "domains": ["utility"],
                    "condition": {
                        "statement": brief,
                        "scope": {"description": "사용자 원문 요구의 범위", "decision_ids": []},
                    },
                    "adoption": "adopted",
                    "belief": "user_reported",
                    "confidence": "high",
                    "providers": [
                        {
                            "id": "user.request.source",
                            "kind": "other",
                            "label": "호스트가 받은 사용자 요구 원문",
                        }
                    ],
                    "depends_on": [],
                    "alternatives": [],
                    "evidence_ids": [],
                    "costs": [],
                    "rationale": "사용자 선호의 출처이며 게임 메커니즘의 성립 근거가 아니다.",
                    "limitations": ["에이전트가 고른 구현은 이 고정 조건에 포함되지 않는다."],
                    "review_triggers": ["실제 사용자 요구 변경"],
                },
            }
        ],
    )


def install_paths(run: Path) -> Path:
    # Same artifact/cache namespace as the existing product trial adapter.
    from pok.common import paths

    artifacts = run / "server/artifacts"
    cache = run / "server/var"
    artifacts.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    paths.artifacts_dir = lambda root=None: artifacts
    paths.var_dir = lambda root=None: cache
    return artifacts


def anoint_discovery_context(stage: int, source_policy: str) -> dict[str, Any]:
    """Provide off-tree anoint candidates as facts, without ranking them."""
    if stage < 3 or source_policy != POK_PRIMARY:
        return {}
    from pok.index.search import search

    return {
        "anoint_only_catalogue": [
            {"entity_id": hit.id, "name_ko": hit.name_ko, "name_en": hit.name_en,
             "kind": hit.passive_kind, "acquisition": hit.acquisition}
            for hit in search(type_="Passive", acquisition="anoint-only", limit=10000)
        ],
        "anoint_catalogue_scope": "Acquisition facts, not recommendations. Inspect effects and "
            "payload restrictions; compare against normal anoints with the final tree. "
            "Anoint-only excludes normal pathing, not grants from items such as Megalomaniac.",
    }


def build_command(
    run: Path,
    turn: Path,
    *,
    context: Path,
    session_id: str | None,
    model: str,
    effort: str,
    codex_exe: str,
    luajit_exe: str | None,
    source_policy: str = WEB_REFERENCE,
) -> list[str]:
    if source_policy not in {WEB_REFERENCE, POK_PRIMARY}:
        raise ValueError("Unknown source policy")
    phase = 2 if session_id else 1
    command = build_product_command(
        run,
        phase=phase,
        product_root=CONTROL_ROOT,
        model=model,
        reasoning_effort=effort,
        codex_exe=codex_exe,
        luajit_exe=luajit_exe,
        session_id=session_id,
    )
    for index, value in enumerate(command):
        if value == 'web_search="disabled"' and source_policy != POK_PRIMARY:
            command[index] = 'web_search="live"'
        elif value.startswith("mcp_servers.pok="):
            value = value.replace("product_server.py", "autonomous_server.py")
            # Append explicit context inside the existing TOML server args array.
            import tomllib

            server = tomllib.loads(value)["mcp_servers"]["pok"]
            old = json.dumps(server["args"])
            new = json.dumps([*server["args"], "--context", str(context)])
            command[index] = value.replace(old, new, 1)
        elif value == str(run / f"phase-{phase}/schema.json"):
            command[index] = str(turn / "schema.json")
        elif value == str(run / f"phase-{phase}/answer.json"):
            command[index] = str(turn / "answer.json")
    return command


def observed(run: Path) -> tuple[set[str], bool, list[str]]:
    tools: set[str] = set()
    web = False
    violations: list[str] = []
    state_path = run / "workflow.json"
    strict = (
        state_path.exists()
        and json.loads(state_path.read_text(encoding="utf-8")).get("source_policy") == POK_PRIMARY
    )
    ledger_path = run / "source-ledger.json"
    receipts = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    for path in sorted(run.glob("turn-*/events.jsonl")):
        for event in complete_events(path):
            if event.get("type") != "item.completed":
                continue
            item = event.get("item", {})
            kind = item.get("type")
            if kind == "mcp_tool_call":
                if item.get("server") != "pok":
                    violations.append(f"Unexpected MCP server: {item.get('server')}")
                elif item.get("status") == "completed" and not item.get("error"):
                    tools.add(item.get("tool", ""))
                    if item.get("tool") == "workflow_primary_source" and receipts:
                        if not {"search_kb", "get_entry", "search_insights"} <= tools:
                            violations.append("기재 웹 검증 전에 PoK 조사가 필요하다")
                        web = True
            elif kind in {"web_search", "web_search_call"}:
                if strict:
                    violations.append("독립 설계 모드에서 일반 웹검색이 노출됐다")
                if not {"search_kb", "get_entry", "search_insights"} <= tools:
                    violations.append("웹 조사보다 PoK 검색·상세·인사이트 조사가 먼저 필요하다")
                web = True
            elif kind not in {"reasoning", "agent_message", "error"}:
                violations.append(f"Unexpected native item: {kind}")
    return tools, web, violations


def apply_reply(state: dict[str, Any], reply: dict[str, Any], record: dict[str, Any]) -> None:
    """Only the host accepts replies; the model has no tool to write this ledger."""
    if reply.get("expected_state_sha256") != digest(state):
        raise ValueError("Reply belongs to a stale workflow state")
    if not str(reply.get("source", "")).strip() or not str(reply.get("text", "")).strip():
        raise ValueError("A reply needs its human source and exact text")
    kind = reply.get("kind")
    if state["status"] == "waiting_experiment" and kind in {
        "approve_experiment",
        "reject_experiment",
    }:
        ids = reply.get("claim_ids", [])
        if not ids or not set(ids) <= set(state["assessment"]["experimental_claim_ids"]):
            raise ValueError("Reply must name the exact pending experimental claims")
        if kind == "approve_experiment":
            for key in ids:
                state["approvals"][key] = claim_fingerprint(record, key)
        state["stage"] = 2
    elif state["status"] == "waiting_anchor_review" and kind == "approve_anchors":
        state["stage"] = 4
        state["stop_after"] = 5
    elif state["status"] in {"waiting_anchor_review", "waiting_feedback"} and kind == "feedback":
        state["stage"] = min(state["stage"], 3)
    elif state["status"] == "waiting_feedback" and kind == "accept_build":
        state["status"] = "complete"
        state["replies"].append(reply)
        return
    else:
        raise ValueError("Reply does not match the current human gate")
    state["replies"].append(reply)
    state["status"] = "running"


def can_continue_timeout(result: dict[str, Any], *, progressed: bool, remaining_s: float) -> bool:
    """Use the same total deadline after a clean timeout with a saved checkpoint."""
    return (
        result.get("state") == "timed_out"
        and progressed
        and remaining_s > 5
        and result.get("cleanup", {}).get("status") == "confirmed"
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.run_dir.resolve()
    if root == CONTROL_ROOT / "artifacts" or not root.is_relative_to(CONTROL_ROOT / "artifacts"):
        raise ValueError("Use an owned run directory inside workspace artifacts")
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 5400:
        raise ValueError("Expected a positive run budget up to 90 minutes")
    lock = root / ".controller.lock"
    root.mkdir(parents=True, exist_ok=True)
    # Exclusive ownership: never launch a second worker on the same workflow.
    with lock.open("x", encoding="utf-8") as stream:
        stream.write(str(os.getpid()))
    try:
        artifacts = install_paths(root)
        from pok.artifacts.design_record import parse_record
        from pok.engine.design_checkpoints import load_checkpoint
        from pok.engine.design_service import create_design, read_design

        state_path = root / "workflow.json"
        if args.resume:
            state: dict[str, Any] = json.loads(state_path.read_text(encoding="utf-8"))
            if state["model"] != args.model or state["effort"] != args.effort:
                raise ValueError("Model settings differ from the persisted workflow")
            requested_policy = getattr(args, "source_policy", None)
            if (
                requested_policy is not None
                and state.get("source_policy", WEB_REFERENCE) != requested_policy
            ):
                raise ValueError("Source policy differs from the persisted workflow")
            if args.reply:
                current = read_design(state["record_ref"])
                apply_reply(
                    state,
                    json.loads(args.reply.read_text(encoding="utf-8-sig")),
                    parse_record(current["record_json"]),
                )
                write_json(state_path, state)
            elif state["status"].startswith("waiting_") or state["status"] == "complete":
                return state
            elif state["status"] not in {"running", "incomplete", "interrupted"}:
                if not getattr(args, "recovery_note", None) or state["status"] != "timed_out":
                    raise ValueError("Failed executions need inspection before resume")
                last = root / state["turns"][-1]["path"] / "execution.json"
                execution = json.loads(last.read_text(encoding="utf-8"))
                if execution.get("cleanup", {}).get("status") != "confirmed":
                    raise ValueError("Cannot resume unconfirmed execution ownership")
                state["recovery_notice"] = args.recovery_note
                state["status"] = "running"
                recovered_record = parse_record(load_checkpoint(state["record_ref"])["record_json"])
                seen_tools, seen_web, violations = observed(root)
                state["assessment"] = check_stage(
                    recovered_record,
                    min(state["stage"], 3),
                    approvals=state["approvals"],
                    observed_tools=seen_tools,
                    web_observed=seen_web,
                    review_policy=state.get("review_policy"),
                )
                state["assessment"]["issues"].extend(violations)
                state["assessment_stage"] = state["stage"]
            if getattr(args, "recovery_note", None):
                state["recovery_notice"] = args.recovery_note
        else:
            if state_path.exists() or args.reply:
                raise ValueError("Fresh execution requires fresh state and no reply")
            brief = args.brief.read_text(encoding="utf-8-sig")
            saved = create_design("autonomous-" + uuid4().hex[:16], brief)
            saved = seed_user_request(saved, brief)
            state = {
                "format": "pok.autonomous-workflow.v1",
                "stage": 1,
                "status": "running",
                "brief": brief,
                "authorized_user_fixed_ids": ["user.request"],
                "record_ref": saved["record_ref"],
                "model": args.model,
                "effort": args.effort,
                "stop_after": args.stop_after,
                "session_id": None,
                "turns": [],
                "approvals": {},
                "replies": [],
                "assessment": {},
                "elapsed_s": 0.0,
                "quality_verified": False,
                "review_policy": getattr(args, "review_policy", None),
                "source_policy": getattr(args, "source_policy", None) or WEB_REFERENCE,
            }
        write_json(state_path, state)
        deadline = time.monotonic() + args.timeout
        method = (Path(__file__).with_name("autonomous-method.md")).read_text(encoding="utf-8")
        assembly = (Path(__file__).parents[1] / "build-assembly/AGENTS.md").read_text(
            encoding="utf-8"
        )
        if state.get("source_policy") == POK_PRIMARY:
            assembly = assembly.split("## 기존 계약", 1)[0]
        while state["stage"] <= 5 and time.monotonic() < deadline:
            if state["status"] == "complete":
                break
            stage = state["stage"]
            turn = root / f"turn-{len(state['turns']) + 1:03d}"
            context_path = root / f"context-{len(state['turns']) + 1:03d}.json"
            context = {
                "stage": stage,
                "record_ref": state["record_ref"],
                "original_brief": state["brief"],
                "authorized_user_fixed_ids": state.get("authorized_user_fixed_ids", []),
                "human_replies": state["replies"],
                "approved_hypotheses": state["approvals"],
                "previous_assessment": state["assessment"],
                "stop_after": state["stop_after"],
                "recovery_notice": state.get("recovery_notice", ""),
                "review_policy": state.get("review_policy"),
                "source_policy": state.get("source_policy", WEB_REFERENCE),
                **anoint_discovery_context(stage, state.get("source_policy", WEB_REFERENCE)),
            }
            remaining = deadline - time.monotonic()
            turn_budget = min(remaining, 1800.0)
            context["turn_deadline_unix"] = time.time() + turn_budget
            write_json(context_path, context)
            prompt = (
                method
                + ("\n" + assembly if stage >= 4 else "")
                + "\n"
                + json.dumps(context, ensure_ascii=False)
                + f"\n남은 전체 예산 {remaining:.1f}초, 이번 응답·저장 예산 {turn_budget:.1f}초. "
                + f"현재 {stage}단계만 수행한다. "
                "실제 도구로 기록을 갱신하고 최종 참조를 제출한다. "
                "앵커와 근거 누락을 형식 문장으로 덮지 않는다."
            )
            command = build_command(
                root,
                turn,
                context=context_path,
                session_id=state["session_id"],
                model=args.model,
                effort=args.effort,
                codex_exe=args.codex_exe,
                luajit_exe=args.luajit_exe,
                source_policy=state.get("source_policy", WEB_REFERENCE),
            )
            result = execute_phase(
                command,
                turn,
                prompt=prompt,
                schema=ANSWER_SCHEMA,
                cwd=root / "workspace",
                timeout_s=turn_budget,
                minimum_free_bytes=512 * 1024 * 1024,
            )
            state["turns"].append({"stage": stage, "path": turn.name, "state": result["state"]})
            state["elapsed_s"] += result["elapsed_s_including_collection"]
            if result.get("session_id"):
                state["session_id"] = result["session_id"]
            head_path = context_path.with_suffix(".head.json")
            head = json.loads(head_path.read_text(encoding="utf-8")) if head_path.exists() else None
            previous_ref = state["record_ref"]
            old_record = parse_record(load_checkpoint(previous_ref)["record_json"])
            if head is not None:
                recovered = load_checkpoint(head)
                recovered_record = parse_record(recovered["record_json"])
                if recovered_record["design_id"] != old_record["design_id"]:
                    raise ValueError("Checkpoint recovery changed design identity")
                state["record_ref"] = head
            if state.get("source_policy") == POK_PRIMARY:
                _, _, source_violations = observed(root)
                if source_violations:
                    state["status"] = "source_policy_violation"
                    state["source_violations"] = source_violations
                    write_json(state_path, state)
                    break
            if result["state"] != "completed":
                state["status"] = result["state"]
                if can_continue_timeout(
                    result,
                    progressed=head is not None and head != previous_ref,
                    remaining_s=deadline - time.monotonic(),
                ):
                    state["status"] = "running"
                    state["recovery_notice"] = (
                        "턴 상한 후 저장된 현재 설계에서 재개한다. 신규 탐색을 다시 시작하지 말고 "
                        "workflow_read_record로 필요한 결정만 확인해 현재 단계 제출을 마친다. "
                        "기존 저장 내용은 최종 판단을 대신하지 않으며 누락은 명시한다."
                    )
                write_json(state_path, state)
                if state["status"] == "running":
                    continue
                break
            answer = json.loads((turn / "answer.json").read_bytes())
            reference = json.loads(answer["record_ref_json"])
            if head is not None and reference != head:
                raise ValueError("Submitted reference is not the last persisted checkpoint")
            current = read_design(reference)
            record = parse_record(current["record_json"])
            if record["goal"]["summary"] != state["brief"]:
                raise ValueError("Participant changed original user brief")
            if old_record["design_id"] != record["design_id"]:
                raise ValueError("Participant switched design identity")
            state["record_ref"] = reference
            tools, web, violations = observed(root)
            assessment = check_stage(
                record,
                min(stage, 3),
                approvals=state["approvals"],
                observed_tools=tools,
                web_observed=web,
                review_policy=state.get("review_policy"),
            )
            assessment["issues"].extend(violations)
            fresh = current["current_assessment"]
            assessment["evidence_integrity"] = fresh["checks"]["evidence_integrity"]
            if fresh["checks"]["evidence_integrity"] == "needs_review":
                assessment["issues"].append("실제 카탈로그·측정 참조의 무결성 검사가 필요하다")
            assessment["issues"].extend(
                f"해결되지 않은 참조: {x}"
                for x in fresh["diagnostics"]
                if x.get("code") == "UNRESOLVED_REFERENCE"
            )
            if stage >= 4:
                if fresh["checks"]["material_integrity"] != "verified_blobs":
                    assessment["issues"].append("실제 PoB/스펙 재료의 저장·연결 검증이 필요하다")
                measured = [
                    x
                    for x in record["evidence"]
                    if x["kind"] == "measurement"
                    and x["scope"]["usage"] == "current"
                    and x["scope"].get("material_revision")
                    == (record.get("material") or {}).get("revision")
                ]
                if not measured:
                    assessment["issues"].append("현재 재료 리비전의 실제 계산 근거가 필요하다")
            if stage == 5:
                criticism = record.get("extensions", {}).get("autonomous_critique", {})
                if not criticism.get("findings") or not criticism.get("response"):
                    assessment["issues"].append("초안 비판과 변경/유지 판단을 기록해야 한다")
            assessment["ready"] = (
                not assessment["issues"] and not assessment["experimental_claim_ids"]
            )
            state["assessment"] = assessment
            state["assessment_stage"] = stage
            (root / "design.md").write_text(current["design_md"], encoding="utf-8")
            write_json(root / "design-record.json", record)
            if assessment["experimental_claim_ids"]:
                state["status"] = "waiting_experiment"
            elif answer["status"] == "needs_user":
                state["status"] = "waiting_feedback"
            elif answer["status"] == "incomplete":
                state["status"] = "incomplete"
            elif assessment["ready"]:
                if stage == 3 and state["stop_after"] == 3:
                    state["status"] = "waiting_anchor_review"
                elif stage == 5:
                    state["status"] = "waiting_feedback"
                else:
                    state["stage"] += 1
                    state["status"] = "running"
            else:
                state["status"] = "running"  # repair missing evidence in the same stage
            write_json(state_path, state)
            write_json(turn / "workflow-assessment.json", assessment)
            if state["status"] != "running":
                break
        if state["status"] == "running":
            state["status"] = "incomplete"
            write_json(state_path, state)
        write_json(
            root / "reply-template.json",
            {
                "expected_state_sha256": digest(state),
                "kind": "feedback",
                "claim_ids": [],
                "source": "실제 사용자 응답 출처",
                "text": "실제 사용자 응답",
            },
        )
        # Root exports are views only; never read them as the source on resume.
        state["artifact_namespace"] = str(artifacts)
        return state
    finally:
        lock.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--brief", type=Path)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--reply", type=Path)
    parser.add_argument("--recovery-note")
    parser.add_argument("--review-policy", choices=["planning-v2"], default="planning-v2")
    parser.add_argument("--source-policy", choices=[WEB_REFERENCE, POK_PRIMARY], default=None)
    parser.add_argument("--stop-after", type=int, choices=[3, 5], default=5)
    parser.add_argument("--timeout", type=float, default=5400)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", required=True)
    parser.add_argument("--codex-exe", required=True)
    parser.add_argument("--luajit-exe")
    args = parser.parse_args()
    if not args.resume and not args.brief:
        parser.error("A fresh workflow requires --brief")
    print(json.dumps(run(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
