"""아이템 클래스 ↔ poe2db 페이지 슬러그 — 조인 축의 단일 정본.

에센스 부여 매핑(ingest)과 접사 풀 열거·합법성 판정(engine)이 같은 조인을 쓴다.
불규칙 복수(Staff→Staves, Focus→Foci)와 개명(Warstaff/Quarterstaff→Quarterstaves)이
있어 기계 유도만으로는 틀린다 — 실측 2026-08-06: 복수형 자동 유도("Staff"+"s")가
Staves 페이지와 어긋나 지팡이 대상 매핑이 통째로 빠질 뻔했다.
"""

from __future__ import annotations

# PoB/KB 아이템 클래스 → poe2db 페이지 슬러그. KB 베이스 레코드의 `item_class`와
# PoB Essence.lua의 클래스 키 표기가 섞여 있어 양쪽 표기를 모두 수록한다.
PAGE_OF_CLASS: dict[str, str] = {
    "Amulet": "Amulets",
    "Belt": "Belts",
    "Body Armour": "Body_Armours",
    "Boots": "Boots",
    "Bow": "Bows",
    "Buckler": "Bucklers",
    "Crossbow": "Crossbows",
    "Dagger": "Daggers",
    "Flail": "Flails",
    "Focus": "Foci",
    "Gloves": "Gloves",
    "Helmet": "Helmets",
    "One Hand Axe": "One_Hand_Axes",
    "One Hand Mace": "One_Hand_Maces",
    "One Hand Sword": "One_Hand_Swords",
    "Quarterstaff": "Quarterstaves",
    "Quiver": "Quivers",
    "Ring": "Rings",
    "Sceptre": "Sceptres",
    "Shield": "Shields",
    "Spear": "Spears",
    "Staff": "Staves",
    "Talisman": "Talismans",
    "Two Hand Axe": "Two_Hand_Axes",
    "Two Hand Mace": "Two_Hand_Maces",
    "Two Hand Sword": "Two_Hand_Swords",
    "Wand": "Wands",
    "Warstaff": "Quarterstaves",
}


def page_of_class(item_class: str) -> str:
    """클래스 → 페이지 슬러그. 미등재 클래스는 규칙 복수형으로 유도한다.

    수집(ingest)처럼 미등재를 **감지**해야 하는 쪽은 `PAGE_OF_CLASS`를 직접 조회해
    없음을 보고하라 — 이 함수는 열거·판정처럼 항상 답이 필요한 쪽의 편의다.
    """
    known = PAGE_OF_CLASS.get(item_class)
    if known:
        return known
    plural = item_class if item_class.endswith("s") else item_class + "s"
    return plural.replace(" ", "_")


def page_matches_class(page: str, item_class: str) -> bool:
    """poe2db 페이지 슬러그가 이 클래스의 페이지인가 (속성 접미 변형 포함).

    desecrated 계열 `applicable_pages`엔 `Body_Armours_str_dex` 같은 속성 접미
    변형이 있다 — 기본 슬러그 일치 또는 `기본슬러그_` 접두면 같은 클래스다.
    """
    base = page_of_class(item_class)
    return page == base or page.startswith(base + "_")
