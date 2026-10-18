"""Compare declared optimization work with recorded evidence; never choose a build.

Legality and recommendation readiness are separate. The caller supplies the scope
and stopping criteria. This module does not claim a global optimum or invent a
required set of items, passives, or objectives. Exploration may record an
incomplete result; recommendation publication must satisfy this contract.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterator, Mapping
from typing import Any

from pok.engine.provenance import (
    derivation_context,
    preserve_execution_history,
    stale_components,
    stamp,
)

PURPOSES = ("exploration", "recommendation")
REVIEW_COMPONENTS = ("items", "jewels", "tree", "supports", "ascendancy")


class OptimizationNotReadyError(ValueError):
    """A final recommendation was requested without sufficient declared evidence."""

    def __init__(self, report: dict[str, Any]) -> None:
        self.report = report
        codes = ", ".join(dict.fromkeys(row["code"] for row in report["blockers"]))
        super().__init__(f"최적화 추천 준비도 미충족: {codes}")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _issue(
    code: str,
    component: str,
    path: str,
    detail: str,
    *,
    expected: Any = None,
    observed: Any = None,
) -> dict[str, Any]:
    identity = {
        "code": code,
        "component": component,
        "path": path,
        "expected": expected,
        "observed": observed,
    }
    digest = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()[:16]
    return {"issue_id": f"{code}:{digest}", **identity, "detail": detail}


def _stamps(spec: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping[str, Any]]]:
    """Top-level and item/jewel receipts have the same evidence shape."""
    containers: list[tuple[str, Mapping[str, Any]]] = [("", spec)]
    for kind in ("items", "jewels"):
        for index, entry in enumerate(spec.get(kind) or []):
            if isinstance(entry, Mapping):
                containers.append((f"{kind}[{index}].", entry))
    for prefix, container in containers:
        marks = container.get("derived_from") or {}
        if not isinstance(marks, Mapping):
            continue
        # Some older per-item receipts are a direct tool stamp, not a component map.
        if "tool" in marks:
            yield prefix + "derived_from", str(marks.get("tool", "")), marks
        else:
            for component, mark in marks.items():
                if isinstance(mark, Mapping):
                    yield prefix + "derived_from." + str(component), str(component), mark


def _receipt_digest(mark: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(mark).encode("utf-8")).hexdigest()


def _owners(spec: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    owners = {}
    for kind, key in (("items", "slot"), ("jewels", "socket_node_id")):
        for index, entry in enumerate(spec.get(kind) or []):
            for local_path, _, _ in _stamps({kind: [entry]}):
                path = local_path.replace(f"{kind}[0]", f"{kind}[{index}]", 1)
                owners[path] = {"collection": kind, key: entry.get(key)}
    return owners


def measured_review_receipt(
    base_spec: dict[str, Any],
    variants: Mapping[str, dict[str, Any]],
    measurements: Mapping[str, Mapping[str, float]],
    *,
    component: str,
    stats: list[str],
    baseline_stats: Mapping[str, float],
    unresolved: list[dict[str, Any]],
) -> dict[str, Any]:
    """Describe successful baseline/alternative measurements, never infer a winner.

    Only the MCP evaluator calls this after calculation. Revalidation owners are
    derived from actual input changes; callers cannot submit paths to clear.
    A changed support cannot certify an item search, and a no-op cannot certify
    any search. The receipt belongs to the baseline, not an unselected variant.
    """
    if component not in REVIEW_COMPONENTS:
        raise ValueError(f"review_component는 {REVIEW_COMPONENTS} 중 하나여야 한다")
    allowed = {
        "items": {"items_sig", "item_substitutes_sig", "item_activity_sig"},
        "jewels": {"jewels_sig"},
        "tree": {"tree_sig", "attribute_choices_sig"},
        "supports": {"skills_sig", "skills_details_sig"},
        "ascendancy": {"character_sig", "tree_sig", "attribute_choices_sig"},
    }[component]
    context = derivation_context(base_spec)
    scope: dict[str, Any] = {
        "candidates": [],
        "slots": [],
        "jewel_sockets": [],
        "tree_nodes": [],
        "skill_groups": [],
        "ascendancies": [],
    }
    owner_labels: dict[tuple[str, Any], list[str]] = {}
    problems = list(unresolved)
    for label, variant in variants.items():
        if label not in measurements:
            continue
        other = derivation_context(variant)
        differences = {
            key
            for key, value in context.items()
            if (key.endswith("_sig") or key == "config") and value != other[key]
        }
        if (
            not differences
            or differences - allowed
            or (
                component == "ascendancy"
                and any(base_spec.get(key) != variant.get(key) for key in ("class_name", "level"))
            )
        ):
            problems.append(
                {
                    "code": "review_scope_mismatch",
                    "scope": [label],
                    "changed_axes": sorted(differences),
                }
            )
            continue
        scope["candidates"].append(label)
        if component in ("items", "jewels"):
            kind, key, output = (
                ("items", "slot", "slots")
                if component == "items"
                else ("jewels", "socket_node_id", "jewel_sockets")
            )
            before = {
                row[key]: {k: v for k, v in row.items() if k != "derived_from"}
                for row in base_spec.get(kind) or []
            }
            after = {
                row[key]: {k: v for k, v in row.items() if k != "derived_from"}
                for row in variant.get(kind) or []
            }
            for owner in before.keys() | after.keys():
                if before.get(owner) != after.get(owner):
                    scope[output].append(owner)
                    owner_labels.setdefault((kind, owner), []).append(label)
        elif component == "supports":
            before_groups = base_spec.get("skills") or []
            after_groups = variant.get("skills") or []
            scope["skill_groups"].extend(
                index + 1
                for index in range(max(len(before_groups), len(after_groups)))
                if (before_groups[index] if index < len(before_groups) else None)
                != (after_groups[index] if index < len(after_groups) else None)
            )
        else:
            scope["tree_nodes"].extend(
                sorted(
                    set(base_spec.get("tree_nodes") or []) ^ set(variant.get("tree_nodes") or [])
                )
            )
            if component == "ascendancy":
                scope["ascendancies"].extend(
                    [base_spec.get("ascendancy"), variant.get("ascendancy")]
                )
    scope = {key: sorted(set(values), key=str) for key, values in scope.items() if values}
    if not scope.get("candidates"):
        problems.append({"code": "no_successful_alternative", "scope": [component]})
    owners = _owners(base_spec)
    revalidations = {}
    for path, _, old_mark in _stamps(base_spec):
        owner = owners.get(path)
        if owner is None:
            continue
        key = "slot" if owner["collection"] == "items" else "socket_node_id"
        labels = owner_labels.get((owner["collection"], owner[key]), [])
        if labels:
            revalidations[path] = {
                "owner": owner,
                "receipt_sha256": _receipt_digest(old_mark),
                "variant_labels": labels,
            }
    evidence = {
        "review_version": 1,
        "selection": "baseline",
        "scope": scope,
        "settings": {"variant_count": len(variants), "stats": stats},
        "termination": {
            "reason": "variants_evaluated",
            "converged": False,
            "measurements": len(measurements),
        },
        "unresolved": problems,
        "measurements": {label: dict(values) for label, values in measurements.items()},
        "baseline_stats": dict(baseline_stats),
        "revalidation_receipts": revalidations,
    }
    mark = stamp(base_spec, component, tool="evaluate_delta", search_evidence=evidence)
    prior_marks = base_spec.get("derived_from") or {}
    prior = prior_marks.get(component) if isinstance(prior_marks, Mapping) else None
    if isinstance(prior, Mapping):
        history = preserve_execution_history(prior)
        if history:
            mark["execution_history"] = history
    return mark


def _scope_issues(expected: Any, observed: Any, component: str, path: str) -> list[dict[str, Any]]:
    if expected is None or expected == "":
        return [
            _issue(
                "invalid_contract", component, path, "기대 범위를 null/빈 문자열로 선언할 수 없다"
            )
        ]
    if isinstance(expected, Mapping):
        if not expected:
            return [_issue("invalid_contract", component, path, "기대 범위를 비울 수 없다")]
        actual = observed if isinstance(observed, Mapping) else {}
        return [
            row
            for key, value in expected.items()
            for row in _scope_issues(value, actual.get(key), component, f"{path}.{key}")
        ]
    if isinstance(expected, list):
        if not expected:
            return [_issue("invalid_contract", component, path, "기대 범위 목록이 비어 있다")]
        actual_values = observed if isinstance(observed, list) else []
        actual_keys = {_canonical(value) for value in actual_values}
        missing = [value for value in expected if _canonical(value) not in actual_keys]
        if missing:
            return [
                _issue(
                    "scope_missing",
                    component,
                    path,
                    "요청한 탐색 범위의 증거가 없다",
                    expected=missing,
                    observed=actual_values,
                )
            ]
        return []
    if expected != observed or type(expected) is not type(observed):
        return [
            _issue(
                "scope_mismatch",
                component,
                path,
                "탐색 범위가 계약과 다르다",
                expected=expected,
                observed=observed,
            )
        ]
    return []


def _number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _settings_issues(rules: Any, settings: Any, component: str) -> list[dict[str, Any]]:
    if not isinstance(rules, Mapping):
        return [_issue("invalid_contract", component, "settings", "settings는 객체여야 한다")]
    actual = settings if isinstance(settings, Mapping) else {}
    out = []
    for key, bounds in rules.items():
        path = f"settings.{key}"
        if not isinstance(bounds, Mapping) or not bounds or set(bounds) - {"min", "max", "equals"}:
            out.append(
                _issue(
                    "invalid_contract",
                    component,
                    path,
                    "설정 조건은 min/max/equals로 선언한다",
                    expected=bounds,
                )
            )
            continue
        value = actual.get(key)
        for op, target in bounds.items():
            if op in ("min", "max") and not _number(target):
                out.append(
                    _issue(
                        "invalid_contract",
                        component,
                        path,
                        "min/max는 유한한 수여야 한다",
                        expected=bounds,
                    )
                )
                break
            matches = (
                (value == target and type(value) is type(target))
                if op == "equals"
                else (_number(value) and (value >= target if op == "min" else value <= target))
            )
            if not matches:
                out.append(
                    _issue(
                        "settings_mismatch",
                        component,
                        path,
                        "실행 설정이 요청한 경계를 충족하지 않는다",
                        expected=dict(bounds),
                        observed=value,
                    )
                )
                break
    return out


def optimization_readiness(
    spec: Mapping[str, Any], *, purpose: str = "exploration"
) -> dict[str, Any]:
    """Return deterministic, JSON-safe evidence status without running an optimizer.

    Contract v1::

        {"version": 1, "required_components": {
          "items": {"scope": {"slots": ["Weapon 1", "Amulet"]},
                    "settings": {"max_rounds": {"min": 2}},
                    "allowed_termination_reasons": ["no_improvement"]}},
         "exceptions": [{"issue_id": "<exact returned id>", "reason": "..."}]}

    Producers attach scope/settings/termination/unresolved under their genuine
    derived_from.<component>.search_evidence. Exceptions acknowledge an exact
    deficit, not a wildcard. Missing/malformed contracts and stale receipts cannot
    be waived by prose. A current-context evaluate_delta receipt can revalidate
    the owners actually measured, bound to each original receipt's digest.
    Caller-supplied revalidated_paths alone never clears evidence.
    """
    if purpose not in PURPOSES:
        raise ValueError(f"purpose는 {PURPOSES} 중 하나여야 한다")
    issues: list[dict[str, Any]] = []
    contract = spec.get("optimization_contract")
    required: Mapping[str, Any] = {}
    if not isinstance(contract, Mapping):
        issues.append(
            _issue(
                "contract_missing",
                "",
                "optimization_contract",
                "최종 추천에는 호출자가 정한 최적화 계약이 필요하다",
            )
        )
        contract = {}
    elif (
        contract.get("version") != 1
        or isinstance(contract.get("version"), bool)
        or set(contract) - {"version", "required_components", "exceptions"}
    ):
        issues.append(
            _issue(
                "invalid_contract",
                "",
                "optimization_contract",
                "지원하는 계약은 version 1이며 알려진 필드만 허용한다",
            )
        )
    components = contract.get("required_components")
    if not isinstance(components, Mapping) or not components:
        if not any(row["code"] == "contract_missing" for row in issues):
            issues.append(
                _issue(
                    "invalid_contract",
                    "",
                    "required_components",
                    "추천할 범위의 required_components를 명시해야 한다",
                )
            )
    else:
        required = components
    current_context = derivation_context(dict(spec))
    marks = spec.get("derived_from") or {}
    marks = marks if isinstance(marks, Mapping) else {}
    for component, requirement in required.items():
        component = str(component)
        allowed_keys = {"scope", "settings", "allowed_termination_reasons", "require_converged"}
        if (
            not isinstance(requirement, Mapping)
            or set(requirement) - allowed_keys
            or not isinstance(requirement.get("scope"), Mapping)
            or not requirement["scope"]
        ):
            issues.append(
                _issue(
                    "invalid_contract",
                    component,
                    "required_components",
                    "각 컴포넌트는 명시적인 scope와 지원되는 조건을 가져야 한다",
                )
            )
            continue
        mark = marks.get(component)
        evidence = mark.get("search_evidence") if isinstance(mark, Mapping) else None
        if not isinstance(evidence, Mapping):
            issues.append(
                _issue(
                    "evidence_missing",
                    component,
                    f"derived_from.{component}",
                    "실행 도장만으로 탐색 범위/종료 증거를 대신할 수 없다",
                )
            )
            continue
        # Provenance's normal staleness report excludes the producer's own axis.
        # A final recommendation must additionally bind the evaluated output to
        # the exact output being published, including that own axis.
        assert isinstance(mark, Mapping)
        if not isinstance(mark.get("tool"), str) or not mark["tool"].strip():
            issues.append(
                _issue(
                    "invalid_evidence",
                    component,
                    f"derived_from.{component}.tool",
                    "평가를 실행한 생산자 이름이 누락되었다",
                )
            )
        for key, current_value in current_context.items():
            if not key.endswith("_sig"):
                continue
            if key not in mark:
                issues.append(
                    _issue(
                        "invalid_evidence",
                        component,
                        f"derived_from.{component}.{key}",
                        "평가 산출물의 문맥 서명이 누락되었다",
                        expected=current_value,
                    )
                )
            elif mark[key] != current_value:
                issues.append(
                    _issue(
                        "output_changed",
                        component,
                        f"derived_from.{component}.{key}",
                        "평가한 구성과 출고할 구성이 다르다",
                        expected=current_value,
                        observed=mark[key],
                    )
                )
        if not isinstance(evidence.get("scope"), Mapping) or not evidence["scope"]:
            issues.append(
                _issue(
                    "invalid_evidence",
                    component,
                    "search_evidence.scope",
                    "실제 탐색 범위는 비어 있지 않은 객체로 기록해야 한다",
                )
            )
        if not isinstance(evidence.get("settings"), Mapping):
            issues.append(
                _issue(
                    "invalid_evidence",
                    component,
                    "search_evidence.settings",
                    "실제 실행 설정은 객체로 기록해야 한다",
                )
            )
        if "unresolved" not in evidence:
            issues.append(
                _issue(
                    "invalid_evidence",
                    component,
                    "search_evidence.unresolved",
                    "미해결 항목이 없더라도 명시적인 빈 unresolved 목록을 기록해야 한다",
                )
            )
        issues.extend(
            _scope_issues(requirement["scope"], evidence.get("scope"), component, "scope")
        )
        issues.extend(
            _settings_issues(requirement.get("settings", {}), evidence.get("settings"), component)
        )
        termination = evidence.get("termination")
        if (
            not isinstance(termination, Mapping)
            or not isinstance(termination.get("reason"), str)
            or not termination["reason"].strip()
        ):
            issues.append(
                _issue(
                    "termination_missing",
                    component,
                    "termination",
                    "실제 종료 사유가 기록되지 않았다",
                )
            )
            termination = {}
        allowed = requirement.get("allowed_termination_reasons")
        converged = requirement.get("require_converged")
        if allowed is None and converged is not True:
            issues.append(
                _issue(
                    "invalid_contract",
                    component,
                    "termination",
                    "허용 종료 사유 또는 require_converged:true를 정해야 한다",
                )
            )
        if allowed is not None:
            if (
                not isinstance(allowed, list)
                or not allowed
                or not all(isinstance(value, str) and value for value in allowed)
            ):
                issues.append(
                    _issue(
                        "invalid_contract",
                        component,
                        "termination.reason",
                        "허용 종료 사유는 비어 있지 않은 문자열 목록이어야 한다",
                    )
                )
            elif termination.get("reason") not in allowed:
                issues.append(
                    _issue(
                        "termination_not_allowed",
                        component,
                        "termination.reason",
                        "이번 종료 사유는 계약이 허용한 사유가 아니다",
                        expected=allowed,
                        observed=termination.get("reason"),
                    )
                )
        if converged is not None and not isinstance(converged, bool):
            issues.append(
                _issue(
                    "invalid_contract",
                    component,
                    "require_converged",
                    "require_converged는 불리언이어야 한다",
                )
            )
        elif converged and termination.get("converged") is not True:
            issues.append(
                _issue(
                    "not_converged",
                    component,
                    "termination.converged",
                    "요청한 수렴 종료 증거가 없다",
                    expected=True,
                    observed=termination.get("converged"),
                )
            )

    stale = stale_components(dict(spec))
    stale_paths = {row.get("path", f"derived_from.{row['component']}") for row in stale}
    receipts = list(_stamps(spec))
    receipt_by_path = {path: mark for path, _, mark in receipts}
    owner_by_path = _owners(spec)
    revalidated: dict[str, str] = {}
    for path, component, mark in receipts:
        evidence = mark.get("search_evidence")
        if path in stale_paths or not isinstance(evidence, Mapping):
            continue
        if path != f"derived_from.{component}" or component not in required:
            continue
        if any(row["component"] == component for row in issues):
            continue
        unresolved = evidence.get("unresolved")
        if not isinstance(unresolved, list) or any(
            not isinstance(row, Mapping) or row.get("code") != "items_pob_gaps"
            for row in unresolved
        ):
            continue
        # Old unversioned marks cannot certify a fresh-context re-evaluation.
        if mark.get("context_version") != 2:
            continue
        records = evidence.get("revalidation_receipts", {})
        if not records:
            continue
        if (
            mark.get("tool") != "evaluate_delta"
            or evidence.get("review_version") != 1
            or not isinstance(records, Mapping)
        ):
            issues.append(
                _issue(
                    "invalid_revalidation",
                    component,
                    path,
                    "재검증은 실제 evaluate_delta 평가 영수증이어야 한다",
                )
            )
            continue
        scope = evidence.get("scope", {})
        measured = evidence.get("measurements", {})
        for covered, record in records.items():
            owner = owner_by_path.get(covered)
            target = receipt_by_path.get(covered)
            valid = isinstance(record, Mapping) and owner is not None and target is not None
            if valid:
                assert isinstance(record, Mapping) and owner is not None and target is not None
                kind = owner["collection"]
                owner_key, scope_key = (
                    ("slot", "slots") if kind == "items" else ("socket_node_id", "jewel_sockets")
                )
                labels = record.get("variant_labels")
                valid = (
                    component == kind
                    and record.get("owner") == owner
                    and record.get("receipt_sha256") == _receipt_digest(target)
                    and owner[owner_key] in scope.get(scope_key, [])
                    and isinstance(labels, list)
                    and bool(labels)
                    and all(isinstance(label, str) for label in labels)
                    and isinstance(measured, Mapping)
                    and bool(evidence.get("baseline_stats"))
                    and all(
                        label in measured and label in scope.get("candidates", [])
                        for label in labels
                    )
                )
            if not valid:
                issues.append(
                    _issue(
                        "invalid_revalidation",
                        component,
                        str(covered),
                        "재검증 대상/슬롯/원본 도장/성공 측정 범위가 일치하지 않는다",
                        observed=record,
                    )
                )
            elif covered in stale_paths:
                revalidated[str(covered)] = path
    for row in stale:
        path = row.get("path", f"derived_from.{row['component']}")
        if path not in revalidated:
            issues.append(
                _issue(
                    "context_unverified" if row.get("status") == "unverified" else "stale_evidence",
                    str(row["component"]),
                    path,
                    str(row["why"]),
                    observed=row,
                )
            )
    for path, component, mark in receipts:
        evidence = mark.get("search_evidence")
        if not isinstance(evidence, Mapping):
            continue
        unresolved = evidence.get("unresolved", [])
        if not isinstance(unresolved, list):
            issues.append(
                _issue(
                    "invalid_evidence",
                    component,
                    f"{path}.search_evidence.unresolved",
                    "unresolved는 목록이어야 한다",
                    observed=unresolved,
                )
            )
            continue
        for entry in unresolved:
            issues.append(
                _issue(
                    "unresolved_evidence",
                    component,
                    path,
                    "미측정/미해결 항목을 처리해야 한다",
                    observed=entry,
                )
            )

    exceptions = contract.get("exceptions", [])
    accepted: dict[str, str] = {}
    nonwaivable = {
        "contract_missing",
        "invalid_contract",
        "invalid_evidence",
        "stale_evidence",
        "context_unverified",
        "evidence_missing",
        "output_changed",
        "termination_missing",
        "invalid_revalidation",
    }
    by_id = {row["issue_id"]: row for row in issues}
    if not isinstance(exceptions, list):
        issues.append(_issue("invalid_contract", "", "exceptions", "exceptions는 목록이어야 한다"))
    else:
        for exception in exceptions:
            if (
                not isinstance(exception, Mapping)
                or set(exception) != {"issue_id", "reason"}
                or not isinstance(exception.get("reason"), str)
                or not exception["reason"].strip()
            ):
                issues.append(
                    _issue(
                        "invalid_contract",
                        "",
                        "exceptions",
                        "예외는 정확한 issue_id와 비어 있지 않은 reason이 필요하다",
                    )
                )
                continue
            identity = exception.get("issue_id")
            issue = by_id.get(identity) if isinstance(identity, str) else None
            if issue is None or issue["code"] in nonwaivable:
                issues.append(
                    _issue(
                        "invalid_contract",
                        "",
                        "exceptions",
                        "존재하지 않거나 문구로 면제할 수 없는 항목이다",
                        observed=identity,
                    )
                )
            else:
                accepted[str(identity)] = exception["reason"].strip()
    blockers = [row for row in issues if row["issue_id"] not in accepted]
    waived = [
        {**row, "exception_reason": accepted[row["issue_id"]]}
        for row in issues
        if row["issue_id"] in accepted
    ]
    return {
        "version": 1,
        "purpose": purpose,
        "status": "not_ready" if blockers else ("ready_with_exceptions" if waived else "ready"),
        "recommendation_ready": not blockers,
        "scope": dict(required),
        "blockers": blockers,
        "accepted_exceptions": waived,
        "revalidated_paths": revalidated,
        "qualification": {
            "kind": "explicit_exceptions" if waived else "declared_scope",
            "known_limitations": [
                {
                    key: row[key]
                    for key in (
                        "issue_id",
                        "component",
                        "path",
                        "detail",
                        "expected",
                        "observed",
                        "exception_reason",
                    )
                }
                for row in waived
            ],
            "global_optimum_proven": False,
            "gameplay_validated": False,
            "model_context_verified": False,
        },
        "claim": "declared_evidence_contract_only_not_global_optimum_or_game_validation",
    }
