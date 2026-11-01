"""Explicit design edits and structural impact reports; no build solver.

The caller owns its current record. These functions neither choose a current
branch nor certify evidence/game feasibility. Persistence and evidence checks
are separate adapters over the same sealed record and actual inputs.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from pok.artifacts.design_record import (
    DesignRecordError,
    canonical_bytes,
    parse_record,
    record_json,
    seal_record,
)


def _graph(record: dict[str, Any]) -> dict[str, set[str]]:
    return {
        entry["id"]: set(entry["depends_on"]) | set(entry["condition"]["scope"]["decision_ids"])
        for entry in record["decisions"]
    }


def _cycles(graph: dict[str, set[str]]) -> list[list[str]]:
    """Iterative Kosaraju: cycles are coupled groups, not forbidden builds."""
    seen: set[str] = set()
    order: list[str] = []
    reverse: dict[str, set[str]] = {key: set() for key in graph}
    for node, dependencies in graph.items():
        for dependency in dependencies & graph.keys():
            reverse[dependency].add(node)
    for root in sorted(graph):
        stack = [(root, False)]
        while stack:
            node, expanded = stack.pop()
            if expanded:
                order.append(node)
            elif node not in seen:
                seen.add(node)
                stack.append((node, True))
                stack.extend(
                    (child, False)
                    for child in sorted(graph[node] & graph.keys(), reverse=True)
                    if child not in seen
                )
    seen.clear()
    groups = []
    for root in reversed(order):
        if root in seen:
            continue
        group: set[str] = set()
        reverse_stack = [root]
        while reverse_stack:
            node = reverse_stack.pop()
            if node in seen:
                continue
            seen.add(node)
            group.add(node)
            reverse_stack.extend(sorted(reverse[node] - seen, reverse=True))
        if len(group) > 1 or root in graph[root]:
            groups.append(sorted(group))
    return sorted(groups)


def _inspect(record: dict[str, Any]) -> dict[str, Any]:
    decisions = {entry["id"] for entry in record["decisions"]}
    evidence = {entry["id"] for entry in record["evidence"]}
    issues: list[dict[str, Any]] = []

    def references(owner: str, field: str, refs: Sequence[str], known: set[str]) -> None:
        for reference in refs:
            if reference not in known:
                issues.append(
                    {
                        "code": "UNRESOLVED_REFERENCE",
                        "severity": "warning",
                        "owner": owner,
                        "field": field,
                        "reference": reference,
                    }
                )

    for entry in record["decisions"]:
        for field in ("depends_on", "alternatives"):
            references(entry["id"], field, entry[field], decisions)
        references(
            entry["id"],
            "condition.scope.decision_ids",
            entry["condition"]["scope"]["decision_ids"],
            decisions,
        )
        references(entry["id"], "evidence_ids", entry["evidence_ids"], evidence)
    for entry in record["evidence"]:
        references(entry["id"], "scope.decision_ids", entry["scope"]["decision_ids"], decisions)
    for question in record["questions"]:
        references(question["id"], "depends_on", question["depends_on"], decisions)
        references(question["id"], "evidence_ids", question["evidence_ids"], evidence)
        if question["state"] == "open":
            code = {
                "agent": "AGENT_TASK_PENDING",
                "user_preference": "USER_DECISION_PENDING",
                "in_game": "USER_OBSERVATION_PENDING",
            }[question["owner"]]
            issues.append(
                {
                    "code": code,
                    "severity": "info",
                    "question_id": question["id"],
                    "claim": question["claim"],
                    "criterion": question["criterion"],
                }
            )
    cycles = _cycles(_graph(record))
    issues.extend(
        {"code": "CYCLE_REVIEW_GROUP", "severity": "info", "decision_ids": group}
        for group in cycles
    )
    return {
        "design_id": record["design_id"],
        "revision": record["revision"],
        "checks": {
            "record_integrity": "valid",
            "references": "unresolved"
            if any(issue["code"] == "UNRESOLVED_REFERENCE" for issue in issues)
            else "valid",
            "evidence_integrity": "not_checked",
            "game_feasibility": "not_checked",
        },
        "material_status": "unbound" if record["material"] is None else "linked_not_verified",
        "review_required_ids": [
            entry["id"]
            for entry in record["decisions"]
            if entry.get("review", {}).get("state") == "required"
        ],
        "dependency_cycles": cycles,
        "diagnostics": issues,
    }


def inspect_record(record_text: str) -> dict[str, Any]:
    return _inspect(parse_record(record_text))


@dataclass(frozen=True)
class RecordChange:
    record_json: str
    changed_decision_ids: tuple[str, ...]
    review_required_ids: tuple[str, ...]
    diagnostics: tuple[dict[str, Any], ...]
    operation_provenance: dict[str, Any]
    no_change: bool = False


def _merge(existing: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(existing)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _upsert(record: dict[str, Any], section: str, value: Any) -> None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        raise DesignRecordError("INVALID_CHANGE", "An entry with a string ID is required")
    for index, existing in enumerate(record[section]):
        if existing["id"] == value["id"]:
            record[section][index] = _merge(existing, value)
            return
    defaults: dict[str, Any] = {}
    if section == "decisions":
        defaults = {
            "adoption": "candidate",
            "belief": "unknown",
            "confidence": "low",
            "providers": [],
            "depends_on": [],
            "alternatives": [],
            "evidence_ids": [],
            "costs": [],
            "condition": {"scope": {"decision_ids": []}},
        }
    elif section == "questions":
        defaults = {"state": "open", "depends_on": [], "evidence_ids": []}
    elif section == "evidence":
        defaults = {"scope": {"decision_ids": []}}
    record[section].append(_merge(defaults, value))


def _remove(record: dict[str, Any], section: str, identity: Any) -> None:
    if not isinstance(identity, str) or not any(
        entry["id"] == identity for entry in record[section]
    ):
        raise DesignRecordError("UNKNOWN_ENTRY", f"No such entry in {section}")
    record[section] = [entry for entry in record[section] if entry["id"] != identity]


def _patch(record: dict[str, Any], changes: Sequence[Mapping[str, Any]]) -> None:
    for change in changes:
        if not isinstance(change, Mapping) or not isinstance(change.get("op"), str):
            raise DesignRecordError("INVALID_CHANGE", "Each change requires a string op")
        op = change.get("op")
        if (
            isinstance(op, str)
            and op.startswith("upsert_")
            and op[7:] in {"decision", "evidence", "question"}
        ):
            if set(change) != {"op", "value"}:
                raise DesignRecordError("INVALID_CHANGE", "Upsert expects only op and value")
            section = {"decision": "decisions", "evidence": "evidence", "question": "questions"}[
                op[7:]
            ]
            _upsert(record, section, change["value"])
        elif (
            isinstance(op, str)
            and op.startswith("remove_")
            and op[7:] in {"decision", "evidence", "question"}
        ):
            if set(change) != {"op", "id"}:
                raise DesignRecordError("INVALID_CHANGE", "Remove expects only op and id")
            section = {"decision": "decisions", "evidence": "evidence", "question": "questions"}[
                op[7:]
            ]
            _remove(record, section, change["id"])
        elif op in {"set_goal", "set_material", "set_mechanism_summary"} and set(change) == {
            "op",
            "value",
        }:
            key = {
                "set_goal": "goal",
                "set_material": "material",
                "set_mechanism_summary": "mechanism_summary",
            }[op]
            record[key] = deepcopy(change["value"])
        elif op == "append_legacy_source" and set(change) == {"op", "value"}:
            record["legacy_sources"].append(deepcopy(change["value"]))
        elif (
            op == "merge_extensions"
            and set(change) == {"op", "value"}
            and isinstance(change["value"], dict)
        ):
            record.setdefault("extensions", {}).update(deepcopy(change["value"]))
        else:
            raise DesignRecordError("INVALID_CHANGE", "Unsupported change or unexpected fields")


_FIXED_FIELDS = ("role", "condition", "providers", "adoption")
_IMPACT_FIELDS = (*_FIXED_FIELDS, "domains", "costs", "evidence_ids", "belief")


def _provider_intent_changed(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> bool:
    """Moving an identical binding to a new material is not a new user choice."""
    if {entry["id"] for entry in old} != {entry["id"] for entry in new}:
        return True
    new_by_id = {entry["id"]: entry for entry in new}
    for provider in old:
        other = new_by_id[provider["id"]]
        keys = ["id", "kind", "entity_id"]
        if not provider.get("entity_id") and not provider.get("binding"):
            keys.append("label")
        if any(provider.get(key) != other.get(key) for key in keys):
            return True
        if provider.get("binding") and provider["binding"]["value_sha256"] != other.get(
            "binding", {}
        ).get("value_sha256"):
            return True
    return False


def apply_record_changes(
    record_text: str,
    expected_revision: str,
    changes: Sequence[Mapping[str, Any]],
    *,
    user_decisions: Mapping[str, str] | None = None,
) -> RecordChange:
    """Apply one explicit bundle, preserving branches and declared user decisions.

    user_decisions is a caller-reported acknowledgment per protected decision ID,
    not authentication of a human. Actual evidence remains separately unverified.
    """
    before = parse_record(record_text)
    if not isinstance(changes, Sequence) or isinstance(changes, str | bytes):
        raise DesignRecordError(
            "INVALID_CHANGE", "Changes must be a sequence of explicit operations"
        )
    canonical_bytes(list(changes))
    if before["revision"] != expected_revision:
        raise DesignRecordError(
            "REVISION_CONFLICT", "Expected revision differs from the provided base"
        )
    if user_decisions is not None and not isinstance(user_decisions, Mapping):
        raise DesignRecordError("INVALID_USER_DECISION", "Expected acknowledgments by decision ID")
    acknowledgments = dict(user_decisions or {})
    if any(
        not isinstance(key, str) or not isinstance(value, str) or not value.strip()
        for key, value in acknowledgments.items()
    ):
        raise DesignRecordError(
            "INVALID_USER_DECISION", "Acknowledgments must name a decision and a nonblank source"
        )
    candidate = deepcopy(before)
    _patch(candidate, changes)
    # Validate the proposed data before traversing it. Nothing has been persisted.
    candidate = seal_record(candidate)
    old = {entry["id"]: entry for entry in before["decisions"]}
    new = {entry["id"]: entry for entry in candidate["decisions"]}
    for identity, entry in old.items():
        target = new.get(identity)
        protected_change = target is None or (
            any(entry.get(key) != target.get(key) for key in ("role", "condition"))
            or _provider_intent_changed(entry["providers"], target["providers"])
            or (
                target["adoption"] in {"rejected", "deferred"}
                and target["adoption"] != entry["adoption"]
            )
        )
        if entry["role"] == "user_fixed" and protected_change and identity not in acknowledgments:
            raise DesignRecordError(
                "USER_FIXED_CHANGE_REQUIRES_DECISION", f"User-fixed decision changed: {identity}"
            )
    if canonical_bytes(candidate) == canonical_bytes(before):
        report = _inspect(before)
        return RecordChange(
            record_text,
            (),
            tuple(report["review_required_ids"]),
            tuple(report["diagnostics"]),
            {"base_revision": expected_revision, "user_decisions": acknowledgments},
            True,
        )
    direct = {
        identity for identity in old.keys() | new.keys() if old.get(identity) != new.get(identity)
    }
    roots = {
        identity
        for identity in direct
        if identity not in old
        or identity not in new
        or any(old[identity].get(key) != new[identity].get(key) for key in _IMPACT_FIELDS)
    }
    old_evidence = {entry["id"]: entry for entry in before["evidence"]}
    new_evidence = {entry["id"]: entry for entry in candidate["evidence"]}
    changed_evidence = {
        key
        for key in old_evidence.keys() | new_evidence.keys()
        if old_evidence.get(key) != new_evidence.get(key)
    }
    for entry in (*before["evidence"], *candidate["evidence"]):
        if entry["id"] in changed_evidence:
            roots.update(entry["scope"]["decision_ids"])
    roots.update(
        entry["id"]
        for entry in candidate["decisions"]
        if changed_evidence.intersection(entry["evidence_ids"])
    )
    if before["material"] != candidate["material"]:
        # Actual pointer/component equivalence is checked by the material adapter,
        # not guessed from a hash or text here. Conservative review is explicit.
        roots.update(new)
    reverse: dict[str, set[str]] = {}
    for graph in (_graph(before), _graph(candidate)):
        for node, dependencies in graph.items():
            for dependency in dependencies:
                reverse.setdefault(dependency, set()).add(node)
    affected = set(roots)
    queue = deque(sorted(roots))
    while queue:
        for dependent in sorted(reverse.get(queue.popleft(), set()) - affected):
            affected.add(dependent)
            queue.append(dependent)
    for entry in candidate["decisions"]:
        if entry["id"] in affected:
            entry["review"] = {
                "state": "required",
                "reasons": ["EXPLICIT_DEPENDENCY_OR_INPUT_CHANGED"],
                "since_revision": expected_revision,
            }
    for question in candidate["questions"]:
        if question["state"] == "resolved" and (
            affected.intersection(question["depends_on"])
            or changed_evidence.intersection(question["evidence_ids"])
        ):
            question["state"] = "open"
    candidate["parents"] = [expected_revision]
    candidate = seal_record(candidate)
    report = _inspect(candidate)
    return RecordChange(
        record_json(candidate),
        tuple(sorted(direct)),
        tuple(report["review_required_ids"]),
        tuple(report["diagnostics"]),
        {
            "base_revision": expected_revision,
            "user_decisions": acknowledgments,
            "requested_changes": deepcopy(list(changes)),
            "newly_affected_ids": sorted(affected & new.keys()),
        },
    )
