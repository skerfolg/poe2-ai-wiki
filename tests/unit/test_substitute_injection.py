"""대리 측정 주입 — PoB가 못 세는 효과를 재되, **추산임이 기록에 남는지** (백로그 #3).

PoB가 계산하지 못하는 문구(트리 500건·룬 슬롯 미매칭)의 값어치를 재려면 등가 문구를
아이템 텍스트에 주입하는 수밖에 없다. 문제는 그렇게 나온 수치가 **실측과 구분되지
않는다**는 것이다 — 산출물을 나중에 읽는 쪽은 어느 값이 주입분인지 알 방법이 없다.

그래서 주입은 `text`에 섞는 게 아니라 `ItemSpec.substitutes`로 **선언**하고, 조립이
manifest에 자동으로 적는다. 규율을 문서에만 두면 안 지켜진다(철칙 5).
"""

from __future__ import annotations

from pok.pob.buildxml import BuildSpec, ItemSpec, to_xml

_BASE = "Rarity: RARE\nTest Amulet\nAmber Amulet\nItem Level: 80\n+10 to Strength"


def test_주입_줄이_PoB로_간다() -> None:
    """선언만 하고 안 보내면 측정 자체가 안 된다 — 접사로 파싱되게 이어붙인다."""
    xml = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            items=(
                ItemSpec(
                    slot="Amulet",
                    text=_BASE,
                    substitutes=("25% more Elemental Damage with Spells",),
                ),
            ),
        )
    )
    assert "25% more Elemental Damage with Spells" in xml
    assert "+10 to Strength" in xml, "원래 모드를 밀어내면 안 된다"


def test_주입이_없으면_텍스트가_그대로다() -> None:
    """평상시 경로에 영향이 없어야 한다 — 빈 줄 하나도 붙이지 않는다."""
    plain = ItemSpec(slot="Amulet", text=_BASE)
    tagged = ItemSpec(slot="Amulet", text=_BASE, substitutes=())
    spec = BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(plain,))
    other = BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(tagged,))
    assert to_xml(spec) == to_xml(other)


def test_주입은_선언된_자리에만_남는다() -> None:
    """`text`에 섞으면 진짜 모드와 구분되지 않는다 — 그래서 칸을 따로 둔다.

    이 테스트가 지키는 것은 **스펙 수준의 구분**이다: PoB로 가는 텍스트는 합쳐지지만
    스펙은 둘을 따로 들고 있어야 조립이 manifest에 "주입분"을 적을 수 있다.
    """
    item = ItemSpec(slot="Amulet", text=_BASE, substitutes=("10% increased Attack Speed",))
    assert "Attack Speed" not in item.text
    assert item.substitutes == ("10% increased Attack Speed",)
