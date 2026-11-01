"""R5 product surface with trial-local storage, without R1 arm restrictions.

The controller selects a frozen product via PYTHONPATH. This module changes no
build policy and imports the product only after installing its storage namespace.
"""

from __future__ import annotations

import argparse
import functools
import inspect
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from redesign_server import artifact_file, path_problems

CONTROL_ROOT = Path(__file__).resolve().parents[2]


def trial_file(
    artifacts: Path,
    action: str,
    path: str = "",
    text: str = "",
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Read this trial; write only work notes, never machine-issued evidence."""
    root = artifacts.resolve()
    target = (root / path).resolve()
    work = root / "work"
    if action == "write" and (target == work or not target.is_relative_to(work)):
        raise ValueError(
            "Only work/ drafts are writable; inputs, references and receipts are read-only"
        )
    return artifact_file(root, action, path, text, expected_sha256)


def configure_product(server: Any, artifacts: Path, repository: Path) -> dict[str, Any]:
    """Keep the product catalog and factual checks; add only common trial I/O."""
    normal = frozenset(server._TOOL_PARAMS)
    if "experiment_file" in normal:
        raise ValueError("Product already owns the common trial I/O tool name")
    remove = getattr(server.mcp, "local_provider", server.mcp).remove_tool
    guarded = []
    for name in ("parse_pob", "parse_design_doc", "list_implicits"):
        if name not in normal:
            continue
        original = getattr(server, name).__wrapped__

        def bind_guard(function: Any, tool_name: str) -> Any:
            @functools.wraps(function)
            def scoped(*args: Any, **kwargs: Any) -> Any:
                bound = inspect.signature(function).bind(*args, **kwargs)
                bound.apply_defaults()
                problems = path_problems(tool_name, dict(bound.arguments), artifacts, repository)
                if problems:
                    return {"ok": False, "blocking": problems, "scope": "trial_path_isolation"}
                return function(*bound.args, **bound.kwargs)

            return scoped

        remove(name)
        server.tool(bind_guard(original, name))
        guarded.append(name)

    def experiment_file(
        action: str,
        path: str = "",
        text: str = "",
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Read own artifacts/inputs/references; write drafts only under work/."""
        return trial_file(artifacts, action, path, text, expected_sha256)

    server.tool(experiment_file)
    actual = frozenset(server._TOOL_PARAMS)
    if actual != normal | {"experiment_file"}:
        raise ValueError("Product catalog changed while configuring trial isolation")
    return {
        "format": "pok.product-trial-server.v1",
        "product_tools": sorted(normal),
        "tools": sorted(actual),
        "path_guarded_tools": guarded,
        "build_policy": "unchanged_product_implementation",
        "optimizer_and_recommendation_policy": "unchanged_product_implementation",
        "common_trial_io": {"tool": "experiment_file", "write_prefix": "work/"},
    }


def validate_locations(product_root: Path, run_dir: Path, control_root: Path) -> tuple[Path, Path]:
    product, run, control = product_root.resolve(), run_dir.resolve(), control_root.resolve()
    if not product.is_relative_to(control):
        raise ValueError("Frozen product must remain inside the controlled workspace")
    if not all(
        (product / marker).exists() for marker in ("pyproject.toml", "knowledge", "src/pok")
    ):
        raise ValueError("Frozen product markers are missing")
    if not run.is_relative_to(control / "artifacts") or run == control / "artifacts":
        raise ValueError("Trial data must remain in its own workspace artifact directory")
    if product != control and (run.is_relative_to(product) or product.is_relative_to(run)):
        raise ValueError("Trial storage must not overlap a frozen product checkout")
    return product, run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--product-root", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    product, run = validate_locations(args.product_root, args.run_dir, CONTROL_ROOT)
    from pok.common import paths
    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()
    if paths.project_root().resolve() != product:
        raise ValueError("Loaded PoK differs from the selected frozen product")
    artifacts, cache = run / "artifacts", run / "var"
    artifacts.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)

    # Install before importing consumers with bound path-function imports.
    paths.artifacts_dir = lambda root=None: artifacts
    paths.var_dir = lambda root=None: cache
    from pok.mcp import server

    policy = configure_product(server, artifacts, product)
    policy["product_root"] = str(product)
    policy["artifacts"] = str(artifacts)
    policy["cache"] = str(cache)
    with (run / f"server-policy-{uuid4().hex}.json").open("x", encoding="utf-8") as receipt:
        json.dump(policy, receipt, ensure_ascii=False, indent=2)
        receipt.write("\n")
    server.main()


if __name__ == "__main__":
    main()
