"""키워드 정의 수집 — 상태 이상 계층의 빈 칸 (이관 건 2026-08-05).

빌드 세션이 "절개 1중첩당 출혈 확률 10%, 최대 10, 출혈 유발 시 초기화"를 KB에서
찾지 못했다. 젬 페이지는 "1 Incision을 부여한다"까지만 말하고 그 규칙은
**메커니즘 자체의 정의**인데, 우리는 그 층을 수집 대상에 넣지 않았다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pok.kb.ingest.keywords import collect_links, parse_definition

RAW = Path("artifacts/ingest-raw/0.5.4b")

# 원시 스냅샷(poe2db HTML)은 gitignore되는 파생물이라 CI에 없다 — 재수집은 네트워크가
# 필요하고 패치판에 묶여 있어 CI에서 확보할 수 없다. 없으면 skip한다(통합 테스트가
# LuaJIT·PoB 스냅샷에 쓰는 규약과 같은 방식). 실측 2026-08-07: 가드가 없어 CI에서
# FileNotFoundError로 터졌다.
pytestmark = pytest.mark.skipif(
    not RAW.is_dir(), reason="artifacts/ingest-raw 스냅샷 없음 (수집 후에만 검증 가능)"
)


def test_only_absolute_hover_urls_are_fetchable() -> None:
    """`?s=Data\\KeywordPopups/…` 상대 쿼리는 팝업이 아니라 **검색 페이지**다.

    받으면 홈페이지가 와서 엉뚱한 정의가 수록된다 — 실측 2026-08-05에 실제로
    `Abyssal_Modifiers`가 "Return of the Ancients 0.5"라는 이름으로 들어왔다.
    """
    links = collect_links(RAW)
    assert len(links) > 400, "원시에서 키워드를 못 모았다"
    absolute = [u for u in links.values() if u.startswith("http")]
    assert 200 < len(absolute) < len(links), "절대/상대가 섞여 있어야 정상"


def test_absolute_hover_wins_over_search_query(tmp_path: Path) -> None:
    """같은 키워드가 두 꼴로 링크되면 **팝업 조각 쪽을 취해야** 한다.

    선입선출이면 어느 키워드가 수집되는지를 **파일명 알파벳 순서**가 정한다:
    `Amulets.html`이 검색 쿼리를 들고 먼저 오면 뒤에 오는 스킬 페이지의 정상 URL이
    묻힌다. 실측 2026-08-08: 그렇게 **90개**가 버려졌고 그중 `Archon_Buff`에
    집정관 버프 지속 10초·회복 20초가 있었다(백로그 #3을 "출처 갭"으로 오분류시킨 것).
    """
    pages = tmp_path / "poe2db" / "us"
    pages.mkdir(parents=True)
    # 알파벳 앞 페이지가 열화된 링크를 준다
    (pages / "Amulets.html").write_text(
        '<a class="KeywordPopups" href="Archon_Buff" '
        'data-hover="?s=Data%5CKeywordPopups%2FArchon">Archon</a>',
        encoding="utf-8",
    )
    (pages / "Zzz_Skill.html").write_text(
        '<a class="KeywordPopups" href="Archon_Buff" '
        'data-hover="https://cdn.poe2db.tw/cache2/us/x/abc">Archon</a>',
        encoding="utf-8",
    )
    assert collect_links(tmp_path)["Archon_Buff"].startswith("http")


def test_definition_separates_title_from_body() -> None:
    """`.card-header`(제목) + `.keyword-body`(정의). 통짜로 자르면 붙는다."""
    parsed = parse_definition((RAW / "poe2db/keywords/Accuracy.html").read_text(encoding="utf-8"))
    assert parsed["name"] == "Accuracy", "제목에 정의 첫 문장이 붙으면 안 된다"
    assert parsed["lines"] and parsed["lines"][0].startswith("Accuracy is used to hit")


def test_incision_rule_is_now_present() -> None:
    """이관 건의 원 증상 — 이 문장이 없어서 세션이 배율을 못 세웠다."""
    parsed = parse_definition((RAW / "poe2db/keywords/Incision.html").read_text(encoding="utf-8"))
    body = " ".join(parsed["lines"])
    assert "10% chance" in body, "스택당 확률"
    assert "maximum of 10 Incision stacks" in body, "최대 중첩"
    assert "removed when Bleeding is inflicted" in body, "출혈 유발 시 초기화"


def test_structured_records_are_merged_not_overwritten() -> None:
    """PoB 구조화 값과 poe2db 문장은 서로를 대신하지 못한다 — 둘 다 남긴다."""
    from pok.index.search import get_entry

    data = get_entry("mechanic.bleed", fields=["data"])["data"]
    assert data.get("scales_from") == ["Physical"], "PoB 구조화 값이 살아 있어야 한다"
    assert data.get("constants"), "PoB 상수도"
    joined = " ".join(data.get("keyword_stats", []))
    assert "bypasses Energy Shield" in joined, "poe2db 문장도 함께"


def test_mechanic_layer_is_no_longer_empty() -> None:
    """`type=Mechanic`이 5건이던 것이 이번 결함의 표면 증상이었다."""
    from pok.index.describe import describe_type

    assert describe_type("Mechanic").total > 200


def test_parallel_scan_falls_back_and_matches_serial() -> None:
    """병렬이 못 뜨면 **직렬로 되돌아간다** — 수집이 막히면 안 된다.

    실측 2026-08-09(1,079장·8코어): 직렬 28.8초 → 병렬 7.0초. 프로세스 풀은
    플랫폼(Windows spawn)·실행 문맥(`<stdin>` 실행·중첩 풀)에 따라 못 뜨므로
    되돌림 경로를 **문서가 아니라 시험으로** 확인한다(철칙 5).
    """
    import pok.kb.ingest.keywords as mod

    pages = sorted((RAW / "poe2db" / "us").glob("*.html"))[:250]
    parallel = [pairs for pairs in mod._scan_all(pages)]

    broken = mod.ProcessPoolExecutor

    class _Broken:
        def __init__(self, *a: object, **k: object) -> None:
            raise OSError("프로세스 풀 못 띄움 (시험)")

    mod.ProcessPoolExecutor = _Broken  # type: ignore[misc,assignment]
    try:
        serial = [pairs for pairs in mod._scan_all(pages)]
    finally:
        mod.ProcessPoolExecutor = broken  # type: ignore[misc]

    assert serial == parallel, "되돌림 결과가 다르면 되돌림이 아니라 다른 동작이다"
    assert any(pairs for pairs in serial), "둘 다 비었으면 시험이 아무것도 안 봤다"
