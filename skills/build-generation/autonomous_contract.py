"""Skill-owned workflow checks; completeness is not game feasibility or quality.

Build choices and evidence live in the existing immutable design record. The
extension below contains references and review coverage, not a second build.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


TEXT = {"type": "string", "minLength": 1}
IDS = {"type": "array", "items": TEXT, "uniqueItems": True}
ANSWER_SCHEMA = object_schema(
    {
        "status": {"type": "string", "enum": ["ready", "needs_user", "incomplete"]},
        "record_ref_json": TEXT,
        # Provider strict-output subset does not accept uniqueItems. Local
        # reference validation remains independent of the model response shape.
        "question_ids": {"type": "array", "items": TEXT},
        "summary": TEXT,
    }
)

FLOW_SCHEMA = object_schema(
    {
        "selected_mechanism_id": TEXT,
        "core_link_ids": IDS,
        "anchor_ids": IDS,
        "component_review": {
            "type": "array",
            "items": object_schema(
                {
                    "kind": {"enum": ["item", "jewel", "skill", "support", "passive"]},
                    "decision_ids": IDS,
                    "reason": TEXT,
                }
            ),
        },
        "budget_review": {
            "type": "array",
            "items": object_schema(
                {
                    "resource": {
                        "enum": [
                            "passive_points",
                            "ascendancy_points",
                            "slots",
                            "reservation",
                            "attributes",
                            "sustain",
                            "operation",
                        ]
                    },
                    "status": {"enum": ["measured", "estimated", "unresolved", "not_applicable"]},
                    "detail": TEXT,
                    "evidence_ids": IDS,
                }
            ),
        },
    }
)


PLANNING_REVIEW_SCHEMA = object_schema(
    {
        "resource_options": {
            "type": "array",
            "minItems": 1,
            "items": object_schema(
                {
                    "channel": {
                        "enum": [
                            "regen",
                            "flask",
                            "leech",
                            "on_hit",
                            "on_kill",
                            "recoup",
                            "pool",
                            "cost_change",
                            "other",
                            "not_applicable",
                        ]
                    },
                    "decision_ids": IDS,
                    "availability_and_tradeoff": TEXT,
                }
            ),
        },
        "resource_scenarios": {
            "type": "array",
            "items": object_schema(
                {
                    "scenario": {"enum": ["mapping", "boss", "restart"]},
                    "decision_ids": IDS,
                    "duration_or_depletion_basis": TEXT,
                    "limitations": TEXT,
                }
            ),
        },
        "critical_strategy": object_schema(
            {
                "choice": {"enum": ["critical", "noncritical", "conditional", "not_applicable"]},
                "decision_ids": IDS,
                "alternatives_and_reason": TEXT,
            }
        ),
        "high_impact_packages": object_schema(
            {
                "decision_ids": IDS,
                "adoption_and_opportunity_cost": TEXT,
            }
        ),
    }
)


def check_planning_reviews(record: dict[str, Any]) -> list[str]:
    from jsonschema import Draft202012Validator

    value = record.get("extensions", {}).get("planning_reviews", {})
    errors = list(Draft202012Validator(PLANNING_REVIEW_SCHEMA).iter_errors(value))
    if errors:
        return [f"선택 검토 필드 {list(x.path)}: {x.message}" for x in errors]
    issues = []
    known = {x["id"] for x in record["decisions"]}
    rows = [
        *value["resource_options"],
        *value["resource_scenarios"],
        value["critical_strategy"],
        value["high_impact_packages"],
    ]
    for row in rows:
        if not row["decision_ids"]:
            issues.append("자원·치명타·고가치 검토에 실제 결정 참조가 필요하다")
        for key in row["decision_ids"]:
            if key not in known:
                issues.append(f"선택 검토의 미해결 결정 참조: {key}")
    if {x["scenario"] for x in value["resource_scenarios"]} != {"mapping", "boss", "restart"}:
        issues.append("맵핑·보스·재시동의 자원 가용 조건을 구분해야 한다")
    if {x["channel"] for x in value["resource_options"]} == {"regen"}:
        issues.append("자연 재생 외 공급/소모 대안을 실제로 검토하고 결정에 연결해야 한다")
    return issues


def claim_fingerprint(record: dict[str, Any], identity: str) -> str:
    """Approval expires when a claim, its providers, dependencies or evidence change."""
    decisions = {x["id"]: x for x in record["decisions"]}
    evidence = {x["id"]: x for x in record["evidence"]}
    pending, seen = [identity], set()
    rows = []
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        row = decisions[key]
        # Approval covers the claim, not later prose/cost/adoption bookkeeping.
        # Binding an unchanged provider to PoB is not a new game assumption.
        value = {k: row[k] for k in ("id", "condition", "depends_on", "evidence_ids")}
        value["providers"] = [
            {k: v for k, v in provider.items() if k != "binding"} for provider in row["providers"]
        ]
        rows.append(value)
        pending.extend(row["depends_on"])
        pending.extend(row["condition"]["scope"]["decision_ids"])
    ev = sorted({key for row in rows for key in row["evidence_ids"]})
    return digest(
        {
            "decisions": sorted(rows, key=lambda x: x["id"]),
            "evidence": [evidence[key] for key in ev],
        }
    )


def check_stage(
    record: dict[str, Any],
    stage: int,
    *,
    approvals: dict[str, str],
    observed_tools: set[str],
    web_observed: bool,
    review_policy: str | None = None,
) -> dict[str, Any]:
    """Check declared evidence/coverage, never decide whether a build is good.

    Web observation and linked source text cannot prove that an agent's reading
    of the interaction is correct. This limit is returned on every assessment.
    """
    from jsonschema import Draft202012Validator

    issues: list[str] = []
    experimental: list[str] = []
    decisions = {x["id"]: x for x in record["decisions"]}
    evidence = {x["id"]: x for x in record["evidence"]}
    flow = record.get("extensions", {}).get("autonomous_flow", {})
    if not record.get("mechanism_summary", "").strip():
        issues.append("메커니즘의 시작·반복·종료·재시동 설명이 필요하다")
    if not {"search_kb", "get_entry", "search_insights"} <= observed_tools:
        issues.append("실제 PoK 검색·상세 읽기·인사이트 조사 기록이 필요하다")
    if stage >= 2:
        if not web_observed:
            issues.append("핵심 연결에 대한 실제 웹 조사 기록이 필요하다")
        shape_errors = list(Draft202012Validator(FLOW_SCHEMA).iter_errors(flow))
        for error in shape_errors:
            issues.append(f"설계 흐름 필드 {list(error.path)}: {error.message}")
        if shape_errors:
            return {
                "ready": False,
                "issues": issues,
                "experimental_claim_ids": [],
                "semantic_quality_verified": False,
                "scope": "declared_coverage_and_observed_execution_only",
            }
        selected = decisions.get(flow.get("selected_mechanism_id"))
        if not selected or selected["adoption"] != "adopted":
            issues.append("채택 메커니즘 결정 참조가 필요하다")
        links = flow.get("core_link_ids", [])
        if not links:
            issues.append("핵심 연결을 개별 결정으로 명시해야 한다")
        for key in links:
            row = decisions.get(key)
            if not row:
                issues.append(f"존재하지 않는 핵심 연결: {key}")
                continue
            linked = [evidence[x] for x in row["evidence_ids"] if x in evidence]
            kinds = {x["kind"] for x in linked}
            if row["belief"] == "contradicted":
                issues.append(f"반증된 핵심 연결: {key}")
            elif row["belief"] != "source_supported" or not {"catalog", "external"} <= kinds:
                try:
                    approved = approvals.get(key) == claim_fingerprint(record, key)
                except KeyError:
                    approved = False
                if not approved:
                    experimental.append(key)
            if not row.get("rationale", "").strip():
                issues.append(f"연결별 근거 해석과 적용 범위 누락: {key}")
    if stage >= 3:
        anchors = flow.get("anchor_ids", [])
        if not anchors:
            issues.append("구체적인 필수·선택 앵커가 필요하다")
        domains: set[str] = set()
        for key in anchors:
            row = decisions.get(key)
            if not row:
                issues.append(f"존재하지 않는 앵커: {key}")
                continue
            if row["adoption"] not in {"adopted", "candidate"}:
                continue
            domains.update(row["domains"])
            providers = row["providers"]
            concrete = [
                x
                for x in providers
                if x["kind"] in {"item", "jewel", "skill", "support", "passive"}
                and x.get("entity_id", "").strip()
            ]
            # Abstract needs may point to separately recorded concrete suppliers.
            for dep in row["depends_on"]:
                concrete.extend(
                    x for x in decisions.get(dep, {}).get("providers", []) if x.get("entity_id")
                )
            if not concrete:
                issues.append(f"추상 조건에 그친 앵커(정확한 공급자 필요): {key}")
            if not row.get("rationale", "").strip() or not row["evidence_ids"]:
                issues.append(f"선정 이유 또는 근거가 없는 앵커: {key}")
            if not row["costs"] or not row.get("review_triggers"):
                issues.append(f"비용·재검토 조건이 없는 앵커: {key}")
        if not {"offence", "defence", "sustain"} <= domains:
            issues.append("공격·방어·자원 앵커를 모두 구체화해야 한다")
        coverage = {x.get("kind") for x in flow.get("component_review", [])}
        if coverage != {"item", "jewel", "skill", "support", "passive"}:
            issues.append("장비·주얼·스킬·보조·패시브 채택/미채택 검토가 필요하다")
        for row in flow.get("component_review", []):
            for key in row.get("decision_ids", []):
                if key not in decisions:
                    issues.append(f"구성 검토의 미해결 결정 참조: {key}")
        budgets = {x.get("resource") for x in flow.get("budget_review", [])}
        if budgets != {
            "passive_points",
            "ascendancy_points",
            "slots",
            "reservation",
            "attributes",
            "sustain",
            "operation",
        }:
            issues.append("포인트·슬롯·점유·능력치·자원·조작 제약 검토가 필요하다")
        for row in flow.get("budget_review", []):
            if row.get("status") == "unresolved":
                issues.append(f"성립 제약 미해결: {row['resource']}: {row['detail']}")
            for key in row.get("evidence_ids", []):
                if key not in evidence:
                    issues.append(f"제약 검토의 미해결 근거 참조: {key}")
    if stage >= 3 and review_policy == "planning-v2":
        issues.extend(check_planning_reviews(record))
    return {
        "ready": not issues and not experimental,
        "issues": issues,
        "experimental_claim_ids": experimental,
        "semantic_quality_verified": False,
        "scope": "declared_coverage_and_observed_execution_only",
    }
