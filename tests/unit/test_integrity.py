"""스펙 자체의 설계 무결성 — 적법한데 **애초에 빌드가 아닌 것** (백로그 #58 ①).

한 세션이 같은 실패를 3연속했고 **세 번 다 도구가 통과시켰다**. 지금까지의 강제
지점은 전부 "지금 적법한가"를 봤기 때문이다. 실측 2026-08-11: 주력기가 스펙에 없는
채로 3회차가 돌았고 `CombinedDPS` 2,562 → 주력기 투입 시 **24,436**.
"""

from __future__ import annotations

from pok.engine.integrity import spec_integrity

COEA = {
    "gem_id": "Metadata/Items/Gems/SkillGemCastOnElementalAilment",
    "name": "Cast on Elemental Ailment",
}
SPARK = {"gem_id": "Metadata/Items/Gems/SkillGemSpark", "name": "Spark", "stat_set_index": 1}
UNLEASH = {"gem_id": "Metadata/Items/Gems/SkillGemUnleashSupport", "name": "Unleash"}


def test_main_group_without_a_damage_skill_is_reported() -> None:
    problems = spec_integrity({"skills": [{"gems": [COEA, UNLEASH]}]})
    assert any("딜을 낼 스킬이 없다" in p for p in problems)
    assert any("24,436" in p for p in problems), "실측을 함께 줘야 크기를 안다"


def test_unconnected_trigger_group_is_reported() -> None:
    """트리거 젬만 든 그룹은 정신력만 점유하고 아무것도 하지 않는다."""
    problems = spec_integrity(
        {"skills": [{"gems": [SPARK]}, {"gems": [COEA]}], "main_socket_group": 1}
    )
    assert any("skills[1]" in p and "발동될 스킬이 없다" in p for p in problems)
    assert not any("skills[0]" in p for p in problems), "정상 그룹까지 짚으면 안 읽힌다"


def test_main_active_skill_pointing_at_a_meta_gem_is_reported() -> None:
    """`mainActiveSkill`은 그룹 안 **순번**이다 — 메타 젬을 가리키면 딜이 0으로 잡힌다."""
    problems = spec_integrity({"skills": [{"gems": [COEA, SPARK], "main_active_skill": 1}]})
    assert any("딜을 내지 않는 젬" in p and "2='Spark'" in p for p in problems), (
        "어느 번호를 가리켜야 하는지까지 줘야 고칠 수 있다"
    )


def test_out_of_range_main_socket_group_is_reported() -> None:
    problems = spec_integrity({"skills": [{"gems": [SPARK]}], "main_socket_group": 3})
    assert any("main_socket_group=3" in p for p in problems)


def test_a_normal_build_is_silent() -> None:
    """게이트가 정상을 막으면 신호가 죽는다 (§0 ⑤) — 경고도 마찬가지다."""
    assert spec_integrity({"skills": [{"gems": [SPARK, UNLEASH]}]}) == ()
    # 트리거 그룹이라도 **발동될 스킬이 함께 있으면** 조용하다
    assert not any(
        "발동될 스킬이 없다" in p
        for p in spec_integrity({"skills": [{"gems": [COEA, SPARK], "main_active_skill": 2}]})
    )


def test_empty_spec_is_reported() -> None:
    assert spec_integrity({"skills": []})[0].startswith("스킬 그룹이 하나도 없다")
