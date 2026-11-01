"""PoB native launches must retain the shared owned-command lifecycle boundary."""

import ast
from pathlib import Path


def test_pob_adapters_do_not_bypass_owned_native_launch_boundary():
    directory = Path(__file__).resolve().parents[2] / "src/pok/pob"
    offenders = []
    spawners = {"Popen", "run", "call", "check_call", "check_output"}
    for path in directory.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        aliases = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
            if alias.name == "subprocess"
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if (
                    isinstance(node.func.value, ast.Name)
                    and node.func.value.id in aliases
                    and (node.func.attr in spawners)
                ):
                    offenders.append(f"{path.name}:{node.lineno}")
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "subprocess"
                and any(alias.name in spawners for alias in node.names)
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        f"Use run_native_capture/spawn_owned, not a direct native launch: {offenders}"
    )
