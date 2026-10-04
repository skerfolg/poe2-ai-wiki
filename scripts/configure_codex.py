"""Create a repo-scoped Codex MCP config using this machine's Python.

Run with the project's Python 3.12+ environment. No global settings are changed.
The managed block is replaceable; unrelated settings are preserved verbatim.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

BEGIN = "# BEGIN POK MCP (scripts/configure_codex.py)"
END = "# END POK MCP"
TOOL_TIMEOUT = 1800


def config_block(root: Path, python: Path) -> str:
    # absolute(), not resolve(): resolving a POSIX venv symlink loses the venv.
    quote = lambda value: json.dumps(str(value), ensure_ascii=False)  # noqa: E731
    root = root.resolve()
    python = python.absolute()
    return "\n".join(
        [
            BEGIN,
            "[mcp_servers.pok]",
            f"command = {quote(python)}",
            'args = ["-m", "pok.mcp"]',
            f"cwd = {quote(root)}",
            'env_vars = ["POK_LUAJIT"]',
            "startup_timeout_sec = 60",
            f"tool_timeout_sec = {TOOL_TIMEOUT}",
            "enabled = true",
            "",
            "[mcp_servers.pok.env]",
            f"PYTHONPATH = {quote(root / 'src')}",
            'PYTHONUTF8 = "1"',
            'PYTHONIOENCODING = "utf-8"',
            'POK_AUTOFILL_BUDGET_S = "1200"',
            END,
            "",
        ]
    )


def merge_config(existing: str, block: str) -> str:
    """Replace only our block. Never overwrite a pre-existing user-owned server."""
    parsed = tomllib.loads(existing)
    lines = existing.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if starts or ends:
        if len(starts) != 1 or len(ends) != 1 or starts[0] >= ends[0]:
            raise ValueError("Malformed POK config markers; repair the managed block first.")
        outside = "".join(lines[: starts[0]] + lines[ends[0] + 1 :])
        if "pok" in tomllib.loads(outside).get("mcp_servers", {}):
            raise ValueError("A pok table exists outside the managed block; preserve it manually.")
        merged = "".join(lines[: starts[0]]) + block + "".join(lines[ends[0] + 1 :])
    else:
        if "pok" in parsed.get("mcp_servers", {}):
            raise ValueError(
                "An existing user-owned pok MCP configuration was found. "
                "Compare it with the printed config; it was not overwritten."
            )
        merged = existing + ("\n" if existing and not existing.endswith("\n") else "")
        merged += ("\n" if existing else "") + block
    tomllib.loads(merged)
    return merged


def validate_python(root: Path, python: Path) -> None:
    if not python.is_file():
        raise ValueError(f"Python does not exist: {python}")
    env = dict(os.environ, PYTHONPATH=str(root / "src"), PYTHONUTF8="1")
    probe = subprocess.run(
        [
            str(python),
            "-c",
            "import sys; assert sys.version_info >= (3, 12), 'Python 3.12+ required'; "
            "import fastmcp, pok.mcp.server; print('PoK tools registered OK')",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    if probe.returncode:
        raise ValueError(f"Python validation failed:\n{probe.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--write", action="store_true", help="Write .codex/config.toml")
    mode.add_argument("--check", action="store_true", help="Validate the generated local config")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    python = args.python.absolute()
    target = root / ".codex" / "config.toml"
    block = config_block(root, python)
    try:
        validate_python(root, python)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if args.check:
            expected = tomllib.loads(block)["mcp_servers"]["pok"]
            actual = tomllib.loads(existing).get("mcp_servers", {}).get("pok")
            if actual != expected:
                raise ValueError("Local pok config is absent or differs. Run --write or review it.")
            print(f"OK: {target}")
        elif args.write:
            merged = merge_config(existing, block)
            target.parent.mkdir(parents=True, exist_ok=True)
            if merged != existing:
                target.write_text(merged, encoding="utf-8", newline="\n")
            print(f"Configured: {target}")
            print(
                "Trust this repository in Codex, then open a new task to load pok and its skills."
            )
            print("Verify: codex mcp get pok --json; then call server_info in the new task.")
        else:
            print(block, end="")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
