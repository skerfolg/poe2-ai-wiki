"""The editor probe must not turn incomplete native evidence into a pass."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pok.pob import item_editor
from pok.pob.versions import PobSnapshot


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> PobSnapshot:
    monkeypatch.setattr(item_editor, "find_luajit", lambda: "fake-luajit")
    monkeypatch.setattr(item_editor, "var_dir", lambda: tmp_path)
    return PobSnapshot("pinned-test-commit", tmp_path, tmp_path)


def _write_output(args: list[str], rows: list[dict[str, Any]], *, complete: bool = True) -> None:
    Path(args[-1]).write_text(
        json.dumps({"protocol": 1, "complete": complete, "items": rows}), encoding="utf-8"
    )


def test_batches_exact_utf8_inputs_in_unique_cleaned_directory(
    monkeypatch: pytest.MonkeyPatch,
    runtime: PobSnapshot,
) -> None:
    inputs: list[Path] = []

    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        inputs.append(Path(args[-2]))
        assert json.loads(inputs[-1].read_text(encoding="utf-8")) == [
            {"label": "장갑", "text": "Rarity: RARE\n원문\nAdorned Wraps"}
        ]
        assert kwargs["cwd"] == runtime.src_dir
        assert kwargs["encoding"] == "utf-8"
        _write_output(
            args,
            [
                {
                    "label": "장갑",
                    "stage": "complete",
                    "checked": True,
                    "compatible": True,
                    "initial_sockets": 2,
                    "opened_sockets": 2,
                }
            ],
        )
        return SimpleNamespace(returncode=0, stdout="POK_OK\n", stderr="")

    monkeypatch.setattr(item_editor.subprocess, "run", run)
    for _ in range(2):
        result = item_editor.audit_item_editor(
            {"장갑": "Rarity: RARE\n원문\nAdorned Wraps"},
            snapshot=runtime,
        )
        assert result["checked"] and result["compatible"]
        assert result["problems"] == []
        assert result["pob_commit"] == runtime.commit
    assert inputs[0] != inputs[1]
    assert all(not path.parent.exists() for path in inputs)


def test_native_error_is_checked_but_incompatible(
    monkeypatch: pytest.MonkeyPatch,
    runtime: PobSnapshot,
) -> None:
    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        _write_output(
            args,
            [
                {
                    "label": "Body Armour",
                    "stage": "set_display_item",
                    "checked": True,
                    "compatible": False,
                    "error": "nil value",
                    "initial_sockets": 4,
                    "opened_sockets": 8,
                }
            ],
        )
        return SimpleNamespace(returncode=0, stdout="POK_OK\n", stderr="")

    monkeypatch.setattr(item_editor.subprocess, "run", run)
    result = item_editor.audit_item_editor({"Body Armour": "original"}, snapshot=runtime)
    assert result["checked"] and not result["compatible"]
    assert result["items"][0]["opened_sockets"] == 8
    assert "nil value" in result["problems"][0]


def test_successful_open_with_socket_count_drift_is_incompatible(
    monkeypatch: pytest.MonkeyPatch,
    runtime: PobSnapshot,
) -> None:
    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        _write_output(
            args,
            [
                {
                    "label": "Gloves",
                    "stage": "double_click_count_check",
                    "checked": True,
                    "compatible": False,
                    "code": "count_changed",
                    "error": "double-click changed socket count: 3 -> 6",
                    "initial_sockets": 3,
                    "opened_sockets": 6,
                }
            ],
        )
        return SimpleNamespace(returncode=0, stdout="POK_OK\n", stderr="")

    monkeypatch.setattr(item_editor.subprocess, "run", run)
    result = item_editor.audit_item_editor({"Gloves": "original"}, snapshot=runtime)
    assert result["checked"] and not result["compatible"]
    assert result["items"][0]["code"] == "count_changed"
    assert "3 -> 6" in result["problems"][0]


def test_timeout_keeps_partial_item_stage_and_unstarted_rows(
    monkeypatch: pytest.MonkeyPatch,
    runtime: PobSnapshot,
) -> None:
    def run(args: list[str], **kwargs: Any) -> None:
        _write_output(
            args,
            [
                {"label": "first", "stage": "complete", "checked": True, "compatible": True},
                {
                    "label": "second",
                    "stage": "set_display_item",
                    "checked": False,
                    "compatible": False,
                },
            ],
            complete=False,
        )
        raise subprocess.TimeoutExpired(args, 0.1)

    monkeypatch.setattr(item_editor.subprocess, "run", run)
    result = item_editor.audit_item_editor(
        {"first": "one", "second": "two", "third": "three"},
        timeout=0.1,
        snapshot=runtime,
    )
    assert not result["checked"] and not result["compatible"]
    assert result["items"][0]["checked"]
    assert result["items"][1]["stage"] == "set_display_item"
    assert result["items"][2]["stage"] == "pending"
    assert "timed out" in result["problems"][0]


@pytest.mark.parametrize("output", ["missing", "malformed", "partial", "no_rows"])
def test_success_exit_without_complete_evidence_does_not_pass(
    monkeypatch: pytest.MonkeyPatch,
    runtime: PobSnapshot,
    output: str,
) -> None:
    def run(args: list[str], **kwargs: Any) -> SimpleNamespace:
        if output == "malformed":
            Path(args[-1]).write_text("{", encoding="utf-8")
        elif output == "partial":
            _write_output(
                args,
                [{"label": "item", "stage": "complete", "checked": True, "compatible": True}],
                complete=False,
            )
        elif output == "no_rows":
            _write_output(args, [])
        return SimpleNamespace(returncode=0, stdout="POK_OK\n", stderr="")

    monkeypatch.setattr(item_editor.subprocess, "run", run)
    result = item_editor.audit_item_editor({"item": "original"}, snapshot=runtime)
    assert not result["checked"] and not result["compatible"]
    assert result["problems"]


def test_missing_runtime_is_unchecked(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing() -> PobSnapshot:
        raise FileNotFoundError("no snapshot")

    monkeypatch.setattr(item_editor, "resolve_snapshot", missing)
    result = item_editor.audit_item_editor({"item": "original"})
    assert not result["checked"] and not result["compatible"]
    assert "unavailable" in result["problems"][0]
