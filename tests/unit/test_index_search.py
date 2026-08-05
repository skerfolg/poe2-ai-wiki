def test_전직으로_노드를_열거한다() -> None:
    """양쪽 빌드 세션이 `knowledge/tree/*.ndjson` grep으로 도피한 지점(2026-08-04).
    포인트 예산 장부를 쓰려면 전직 노터블 전량이 필요한데 조회 경로가 없었다."""
    from pok.index.search import search

    hits = search(ascendancy="블러드 메이지", limit=99)
    assert len(hits) > 5
    names = {h.name_ko for h in hits}
    assert "블러드 메이지" in names  # 시작 노드
    assert "피 가시" in names  # 노터블 — 이름이 전직명과 무관해도 잡힌다


def test_전직은_어느_표기로도_찾힌다() -> None:
    """표기 불일치가 조회 실패의 단골 원인이다(B-1)."""
    from pok.index.search import search

    by_ko = {h.id for h in search(ascendancy="블러드 메이지", limit=99)}
    by_en = {h.id for h in search(ascendancy="Blood Mage", limit=99)}
    assert by_ko and by_ko == by_en


def test_전직_필터는_질의와_함께_쓸_수_있다() -> None:
    from pok.index.search import search

    hits = search(query="출혈", ascendancy="블러드 메이지", limit=99)
    assert hits and all(h.type == "Passive" for h in hits)
