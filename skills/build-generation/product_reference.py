"""Current raw-reference surface; no model calls or build selection."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from product_integrity import load_pinned_json
from product_server import configure_product
from redesign_raw import raw_source as read_raw

BASIC_TOOLS = frozenset(
    {
        "get_tool_result",
        "server_info",
        "compute_pob",
        "check_item_legality",
        "assemble_pob",
        "parse_pob",
        "restore_pob_spec",
        "connect_anchors",
        "list_builds",
        "read_pob_document",
        "prepare_pob_delivery",
    }
)


def explicit_export(function: Callable[..., Any]) -> Callable[..., Any]:
    """Reference assembly never enters the legacy automatic rare selection path."""

    original_signature = inspect.signature(function)
    signature = original_signature.replace(
        parameters=[
            parameter.replace(default="explicit") if parameter.name == "input_policy" else parameter
            for parameter in original_signature.parameters.values()
        ]
    )

    @functools.wraps(function)
    def guarded(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(*args, **kwargs)
        if bound.arguments.get("input_policy", "explicit") != "explicit":
            return {"ok": False, "blocking": ["Reference export requires input_policy=explicit"]}
        if bound.arguments.get("purpose", "exploration") != "exploration":
            return {
                "ok": False,
                "blocking": ["Reference export uses exploration, not recommendation"],
            }
        bound.apply_defaults()
        bound.arguments["input_policy"] = "explicit"
        return function(*bound.args, **bound.kwargs)

    # FastMCP injects schema defaults before invoking the wrapper. Publish the
    # actual reference default rather than the wrapped product's legacy default.
    cast(Any, guarded).__signature__ = signature
    guarded.__doc__ = (
        "Explicit reference assembly; input_policy defaults to explicit. "
        "Legacy automatic rare selection and recommendation exports are rejected. "
        "Calculation/legality do not certify build quality or game feasibility."
    )
    return guarded


def configure_reference(
    server: Any,
    artifacts: Path,
    repository: Path,
    *,
    expected_tools: frozenset[str],
    facts: Path,
    pob: Path,
) -> dict[str, Any]:
    """Require a pinned catalog before exposing a strictly bounded basic subset."""
    actual = frozenset(server._TOOL_PARAMS)
    if actual != expected_tools:
        raise ValueError("Reference source catalog differs from its frozen manifest")
    if not actual >= BASIC_TOOLS:
        raise ValueError("Reference source is missing required basic tools")
    if facts.resolve() != (repository / "knowledge").resolve() or not facts.is_dir():
        raise ValueError("Reference facts must be the product's frozen common knowledge")
    if pob.resolve() != (repository / "external/pob/5d173cb").resolve() or not pob.is_dir():
        raise ValueError("Reference PoB must be the product's declared fixed snapshot")
    policy = configure_product(server, artifacts, repository)
    remove = getattr(server.mcp, "local_provider", server.mcp).remove_tool
    original = server.assemble_pob.__wrapped__
    remove("assemble_pob")
    server.tool(explicit_export(original))
    for name in actual - BASIC_TOOLS:
        remove(name)
        server._TOOL_PARAMS.pop(name)
    pools = {"facts": facts.resolve(), "pob": pob.resolve()}

    def raw_source(
        pool: str,
        action: str,
        path: str = "",
        query: str = "",
        offset: int = 0,
        limit: int = 20,
    ) -> dict[str, Any]:
        """Literal read/list/search of frozen facts or PoB text; no ranking or optimizer.

        facts is the same fixed KB/insights served to product arms, presented as
        literal files. Ingestion/ladder/proposals/prior trial answers are excluded.
        read offsets are characters; list/search offsets are entries.
        """
        return read_raw(pools, pool, action, path, query, offset, limit)

    server.tool(raw_source)
    expected_surface = BASIC_TOOLS | {"experiment_file", "raw_source"}
    if frozenset(server._TOOL_PARAMS) != expected_surface:
        raise ValueError("Reference surface differs after restriction")
    server.mcp.instructions = (
        "Direct-design reference: use raw_source on the same fixed facts and PoB text. "
        "No KB API/graphs/optimizers/product generation workflow are exposed. "
        "Basic calculation, explicit assembly and file delivery share PoK libraries; "
        "this is not a literal no-PoK replay. Assembly defaults to explicit inputs and "
        "exploration; legacy automatic rare selection and recommendation are rejected. "
        "Write notes/manual XML only under experiment_file work/. "
        "Do not access other trials or infer quality from successful calculation."
    )
    return {
        **policy,
        "format": "pok.reference-product-surface.v1",
        "source_catalog": sorted(actual),
        "tools": sorted(expected_surface),
        "raw_pools": {key: str(value) for key, value in pools.items()},
        "automatic_export_optimization": False,
        "reference_workflow": "direct_design",
        "claim": "shared_basic_libraries_not_pure_no_pok_or_optimizer_only_comparison",
    }


def load_reference_policy(reference: dict[str, str], control_root: Path) -> dict[str, Any]:
    """A hash-pinned, controller-only catalog; never learn it from the live server."""
    if set(reference) != {"path", "sha256"}:
        raise ValueError("Expected reference policy path and sha256")
    path = Path(reference["path"]).resolve()
    if not path.is_relative_to(control_root.resolve() / "artifacts"):
        raise ValueError("Reference policy must remain inside controlled artifacts")
    value = load_pinned_json(path, reference["sha256"])
    tools = value.get("source_tools")
    if (
        set(value) != {"format", "source_tools"}
        or value["format"] != "pok.reference-policy.v1"
        or not isinstance(tools, list)
        or not all(isinstance(name, str) and name for name in tools)
        or len(set(tools)) != len(tools)
        or not set(tools) >= BASIC_TOOLS
    ):
        raise ValueError("Invalid frozen reference policy")
    return value
