"""Arm policy does not require optimizers to evaluate deliberate manual items."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "redesign_arm_policy", ROOT / "skills/build-generation/redesign_server.py"
)
assert SPEC is not None and SPEC.loader is not None
POLICY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POLICY)


def test_common_fixture_can_be_read_but_not_overwritten(tmp_path):
    source = tmp_path / "inputs/build.json"
    source.parent.mkdir()
    source.write_text("original", encoding="utf-8")
    assert POLICY.artifact_file(tmp_path, "read", "inputs/build.json")["text"] == "original"
    with pytest.raises(ValueError, match="read-only"):
        POLICY.artifact_file(tmp_path, "write", "inputs/build.json", "changed")
    with pytest.raises(ValueError, match="read-only"):
        POLICY.artifact_file(tmp_path, "write", "inputs/new.json", "new")
    assert source.read_text(encoding="utf-8") == "original"


def test_only_explicit_optimizers_differ_between_f_and_o():
    assert POLICY.allowed_names("O") - POLICY.allowed_names("F") == POLICY.OPTIMIZERS
    assert POLICY.allowed_names("P") == POLICY.allowed_names("O")
    assert {"compute_pob", "assemble_pob", "check_item_legality"} <= POLICY.allowed_names("F")
    with pytest.raises(ValueError):
        POLICY.allowed_names("unknown")


@pytest.mark.parametrize("arm", ["F", "O"])
def test_manual_rare_can_export_without_implicit_optimizer(arm):
    spec = {"items": [{"slot": "Helmet", "text": "Rarity: Rare\nExample\nHood"}]}
    assert POLICY.export_problems(arm, spec, "exploration")
    spec["items"][0]["derived_from"] = {"tool": "manual", "why": "Explicit test choice"}
    assert POLICY.export_problems(arm, spec, "exploration") == []
    assert POLICY.export_problems(arm, spec, "recommendation")


def test_p_leaves_original_assembly_policy_to_normal_engine():
    assert POLICY.export_problems("P", {}, "recommendation") == []


def test_optional_paths_cannot_read_other_runs_or_user_builds(tmp_path):
    artifacts = tmp_path / "run/artifacts"
    repo = tmp_path / "repo"
    assert POLICY.path_problems("parse_pob", {"code_path": str(repo / "old.pob")}, artifacts, repo)
    assert not POLICY.path_problems(
        "parse_pob", {"code_path": str(artifacts / "current.pob")}, artifacts, repo
    )
    assert POLICY.path_problems("parse_design_doc", {"build_id": "../other"}, artifacts, repo)
    assert not POLICY.path_problems(
        "parse_design_doc", {"build_id": "current-build"}, artifacts, repo
    )
    assert POLICY.path_problems("list_implicits", {"root_dir": str(tmp_path)}, artifacts, repo)
    assert not POLICY.path_problems(
        "list_implicits", {"root_dir": str(repo / "knowledge")}, artifacts, repo
    )


def test_common_file_io_preserves_text_and_rejects_stale_revision(tmp_path):
    text = "# 설계\n\n앵커와 근거 — v1\n"
    result = POLICY.artifact_file(tmp_path, "write", "sessions/design.md", text)
    assert result["ok"]
    read = POLICY.artifact_file(tmp_path, "read", "sessions/design.md")
    assert read["text"] == text
    assert read["sha256"] == result["sha256"]
    stale = POLICY.artifact_file(tmp_path, "write", "sessions/design.md", "wrong", "stale")
    assert stale["ok"] is False
    assert POLICY.artifact_file(tmp_path, "read", "sessions/design.md")["text"] == text
    assert POLICY.artifact_file(tmp_path, "list")["entries"][0]["name"] == "sessions"


@pytest.mark.parametrize("action", ["read", "write", "list"])
def test_common_file_io_cannot_reach_other_run(tmp_path, action):
    with pytest.raises(ValueError, match="escapes"):
        POLICY.artifact_file(tmp_path / "current", action, "../other/answer.json", "do not write")
    assert not (tmp_path / "other").exists()


@pytest.mark.parametrize("action", ["read", "write"])
def test_common_file_io_does_not_replace_the_root_directory(tmp_path, action):
    with pytest.raises(ValueError, match="file path"):
        POLICY.artifact_file(tmp_path, action)
