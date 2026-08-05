"""B-9 상태이상 계열 수록 — 출혈 한 건이 아니라 **계열 전체**를 수집하는가."""

from __future__ import annotations

from pok.kb.ingest.ailments import parse_ailments, pob_src


def test_parses_whole_family_not_just_bleed() -> None:
    """상태이상 6종 + 축적 4종(Freeze 중복) = 9종.

    출혈만 수록하면 KD-5가 지적한 건 바이 건 실패를 반복한다 — PoB에 계열 전체가
    테이블로 있으므로 전량을 받는다.
    """
    parsed = parse_ailments(pob_src())
    assert set(parsed) == {
        "Bleed",
        "Poison",
        "Ignite",
        "Chill",
        "Freeze",
        "Shock",  # ailmentTypeList
        "Electrocute",
        "HeavyStun",
        "Pin",  # buildupTypes (Freeze는 양쪽에 있다)
    }


def test_scales_from_is_the_decisive_field() -> None:
    """`ScalesFrom`이 설계 판단을 가른다 — 리포트에서 세션이 소스를 직접 읽어 얻은 것."""
    parsed = parse_ailments(pob_src())
    assert parsed["Bleed"]["scales_from"] == ["Physical"], "출혈은 물리에서만"
    assert parsed["Bleed"]["damage_type"] == "Physical"
    assert set(parsed["Poison"]["scales_from"]) == {"Physical", "Chaos"}
    assert parsed["Ignite"]["scales_from"] == ["Fire"]
    assert set(parsed["HeavyStun"]["scales_from"]) == {
        "Physical",
        "Fire",
        "Cold",
        "Lightning",
        "Chaos",
    }, "강한 기절은 5속성 전부에서 축적된다"


def test_nested_tables_do_not_leak_into_the_family() -> None:
    """중첩 테이블 경계 — 정규식으로 자르면 `Cold`·`Lightning`이 상태이상으로 샌다.

    실측: non-greedy 매칭이 `nonDamagingAilment`를 삼켜 `ScalesFrom` 안의 키와
    `BaseChillDuration` 같은 상수 이름까지 항목으로 잡혔다(16종). 괄호 균형으로
    자르고 계열 목록으로 제한해 9종이 됐다.
    """
    parsed = parse_ailments(pob_src())
    assert not {"Cold", "Lightning", "BaseChillDuration", "ChillMaxEffect"} & set(parsed)


def test_classification_and_constants() -> None:
    parsed = parse_ailments(pob_src())
    assert parsed["Ignite"]["elemental"] is True and parsed["Bleed"]["elemental"] is False
    assert parsed["Shock"]["damaging"] is False, "감전은 비피해 상태이상"
    assert parsed["Bleed"]["constants"]["BleedingHitDamagePercentPerMinute"] == 900
    assert parsed["Bleed"]["constants"]["BaseBleedingDuration"] == 5
