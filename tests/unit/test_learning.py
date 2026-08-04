"""P5 학습 루프 — 피드백 기록 → 큐레이션 게이트 → 승격 (PROJECT_STRUCTURE §6).

핵심 불변식: **정본 진입은 승인된 주장만**. 관찰 원문에도 오류가 섞이므로
(실증 2026-08-03: 폐기 노트의 한 수치가 인게임 확인값과 달랐다) 통째 승격은 금지다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pok.artifacts.promote import merge_verification, promote_insight, set_scope
from pok.kb.insights import load_insights
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


# ── 3계층 사다리 (BLUEPRINT §15 미결 3번, 사용자 결정 2026-08-04) ─────
#
# season → durable → canonical 레코드. 한 폴더에 평평하게 쌓으면 "이번 시즌 관찰"과
# "게임의 항구적 규칙"이 같은 무게로 읽힌다 — 후자가 지워도 되는 아이디어처럼 보인다.


def _promoted(root: Path, slug: str = "rule") -> str:
    fid = _record(root)
    promote_insight(
        fid,
        slug,
        "규칙",
        "- 사실 A",
        label="IN_GAME",
        verified_by="사용자",
        patch="0.5.4b",
        root=root,
    )
    return fid


def test_새_인사이트는_시즌_한정으로_시작한다(tmp_path: Path) -> None:
    """기본값이 durable이면 검증 안 된 관찰이 항구적 지식 행세를 한다."""
    root = _repo(tmp_path)
    _promoted(root)
    (ins,) = load_insights(root)
    assert ins.scope == "season"


def test_scope는_어휘_밖을_거부한다(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    fid = _record(root)
    with pytest.raises(ValueError, match="scope"):
        promote_insight(
            fid,
            "s",
            "t",
            "b",
            label="IN_GAME",
            verified_by="사용자",
            patch="t",
            scope="permanent",
            root=root,
        )


def test_사다리_1칸은_판정_기록을_남긴다(tmp_path: Path) -> None:
    """무엇을 durable로 올릴지는 기계가 못 정한다 — 근거 없는 승격은 거부."""
    root = _repo(tmp_path)
    _promoted(root)
    with pytest.raises(ValueError, match="verified_by"):
        set_scope("rule", "durable", verified_by=" ", root=root)

    set_scope("rule", "durable", verified_by="여러 빌드에서 재확인 2026-08-04", root=root)
    (ins,) = load_insights(root)
    assert ins.scope == "durable"
    assert "재확인" in ins.meta["scope_verified_by"]
    assert ins.body.startswith("# 규칙")  # 본문은 그대로


def test_scope_변경은_멱등하다(tmp_path: Path) -> None:
    """두 번 올려도 front matter에 scope가 중복으로 쌓이면 안 된다."""
    root = _repo(tmp_path)
    _promoted(root)
    set_scope("rule", "durable", verified_by="1차", root=root)
    set_scope("rule", "durable", verified_by="2차", root=root)
    text = (root / "knowledge" / "insights" / "rule.md").read_text(encoding="utf-8")
    assert text.count("scope: durable") == 1
    assert "1차" not in text and "2차" in text


def test_검증_라벨은_교체가_아니라_누적이다() -> None:
    """회귀(2026-08-04): 새 필드 라벨 하나를 넣다가 기존 라벨 2건을 잃었다.
    라벨 대장은 필드별로 쌓이는 물건이라 중첩 dict를 통째 갈아끼우면 안 된다."""
    prev = {
        "efficiency_formula": "x",
        "_verification": {
            "efficiency_formula": "SUPPORTED_INFERENCE",
            "efficiency_stacking": "SUPPORTED_INFERENCE",
        },
    }
    patched = merge_verification(prev, {"_verification": {"new_field": "IN_GAME"}})
    assert patched["_verification"] == {
        "efficiency_formula": "SUPPORTED_INFERENCE",
        "efficiency_stacking": "SUPPORTED_INFERENCE",
        "new_field": "IN_GAME",
    }


def test_같은_필드의_라벨은_새_판정이_이긴다() -> None:
    prev = {"_verification": {"f": "SUPPORTED_INFERENCE"}}
    assert merge_verification(prev, {"_verification": {"f": "IN_GAME"}})["_verification"] == {
        "f": "IN_GAME"
    }


def test_기존_대장이_없으면_그대로_넣는다() -> None:
    assert merge_verification({}, {"_verification": {"f": "IN_GAME"}})["_verification"] == {
        "f": "IN_GAME"
    }


def test_promoted_to는_누적이다(tmp_path: Path) -> None:
    """한 인사이트의 사실이 여러 레코드로 나뉘어 갈 수 있다 — 덮어쓰면 앞선
    계보가 사라진다(실측 2026-08-04: 로우라이프가 resource.life 계보를 잃었다)."""
    root = _repo(tmp_path)
    _promoted(root)
    path = root / "knowledge" / "insights" / "rule.md"
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("---\n\n#", "promoted_to: a.first\n---\n\n#", 1), encoding="utf-8")

    from pok.artifacts.promote import _append_promoted_to

    _append_promoted_to(path, {"b.second"})
    assert "promoted_to: a.first, b.second" in path.read_text(encoding="utf-8")
