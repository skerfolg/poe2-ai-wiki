"""Phase-scoped product transport for the autonomous skill, not an engine solver."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from autonomous_contract import FLOW_SCHEMA, PLANNING_REVIEW_SCHEMA
from product_server import CONTROL_ROOT, configure_product, validate_locations
from session import READ_TOOLS

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


def configure_workflow(
    server: Any,
    stage: int,
    context: dict[str, Any],
    on_checkpoint: Callable[[dict[str, Any]], None] | None = None,
) -> list[str]:
    """Enforce the design-only boundary and keep human replies outside model writes."""
    if stage not in range(1, 6):
        raise ValueError("Unknown workflow stage")

    def budget() -> float | None:
        deadline = context.get("turn_deadline_unix")
        return max(0.0, deadline - time.time()) if isinstance(deadline, int | float) else None

    remove = getattr(server.mcp, "local_provider", server.mcp).remove_tool
    for name in {"create_design_record", "import_design_document"} & set(server._TOOL_PARAMS):
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
            if change.get("op") == "upsert_decision":
                if value.get("id") in fixed_ids:
                    raise ValueError("Host-owned user request is immutable")
                if value.get("role") == "user_fixed":
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
            return cast(dict[str, Any], result)

        server.tool(
            attach_pob_document_measurement,
            literal_arguments=frozenset({"record_ref", "document_measurement_ref"}),
        )

    def workflow_context() -> dict[str, Any]:
        """Read controller-owned stage, exact design ref and scoped human replies."""
        return {
            **context,
            "flow_extension_schema": FLOW_SCHEMA,
            "planning_review_schema": PLANNING_REVIEW_SCHEMA,
            "workflow_time_remaining_s": budget(),
            "actual_tools": sorted(server._TOOL_PARAMS),
        }

    server.tool(workflow_context)

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

    def workflow_read_record(section: str = "flow", ids: list[str] | None = None) -> dict[str, Any]:
        """Read a typed projection of the current sealed record, without editing it.

        Read decisions/evidence/questions by ID. Without IDs, return an index.
        This avoids paging the entire opaque JSON just to resume a saved design.
        """
        from pok.engine.design_checkpoints import load_checkpoint

        saved = load_checkpoint(context["record_ref"])
        record = json.loads(saved["record_json"])
        if section == "flow":
            value = record.get("extensions", {}).get("autonomous_flow", {})
        elif section == "mechanism":
            value = record.get("mechanism_summary", "")
        elif section in {"decisions", "evidence", "questions"}:
            rows = record[section]
            if ids:
                if set(ids) - {row["id"] for row in rows}:
                    raise ValueError("Projection requested unknown IDs")
                value = [row for row in rows if row["id"] in ids]
            else:
                value = [
                    {
                        key: row[key]
                        for key in ("id", "title", "label", "role", "adoption")
                        if key in row
                    }
                    for row in rows
                ]
        else:
            raise ValueError("Expected flow, mechanism, decisions, evidence or questions")
        return {
            "record_ref": context["record_ref"],
            "section": section,
            "value": value,
            "projection_only": True,
            "canonical_json_unchanged": True,
            "workflow_time_remaining_s": budget(),
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

    actual = configure_workflow(server, context["stage"], context, checkpoint)
    policy = {
        "stage": context["stage"],
        "actual_tools": actual,
        "assembly_enabled": context["stage"] >= 4,
        "product_root": str(product),
    }
    context_path.with_suffix(".policy.json").write_text(
        json.dumps(policy, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    server.main()


if __name__ == "__main__":
    main()
