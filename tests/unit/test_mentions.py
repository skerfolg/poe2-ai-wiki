"""메커니즘 언급 스캐너 — 의심 엣지 발견은 기계, 판정은 사용자 (2026-08-06).

사용자 요구: "의심되는 메커니즘을 발견하고 사용자에게 리포트" — 엣지를 하나하나
가르치는 구조는 지속 불가하므로, 발견을 결정적 스캔으로 내리고 판정만 남긴다.
"""

from __future__ import annotations

from pok.kb.graph.mentions import scan_mechanic_mentions


def test_state_transition_candidates_are_found_and_ranked_first() -> None:
    """사용자 예시 연쇄의 고리(동결→산산조각)가 실제로 발견돼야 한다."""
    scan = scan_mechanic_mentions(concepts=["freeze", "shatter", "frozen"], limit=40)
    assert scan.lexicon_size > 200, "메커니즘 사전(GAME_DATA 정의문)이 로드돼야 한다"
    pairs = {(e.source_id, e.mechanic_id) for e in scan.edges}
    assert ("mechanic.shatter", "mechanic.frozen") in pairs, (
        "'Frozen enemies Shatter when killed' — 상태 전이 후보의 표본"
    )
    shatter = next(e for e in scan.edges if e.source_id == "mechanic.shatter")
    assert shatter.conditional and "Frozen" in shatter.quote, "판정은 인용문을 보고 한다"
    assert scan.edges[0].source_type == "Mechanic", "상태 전이(연쇄의 뼈대)가 앞에 온다"


def test_concept_filter_narrows_and_truncation_is_reported() -> None:
    """전량을 내밀면 판정 게이트가 마비된다 — 컨셉 필터 + 절단 보고."""
    narrow = scan_mechanic_mentions(concepts=["bleed"], limit=30)
    assert 0 < len(narrow.edges) <= 30
    assert narrow.total_found > len(narrow.edges), "필터 전 전체 규모가 항상 보인다"
    wide = scan_mechanic_mentions(limit=10)
    assert any("10건만 반환" in n for n in wide.notes), "절단은 조용히 하지 않는다"


def test_negation_is_flagged_not_filtered() -> None:
    """부정 문맥(면역·차단)은 걸러내지 않고 표시만 한다 — 판정은 사용자 몫."""
    scan = scan_mechanic_mentions(limit=3000)
    negated = [e for e in scan.edges if e.negated]
    assert negated, "immune/cannot 류 문맥이 negated로 표시돼야 한다"
    assert scan.edges, "표시는 하되 목록에서 빠지면 안 된다"
