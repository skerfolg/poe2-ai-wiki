"""P2: MCP 도구 — 얇은 어댑터 검증 (실 KB 인덱스 사용, 네트워크 없음)."""

from __future__ import annotations

from pok.mcp.server import get_entry, related, search_kb


def test_search_kb_compact_hits() -> None:
    hits = search_kb(query="카오스 오브", limit=3)
    assert any(h["id"] == "item.chaos-orb" for h in hits)
    h = hits[0]
    assert set(h) == {"id", "type", "name_ko", "name_en", "tags", "verification"}, (
        "1단계는 압축 히트만 (D14 토큰 예산)"
    )


def test_search_kb_type_filter() -> None:
    hits = search_kb(query="Strength", type="Modifier", limit=5)
    assert hits and all(h["type"] == "Modifier" for h in hits)


def test_get_entry_fields_and_narrative() -> None:
    rec = get_entry(id="passive.chaos-inoculation", fields=["name", "verification"])
    assert set(rec) == {"id", "type", "name", "verification"}, "fields 선별 (2단계)"

    full = get_entry(id="passive.chaos-inoculation", include_narrative=True)
    assert "narrative" in full and "카오스 면역" in full["narrative"], (
        "서술 문서(knowledge/wiki)를 요청 시 동봉"
    )


def test_related_bidirectional() -> None:
    edges = related(id="defence.energy-shield")
    assert any(
        e["direction"] == "reverse" and e["src"] == "passive.chaos-inoculation" for e in edges
    ), "역방향(이 엔티티를 가리키는 관계)은 인덱스가 생성"
