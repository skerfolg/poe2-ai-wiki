"""PoB launcher headers are stripped in memory, preserving source and line numbers."""

import subprocess
from pathlib import Path

import pytest

from pok.pob.versions import find_luajit

try:
    LUAJIT = find_luajit()
except (FileNotFoundError, RuntimeError):
    LUAJIT = None

pytestmark = pytest.mark.skipif(LUAJIT is None, reason="LuaJIT unavailable")


@pytest.mark.parametrize("header", [b"#@\n", b"#!/usr/bin/env luajit\r\n", b""])
def test_wrapper_header_is_only_removed_in_memory(tmp_path, header):
    original = header + b'print("LOADER_OK")\n'
    wrapper = tmp_path / "HeadlessWrapper.lua"
    wrapper.write_bytes(original)
    loader = Path(__file__).resolve().parents[2] / "scripts/pob_headless.lua"
    assert LUAJIT is not None
    result = subprocess.run(
        [str(LUAJIT), str(loader)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "LOADER_OK"
    assert wrapper.read_bytes() == original


def test_wrapper_error_keeps_original_line_number(tmp_path):
    original = b'#@\nerror("sentinel")\n'
    wrapper = tmp_path / "HeadlessWrapper.lua"
    wrapper.write_bytes(original)
    loader = Path(__file__).resolve().parents[2] / "scripts/pob_headless.lua"
    assert LUAJIT is not None
    result = subprocess.run(
        [str(LUAJIT), str(loader)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    assert result.returncode != 0
    assert "HeadlessWrapper.lua:2: sentinel" in result.stderr
    assert wrapper.read_bytes() == original


def test_nested_wrapper_loads_header_modules_without_disk_changes(tmp_path):
    files = {
        "HeadlessWrapper.lua": b'#@\ndofile("Launch.lua")\n',
        "Launch.lua": b'#@ launcher\nassert(loadfile("module.lua"))()\n',
        "module.lua": b'#@ module\nprint("NESTED_OK")\n',
    }
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    loader = Path(__file__).resolve().parents[2] / "scripts/pob_headless.lua"
    assert LUAJIT is not None
    result = subprocess.run(
        [str(LUAJIT), str(loader)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
        check=True,
    )
    assert result.stdout.strip() == "NESTED_OK"
    assert all((tmp_path / name).read_bytes() == data for name, data in files.items())
