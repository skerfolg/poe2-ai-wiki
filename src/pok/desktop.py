"""Desktop runtime CLI used by pok-ui bundles."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import NoReturn

from pok.common.stdio import force_utf8_stdio
from pok.pob.runtime_identity import runtime_identity


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _serve(_args: argparse.Namespace) -> NoReturn:
    force_utf8_stdio()
    from pok.mcp.server import main

    main()
    raise SystemExit(0)


def _identity(args: argparse.Namespace) -> int:
    _print_json(runtime_identity(Path(args.root).resolve() if args.root else None))
    return 0


def _export_ui(args: argparse.Namespace) -> int:
    try:
        module = importlib.import_module("pok.pob.ui_export")
    except ModuleNotFoundError as exc:
        raise SystemExit("pok.pob.ui_export is not available in this runtime") from exc
    export_catalog = module.export_catalog
    result = export_catalog(Path(args.output).resolve())
    _print_json(result if isinstance(result, dict) else {"path": str(result)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m pok.desktop")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Run the MCP server over stdio")
    serve.set_defaults(func=_serve)
    identity = sub.add_parser("identity", help="Print runtime identity")
    identity.add_argument("--root", default="")
    identity.set_defaults(func=_identity)
    export = sub.add_parser("export-ui", help="Export PoB-derived UI catalog")
    export.add_argument("--output", required=True)
    export.set_defaults(func=_export_ui)
    return parser


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
