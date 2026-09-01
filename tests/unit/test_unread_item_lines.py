"""PoB가 **문구를 못 읽는 장비**를 측정 반환에 싣는가 (#133).

표시(`pob_modeling`)는 KB 레코드에 **이미 붙어 있었다.** 그런데 판단은 측정값을 보고
내리므로, 조회 시점에만 있는 신호는 그 자리에 없는 것과 같다 — 실측 사고 2026-08-28:
`The Vertex` 변형 2(「Equipment has no Attribute Requirements」)를 PoB가 못 읽어
`req_shortfall`이 떴고, 세션이 **사용자에게 「힘 380 부족」 경보를 냈다가 철회**했다.

실측으로 확인(스냅샷 5d173cb · Glorious Plate 착용 · Monk 90):

    투구 없음                        ReqStr 121
    변형 1 (50% reduced)             ReqStr  60   ← 읽힌다
    변형 2 (Equipment has no …)      ReqStr 121   ← **안 낀 것과 동일**
    변형 3 (Skill Gems have no …)    ReqStr 121   (젬 요구만 건드린다 — 정상)

⚠ 절반은 **울리지 않는 것**을 지킨다. 유니크 raw에는 안 고른 변형의 줄까지 들어 있어,
변형을 안 보면 정상 구성(변형 1·3)에 경보가 붙는다 — 거짓 경보는 게이트 우회를
학습시킨다(BACKLOG 형태 ⑪).
"""

from __future__ import annotations

from pok.engine.items import unread_item_lines

_VERTEX = """Rarity: UNIQUE
The Vertex
Tribal Mask
Variant: Pre 0.4.0
Variant: Equipment
Variant: Skill Gems
Selected Variant: {v}
Item Level: 80
{{variant:2}}Equipment has no Attribute Requirements
{{variant:3}}Skill Gems have no Attribute Requirements
{{variant:1}}Equipment and Skill Gems have 50% reduced Attribute Requirements
"""


def _spec(variant: int) -> dict[str, object]:
    return {"items": [{"slot": "Helmet", "text": _VERTEX.format(v=variant)}]}


def test_못_읽는_변형을_고르면_슬롯과_문구를_낸다() -> None:
    assert unread_item_lines(_spec(2)) == [
        {
            "slot": "Helmet",
            "item": "The Vertex",
            "unread": ["Equipment has no Attribute Requirements"],
        }
    ]


def test_읽히는_변형에는_울리지_않는다() -> None:
    """같은 아이템의 **다른 변형**은 정상이다. 레코드 단위로 울리면 전부 거짓 경보다."""
    assert unread_item_lines(_spec(1)) == []
    assert unread_item_lines(_spec(3)) == []


def test_장비가_없으면_조용하다() -> None:
    assert unread_item_lines({}) == []
    assert (
        unread_item_lines({"items": [{"slot": "Helmet", "text": "Rarity: RARE\nA\nTribal Mask"}]})
        == []
    )
