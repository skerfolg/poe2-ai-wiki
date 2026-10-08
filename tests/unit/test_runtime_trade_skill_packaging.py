from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from scripts.build_runtime import _copy_skill_inputs

from pok.pob.runtime_identity import runtime_identity, sha256_tree


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_trade_script(module_name: str = "packaged_trade_search"):
    script = Path(__file__).resolve().parents[2] / "skills/trade-search/scripts/trade_search.py"
    spec = importlib.util.spec_from_file_location(module_name, script)
    if spec is None or spec.loader is None:
        raise AssertionError("trade_search.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_runtime_packages_only_trade_search_skill_entry_and_common_instructions(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    out = tmp_path / "runtime"
    _write(root / "skills" / "AGENTS.md", "# common\n")
    _write(root / "skills" / "trade-search" / "AGENTS.md", "# trade\n")
    _write(root / "skills" / "trade-search" / "scripts" / "trade_search.py", "print('ok')\n")
    _write(root / "skills" / "authoring-only" / "AGENTS.md", "# no\n")
    _write(
        root / ".agents" / "skills" / "trade-search" / "SKILL.md",
        "---\nname: trade-search\ndescription: packaged trade search skill\n---\n",
    )
    _write(
        root / ".agents" / "skills" / "authoring-only" / "SKILL.md",
        "---\nname: authoring-only\ndescription: not runtime safe\n---\n",
    )

    _copy_skill_inputs(root, out)

    assert (out / "skills" / "AGENTS.md").read_text(encoding="utf-8") == "# common\n"
    assert (out / "skills" / "trade-search" / "AGENTS.md").is_file()
    assert (out / ".agents" / "skills" / "trade-search" / "SKILL.md").is_file()
    assert not (out / "skills" / "authoring-only").exists()
    assert not (out / ".agents" / "skills" / "authoring-only").exists()
    runtime_agents = (out / "AGENTS.md").read_text(encoding="utf-8")
    assert "python/python.exe" in runtime_agents
    assert "POK_DATA_HOME/live/trade-search/" in runtime_agents
    assert "POK_CACHE_HOME/trade-search/" in runtime_agents


def test_trade_search_skill_changes_affect_runtime_source_digest(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    _write(root / "src" / "pok" / "example.py", "VALUE = 1\n")
    _write(root / "scripts" / "pob_probe.lua", "return 1\n")
    _write(root / "skills" / "AGENTS.md", "# common\n")
    skill = root / "skills" / "trade-search" / "AGENTS.md"
    _write(skill, "# trade\n")
    _write(root / ".agents" / "skills" / "trade-search" / "SKILL.md", "# shim\n")

    include = (
        "src/pok/**/*.py",
        "src/pok/**/*.lua",
        "scripts/pob*.lua",
        "skills/AGENTS.md",
        "skills/trade-search/**/*",
        ".agents/skills/trade-search/SKILL.md",
    )
    before = sha256_tree(root, include=include)
    skill.write_text("# changed\n", encoding="utf-8")

    assert sha256_tree(root, include=include) != before


def test_runtime_identity_source_digest_observes_packaged_skill_changes(tmp_path: Path) -> None:
    commit = "abcdef0123456789abcdef0123456789abcdef01"
    root = tmp_path / "repo"
    _write(root / "pyproject.toml", "[project]\nname='pok-test'\n")
    _write(root / "knowledge" / "ingest" / "manifest.json", f'{{"pob_commit":"{commit}"}}\n')
    _write(root / "external" / "pob" / commit[:7] / "src" / "HeadlessWrapper.lua", "return 1\n")
    _write(root / "src" / "pok" / "example.py", "VALUE = 1\n")
    _write(root / "scripts" / "pob_probe.lua", "return 1\n")
    _write(root / "skills" / "AGENTS.md", "# common\n")
    skill = root / "skills" / "trade-search" / "AGENTS.md"
    _write(skill, "# trade\n")
    _write(root / ".agents" / "skills" / "trade-search" / "SKILL.md", "# shim\n")

    before = runtime_identity(root, force_compute=True)
    skill.write_text("# changed\n", encoding="utf-8")
    after = runtime_identity(root, force_compute=True)

    assert after["pok"]["sourceDigest"] != before["pok"]["sourceDigest"]


def test_trade_search_default_cache_uses_packaged_cache_home(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cache_home = tmp_path / "cache-home"
    query = (
        Path(__file__).resolve().parents[2]
        / "skills/trade-search/references/rare-boots.query.json"
    )
    monkeypatch.setenv("POK_CACHE_HOME", str(cache_home))
    trade = _load_trade_script("packaged_trade_search_env")

    args = trade.parser().parse_args(
        [
            "prepare",
            "--host",
            "global",
            "--league",
            "Standard",
            "--query",
            str(query),
        ]
    )
    result = trade.execute(args)

    assert args.cache_dir == cache_home / "trade-search"
    assert result["status"] == "prepared"
    assert result["executed"] is False
    assert not args.cache_dir.exists()
