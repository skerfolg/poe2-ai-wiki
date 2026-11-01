"""Experimental F/O/P MCP surfaces; never the normal registered PoK server.

No generation stages, model calls, recommendations or game decisions live here.
Each server owns a fresh artifact namespace and explicitly records its surface.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

OPTIMIZERS = frozenset({"optimize_tree", "optimize_items", "optimize_rare", "optimize_runes"})
TOOLS = frozenset(
    [
        "get_tool_result",
        "search_kb",
        "get_entry",
        "search_insights",
        "get_insight",
        "server_info",
        "describe_kb",
        "describe_type",
        "find_by_value",
        "related",
        "compute_pob",
        "evaluate_delta",
        "check_item_legality",
        "assemble_pob",
        "parse_pob",
        "restore_pob_spec",
        "measure_leverage",
        "check_pob_stability",
        "audit_config_upkeep",
        "check_constraints",
        "evaluate_objective",
        "parse_design_doc",
        "list_builds",
        "compute_trigger_rate",
        "connect_anchors",
        "optimize_tree",
        "prepare_tree_variant",
        "measure_tree_slack",
        "evaluate_bundles",
        "evaluate_change_bundle",
        "optimize_items",
        "optimize_rare",
        "list_implicits",
        "optimize_runes",
        "find_clusters",
        "passed_over_nodes",
        "suggest_anchors",
        "scan_synergies",
        "discover_mechanics",
        "find_hypotheses",
        "find_carriers",
        "find_payloads",
        "scan_supply_edges",
        "trace_chains",
        "scan_state_edges",
        "trace_mechanism_chains",
        "trace_cross_chains",
        "scan_scalers",
        "scan_antagonists",
        "scan_enablers",
    ]
)
REFERENCE_TOOLS = frozenset(
    {
        "get_tool_result",
        "server_info",
        "compute_pob",
        "evaluate_delta",
        "check_item_legality",
        "assemble_pob",
        "parse_pob",
        "restore_pob_spec",
        "connect_anchors",
        "list_builds",
    }
)


def allowed_names(arm: str) -> frozenset[str]:
    if arm == "R":
        return REFERENCE_TOOLS
    if arm not in {"F", "O", "P"}:
        raise ValueError("Expected an explicit experimental arm F/O/P/R")
    return TOOLS - OPTIMIZERS if arm == "F" else TOOLS


def export_problems(arm: str, build_spec: dict[str, Any], purpose: str) -> list[str]:
    """F/O cannot reach hidden rare optimization through the export path."""
    allowed_names(arm)
    if arm == "P":
        return []
    from pok.engine.autofill import unstamped_rares

    problems = []
    if purpose != "exploration":
        problems.append("This arm exports exploration builds; recommendation gates are excluded.")
    if unstamped_rares(build_spec):
        problems.append(
            "Export cannot automatically replace rare items in this arm. Supply actual item text "
            "and its provenance. For an intentional manual item, use derived_from.tool=manual "
            "and derived_from.why. No optimizer call is required for a manual item."
        )
    return problems


def path_problems(
    name: str, arguments: dict[str, Any], artifacts: Path, repository: Path
) -> list[str]:
    """Prevent optional path arguments from reading another run's answers."""
    if name == "parse_pob" and arguments.get("code_path"):
        candidate = Path(arguments["code_path"]).expanduser().resolve()
        if not candidate.is_relative_to(artifacts.resolve()):
            return ["code_path must remain in this run's artifact namespace"]
    if name == "parse_design_doc":
        identifier = arguments.get("build_id", "")
        if not identifier or Path(identifier).name != identifier or identifier in {".", ".."}:
            return ["build_id must identify a build in this run, not a path"]
    if name == "list_implicits" and arguments.get("root_dir"):
        candidate = Path(arguments["root_dir"]).resolve()
        if candidate not in {repository.resolve(), (repository / "knowledge").resolve()}:
            return ["root_dir must identify the frozen common KB"]
    return []


def artifact_file(
    root: Path, action: str, path: str = "", text: str = "", expected_sha256: str | None = None
) -> dict[str, Any]:
    """Shared experiment I/O only; no shell, game decisions or external paths."""
    destination = (root / path).resolve()
    if not destination.is_relative_to(root.resolve()):
        raise ValueError("File path escapes this experiment's artifacts")
    if action == "list":
        return {
            "entries": [
                {"name": p.name, "directory": p.is_dir()} for p in sorted(destination.iterdir())
            ]
            if destination.exists()
            else []
        }
    if action not in {"read", "write"}:
        raise ValueError("Expected list, read or write")
    if destination == root.resolve():
        raise ValueError("Read/write requires a file path inside the artifact root")
    if action == "write" and destination.is_relative_to(root.resolve() / "inputs"):
        raise ValueError("Common experiment inputs are read-only")
    before = destination.read_bytes() if destination.is_file() else None
    digest = hashlib.sha256(before).hexdigest() if before is not None else None
    if action == "read":
        if before is None:
            return {"ok": False, "reason": "File not found"}
        return {"ok": True, "text": before.decode("utf-8"), "sha256": digest}
    if expected_sha256 is not None and expected_sha256 != digest:
        return {"ok": False, "reason": "File changed since the expected revision", "sha256": digest}
    destination.parent.mkdir(parents=True, exist_ok=True)
    raw = text.encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as staged:
        staged.write(raw)
        temporary = Path(staged.name)
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {"ok": True, "path": str(destination), "sha256": hashlib.sha256(raw).hexdigest()}


def configure(server: Any, arm: str, artifacts: Path, repository: Path) -> dict[str, Any]:
    """Configure only a fresh process; refuse catalog drift instead of guessing."""
    permitted = allowed_names(arm)
    actual = frozenset(server._TOOL_PARAMS)
    if actual != TOOLS:
        raise ValueError(f"Catalog drift: missing={TOOLS - actual}, extra={actual - TOOLS}")
    remove = getattr(server.mcp, "local_provider", server.mcp).remove_tool

    def restrict_paths(name: str) -> None:
        original = getattr(server, name).__wrapped__

        @functools.wraps(original)
        def scoped(*args: Any, **kwargs: Any) -> Any:
            import inspect

            bound = inspect.signature(original).bind(*args, **kwargs)
            bound.apply_defaults()
            problems = path_problems(name, dict(bound.arguments), artifacts, repository)
            if problems:
                return {"ok": False, "blocking": problems, "experimental_arm": arm}
            return original(*bound.args, **bound.kwargs)

        remove(name)
        server.tool(scoped)

    for name in ("parse_pob", "parse_design_doc", "list_implicits"):
        restrict_paths(name)
    if arm != "P":
        from pok.mcp.tools import build

        original = build.assemble_pob

        @functools.wraps(original)
        def exploration_export(*args: Any, **kwargs: Any) -> dict[str, Any]:
            import inspect

            bound = inspect.signature(original).bind(*args, **kwargs)
            bound.apply_defaults()
            problems = export_problems(
                arm, bound.arguments["build_spec"], bound.arguments["purpose"]
            )
            if problems:
                return {"ok": False, "experimental_arm": arm, "blocking": problems}
            return original(*bound.args, **bound.kwargs)

        # The same input schema is retained; only the experimental export policy
        # differs. The frozen arm prompt discloses this policy before generation.
        exploration_export.__name__ = "assemble_pob"
        remove("assemble_pob")
        server.tool(exploration_export)
    for name in actual - permitted:
        remove(name)
        server._TOOL_PARAMS.pop(name)

    def experiment_file(
        action: str, path: str = "", text: str = "", expected_sha256: str | None = None
    ) -> dict[str, Any]:
        """Read/write/list only this run's artifacts, using relative paths.

        Use builds/<build_id>/design.md for a build design document, or sessions/
        for drafts. Write returns a full path usable as parse_pob.code_path.
        Supplied common fixtures under inputs/ can be read but not overwritten.
        This common harness operation replaces file editing, not engine tools.
        """
        return artifact_file(artifacts, action, path, text, expected_sha256)

    server.tool(experiment_file)
    extra = {"experiment_file"}
    if arm == "R":
        import importlib.util

        server.mcp.instructions = (
            "R raw-source reference. Use raw_source list/read/search on fixed raw and PoB text. "
            "Canonical KB search, graph navigation and optimizers are not exposed. "
            "Basic calculation/validation and scoped file I/O are shared with other arms. "
            "This is not an exact replay of any previous experiment."
        )

        path = Path(__file__).with_name("redesign_raw.py")
        spec = importlib.util.spec_from_file_location("redesign_raw_reference", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from pok.pob.versions import resolve_snapshot

        pools = {
            "raw": repository / "artifacts/ingest-raw",
            "pob": resolve_snapshot().root,
        }

        def raw_source(
            pool: str,
            action: str,
            path: str = "",
            query: str = "",
            offset: int = 0,
            limit: int = 20,
        ) -> dict[str, Any]:
            """Literal list/read/search of fixed raw or pob text; no canonical KB navigation.

            raw contains ingestion snapshots, ladder and recorded observations.
            read uses character offsets; list/search use entry offsets. No files are written.
            """
            result: dict[str, Any] = module.raw_source(
                pools, pool, action, path, query, offset, limit
            )
            return result

        server.tool(raw_source)
        extra.add("raw_source")

    return {
        "arm": arm,
        "tools": sorted(permitted | extra),
        "optimizers_exposed": bool(permitted & OPTIMIZERS),
        "automatic_export_optimization": arm == "P",
        "recommendation_gate": arm == "P",
        "basic_fact_checks": "unchanged",
        "optional_file_inputs": "run artifacts or frozen common KB only, identical for all arms",
        "common_harness_file_tool": "experiment_file; no executable code or outside paths",
        "normal_server_modified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arm", choices=["F", "O", "P", "R"], required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    from pok.common import paths
    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()
    root = Path(args.run_dir).resolve()
    if not root.is_relative_to(paths.project_root() / "artifacts"):
        raise ValueError("Experiment run directory must remain inside the existing artifacts root")
    destination = root / "artifacts"
    destination.mkdir(parents=True, exist_ok=True)

    # Install the namespace before importing consumers, so bound imports agree.
    # KB, PoB and factual checks stay the same for all arms.
    def artifact_root(root: Path | None = None) -> Path:
        return destination

    paths.artifacts_dir = artifact_root
    cache = root / "var"
    cache.mkdir(parents=True, exist_ok=True)

    def cache_root(root: Path | None = None) -> Path:
        return cache

    paths.var_dir = cache_root
    from pok.mcp import server

    manifest = configure(server, args.arm, destination, paths.project_root())
    (root / "server-policy.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    server.main()


if __name__ == "__main__":
    main()
