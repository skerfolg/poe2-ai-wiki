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


def test_server_info_reports_signatures_not_just_names() -> None:
    """도구 **이름**만으로는 부족하다 — 갱신의 상당수가 "기존 도구에 인자 추가"다.

    실측 2026-08-06(이관 D-2): `check_constraints`는 목록에 있고 호출도 되는데
    `axes` 인자만 없는 옛 프로세스가 "이상 없음"으로 통과했다. 파라미터 지문이
    있어야 호출을 시도하기 전에 재시작 필요를 판정할 수 있다.
    """
    from pok.mcp import server

    info = server.server_info()
    assert info["tool_count"] > 20
    tools = info["tools"]
    assert isinstance(tools, dict), "이름 목록이 아니라 {이름: 파라미터 지문}이어야 한다"
    assert "axes" in tools["check_constraints"], "지문이 비면 D-2가 재발한다"
    assert "ids" in tools["find_by_value"]
    assert "attribute_choices" not in tools["search_kb"], "지문은 도구별이어야 한다"


def test_server_info_separates_loaded_from_source_commit() -> None:
    """git HEAD만 보고하면 **소스를 고치는 순간 commit이 따라 올라간다** (이관 D-1).

    방지 장치가 방지하려는 조건(소스 갱신 + 옛 프로세스)에서 항상 통과했다 —
    기동 시점 커밋을 프로세스에 캡처하고 둘을 분리해야 불일치가 신호가 된다.
    """
    from pok.mcp import server

    original = server._LOADED_COMMIT
    try:
        # ⚠ 「로드 직후니 둘이 같다」에 기대면 **다른 세션이 커밋하는 순간 깨진다** —
        #   import 시점과 호출 시점 사이에 HEAD가 움직인다. 이 레포는 세션 여럿이
        #   같은 트리를 공유하므로 실제로 깨졌다(2026-08-12, 코덱스 수집과 동시 작업).
        #   검사하려는 것은 **두 값의 비교 동작**이지 HEAD의 안정성이 아니다.
        server._LOADED_COMMIT = server.server_info()["source_commit"]
        info = server.server_info()
        assert "loaded_commit" in info and "source_commit" in info
        assert info["stale"] is False, "두 커밋이 같으면 stale이 서면 안 된다"

        # 로드 커밋이 옛것인 상황을 재현 — stale이 서고 note가 재시작을 지시해야 한다
        server._LOADED_COMMIT = "0000000"
        stale_info = server.server_info()
        assert stale_info["stale"] is True
        assert "재시작" in stale_info["note"]
    finally:
        server._LOADED_COMMIT = original
