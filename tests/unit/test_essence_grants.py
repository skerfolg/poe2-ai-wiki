"""에센스 부여 매핑 — 개별 페이지 파서·정규화·클래스 조인 (픽스처, 네트워크 없음).

ingest 갭 해소(2026-08-06): 완벽 에센스(합금) 전용 모드가 spawn_weights 전부 0에
부위 매핑도 없어 "어느 부위에 부여 가능한가"를 판정할 수 없었다. 정본 매핑은
poe2db 개별 에센스 페이지의 Class|Modifier 테이블에서 온다.
"""

from __future__ import annotations

from pok.kb.ingest.essences import _grant_norm, parse_detail_page
from pok.kb.item_classes import PAGE_OF_CLASS, page_matches_class, page_of_class

# 개별 에센스 페이지의 매핑 테이블 원형 축약 (Runic Alloy 실측 구조)
DETAIL_HTML = """
<html><body>
<div class="card"><table>
 <tr><th>24h Value</th><th>24h volume traded</th></tr>
 <tr><td>12 Exalted Orb</td><td>861</td></tr>
</table></div>
<div class="card"><table>
 <tr><th>Class</th><th>Modifier</th><th>Pre/Suf</th><th>Required Level</th></tr>
 <tr><td><a class="ItemClasses" href="Rings">Rings</a></td>
     <td><span class="mod-value">+(37<span class="ndash">—</span>49)</span> to maximum
         <a class="KeywordPopups" href="Runic_Ward">Runic Ward</a></td>
     <td>Prefix</td><td>10</td></tr>
 <tr><td><a class="ItemClasses" href="Sceptres">Sceptres</a></td>
     <td>+ (4<span class="ndash">—</span>5) maximum stacks of Puppet Master</td>
     <td>Suffix</td><td>52</td></tr>
</table></div>
</body></html>
"""


def test_parse_detail_page_extracts_class_mod_mapping() -> None:
    rows = parse_detail_page(DETAIL_HTML)
    assert len(rows) == 2, "가격 테이블은 걸러지고 매핑 테이블만 읽어야 한다"
    ring = rows[0]
    assert ring["page"] == "Rings"
    assert ring["text"] == "+(37-49) to maximum Runic Ward"
    assert ring["affix_type"] == "prefix"
    assert ring["req_level"] == 10
    assert rows[1]["page"] == "Sceptres"
    assert rows[1]["affix_type"] == "suffix"


def test_grant_norm_absorbs_page_spacing_variants() -> None:
    """의미가 같은 표기 차이만 지운다 — 실측 두 변형의 회귀."""
    # `+ (4-5)` 공백 (The Runebinder's Alloy 셉터 행)
    assert _grant_norm("+ (4—5) maximum stacks") == _grant_norm("+(4-5) maximum stacks")
    # 키워드 배지 제거 흔적의 쉼표 앞 공백 (Perfect Essence of Enhancement)
    assert _grant_norm("Global Armour , Evasion and Energy Shield") == _grant_norm(
        "Global Armour, Evasion and Energy Shield"
    )


def test_page_of_class_handles_irregular_plurals() -> None:
    """불규칙 복수·개명 — 자동 유도("Staff"+"s")가 틀렸던 회귀."""
    assert page_of_class("Staff") == "Staves"
    assert page_of_class("Focus") == "Foci"
    assert page_of_class("Quarterstaff") == "Quarterstaves"
    assert page_of_class("Warstaff") == "Quarterstaves"  # PoB 표기
    assert page_of_class("Two Hand Sword") == "Two_Hand_Swords"
    assert page_of_class("Claw") == "Claws"  # 미등재 클래스는 규칙 복수형


def test_page_matches_class_accepts_attribute_suffix_variants() -> None:
    assert page_matches_class("Body_Armours", "Body Armour")
    assert page_matches_class("Body_Armours_str_dex", "Body Armour")
    assert not page_matches_class("Boots", "Body Armour")
    assert not page_matches_class("Ringss", "Ring"), "접미 변형은 `_` 경계로만 허용"


def test_class_map_covers_kb_base_item_classes() -> None:
    """KB 베이스의 item_class가 맵 밖으로 새면 조인이 조용히 구멍난다."""
    from pok.kb.store import load

    store = load()
    classes = {
        str((r.raw.get("data") or {}).get("item_class") or "")
        for r in store.records.values()
        if r.type == "Item" and (r.raw.get("data") or {}).get("rarity") == "normal"
    }
    equipment = classes & set(PAGE_OF_CLASS)  # 장비 클래스는 명시 수록돼 있어야 한다
    for cls in ("Staff", "Focus", "Quarterstaff", "Body Armour", "Two Hand Mace"):
        assert cls in equipment, f"{cls}가 KB 또는 PAGE_OF_CLASS에서 빠졌다"
