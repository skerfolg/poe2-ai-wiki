"""Both supported OS jobs must run native Python adapters, not only the Lua spike."""

from pathlib import Path


def test_native_ci_covers_python_adapters_and_owned_process_lifecycle():
    source = (Path(__file__).resolve().parents[2] / ".github/workflows/pob-smoke.yml").read_text(
        encoding="utf-8"
    )
    assert "windows-latest" in source and "macos-latest" in source
    assert 'python-version: "3.12"' in source
    assert "path: external/pob" in source
    assert 'dir="external/pob/${POB_COMMIT:0:7}"' in source
    assert "POK_LUAJIT=" in source
    assert "python -m pytest tests/integration tests/unit/test_owned_process.py" in source
    assert "--junitxml=native-results.xml" in source
    assert "if: always()" in source and "path: native-results.xml" in source
