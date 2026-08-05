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


def test_server_info_reports_actual_registered_tools() -> None:
    """이관 통보를 받은 세션이 **호출 가능 여부를 확인**할 수단 (이관 4 C10).

    실측 2026-08-05: 한 세션이 소스를 읽고 "도구가 있다"고 보고했는데 호출은
    `Unexpected keyword argument`로 실패했다. MCP 서버는 세션 시작 시점의 코드로
    상주하므로 재시작 전에는 새 도구가 없다.
    """
    from pok.mcp import server

    info = server.server_info()
    assert info["tool_count"] > 20
    # 모듈 전역을 훑으면 데코레이터 반환 형태에 따라 0종이 나온다 — 등록부에서 읽는다
    assert {"search_kb", "find_by_value", "describe_type", "check_constraints"} <= set(
        info["tools"]
    )
    assert info["commit"], "커밋을 알려줘야 '통보받은 판인가'를 확인할 수 있다"
