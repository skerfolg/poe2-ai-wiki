"""Phase-scoped product transport for the autonomous skill, not an engine solver."""

from __future__ import annotations

import argparse
import functools
import inspect
import json
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from autonomous_contract import FLOW_SCHEMA, PLANNING_REVIEW_SCHEMA
from product_server import CONTROL_ROOT, configure_product, validate_locations
from session import READ_TOOLS
from source_policy import (
    BLOCKED_TYPES,
    DROP,
    EDIT_OPERATIONS,
    POK_PRIMARY,
    WEB_REFERENCE,
    fetch_data,
    scrub_records,
)

DESIGN_TOOLS = READ_TOOLS | {
    "server_info",
    "get_server_capabilities",
    "describe_kb",
    "get_tool_result",
    "get_design_record_schema",
    "read_design_record",
    "inspect_design_record",
    "update_design_record",
    "check_constraints",
    "prepare_tree_variant",
    "check_item_legality",
    "compute_trigger_rate",
    "connect_anchors",
    "experiment_file",
}


def checkpoint_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Small receipt; full assessments remain available through explicit inspection."""
    output: dict[str, Any] = {
        key: result[key] for key in ("record_ref", "workflow_time_remaining_s") if key in result
    }
    assessment = result.get("current_assessment")
    if isinstance(assessment, dict):
        diagnostics = assessment.get("diagnostics", [])
        output["current_assessment"] = {
            "checks": assessment.get("checks", {}),
            "diagnostics": diagnostics[:8],
            "diagnostic_count": len(diagnostics),
            "full_detail_tool": "inspect_design_record",
        }
    return output


def is_review_only_refresh(old: dict[str, Any], new: dict[str, Any]) -> bool:
    """Review bookkeeping is not permission to change a protected user choice."""
    return (
        old.get("review", {}).get("state") == "required"
        and "review" not in new
        and {key: value for key, value in old.items() if key != "review"} == new
    )


def configure_workflow(
    server: Any,
    stage: int,
    context: dict[str, Any],
    on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
    on_source: Callable[[dict[str, Any]], None] | None = None,
) -> list[str]:
    """Enforce the design-only boundary and keep human replies outside model writes."""
    if stage not in range(1, 6):
        raise ValueError("Unknown workflow stage")
    if context.get("source_policy", WEB_REFERENCE) not in {POK_PRIMARY, WEB_REFERENCE}:
        raise ValueError("Unknown source policy")

    def budget() -> float | None:
        deadline = context.get("turn_deadline_unix")
        return max(0.0, deadline - time.time()) if isinstance(deadline, int | float) else None

    remove = getattr(server.mcp, "local_provider", server.mcp).remove_tool
    strict_sources = context.get("source_policy") == POK_PRIMARY
    source_lock = threading.Lock()
    blocked_ids: set[str] = set()
    if strict_sources:
        from pok.index.search import search

        for kind in BLOCKED_TYPES:
            blocked_ids.update(row.id for row in search(type_=kind, limit=10000))

        def fact_reader(function: Any, name: str) -> Any:
            @functools.wraps(function)
            def scoped(*args: Any, **kwargs: Any) -> Any:
                bound = inspect.signature(function).bind(*args, **kwargs)
                bound.apply_defaults()
                if bound.arguments.get("type") in BLOCKED_TYPES:
                    raise ValueError("Full builds and usage profiles are excluded by source policy")
                if bound.arguments.get("id") in blocked_ids:
                    raise ValueError("Full builds and usage profiles are excluded by source policy")
                if "include_narrative" in bound.arguments:
                    bound.arguments["include_narrative"] = False
                requested_limit = bound.arguments.get("limit")
                if name == "search_kb" and isinstance(requested_limit, int):
                    if not 1 <= requested_limit <= 10000:
                        raise ValueError("Expected search limit 1..10000")
                    bound.arguments["limit"] = requested_limit + len(blocked_ids)
                result = scrub_records(function(*bound.args, **bound.kwargs), blocked_ids)
                if result is DROP:
                    raise ValueError("Result excluded by fact-only source policy")
                if (
                    name == "search_kb"
                    and isinstance(result, list)
                    and isinstance(requested_limit, int)
                ):
                    result = result[:requested_limit]
                    if not result:
                        result = [
                            {
                                "empty": True,
                                "why": [
                                    "Full build/profile hits are excluded. "
                                    "Query game entities/effect text instead."
                                ],
                            }
                        ]
                return result

            return scoped

        for name in READ_TOOLS & set(server._TOOL_PARAMS):
            original_read = getattr(server, name).__wrapped__
            remove(name)
            server.tool(fact_reader(original_read, name))
    removed_design_tools = {"create_design_record", "import_design_document"}
    if strict_sources:
        removed_design_tools.add("list_builds")
    for name in removed_design_tools & set(server._TOOL_PARAMS):
        remove(name)
        server._TOOL_PARAMS.pop(name, None)
    if stage <= 3:
        for name in set(server._TOOL_PARAMS) - DESIGN_TOOLS:
            remove(name)
            # FastMCP removal does not remove the product's argument registry.
            server._TOOL_PARAMS.pop(name, None)
    original = server.update_design_record.__wrapped__
    remove("update_design_record")

    def update_design_record(
        record_ref: dict[str, Any],
        expected_revision: str,
        changes: list[dict[str, Any]],
        user_decisions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Explicit child revision. Human permissions must come from workflow replies."""
        if user_decisions:
            raise ValueError("Model cannot grant human permissions")
        if record_ref != context["record_ref"]:
            raise ValueError("Update must extend the current workflow checkpoint")
        if any(x.get("op") == "set_goal" for x in changes):
            raise ValueError("Original user brief is immutable in this workflow")
        fixed_ids = set(context.get("authorized_user_fixed_ids", []))
        for change in changes:
            value = change.get("value") or {}
            if strict_sources:
                op = change.get("op")
                if op not in EDIT_OPERATIONS:
                    raise ValueError(
                        "Unsupported edit op; use workflow_contract('edits'). "
                        "Extensions use merge_extensions with op/value only"
                    )
                expected_keys = {"op", "id"} if op.startswith("remove_") else {"op", "value"}
                if set(change) != expected_keys:
                    raise ValueError("Edit fields do not match workflow_contract('edits')")
                if op == "upsert_evidence" and value.get("kind") == "external":
                    receipts = context.get("_source_receipts", {})
                    url = (value.get("source") or {}).get("url")
                    if not any(row.get("url") == url for row in receipts.values()):
                        raise ValueError(
                            "External evidence needs a real issued primary-source receipt"
                        )
            if change.get("op") == "upsert_decision":
                if value.get("id") in fixed_ids:
                    from pok.engine.design_checkpoints import load_checkpoint

                    record = json.loads(load_checkpoint(record_ref)["record_json"])
                    old = next(x for x in record["decisions"] if x["id"] == value["id"])
                    if not is_review_only_refresh(old, value):
                        raise ValueError("Host-owned user request is immutable")
                elif value.get("role") == "user_fixed":
                    raise ValueError("Only the host may establish user_fixed provenance")
            if change.get("op") == "remove_decision" and change.get("id") in fixed_ids:
                raise ValueError("Host-owned user request is immutable")
        if stage <= 3 and any(x.get("op") == "set_material" for x in changes):
            raise ValueError("Design-only run cannot attach PoB material")
        result = original(record_ref, expected_revision, changes, user_decisions=None)
        if result.get("record_ref"):
            context["record_ref"] = result["record_ref"]
            if on_checkpoint:
                on_checkpoint(result["record_ref"])
        result["workflow_time_remaining_s"] = budget()
        if strict_sources:
            return checkpoint_summary(result)
        return cast(dict[str, Any], result)

    server.tool(update_design_record, literal_arguments=frozenset({"record_ref", "changes"}))

    if "attach_pob_document_measurement" in server._TOOL_PARAMS:
        attach = server.attach_pob_document_measurement.__wrapped__
        remove("attach_pob_document_measurement")

        def attach_pob_document_measurement(
            record_ref: dict[str, Any],
            expected_revision: str,
            document_measurement_ref: dict[str, Any],
            evidence_id: str,
            label: str,
            description: str,
            path: str = "/stats",
            usage: str = "current",
            material_revision: str | None = None,
            decision_ids: list[str] | None = None,
        ) -> dict[str, Any]:
            """Attach real measurement and advance the host-owned checkpoint."""
            if record_ref != context["record_ref"]:
                raise ValueError("Measurement must extend the current workflow checkpoint")
            result = attach(
                record_ref,
                expected_revision,
                document_measurement_ref,
                evidence_id,
                label,
                description,
                path,
                usage,
                material_revision,
                decision_ids,
            )
            if result.get("record_ref"):
                context["record_ref"] = result["record_ref"]
                if on_checkpoint:
                    on_checkpoint(result["record_ref"])
            if strict_sources:
                return checkpoint_summary(result)
            return cast(dict[str, Any], result)

        server.tool(
            attach_pob_document_measurement,
            literal_arguments=frozenset({"record_ref", "document_measurement_ref"}),
        )

    def workflow_context() -> dict[str, Any]:
        """Read controller-owned stage, exact design ref and scoped human replies."""
        if strict_sources:
            return {
                **{k: v for k, v in context.items() if not k.startswith("_")},
                "contract_tool": "workflow_contract",
                "source_receipt_ids": list(context.get("_source_receipts", {})),
                "workflow_time_remaining_s": budget(),
                "actual_tools": sorted(server._TOOL_PARAMS),
            }
        return {
            **context,
            "flow_extension_schema": FLOW_SCHEMA,
            "planning_review_schema": PLANNING_REVIEW_SCHEMA,
            "workflow_time_remaining_s": budget(),
            "actual_tools": sorted(server._TOOL_PARAMS),
        }

    server.tool(workflow_context)

    def workflow_contract(section: str = "edits") -> dict[str, Any]:
        """Read edits/flow/planning/recommendation contract without the entire record."""
        values = {"edits": EDIT_OPERATIONS, "flow": FLOW_SCHEMA, "planning": PLANNING_REVIEW_SCHEMA,
                  "recommendation": {
                      "optimization_contract": {
                          "version": 2,
                          "required_components": ["supports"],
                          "comparisons": [{"result_id": "actual saved evaluate_delta result id",
                                           "selected": "baseline or measured variant key",
                                           "reason": "caller selection reason"}],
                          "design_ref": "current actual design checkpoint reference",
                      },
                      "allowed_components": ["items", "jewels", "tree", "supports", "ascendancy"],
                      "limits": "Use actual saved measurements and current input; no invented IDs. "
                                "A host-owned decision can only be refreshed by removing its "
                                "review field with every other field equal as JSON values. "
                                "That is rechecking unchanged requirements, not human permission "
                                "or changing their intent. Other changes remain prohibited.",
                  }}
        if section not in values:
            raise ValueError("Expected edits, flow, planning or recommendation")
        return {"section": section, "value": values[section]}

    server.tool(workflow_contract)

    def workflow_calculator_options(query: str, limit: int = 30) -> dict[str, Any]:
        """Find pinned PoB configuration keys/labels/conditions, without enabling them.

        An absent result means this catalog has no matching control, not that the
        game state is impossible. Use actual document/skill controls separately.
        """
        from dataclasses import asdict

        from pok.pob.catalog import config_options

        needle = query.strip().casefold()
        if not needle or not 1 <= limit <= 100:
            raise ValueError("Nonempty query and limit between 1 and 100 required")
        matches = [
            option for option in config_options()
            if needle in " ".join(
                (option.var, option.label, option.tooltip, *option.conditions)
            ).casefold()
        ]
        return {"options": [asdict(option) for option in matches[:limit]],
                "total": len(matches), "settings_changed": False,
                "source": "pinned PoB ConfigOptions.lua via pok.pob.catalog"}

    server.tool(workflow_calculator_options)

    def workflow_catalog_source(
        entity_id: str,
        field_path: str = "/data",
        catalog: str = "kb",
    ) -> dict[str, Any]:
        """Return a real catalog source hash and the requested value, not game judgment."""
        from pok.artifacts.tool_results import select
        from pok.engine.design_evidence import value_sha256
        from pok.index.search import get_entry, get_insight

        if catalog not in {"kb", "insight"}:
            raise ValueError("Expected kb or insight")
        if strict_sources and entity_id in blocked_ids:
            raise ValueError("Build/corpus source is excluded")
        record = get_entry(entity_id) if catalog == "kb" else get_insight(entity_id)
        value = select(record, field_path)
        return {
            "source": {
                "catalog": catalog,
                "entity_id": entity_id,
                "record_sha256": value_sha256(record),
                "field_path": field_path,
            },
            "value": value,
            "meaning_verified": False,
            "workflow_time_remaining_s": budget(),
        }

    server.tool(workflow_catalog_source)

    if strict_sources and stage >= 2:

        def workflow_primary_source(
            claim_id: str,
            entity_id: str,
            patch_version: str | None = None,
            focus: str | None = None,
        ) -> dict[str, Any]:
            """Verify an already selected provider using its game data page only.

            First save the claim and provider with PoK evidence. No arbitrary URLs,
            build guides, recommendations or community/wiki tabs are fetched.
            A source receipt proves a read, never the truth of a mechanism interpretation.
            patch_version selects the official patch text mirror instead of the entity page.
            focus pages a literal keyword within that data; it is not an internet search.
            """
            from uuid import uuid4

            from pok.engine.design_checkpoints import load_checkpoint
            from pok.index.search import get_entry

            selected_ref = dict(context["record_ref"])
            saved = load_checkpoint(selected_ref)
            record = json.loads(saved["record_json"])
            claim = next((row for row in record["decisions"] if row["id"] == claim_id), None)
            if claim is None or entity_id not in {p.get("entity_id") for p in claim["providers"]}:
                raise ValueError("Save the claim's concrete PoK provider before web verification")
            evidence = {e["id"]: e for e in record["evidence"]}
            if not any(
                evidence.get(eid, {}).get("kind") == "catalog" for eid in claim["evidence_ids"]
            ):
                raise ValueError("Claim needs PoK catalog evidence before web verification")
            if entity_id in blocked_ids:
                raise ValueError("Build/corpus source is excluded")
            result = fetch_data(get_entry(entity_id), patch_version=patch_version)
            receipt = {k: v for k, v in result.items() if k != "text"}
            receipt.update(
                id=uuid4().hex,
                claim_id=claim_id,
                entity_id=entity_id,
                preselected_record_ref=selected_ref,
                observed_at_utc=datetime.now(UTC).isoformat(),
            )
            # Source bodies and receipts are host-owned, outside experiment_file's namespace.
            source_root = Path(context["_source_root"])
            source_root.mkdir(parents=True, exist_ok=True)
            (source_root / (receipt["id"] + ".txt")).write_bytes(result["text"].encode("utf-8"))
            with source_lock:
                context.setdefault("_source_receipts", {})[receipt["id"]] = receipt
                if on_source:
                    on_source(context["_source_receipts"])
            offset = max(0, result["text"].casefold().find(focus.casefold()) - 200) if focus else 0
            return {
                "receipt": receipt,
                "text": result["text"][offset : offset + 2400],
                "offset": offset,
                "focus_found": focus is None or focus.casefold() in result["text"].casefold(),
                "text_length": len(result["text"]),
                "meaning_verified": False,
            }

        server.tool(workflow_primary_source)

        def workflow_source_text(
            receipt_id: str, offset: int = 0, max_chars: int = 3000
        ) -> dict[str, Any]:
            """Page a real issued game-data source; no arbitrary files or URLs."""
            if receipt_id not in context.get("_source_receipts", {}):
                raise ValueError("Unknown source receipt")
            if offset < 0 or not 1 <= max_chars <= 6000:
                raise ValueError("Expected offset >= 0 and max_chars 1..6000")
            text = (Path(context["_source_root"]) / (receipt_id + ".txt")).read_text(
                encoding="utf-8"
            )
            return {
                "receipt": context["_source_receipts"][receipt_id],
                "text": text[offset : offset + max_chars],
                "text_length": len(text),
            }

        server.tool(workflow_source_text)

    def workflow_read_record(
        section: str = "flow",
        ids: list[str] | None = None,
        offset: int = 0,
        limit: int = 30,
    ) -> dict[str, Any]:
        """Read a typed projection of the current sealed record, without editing it.

        Read decisions/evidence/questions by ID. Without IDs, return an index.
        This avoids paging the entire opaque JSON just to resume a saved design.
        """
        from pok.engine.design_checkpoints import load_checkpoint

        saved = load_checkpoint(context["record_ref"])
        record = json.loads(saved["record_json"])
        next_offset = None
        total = None
        if section == "flow":
            value = record.get("extensions", {}).get("autonomous_flow", {})
        elif section == "material":
            value = record.get("material")
        elif section == "mechanism":
            value = record.get("mechanism_summary", "")
        elif section in {"decisions", "evidence", "questions"}:
            rows = record[section]
            if ids:
                if set(ids) - {row["id"] for row in rows}:
                    raise ValueError("Projection requested unknown IDs")
                value = [row for row in rows if row["id"] in ids]
            else:
                total = len(rows)
                if strict_sources:
                    if offset < 0 or not 1 <= limit <= 100:
                        raise ValueError("Expected offset >= 0 and limit 1..100")
                    rows = rows[offset : offset + limit]
                    next_offset = offset + limit if offset + limit < total else None
                value = [
                    {
                        key: row[key]
                        for key in ("id", "title", "label", "role", "adoption")
                        if key in row
                    }
                    for row in rows
                ]
        else:
            raise ValueError("Expected flow, mechanism, material, decisions, evidence or questions")
        return {
            "record_ref": context["record_ref"],
            "section": section,
            "value": value,
            "projection_only": True,
            "canonical_json_unchanged": True,
            "workflow_time_remaining_s": budget(),
            "total": total,
            "next_offset": next_offset,
        }

    server.tool(workflow_read_record)
    return sorted(server._TOOL_PARAMS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--context", type=Path, required=True)
    args = parser.parse_args()
    product, run = validate_locations(args.product_root, args.run_dir, CONTROL_ROOT)
    context_path = args.context.resolve()
    if not context_path.is_relative_to(run.parent):
        raise ValueError("Workflow context must belong to this run")
    context = json.loads(context_path.read_text(encoding="utf-8"))
    from pok.common import paths
    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()
    if paths.project_root().resolve() != product:
        raise ValueError("Loaded product source differs from requested checkout")
    artifacts, cache = run / "artifacts", run / "var"
    artifacts.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    paths.artifacts_dir = lambda root=None: artifacts
    paths.var_dir = lambda root=None: cache
    from pok.mcp import server

    configure_product(server, artifacts, product)

    def checkpoint(reference: dict[str, Any]) -> None:
        from autonomous_run import write_json

        write_json(context_path.with_suffix(".head.json"), reference)

    ledger = run.parent / "source-ledger.json"
    if context.get("source_policy") == POK_PRIMARY:
        context["_source_root"] = str(run.parent / "source-pages")
        context["_source_receipts"] = (
            json.loads(ledger.read_text(encoding="utf-8")) if ledger.exists() else {}
        )

    def source_checkpoint(receipts: dict[str, Any]) -> None:
        from autonomous_run import write_json

        write_json(ledger, receipts)

    actual = configure_workflow(server, context["stage"], context, checkpoint, source_checkpoint)
    policy = {
        "stage": context["stage"],
        "actual_tools": actual,
        "assembly_enabled": context["stage"] >= 4,
        "product_root": str(product),
        "source_policy": context.get("source_policy", "web-reference"),
    }
    context_path.with_suffix(".policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    server.main()


if __name__ == "__main__":
    main()
