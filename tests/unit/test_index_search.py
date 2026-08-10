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


def test_diagnose_empty_names_the_real_cause() -> None:
    """0건일 때 **왜**를 낸다 — 빈 배열은 아무것도 말하지 않아 파일 탐색을 부른다.

    실측 2026-08-05: 빌드 테스트 3회차의 `search_kb` 빈 결과 9건이 전부 KB 갭이
    아니라 질의 방식 문제였다(한글 효과 문구 5 · type 오해 1 · AND 과협소 3).
    """
    from pok.index.search import diagnose_empty

    # ① 한글 효과 질의 — 이름은 한글이 되지만 효과 문구는 영어뿐이다
    ko = diagnose_empty(query="공격 속도", type_="Support")
    assert any("한글" in r for r in ko.reasons)
    assert ("속도", 0) in ko.token_counts, "어느 토큰이 죽었는지 지목해야 한다"

    # ② type 오해 — 룬은 Item이 아니라 Modifier에 있다
    rune = diagnose_empty(query="Rune", type_="Item")
    assert dict(rune.other_types).get("Modifier", 0) > 0
    assert any("다른 타입에는 있다" in r for r in rune.reasons)

    # ③ AND 매칭 — 토큰이 각각은 있는데 한 레코드에 함께 없다
    both = diagnose_empty(query="Jewel Attack Speed", type_="Modifier")
    assert all(n > 0 for _, n in both.token_counts)
    assert any("AND" in r for r in both.reasons)

    # ④ 정말 없는 것 — 필터로 설명되지 않으면 그렇게 말한다 (KD-5: ingest 문제)
    gone = diagnose_empty(query="zzzqqnonexistent")
    assert any("정말 KB에 없을 수 있다" in r for r in gone.reasons)


def test_empty_search_still_records_as_empty() -> None:
    """진단을 실었다고 **갭 신호를 잃으면 안 된다** — 텔레메트리는 여전히 empty."""
    from pok.common import telemetry
    from pok.mcp import server

    fn = getattr(server.search_kb, "fn", server.search_kb)
    out = fn(query="공격 속도", type="Support", limit=15)
    assert len(out) == 1 and out[0]["empty"] is True
    assert out[0]["why"], "이유가 비면 진단이 아니다"
    assert telemetry.classify(out) == "empty"


def test_이름이_맞는_레코드가_먼저_온다() -> None:
    """B-14 실측 2026-08-07: `search_kb("보이지 않는 길")`이 엉뚱한 결과만 냈다.
    레코드는 **있었다** — 176개 노드가 stats에 "보이지 않는 길 필요"를 달고 있어
    177건이 매칭됐고, `ORDER BY r.id`가 정작 그 노드를 **164번째**로 밀었다.
    세션은 상위 10건만 보고 "KB에 없다"로 결론냈다.
    """
    from pok.index.search import search

    for q in ("보이지 않는 길", "The Unseen Path"):
        hits = search(query=q, limit=5)
        assert hits[0].id == "passive.the-unseen-path-5571", f"{q}: 이름 정확 일치가 1위여야 한다"


def test_해금_제약이_검색_히트에_실린다() -> None:
    """B-13: 차단이 조립 시점(assemble_pob)에만 있으면 세션은 그 전에 이미 잘못된
    설계 결론을 낸다. 후보를 내는 **모든 지점**에서 같은 판정이 나와야 한다.
    """
    from pok.index.search import search

    (locked,) = search(query="힘 소진", type_="Passive", for_ascendancy="Witch1")
    assert locked.locked_to == "Oracle"
    assert locked.excluded_by_unlock and "찍을 수 없다" in locked.excluded_by_unlock

    # **빼지 않고 표시한다** — 조용히 빼면 "KB에 없다"로 오독된다
    (owner,) = search(query="힘 소진", type_="Passive", for_ascendancy="Oracle")
    assert owner.locked_to == "Oracle" and owner.excluded_by_unlock is None

    # 선행 노드 요구형 — 전직 제약이 아니라서 전직 대조만으로는 안 잡힌다
    (prereq,) = search(query="탈주자의 길", type_="Passive", for_ascendancy="Witch1")
    assert prereq.locked_to is None
    assert set(prereq.requires_nodes) == {50239, 9535, 61309}
    assert prereq.excluded_by_unlock and "선행 노드" in prereq.excluded_by_unlock


def test_제약_없는_히트는_칸이_비어_나온다() -> None:
    """압축 히트(D14)에 상시 None 세 칸을 실으면 전 질의가 토큰을 문다."""
    from dataclasses import asdict

    from pok.index.search import search
    from pok.mcp import server

    (hit,) = search(query="Behemoth", type_="Passive", limit=1, for_ascendancy="Witch1")
    assert (hit.locked_to, hit.requires_nodes, hit.excluded_by_unlock) == (None, (), None)
    # 비어 있는 경고 칸은 전부 빠진다 — 새 경고를 더할 때마다 여기 늘어난다.
    # (`pob_gap`은 이 레코드에 실제 값이 있어 남는다)
    assert set(asdict(hit)) - set(server._hit_dict(hit)) == {
        "locked_to",
        "requires_nodes",
        "excluded_by_unlock",
        "carrier_unknown",
    }

    fn = getattr(server.search_kb, "fn", server.search_kb)
    (out,) = fn(query="힘 소진", type="Passive", for_ascendancy="Witch1")
    assert out["locked_to"] == "Oracle" and out["excluded_by_unlock"]
