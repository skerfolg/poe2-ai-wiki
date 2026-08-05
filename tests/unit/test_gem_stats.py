"""젬 효과 문구 수록 — "배율이 KB에 있는가"를 **단일 지점**에서 잠근다.

이관 건 2026-08-05: 빌드 세션이 보조 젬 배율을 한 건도 인용하지 못했다.
Support 537건 전량에 효과 수치가 없었고, 원인은 파서가 `.Stats`를 **읽고도**
`.explicitMod`를 추출 대상에 넣지 않은 것이었다(B-4의 변종 — 그때는 스캔 범위를
넓혔지 추출 대상은 손대지 않았다).

증상만 고치면 축을 바꿔 또 재발하므로, 여기서는 **레코드 쪽 결과**를 본다.
파서를 어떻게 고치든 "젬에 효과 문구가 있는가"가 무너지면 걸린다.
"""

from __future__ import annotations

import pathlib

from pok.index.describe import describe_type
from pok.kb.ingest.parse import parse_detail

RAW = pathlib.Path("artifacts/ingest-raw/0.5.4b/poe2db/us")

# 원시 스냅샷이 없어 문구를 붙이지 못한 젬. **늘어나면 테스트가 깨진다** —
# 조용한 누락을 막는 게 목적이라 목록을 여기 고정한다.
KNOWN_MISSING_RAW = {"support.chain", "support.fire-infusion", "support.pierce", "support.unleash"}


def test_support_gems_carry_effect_numbers() -> None:
    """보조 젬에 효과 문구가 실려 있어야 한다 — 없으면 KB만으로 젬을 고를 수 없다."""
    profile = describe_type("Support")
    stats = next((f for f in profile.fields if f.field == "stats"), None)
    assert stats is not None, "Support 레코드에 stats 필드가 아예 없다"
    allowed_gap = len(KNOWN_MISSING_RAW) / profile.total * 100.0
    assert stats.pct >= 100.0 - allowed_gap - 0.5, (
        f"효과 문구 충전율 {stats.pct}% — 알려진 누락({len(KNOWN_MISSING_RAW)}건)보다 크다"
    )


def test_active_skills_carry_effect_numbers() -> None:
    """액티브 스킬도 같은 파서 경로를 탄다 — 함께 잠근다."""
    stats = next((f for f in describe_type("Skill").fields if f.field == "stats"), None)
    assert stats is not None and stats.pct > 95.0


def test_description_is_prose_and_stats_are_numbers() -> None:
    """`description`(산문)과 `stats`(수치)는 **다른 것**이다.

    파서가 `og:description`만 담아서 둘을 같은 것으로 취급한 게 이번 결함의 뿌리다.
    """
    page = parse_detail((RAW / "Bleed_I.html").read_text(encoding="utf-8", errors="replace"))
    assert page.description and not any(c.isdigit() for c in page.description), "산문엔 수치가 없다"
    assert page.stats == ["Supported Skills have 50% chance to inflict Bleeding"]


def test_br_separates_lines_but_inline_tags_do_not() -> None:
    """구분자는 `<br>`뿐이다.

    `get_text("\\n")`을 그냥 쓰면 `<a>`·`<span class=mod-value>`마다 줄이 갈려
    `"Supported Skills have / 80 / % more…"`로 조각난다 — 실측 2026-08-05.
    """
    page = parse_detail((RAW / "Abiding_Hex.html").read_text(encoding="utf-8", errors="replace"))
    assert page.stats == [
        "Supported Skills consume a Power Charge on use",
        "Supported Skills have 80% more duration when consuming a Power Charge",
    ]


def test_internal_identifiers_are_not_effect_text() -> None:
    """`receive_bleeding_chance_%_when_hit` 같은 내부 식별자는 문구가 아니다."""
    page = parse_detail((RAW / "Incision.html").read_text(encoding="utf-8", errors="replace"))
    assert page.stats == [
        "Hits from Supported Skills inflict 1 Incision",
        "3% more Magnitude of Bleeding inflicted with Supported Skills per Incision "
        "consumed Recently, up to 30%",
    ]


def test_effect_text_is_searchable() -> None:
    """수록만으로는 부족하다 — **찾을 수 있어야** 세션이 젬을 고른다."""
    from pok.index.search import search

    hits = search(query="chance to inflict Bleeding", type_="Support", limit=5)
    assert any(h.id == "support.bleed-i" for h in hits)


def test_new_data_keys_are_registered_as_machine_generated() -> None:
    """새 data 키는 `_MACHINE_DATA_KEYS`에 등록해야 재수집이 갱신한다.

    미등록 키는 기계 산출인데도 사람 판정으로 취급돼 재수집이 덮지 못한다(실측 사고).
    """
    from pok.kb.ingest.merge import _MACHINE_DATA_KEYS

    assert {"stats", "implicit_stats", "quality_stats"} <= _MACHINE_DATA_KEYS
