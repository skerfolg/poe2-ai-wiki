"""인사이트 파싱·검색 (P5 RAG).

인사이트는 레코드와 성격이 다르다 — 본문이 곧 내용이고, 소비자는 "이걸 펼칠지"를
발췌로 판단한다. 그래서 검색이 발췌를 못 주면 결국 전문을 읽게 되고 검색한 의미가
사라진다. 이 파일은 그 계약을 지킨다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pok.index.search import get_insight, search_insights
from pok.kb.insights import load_insights, parse_insight

_DOC = """---
id: insight.sample-rule
label: IN_GAME
verified_by: 사용자 판정 2026-08-04 (설명: 콜론 포함)
feedback_id: 20260804-sample
patch: 0.5.4b
---

# 표본 규칙

로우라이프는 점유로만 성립한다.
"""


def test_front_matter와_본문을_가른다() -> None:
    ins = parse_insight(_DOC, Path("sample-rule.md"))
    assert (ins.id, ins.slug, ins.label) == ("insight.sample-rule", "sample-rule", "IN_GAME")
    assert ins.title == "표본 규칙"
    assert ins.body.startswith("# 표본 규칙")
    assert "---" not in ins.body


def test_값에_콜론이_있어도_잘리지_않는다() -> None:
    """verified_by 같은 계보 문장에는 콜론이 흔하다 — 첫 콜론에서만 나눠야 한다."""
    ins = parse_insight(_DOC, Path("sample-rule.md"))
    assert ins.verified_by == "사용자 판정 2026-08-04 (설명: 콜론 포함)"
    assert ins.feedback_id == "20260804-sample" and ins.patch == "0.5.4b"


def test_front_matter가_없어도_본문은_살린다() -> None:
    """손으로 쓴 문서가 섞여도 검색에서 사라지면 안 된다 — 누락보다 불완전이 낫다."""
    ins = parse_insight("# 맨몸 문서\n\n내용", Path("bare.md"))
    assert ins.id == "insight.bare" and ins.title == "맨몸 문서"
    assert ins.label == "UNVERIFIED"  # 라벨이 없으면 미검증으로 본다


# ── 정본 대상 (인덱스 self-healing 경유) ─────────────────────────────


def test_정본_인사이트가_전량_색인된다() -> None:
    hits = search_insights(limit=100)
    assert len(hits) == len(load_insights())
    assert all(h.title and h.label for h in hits)


def test_질의는_본문까지_찾는다() -> None:
    """제목에 없는 말로도 찾혀야 한다 — 인사이트는 본문이 내용이다."""
    hits = search_insights("점유")
    slugs = {h.slug for h in hits}
    assert "low-life-supply-is-reservation" in slugs
    hit = next(h for h in hits if h.slug == "low-life-supply-is-reservation")
    assert "점유" in hit.excerpt  # 발췌에 매칭 지점이 담긴다


def test_라벨로_신뢰도를_거른다() -> None:
    hits = search_insights(label="IN_GAME", limit=100)
    assert hits and all(h.label == "IN_GAME" for h in hits)


def test_질의_없으면_전량_목록() -> None:
    """무엇이 있는지 훑는 것도 정당한 용법 — 인사이트는 모수가 작다."""
    assert len(search_insights(limit=100)) == len(load_insights())


def test_전문_조회는_계보를_함께_준다() -> None:
    """이 판단이 어디서 왔는지 알아야 소비자가 신뢰도를 스스로 판정한다."""
    full = get_insight("low-life-supply-is-reservation")
    assert full["label"] == "IN_GAME"
    assert "점유" in full["body"]
    assert full["meta"]["feedback_id"] and full["meta"]["verified_by"]


def test_slug와_id_둘_다로_찾힌다() -> None:
    by_slug = get_insight("low-life-supply-is-reservation")
    by_id = get_insight("insight.low-life-supply-is-reservation")
    assert by_slug == by_id


def test_없는_인사이트는_예외() -> None:
    with pytest.raises(KeyError):
        get_insight("insight.does-not-exist")


def test_scope로_계층을_거른다() -> None:
    """3계층 사다리 — durable은 시즌을 넘어 유지되는 지식이다."""
    durable = search_insights(scope="durable", limit=100)
    assert durable and all(h.scope == "durable" for h in durable)
    assert "low-life-supply-is-reservation" in {h.slug for h in durable}


def test_레코드로_올라간_인사이트는_계보를_남긴다() -> None:
    """사실은 레코드로 갔지만 인사이트는 지우지 않는다 — 규율이 거기 남는다."""
    full = get_insight("low-life-supply-is-reservation")
    assert full["scope"] == "durable"
    assert "mechanic.reservation" in full["meta"]["promoted_to"]
