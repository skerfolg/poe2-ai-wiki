"""조용한 실패를 명시적 실패로 (이관 건 3, 2026-08-05).

없는 `gem_id`를 줘도 PoB는 오류를 내지 않는다 — `nameSpec`으로 대체 해석한다.
이름까지 틀리면 **젬이 소리 없이 사라지고** 호출자는 낮은 숫자를 실측으로 받는다.
한 세션이 없는 id로 트리 62포인트를 최적화한 뒤에야 발견했다.
"""

from __future__ import annotations

import pytest

from pok.engine.constraints.config_relevance import find_unset_options
from pok.pob.buildxml import spec_from_dict
from pok.pob.catalog import config_vars, gem_ids, suggest_gem_ids

BASE = {"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90}
SPARK = "Metadata/Items/Gems/SkillGemSpark"


def test_catalog_extraction_is_complete_enough() -> None:
    assert len(gem_ids()) > 900 and SPARK in gem_ids()
    assert len(config_vars()) > 500
    assert {"multiplierIncisionStackCount", "conditionBleedAggravated"} <= config_vars()


def test_unknown_gem_id_is_rejected_with_the_canonical_candidate() -> None:
    """이관 노트의 실측 그대로 — 표시 이름이 맞으면 정본 id를 정확히 짚어야 한다."""
    with pytest.raises(ValueError, match="SkillGemMeleePhysicalDamageSupport"):
        spec_from_dict(
            {
                **BASE,
                "skills": [
                    {
                        "gems": [
                            {
                                "gem_id": "Metadata/Items/Gems/SkillGemHeavySwingSupport",
                                "name": "Heavy Swing",
                                "level": 20,
                            }
                        ]
                    }
                ],
            }
        )


def test_unknown_config_key_is_rejected_with_candidates() -> None:
    with pytest.raises(ValueError, match="multiplierIncisionStackCount"):
        spec_from_dict({**BASE, "config": {"multiplierIncisionStacks": 5}})


def test_valid_spec_passes() -> None:
    spec = spec_from_dict(
        {
            **BASE,
            # 스파크는 모드가 둘이라 `stat_set_index`가 필요하다(#52)
            "skills": [
                {"gems": [{"gem_id": SPARK, "name": "Spark", "level": 20, "stat_set_index": 1}]}
            ],
            "config": {"multiplierIncisionStackCount": 10},
        }
    )
    assert spec.skills[0].gems[0].gem_id == SPARK


def test_name_suggestion_beats_id_similarity() -> None:
    """이름이 대개 맞고 id만 틀리다 — id 유사도부터 재면 엉뚱한 젬이 나온다."""
    assert suggest_gem_ids("Heavy Swing") == [
        "Metadata/Items/Gems/SkillGemMeleePhysicalDamageSupport"
    ]


def test_relevant_unset_config_is_surfaced() -> None:
    """기본값 0을 실측으로 오해하는 것을 막는다 — 이관 노트의 두 건이 나와야 한다."""
    stats = {
        "support.incision": [
            "Hits from Supported Skills inflict 1 Incision",
            "3% more Magnitude of Bleeding inflicted with Supported Skills per Incision "
            "consumed Recently, up to 30%",
        ],
        "support.bleed-i": ["Supported Skills have 50% chance to inflict Bleeding"],
    }
    found = {u.var for u in find_unset_options(stats, configured=[])}
    assert "multiplierIncisionStackCount" in found, "절개 스택 — 0이면 젬이 무가치해 보인다"
    assert "conditionBleedAggravated" in found, "가중 출혈 — off면 수치가 절반이다"


def test_configured_options_drop_out() -> None:
    stats = {"support.incision": ["Hits from Supported Skills inflict 1 Incision"]}
    found = {u.var for u in find_unset_options(stats, ["multiplierIncisionStackCount"])}
    assert "multiplierIncisionStackCount" not in found


def test_unrelated_build_does_not_get_bleed_options() -> None:
    """관련성 매칭이 헐거우면 경고가 소음이 되어 아무도 안 읽는다."""
    found = {
        u.var
        for u in find_unset_options(
            {"skill.spark": ["Fires projectiles that deal Lightning Damage"]}, configured=[]
        )
    }
    assert not ({"multiplierIncisionStackCount", "conditionBleedAggravated"} & found)


def test_class_and_ascendancy_are_validated_with_candidates() -> None:
    """조용한 폴백 회귀 (이관 3 #6): 실명·오탈자가 오류 없이 통과했다.

    `ascendancy="Infernalist"`(실명)를 주면 PoB가 조용히 무시하고 meta.ascendancy가
    "None"이 됐다 — 스펙이 요구하는 값은 내부 코드("Witch1")인데 KB의
    `ascendancy_name`은 실명이라 매핑을 모르면 맞힐 수 없다.
    """
    import pytest

    from pok.pob.buildxml import spec_from_dict

    spec_from_dict({"class_name": "Witch", "ascendancy": "Witch1"})  # 정상은 통과
    with pytest.raises(ValueError) as err:
        spec_from_dict({"class_name": "Witch", "ascendancy": "Infernalist"})
    assert "Witch1" in str(err.value), "실명을 주면 정본 코드를 알려줘야 한다"
    with pytest.raises(ValueError) as err2:
        spec_from_dict({"class_name": "NotAClass", "ascendancy": "Witch1"})
    assert "허용" in str(err2.value)


def test_unique_without_explicit_lines_is_rejected() -> None:
    """유니크 옵션 조용한 무시 회귀 (이관 3 #1).

    이름+베이스만 주면 PoB가 **아무 효과도 안 붙인 채** 계산한다 — 오류도 경고도
    없어 "그 유니크를 쓴 수치"로 읽힌다(실측: 288.63 vs 옵션 포함 433.08).
    """
    import pytest

    from pok.pob.buildxml import spec_from_dict

    base = {"class_name": "Witch", "ascendancy": "Witch1"}
    with pytest.raises(ValueError) as err:
        spec_from_dict(
            {**base, "items": [{"slot": "Weapon 1", "text": "Sacred Flame\nShrine Sceptre"}]}
        )
    assert "옵션 줄이 하나도 없다" in str(err.value)
    # 옵션을 적으면 통과한다 — 롤 수치가 KB 범위와 달라도 같은 줄로 본다
    spec_from_dict(
        {
            **base,
            "items": [
                {
                    "slot": "Weapon 1",
                    "text": "Rarity: UNIQUE\nSacred Flame\nShrine Sceptre\nImplicits: 0\n"
                    "Gain 50% of Damage as Extra Fire Damage",
                }
            ],
        }
    )
    # 일반 희귀는 무관하다
    spec_from_dict(
        {
            **base,
            "items": [
                {
                    "slot": "Ring 1",
                    "text": "Rarity: RARE\nMy Ring\nGold Ring\nImplicits: 0\n+80 to maximum Life",
                }
            ],
        }
    )


def test_staged_skill_requires_explicit_stages() -> None:
    """단계형 스킬의 조용한 1단계 계산 회귀 (이관 4 #11).

    PoB는 젬 인스턴스의 `skillStageCount`가 없으면 **1단계**로 잰다
    (`CalcActiveSkill.lua:868`). 실측: 화염파 1단계 288.6 vs 10단계 1402.4 —
    **4.86배**. 세션은 그 1단계 수치를 실측으로 받아 설계 판단을 내렸다.
    어느 단계로 설계할지는 판단이므로 값을 정해 주지 않고, 미지정만 막는다.
    """
    import pytest

    from pok.pob.buildxml import spec_from_dict, to_xml

    gem = {
        "name": "Flameblast",
        "gem_id": "Metadata/Items/Gems/SkillGemFlameblast",
        "level": 20,
    }
    base = {"class_name": "Witch", "ascendancy": "Witch1"}
    with pytest.raises(ValueError) as err:
        spec_from_dict({**base, "skills": [{"gems": [gem]}]})
    assert "단계형" in str(err.value) and "1단계로 계산" in str(err.value)

    spec = spec_from_dict({**base, "skills": [{"gems": [{**gem, "stages": 10}]}]})
    assert spec.skills[0].gems[0].stages == 10
    xml = to_xml(spec)
    assert 'skillStageCount="10"' in xml and 'skillStageCountCalcs="10"' in xml

    # 단계형이 아닌 스킬은 무관하다 (`stat_set_index`는 스파크가 모드 2개라 필요 — #52)
    spec_from_dict({**base, "skills": [{"gems": [
        {"name": "Spark", "gem_id": "Metadata/Items/Gems/SkillGemSpark", "level": 20,
         "stat_set_index": 1}
    ]}]})  # fmt: skip


def test_short_explicit_is_matched_by_line_not_length() -> None:
    """짧은 문구를 **길이로 걸러 내면 오거부**가 된다 (백로그 #24).

    부분 문자열 비교의 12자 문턱은 짧은 조각이 남의 줄에 우연히 걸리는 오탐을
    막으려던 것인데, 그 문턱 때문에 `Onslaught`(정규화 9자)가 **비교 대상에서 통째로
    빠졌다.** 텍스트에 멀쩡히 있는데도 "옵션 줄이 하나도 없다"가 됐고, 그 유니크가
    있는 **Helmet 슬롯 전체가 죽었다**(실측 2026-08-09 — 도구가 만든 자기 후보를
    도구가 거부했다).

    ⚠ 이 결함은 KB 전체에서 `item.thrillsteel` **1건**이 유발했다. 한 건이 슬롯
    하나를 통째로 막는다 — 후보 하나의 예외가 최적화 루프 전체를 죽이기 때문이다.
    """
    import pytest

    from pok.engine.items import enumerate_slot_uniques
    from pok.pob.buildxml import spec_from_dict

    base = {"class_name": "Witch", "ascendancy": "Witch1"}
    thrill = next(c for c in enumerate_slot_uniques("Helmet") if c.label == "item.thrillsteel")
    assert thrill.text.splitlines()[-1] == "Onslaught", "후보 생성기는 정상이다 — 문제는 검사기"
    spec_from_dict({**base, "items": [{"slot": "Helmet", "text": thrill.text}]})

    # 게이트는 살아 있어야 한다 — 옵션을 정말 안 적으면 여전히 거부
    with pytest.raises(ValueError) as err:
        spec_from_dict(
            {
                **base,
                "items": [
                    {
                        "slot": "Helmet",
                        "text": "Rarity: UNIQUE\nThrillsteel\nSpired Greathelm\nImplicits: 0",
                    }
                ],
            }
        )
    assert "옵션 줄이 하나도 없다" in str(err.value)
