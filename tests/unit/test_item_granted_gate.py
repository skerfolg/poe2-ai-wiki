"""젬으로 못 켜는 스킬을 소켓하면 거부한다 (백로그 #47, 2026-08-10).

PoB에는 `Metadata/Items/Gems/SkillGemFirebolt`가 있어 소켓하면 **조용히 계산된다**
(실측 `TotalDPS 217.5`). 그런데 Firebolt의 획득 출처는 지팡이 부여뿐이라 인게임에선
그 스킬을 켤 방법이 없다 — 한 세션이 그 수치 위에서 전 회차를 조립했다.

⚠ 함께 지키는 것: **젬 경로와 아이템 부여는 배타가 아니다.** Herald 3종·Spark·
Unleash·Blink 등 8종이 둘 다 가진다. 그 8종을 막으면 게이트가 정상 트래픽을 막아
신호가 죽는다(BACKLOG §0 ⑤) — 그래서 아래 두 방향을 같이 시험한다.
"""

from __future__ import annotations

import pytest

from pok.pob.buildxml import spec_from_dict

BASE = {"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90}


def _spec(gem_id: str, name: str) -> dict[str, object]:
    # `stat_set_index`는 여기 관심사가 아니지만 모드 2개인 젬은 선언을 요구한다(#52)
    gem = {"gem_id": gem_id, "name": name, "level": 20, "stat_set_index": 1}
    return {**BASE, "skills": [{"gems": [gem]}]}


def test_item_granted_skill_socketed_as_a_gem_is_rejected() -> None:
    with pytest.raises(ValueError) as err:
        spec_from_dict(_spec("Metadata/Items/Gems/SkillGemFirebolt", "Firebolt"))
    msg = str(err.value)
    assert "아이템 부여 스킬" in msg
    assert "Ashen Staff" in msg, "부여원을 알려주지 않으면 호출자가 고칠 수 없다"


@pytest.mark.parametrize(
    ("gem_id", "name"),
    [
        ("Metadata/Items/Gems/SkillGemSpark", "Spark"),
        ("Metadata/Items/Gems/SkillGemHeraldOfAsh", "Herald of Ash"),
        ("Metadata/Items/Gems/SkillGemUnleashSupport", "Unleash"),
    ],
)
def test_skills_with_both_routes_still_pass(gem_id: str, name: str) -> None:
    """젬으로도 나오는 스킬은 통과해야 한다 — poe2db From 카드가 **여러 장**이다.

    파서가 마지막 카드로 덮어써서 젬 경로가 사라졌고, 8종이 `item-granted`로
    오분류돼 있었다(`skill.spark`·Herald 3종·`skill.unleash`·`skill.blink`…).
    """
    spec = spec_from_dict(_spec(gem_id, name))
    assert spec.skills[0].gems[0].gem_id == gem_id


def test_gem_route_survives_multiple_from_cards() -> None:
    """분류의 출처를 직접 시험한다 — 게이트가 옳아도 라벨이 틀리면 소용없다."""
    from pok.kb.ingest.merge import skill_source

    both = skill_source(["Uncut Skill Gem", "Earthbound"], {"earthbound": "item.earthbound"})
    assert both["source"] == "gem", "젬으로 켤 수 있으면 젬이다"
    assert both["granted_by"] == ["Earthbound"], "부여원은 지우지 않는다"
    only_item = skill_source(["Ashen Staff"], {"ashen staff": "item.ashen-staff"})
    assert only_item["source"] == "item-granted"


def test_부여원을_장착했으면_통과한다() -> None:
    """게이트의 근거는 「젬 획득 경로가 **없다**」이다 — 있으면 막을 이유가 없다.

    인게임에서 유저는 아이템이 준 스킬에 주얼러 오브로 보조를 붙인다. PoB는 그 구성을
    `source` **없는** 그룹으로 들고 있고, 옛 게이트는 그것을 「젬으로 켰다」로 오인해
    막았다. 실측 2026-08-13(블러드 메이지 래더 코드): 그 그룹이 빠지자 같은 빌드가
    **DPS 1,935,569 → 12,334**(157배)가 됐다.
    """
    granted = spec_from_dict(
        {
            **BASE,
            # Firebolt의 부여원은 지팡이 계열이다 — 그중 하나를 실제로 끼운다
            "items": [{"slot": "Weapon 1", "text": "Rarity: NORMAL\nAshen Staff"}],
            "skills": [
                {
                    "gems": [
                        {
                            "gem_id": "Metadata/Items/Gems/SkillGemFirebolt",
                            "name": "Firebolt",
                            "level": 20,
                            "stat_set_index": 1,
                        }
                    ]
                }
            ],
        }
    )
    assert granted is not None, "부여원을 장착했는데도 막혔다"


def test_부여원이_없으면_여전히_막는다() -> None:
    """#47의 보호는 그대로다 — 완화가 아니라 **조건을 정확히** 한 것이다.

    이게 깨지면 Firebolt 사고(젬 획득 경로 없이 조용히 계산)가 그대로 재발한다.
    """
    with pytest.raises(ValueError, match="아이템 부여 스킬"):
        spec_from_dict(
            {
                **BASE,
                "items": [{"slot": "Weapon 1", "text": "Rarity: RARE\nPok Wand\nDueling Wand"}],
                "skills": [
                    {
                        "gems": [
                            {
                                "gem_id": "Metadata/Items/Gems/SkillGemFirebolt",
                                "name": "Firebolt",
                                "level": 20,
                                "stat_set_index": 1,
                            }
                        ]
                    }
                ],
            }
        )
