"""Loaded memory identity must not be replaced with newly edited disk content."""

import sys
from types import ModuleType

from pok.engine.measurement_provenance import observe_loaded_execution
from pok.kb import store


def test_disk_edit_keeps_loaded_code_identity_until_code_is_replaced(tmp_path, monkeypatch):
    path = tmp_path / "example.py"
    path.write_text("def value(): return 1\n", encoding="utf-8")
    module = ModuleType("pok._identity_fixture")
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), vars(module))
    monkeypatch.setitem(sys.modules, module.__name__, module)
    before = observe_loaded_execution(root=tmp_path)
    path.write_text("def value(): return 2\n", encoding="utf-8")
    unchanged = observe_loaded_execution(root=tmp_path)
    assert unchanged["python"] == before["python"]
    assert module.value() == 1
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), vars(module))
    changed = observe_loaded_execution(root=tmp_path)
    assert changed["python"]["sha256"] != before["python"]["sha256"]
    assert module.value() == 2


def test_wrapped_entrypoint_closure_code_is_observed(tmp_path):
    def original():
        return 1

    def replacement():
        return 2

    def wrap(function):
        def wrapper():
            return function()

        return wrapper

    entrypoint = wrap(original)
    first = observe_loaded_execution(root=tmp_path, entrypoint=entrypoint)
    original.__code__ = replacement.__code__
    second = observe_loaded_execution(root=tmp_path, entrypoint=entrypoint)
    assert first["python"]["sha256"] != second["python"]["sha256"]
    assert entrypoint() == 2


def test_cached_kb_fingerprint_reads_existing_memory_not_new_disk(tmp_path, monkeypatch):
    knowledge = tmp_path / "knowledge"
    knowledge.mkdir()
    file = knowledge / "example.json"
    file.write_text('{"value":1}', encoding="utf-8")
    record = store.Record("example", "Item", file, {"value": 1})
    snapshot = store.Store({"example": record}, {})
    monkeypatch.setitem(store._LOAD_CACHE, knowledge.resolve(), ((0, 0, 0), snapshot))
    before = store.loaded_snapshot_identity(tmp_path)
    file.write_text('{"value":2}', encoding="utf-8")
    assert store.loaded_snapshot_identity(tmp_path) == before
    record.raw["value"] = 2
    changed = store.loaded_snapshot_identity(tmp_path)
    assert changed["sha256"] != before["sha256"]
    assert changed["snapshot_id"] == before["snapshot_id"]
    assert changed["current_disk_validation"] == "not_checked"


def test_missing_kb_does_not_trigger_loading(tmp_path, monkeypatch):
    def forbidden_load(*args, **kwargs):
        raise AssertionError("Do not load a KB merely to report memory identity")

    monkeypatch.setattr(store, "load", forbidden_load)
    observed = observe_loaded_execution(root=tmp_path)
    assert observed["kb"]["status"] == "not_loaded"
    assert observed["native_process"] == "not_verified"
