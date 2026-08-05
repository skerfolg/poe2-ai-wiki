"""키워드 정의 수집 — 상태 이상 계층의 빈 칸 (이관 건 2026-08-05).

빌드 세션이 "절개 1중첩당 출혈 확률 10%, 최대 10, 출혈 유발 시 초기화"를 KB에서
찾지 못했다. 젬 페이지는 "1 Incision을 부여한다"까지만 말하고 그 규칙은
**메커니즘 자체의 정의**인데, 우리는 그 층을 수집 대상에 넣지 않았다.
"""

from __future__ import annotations

from pathlib import Path

from pok.kb.ingest.keywords import collect_links, parse_definition

RAW = Path("artifacts/ingest-raw/0.5.4b")


def test_only_absolute_hover_urls_are_fetchable() -> None:
    """`?s=Data\\KeywordPopups/…` 상대 쿼리는 팝업이 아니라 **검색 페이지**다.

    받으면 홈페이지가 와서 엉뚱한 정의가 수록된다 — 실측 2026-08-05에 실제로
    `Abyssal_Modifiers`가 "Return of the Ancients 0.5"라는 이름으로 들어왔다.
    """
    links = collect_links(RAW)
    assert len(links) > 400, "원시에서 키워드를 못 모았다"
    absolute = [u for u in links.values() if u.startswith("http")]
    assert 200 < len(absolute) < len(links), "절대/상대가 섞여 있어야 정상"


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
