"""PoB가 **베이스명을 못 맞춰 버린 아이템**을 신고하는가 (#135).

베이스명이 `Data/Bases/*.lua`에 없으면 PoB는 그 아이템을 **오류 없이 버린다** —
암시도 접사도 하나도 안 붙고 계산은 끝까지 돈다. 조립이 통과하고 수치만 틀리므로
사고는 원인이 아닌 곳에서 찾게 된다(형태 ⑩ 조용한 거짓 성립).

실측 2026-08-28(희귀 갑옷 하나, Monk 90):

    Conjurer Mantle              → Spirit 130 · 저항 -10/-10/-10
    Runemastered Conjurer Mantle → Spirit 100 · 저항 -50/-50/-50   ← **안 낀 것과 동일**

⚠ 접수 진단은 「베이스 목록엔 있는데 텍스트 파서가 못 맞춘다」였는데 **틀렸다**:
`Runemastered Conjurer Mantle`은 PoB에도 우리 정본에도 없다(있는 것은
`Runeforged Conjurer Mantle`). 즉 #54와 같은 축 — **없는 베이스**다. 그래서 이
시험이 잠그는 것은 이름 대조가 아니라 **신고 경로**다: 무엇이 버려졌는지 말하는가.
"""

from __future__ import annotations

from pok.pob.runner import find_dropped_items

_XML = (
    '<Items activeItemSet="1">\n'
    '    <Item id="1">Rarity: RARE\nGood\nConjurer Mantle\nItem Level: 80\n+30 to Spirit</Item>\n'
    '    <Item id="2">Rarity: RARE\nBad\nRunemastered Conjurer Mantle\nItem Level: 80</Item>\n'
    '    <ItemSet id="1" title="pok">\n'
    '      <Slot name="Body Armour" itemId="1" active="true"/>\n'
    '      <Slot name="Boots" itemId="2" active="true"/>\n'
    "    </ItemSet>\n  </Items>"
)


def test_버려진_아이템을_슬롯과_베이스명까지_낸다() -> None:
    """「무엇이 빠졌나」로 끝나면 못 고친다 — 어느 슬롯의 어떤 베이스인지까지 낸다."""
    dropped = find_dropped_items(_XML, {"items": [{"id": "1"}]})
    assert dropped == (
        {
            "id": "2",
            "slot": "Boots",
            "name": "Bad",
            "base": "Runemastered Conjurer Mantle",
        },
    )


def test_전부_읽혔으면_조용하다() -> None:
    """정상에 신고를 붙이면 신호가 죽는다(형태 ⑤ — 게이트가 정상을 막으면 안 본다)."""
    assert find_dropped_items(_XML, {"items": [{"id": "1"}, {"id": "2"}]}) == ()


def test_주얼도_PoB_목록에_있으면_오탐이_아니다() -> None:
    """주얼은 슬롯이 아니라 트리 소켓에 박히지만 `POK_META.items`에는 실린다
    (실측: `slot="Jewel 61419"`). 슬롯으로 대조했으면 전부 오탐이었을 자리다."""
    xml = (
        '<Items><Item id="1">Rarity: RARE\nA\nConjurer Mantle</Item>'
        '<Item id="2">Rarity: RARE\nJ\nSapphire</Item></Items>'
    )
    assert (
        find_dropped_items(xml, {"items": [{"id": "1"}, {"id": "2", "slot": "Jewel 61419"}]}) == ()
    )


def test_옛_프로토콜_결과에는_침묵한다() -> None:
    """`items`가 없던 판의 캐시 payload를 「전부 버려졌다」로 읽으면 거짓 경보다.

    모르는 것을 신고하지 않는다 — #109가 「없는 키를 0으로」 읽어 부호까지 뒤집힌
    전례가 있다.
    """
    assert find_dropped_items(_XML, {}) == ()
    assert find_dropped_items(_XML, {"items": "깨진 값"}) == ()


def test_속성_순서가_달라도_찾는다() -> None:
    """PoB의 XML 기록기는 `pairs(attrib)`로 돌아 **속성 순서가 고정이 아니다**.

    `id`가 첫 속성이라고 보면 남의 코드(래더 PoB)에서만 조용히 못 찾고, 그러면 멀쩡한
    아이템이 전부 「버려졌다」로 신고된다 — 거짓 경보는 게이트 우회를 학습시킨다(형태 ⑪).
    """
    xml = (
        '<Items><Item variantAlt="1" id="1">Rarity: RARE\nGood\nConjurer Mantle</Item>'
        '<Item id="2" variantAlt="2">Rarity: RARE\nBad\nBogus Base</Item>'
        '<ItemSet id="1"><Slot active="true" itemId="2" name="Boots"/></ItemSet></Items>'
    )
    assert find_dropped_items(xml, {"items": [{"id": "1"}]}) == (
        {"id": "2", "slot": "Boots", "name": "Bad", "base": "Bogus Base"},
    )
