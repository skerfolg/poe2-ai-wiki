"""Product evaluation preserves the real catalog and protects machine evidence."""

import functools
import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def adapter(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills/build-generation")
    )
    return importlib.import_module("product_server")


@pytest.mark.parametrize(
    "path",
    [
        "inputs/brief.md",
        "reference/skill.md",
        "builds/x/manifest.json",
        "sessions/receipt.json",
        "../outside",
        "work/../builds/x/spec.json",
        "work",
    ],
)
def test_trial_notes_cannot_modify_machine_or_control_material(adapter, tmp_path, path):
    with pytest.raises(ValueError):
        adapter.trial_file(tmp_path, "write", path, "replacement")
    assert not list(tmp_path.rglob("*"))


def test_drafts_have_revision_checks_and_cannot_escape_on_read(adapter, tmp_path):
    saved = adapter.trial_file(tmp_path, "write", "work/spec.json", '{"draft":1}')
    stale = adapter.trial_file(tmp_path, "write", "work/spec.json", "changed", "0" * 64)
    assert not stale["ok"]
    read = adapter.trial_file(tmp_path, "read", "work/spec.json")
    assert read["text"] == '{"draft":1}' and read["sha256"] == saved["sha256"]
    with pytest.raises(ValueError):
        adapter.trial_file(tmp_path, "read", "../outside")


class Product:
    def __init__(self):
        self._TOOL_PARAMS = {}
        self.registered = {}
        self.called = []
        self.mcp = SimpleNamespace(local_provider=SimpleNamespace(remove_tool=lambda name: None))
        for name in (
            "parse_pob",
            "create_design_record",
            "recover_execution",
            "optimize_items",
            "future_product_tool",
        ):

            def original(code_path="", name=name):
                self.called.append(name)
                return {"product": name}

            original.__name__ = name

            @functools.wraps(original)
            def wrapped(*args, function=original, **kwargs):
                return function(*args, **kwargs)

            setattr(self, name, wrapped)
            self.tool(wrapped)

    def tool(self, function):
        self._TOOL_PARAMS[function.__name__] = set()
        self.registered[function.__name__] = function
        return function


def test_real_product_tools_are_retained_including_future_and_record_tools(adapter, tmp_path):
    server = Product()
    normal = set(server._TOOL_PARAMS)
    manifest = adapter.configure_product(server, tmp_path / "artifacts", tmp_path / "product")
    assert set(manifest["product_tools"]) == normal
    assert set(server._TOOL_PARAMS) == normal | {"experiment_file"}
    assert server.registered["future_product_tool"]() == {"product": "future_product_tool"}
    assert server.registered["create_design_record"]() == {"product": "create_design_record"}
    blocked = server.registered["parse_pob"](code_path=str(tmp_path / "other-trial/answer.pob"))
    assert not blocked["ok"] and "parse_pob" not in server.called
    accepted = server.registered["parse_pob"](code_path=str(tmp_path / "artifacts/work/build.pob"))
    assert accepted == {"product": "parse_pob"}


def test_frozen_product_cannot_be_used_as_trial_storage(adapter, tmp_path):
    product = tmp_path / "artifacts/baseline"
    for marker in ("knowledge", "src/pok"):
        (product / marker).mkdir(parents=True)
    (product / "pyproject.toml").write_text("", encoding="utf-8")
    trial = tmp_path / "artifacts/trial"
    assert adapter.validate_locations(product, trial, tmp_path) == (product, trial)
    with pytest.raises(ValueError, match="overlap"):
        adapter.validate_locations(product, product / "artifacts/trial", tmp_path)
    with pytest.raises(ValueError):
        adapter.validate_locations(product, tmp_path.parent / "outside", tmp_path)
