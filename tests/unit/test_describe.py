"""B-11 메타 조회 — "KB에 무엇이 어떤 형태로 있나"에 도구가 답하는가."""

from __future__ import annotations

import pytest

from pok.index.describe import describe_kb, describe_type


def test_describe_type_reports_fill_rate_not_schema() -> None:
    """필드 **충전율**을 낸다 — 스키마 정의로는 알 수 없는 것이다.

    실측: Skill의 `description`은 100%지만 `category`는 12.5%뿐이다. 이 차이를
    모르면 `category`로 거르는 설계가 대부분의 스킬을 조용히 놓친다.
    """
    profile = describe_type("Skill")
    assert profile.total > 0
    fields = {f.field: f for f in profile.fields}
    assert fields["description"].pct == 100.0
    assert 0 < fields["category"].pct < 50, "충전율이 낮은 필드를 낮다고 말해야 한다"
    assert fields["cost"].value_types == ("list",)
    assert fields["description"].samples, "값 샘플이 있어야 형태를 안다"


def test_korean_coverage_is_measured_by_content_not_field_name() -> None:
    """한글 보유율은 필드 **이름**이 아니라 **내용**으로 잰다.

    명명 규약이 타입마다 다르다 — Passive는 `stats`가 한글이고 `stats_en`이 영어,
    Item·Modifier는 `*_ko`다. `_ko` 접미사만 세면 Passive가 19%로 보이지만 실제
    한글 보유율은 99.6%다(실측 2026-08-05, 진단 문구를 이 오차로 잘못 적었었다).
    """
    assert describe_type("Passive").korean_effect_pct > 90
    assert describe_type("Support").korean_effect_pct < 5, "Support 효과 문구는 영어뿐"


def test_describe_type_field_gives_value_distribution() -> None:
    """field를 주면 값 분포 — "이 필드에 실제로 어떤 값이 오는가"."""
    profile = describe_type("Skill", field="category")
    cat = next(f for f in profile.fields if f.field == "category")
    assert any("건)" in s for s in cat.samples), "빈도가 붙어야 분포다"


def test_describe_type_unknown_lists_known_types() -> None:
    """없는 타입을 물으면 **있는 타입을 알려준다** — 막다른 길을 만들지 않는다."""
    with pytest.raises(KeyError, match="Skill"):
        describe_type("Nonexistent")


def test_describe_kb_gives_overview() -> None:
    kb = describe_kb()
    assert kb["total"] > 10000
    types = {r["type"] for r in kb["types"]}
    assert {"Skill", "Support", "Passive", "Item", "Modifier"} <= types


def test_find_by_value_answers_what_fits_in_the_headroom() -> None:
    """ "정신력 40 남았다"에서 **그 40으로 무엇을 넣나**로 넘어가는 경로.

    실측 2026-08-05: 점유 검사기가 잔여까지는 냈는데 후보를 물을 도구가 없었다.
    `search_kb`는 텍스트만 매칭해 `reservation` 같은 수치 필드에 닿지 못한다.
    """
    from pok.index.describe import find_by_value

    hits = find_by_value("reservation.max", type_="Skill", maximum=40, limit=50)
    assert hits, "정신력 40 이하로 점유하는 스킬이 있어야 한다"
    assert all(h.value <= 40 for h in hits)
    assert hits == sorted(hits, key=lambda h: (h.value, h.id)), "값 오름차순 (순위 판단 없음)"
    assert all("reservation[" in h.path for h in hits), "리스트는 원소마다 갈라진다"

    # 범위 밖은 걸러진다 — 상한만 준 것과 하한을 함께 준 것이 일관되어야 한다
    high = find_by_value("reservation.max", type_="Skill", minimum=90, limit=50)
    assert high and all(h.value >= 90 for h in high)
    assert not ({h.id for h in hits} & {h.id for h in high}), "40 이하와 90 이상은 겹칠 수 없다"


def test_find_by_value_ignores_non_numeric_and_bool() -> None:
    """bool은 수치가 아니다 — `pob_computable: False`가 0으로 잡히면 안 된다."""
    from pok.index.describe import find_by_value

    assert not find_by_value("pob_computable", type_="Skill", limit=10)
