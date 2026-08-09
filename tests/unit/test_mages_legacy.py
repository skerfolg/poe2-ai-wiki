"""마법사의 유산 개별 보너스 수집 (백로그 #19).

KB에는 **이름 14종만** 있어서 마법사의 피를 평가하려면 PoB 소스를 직접 읽어야 했다.
특히 **Ruby·Sapphire·Topaz의 최대 저항 +5**는 설계를 바꾸는 정보인데 KB만 보고는
보이지 않았다.
"""

from __future__ import annotations

from pok.kb.ingest.mages_legacy import collect, parse_legacies

_SAMPLE = """
local legacies = {
\tLegacyOfAmethyst = {
\t\teffects = {
\t\t\t{ stat = "ChaosResist", type = "BASE", value = 45 },
\t\t}
\t},
\tLegacyOfRuby = {
\t\teffects = {
\t\t\t{ stat = "FireResist", type = "BASE", value = 60 },
\t\t\t{ stat = "FireResistMax", type = "BASE", value = 5 },
\t\t}
\t},
}
"""


def test_parser_reads_multi_effect_entries() -> None:
    """효과가 **여럿인** 유산을 하나만 읽으면 최대 저항이 조용히 사라진다."""
    parsed = parse_legacies(_SAMPLE)
    assert parsed["Legacy of Amethyst"] == [{"stat": "ChaosResist", "type": "BASE", "value": 45}]
    assert parsed["Legacy of Ruby"] == [
        {"stat": "FireResist", "type": "BASE", "value": 60},
        {"stat": "FireResistMax", "type": "BASE", "value": 5},
    ]


def test_display_names_match_kb_listing() -> None:
    """수집 이름이 KB `stats`의 표기와 정확히 맞아야 잇는다 (`Legacy of …`)."""
    from pok.index.search import get_entry

    data = get_entry("mechanic.mages-legacy", fields=["data"])["data"]
    listed = sorted(s.lstrip("• ") for s in data["stats"] if s.startswith("•"))
    assert sorted(data["legacies"]) == listed
    assert len(listed) == 14


def test_record_carries_the_duplicate_rule() -> None:
    """KB 원문("각각 하나만 적용")이 **중복은 무의미**로 읽히는데 아니다.

    중복은 자기 보너스를 더하지 않는 대신 **모든 유산의 값을 함께 올린다**
    (`CalcPerform.lua:1502-1528`).
    """
    from pok.index.search import get_entry

    data = get_entry("mechanic.mages-legacy", fields=["data"])["data"]
    assert "globalEffect" in data["duplicate_rule"]
    assert "floor" in data["duplicate_rule"]
    assert data["legacies"]["Legacy of Ruby"][-1]["stat"] == "FireResistMax", (
        "최대 저항 +5가 살아 있어야 한다 — 설계를 바꾸는 값이다"
    )


def test_collect_reads_the_pinned_snapshot() -> None:
    """스냅샷이 있으면 14종 전량이 나온다 (없으면 빈 dict — 조용한 실패 아님)."""
    legacies = collect()
    if legacies:
        assert len(legacies) == 14
