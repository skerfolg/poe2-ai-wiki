"""P5 학습 루프 — 피드백 기록 → 큐레이션 게이트 → 승격 (PROJECT_STRUCTURE §6).

핵심 불변식: **정본 진입은 승인된 주장만**. 관찰 원문에도 오류가 섞이므로
(실증 2026-08-03: 폐기 노트의 한 수치가 인게임 확인값과 달랐다) 통째 승격은 금지다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pok.artifacts.promote import promote_insight
from pok.learning.curation import Claim, decide, load_candidates, propose
from pok.learning.feedback import list_feedback, record_feedback


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "artifacts").mkdir(parents=True)
    (root / "knowledge").mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    return root


def _record(root: Path) -> str:
    out = record_feedback(
        "테스트 관찰",
        "# 원문\n- 사실 A\n- 틀린 주장 B\n",
        kind="in-game-test",
        source={"provider": "tester"},
        root=root,
    )
    return out.name


def test_피드백은_원문과_계보를_보존한다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fid = _record(root)
    d = root / "artifacts" / "feedback" / "raw" / fid
    assert "사실 A" in (d / "content.md").read_text(encoding="utf-8")
    meta = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    assert meta["state"] == "raw" and meta["source"]["provider"] == "tester"
    assert len(meta["content_sha256"]) == 64
    assert [m["feedback_id"] for m in list_feedback("raw", root=root)] == [fid]


def test_판정_전에는_승격_대상이_없다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fid = _record(root)
    propose(fid, [Claim("사실 A", "IN_GAME", "원문 §1")], root=root)
    cand = load_candidates(fid, root=root)
    assert cand.approved == [] and len(cand.pending) == 1


def test_기각에는_사유가_필요하다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fid = _record(root)
    propose(fid, [Claim("틀린 주장 B", "UNVERIFIED", "원문 §2")], root=root)
    with pytest.raises(ValueError, match="사유"):
        decide(fid, {"틀린 주장 B": ("rejected", "  ")}, root=root)
    result = decide(fid, {"틀린 주장 B": ("rejected", "인게임 확인값과 불일치")}, root=root)
    assert result.approved == []
    assert result.claims[0].note == "인게임 확인값과 불일치"


def test_제안_재호출이_판정을_지우지_않는다(tmp_path: Path) -> None:
    """회귀(2026-08-03): 저장 경로가 병합 로직을 타면 승인이 pending으로 되돌아갔다."""
    root = _repo(tmp_path)
    fid = _record(root)
    claims = [Claim("사실 A", "IN_GAME", "원문 §1"), Claim("틀린 주장 B", "UNVERIFIED", "원문 §2")]
    propose(fid, claims, root=root)
    decide(
        fid,
        {"사실 A": ("approved", "승인"), "틀린 주장 B": ("rejected", "불일치")},
        root=root,
    )
    propose(fid, [*claims, Claim("새 주장 C", "IN_GAME", "원문 §3")], root=root)
    cand = load_candidates(fid, root=root)
    assert [c.text for c in cand.approved] == ["사실 A"]  # 판정 보존
    assert len(cand.pending) == 1 and cand.pending[0].text == "새 주장 C"


def test_승격에는_검증_주체와_계보가_필수(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fid = _record(root)
    with pytest.raises(ValueError, match="verified_by"):
        promote_insight(
            fid, "s", "제목", "본문", label="IN_GAME", verified_by=" ", patch="t", root=root
        )
    with pytest.raises(FileNotFoundError, match="계보"):
        promote_insight(
            "없는-피드백",
            "s",
            "제목",
            "본문",
            label="IN_GAME",
            verified_by="사용자",
            patch="t",
            root=root,
        )


def test_승격은_정본에_라벨과_계보를_박는다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fid = _record(root)
    out = promote_insight(
        fid,
        "test-insight",
        "테스트 인사이트",
        "- 사실 A",
        label="IN_GAME",
        verified_by="사용자 승인 2026-08-03",
        patch="0.5.4b",
        root=root,
    )
    text = out.read_text(encoding="utf-8")
    assert out.parent.name == "insights"
    assert "label: IN_GAME" in text and "verified_by: 사용자 승인 2026-08-03" in text
    assert f"feedback_id: {fid}" in text  # 원문으로 되짚을 수 있어야 한다
    meta = json.loads(
        (root / "artifacts" / "feedback" / "raw" / fid / "manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert meta["state"] == "promoted"
