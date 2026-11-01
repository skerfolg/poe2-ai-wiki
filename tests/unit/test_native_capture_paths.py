"""Native adapters keep separate inputs and propagate cancellation through cleanup."""

import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import pytest

from pok.common.execution import ExecutionStopped
from pok.pob import item_editor, item_parse_gaps, parse_gaps, roundtrip
from pok.pob.versions import PobSnapshot


def adapter(kind, tmp_path, monkeypatch):
    module = {"roundtrip": roundtrip, "tree": parse_gaps, "item": item_parse_gaps}[kind]
    monkeypatch.setattr(module, "var_dir", lambda *args: tmp_path)
    monkeypatch.setattr(module, "find_luajit", lambda: "unused-luajit")
    snapshot = PobSnapshot("fixture", tmp_path, tmp_path)
    if kind == "roundtrip":
        invoke = partial(module.roundtrip, {"one": "original"}, snapshot=snapshot)
        output = "POK_RAW:one\toriginal\nPOK_OK\n"
    elif kind == "tree":
        invoke = partial(module.dump_tree_parse_gaps, snapshot=snapshot)
        output = 'POK_TREE:{"version":"fixture","nodes":1}\nPOK_OK\n'
    else:
        invoke = partial(module._probe, {"one": ["original"]}, "same-base", snapshot, 10)
        output = "POK_OK\n"
    return module, invoke, output


@pytest.mark.parametrize("kind", ["roundtrip", "tree", "item"])
def test_parallel_native_adapters_do_not_share_input_paths(kind, tmp_path, monkeypatch):
    module, invoke, output = adapter(kind, tmp_path, monkeypatch)
    paths = []
    gate = Barrier(2)

    def capture(args, **kwargs):
        path = Path(args[-1])
        paths.append(path)
        gate.wait(timeout=5)
        assert len(set(paths)) == 2
        assert path.read_text(encoding="utf-8")
        gate.wait(timeout=5)
        return SimpleNamespace(returncode=0, stdout=output, stderr="")

    monkeypatch.setattr(module, "run_native_capture", capture)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first, second = executor.submit(invoke), executor.submit(invoke)
        first.result(timeout=10)
        second.result(timeout=10)
    assert all(not path.exists() for path in paths)


@pytest.mark.parametrize("kind", ["roundtrip", "tree", "item"])
def test_cancellation_propagates_and_removes_only_own_input(kind, tmp_path, monkeypatch):
    module, invoke, _ = adapter(kind, tmp_path, monkeypatch)
    paths = []

    def capture(args, **kwargs):
        paths.append(Path(args[-1]))
        raise ExecutionStopped("test-request", "cancel_requested")

    monkeypatch.setattr(module, "run_native_capture", capture)
    unrelated = tmp_path / "unrelated-input"
    unrelated.write_text("keep", encoding="utf-8")
    with pytest.raises(ExecutionStopped):
        invoke()
    assert paths and all(not path.exists() for path in paths)
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_item_editor_cancellation_preserves_partial_output_before_directory_cleanup(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(item_editor, "var_dir", lambda: tmp_path)
    monkeypatch.setattr(item_editor, "find_luajit", lambda: "unused")
    paths = []

    def capture(args, **kwargs):
        paths.append(Path(args[-1]))
        paths[0].write_text('{"protocol":1,"complete":false}', encoding="utf-8")
        raise ExecutionStopped("test-request", "cancel_requested")

    monkeypatch.setattr(item_editor, "run_native_capture", capture)
    with pytest.raises(ExecutionStopped) as failure:
        item_editor.audit_item_editor(
            {"장갑": "원문"}, snapshot=PobSnapshot("test", tmp_path, tmp_path)
        )
    assert json.loads(failure.value.details["item_editor_partial_output"])["complete"] is False
    assert "장갑" in failure.value.details["item_editor_input"]
    assert not paths[0].parent.exists()
