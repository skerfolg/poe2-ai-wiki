"""Codex registration must preserve local settings and Windows launch paths."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location(
    "configure_codex", _ROOT / "scripts/configure_codex.py"
)
assert _SPEC and _SPEC.loader
setup = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(setup)


def test_launch_config_roundtrips_paths_and_supports_long_calls(tmp_path: Path) -> None:
    root = tmp_path / "PoE 위키 with spaces"
    interpreter = root / ".venv" / "Scripts" / "python.exe"
    server = tomllib.loads(setup.config_block(root, interpreter))["mcp_servers"]["pok"]
    assert server["command"] == str(interpreter.absolute())
    assert server["cwd"] == str(root.resolve())
    assert server["args"] == ["-m", "pok.mcp"]
    assert server["env"]["PYTHONPATH"] == str(root.resolve() / "src")
    assert server["tool_timeout_sec"] > int(server["env"]["POK_AUTOFILL_BUDGET_S"])
    assert server["tool_timeout_sec"] > 600  # optimize_tree's default budget
    assert "POK_LUAJIT" in server["env_vars"]


def test_reconfigure_preserves_other_settings_and_is_idempotent(tmp_path: Path) -> None:
    before = 'model = "user-choice"\n\n[mcp_servers.other]\ncommand = "other-server"\n'
    block = setup.config_block(tmp_path, tmp_path / "python")
    configured = setup.merge_config(before, block)
    assert configured.startswith(before)
    assert setup.merge_config(configured, block) == configured
    after = "\n[features]\nsome_setting = true\n"
    changed = setup.merge_config(configured + after, setup.config_block(tmp_path, tmp_path / "new"))
    assert changed.startswith(before)
    assert changed.endswith(after)
    assert tomllib.loads(changed)["mcp_servers"]["pok"]["command"].endswith("new")


def test_unmanaged_server_is_not_silently_replaced(tmp_path: Path) -> None:
    original = '[mcp_servers.pok]\ncommand = "custom-wrapper"\n'
    with pytest.raises(ValueError, match="user-owned"):
        setup.merge_config(original, setup.config_block(tmp_path, tmp_path / "python"))


def test_broken_markers_do_not_truncate_local_settings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="markers"):
        setup.merge_config(setup.BEGIN + "\n", setup.config_block(tmp_path, tmp_path / "python"))


def test_posix_venv_executable_symlink_is_not_resolved(tmp_path: Path) -> None:
    python = tmp_path / "python"
    target = tmp_path / "base-python"
    target.touch()
    try:
        python.symlink_to(target)
    except OSError:
        pytest.skip("Symlinks require local permission on Windows")
    config = tomllib.loads(setup.config_block(tmp_path, python))
    assert config["mcp_servers"]["pok"]["command"] == str(python.absolute())
