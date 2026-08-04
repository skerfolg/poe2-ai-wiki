"""보존 정책 (§9-3) — 이 파일이 지키는 것은 "지우는 기능"이 아니라 **못 지우게 하는 것**.

산출물은 재생성 불가다. 계보가 끊기면 "이 판단이 어디서 왔나"에 영영 답할 수 없다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pok.artifacts.retention import delete, scan


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "artifacts" / "builds").mkdir(parents=True)
    (root / "artifacts" / "feedback" / "raw").mkdir(parents=True)
    (root / "artifacts" / "sessions").mkdir(parents=True)
    (root / "knowledge" / "insights").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    return root


def _feedback(root: Path, name: str, *, state: str = "raw") -> None:
    d = root / "artifacts" / "feedback" / "raw" / name
    d.mkdir()
    (d / "content.md").write_text("원문", encoding="utf-8")
    (d / "manifest.json").write_text(json.dumps({"state": state}), encoding="utf-8")


def _insight(root: Path, slug: str, feedback_id: str) -> None:
    (root / "knowledge" / "insights" / f"{slug}.md").write_text(
        f"---\nid: insight.{slug}\nlabel: IN_GAME\nfeedback_id: {feedback_id}\n---\n\n# {slug}\n",
        encoding="utf-8",
    )


def _build(root: Path, name: str) -> None:
    d = root / "artifacts" / "builds" / name
    d.mkdir()
    (d / "design.md").write_text("설계", encoding="utf-8")


def test_인사이트가_가리키는_원문은_보호된다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _feedback(root, "fb-1")
    _insight(root, "rule-a", "fb-1")
    item = next(i for i in scan(root).items if i.name == "fb-1")
    assert item.protected
    assert "insight:rule-a" in item.referenced_by


def test_여러_인사이트가_한_원문을_가리킬_수_있다(tmp_path: Path) -> None:
    """실제로 CoMD 폐기 노트 하나에서 인사이트 5건이 나왔다(2026-08-04)."""
    root = _repo(tmp_path)
    _feedback(root, "fb-1")
    for slug in ("rule-a", "rule-b", "rule-c"):
        _insight(root, slug, "fb-1")
    item = next(i for i in scan(root).items if i.name == "fb-1")
    assert sorted(item.referenced_by) == ["insight:rule-a", "insight:rule-b", "insight:rule-c"]


def test_승격_상태만으로도_보호된다(tmp_path: Path) -> None:
    """인사이트 파일이 아직 없어도 promoted면 계보의 일부다."""
    root = _repo(tmp_path)
    _feedback(root, "fb-1", state="promoted")
    item = next(i for i in scan(root).items if i.name == "fb-1")
    assert item.protected and "state:promoted" in item.referenced_by


def test_참조_없는_것은_후보로만_나온다(tmp_path: Path) -> None:
    """후보 = 삭제 대상이 아니라 **사람이 판단할 대상**이다."""
    root = _repo(tmp_path)
    _build(root, "old-build")
    report = scan(root)
    assert [i.name for i in report.candidates] == ["old-build"]
    assert report.protected == []
    assert (root / "artifacts" / "builds" / "old-build").exists()  # 스캔은 지우지 않는다


def test_참조된_것은_삭제를_거부한다(tmp_path: Path) -> None:
    """계보 절단 방지 — 이게 이 모듈의 존재 이유다."""
    root = _repo(tmp_path)
    _feedback(root, "fb-1")
    _insight(root, "rule-a", "fb-1")
    with pytest.raises(ValueError, match="계보 절단"):
        delete(["fb-1"], reason="정리", root=root)
    assert (root / "artifacts" / "feedback" / "raw" / "fb-1").exists()


def test_사유_없는_삭제는_거부한다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _build(root, "b1")
    with pytest.raises(ValueError, match="사유"):
        delete(["b1"], reason="  ", root=root)


def test_없는_보관물은_예외(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    with pytest.raises(KeyError):
        delete(["없음"], reason="정리", root=root)


def test_참조_없는_것은_사유와_함께_지운다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _build(root, "b1")
    _build(root, "b2")
    assert delete(["b1"], reason="중복 산출물", root=root) == ["b1"]
    assert not (root / "artifacts" / "builds" / "b1").exists()
    assert (root / "artifacts" / "builds" / "b2").exists()  # 지목한 것만


def test_한_건이라도_보호되면_전체를_거부한다(tmp_path: Path) -> None:
    """부분 삭제로 조용히 넘어가면 무엇이 지워졌는지 알 수 없다."""
    root = _repo(tmp_path)
    _build(root, "b1")
    _feedback(root, "fb-1", state="promoted")
    with pytest.raises(ValueError, match="계보 절단"):
        delete(["b1", "fb-1"], reason="정리", root=root)
    assert (root / "artifacts" / "builds" / "b1").exists()  # 통째로 취소된다
