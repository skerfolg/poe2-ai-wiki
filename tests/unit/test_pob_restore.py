"""PoB 코드 → 스펙 복원 (#67 6차, 사용자 지시 2026-08-12).

래더 코퍼스에 PoB 코드가 300벌 쌓였는데 우리 엔진에 **한 벌도 못 넣었다**.
「실제 빌드 재최적화」·「우리 산출물 대 래더 A/B」가 전부 여기서 막혔다.
"""

from __future__ import annotations

import base64
import zlib

from pok.pob.restore import spec_from_pob_xml

_XML = """<?xml version="1.0"?>
<PathOfBuilding2>
 <Build level="90" className="Monk" ascendClassName="Martial Artist" mainSocketGroup="1"/>
 <Tree>
  <Spec nodes="11495,44683,21984,13828,10131,999999" ascendancyInternalId="Monk1" masteryEffects="">
   <Sockets><Socket nodeId="21984" itemId="2"/><Socket nodeId="999" itemId="2"/></Sockets>
   <Overrides><AttributeOverride strNodes="13828" dexNodes="10131" intNodes=""/></Overrides>
   <WeaponSet1/><WeaponSet2/>
  </Spec>
 </Tree>
 <Skills><SkillSet>
  <Skill enabled="true" mainActiveSkill="nil">
   <Gem gemId="Metadata/Items/Gem/SkillGemWindDancer" nameSpec="Wind Dancer"
        level="nil" quality="0" enabled="true"/>
  </Skill>
  <Skill enabled="true" source="Item" mainActiveSkill="1">
   <Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20" quality="0"/>
  </Skill>
 </SkillSet></Skills>
 <Items>
  <Item id="1">Rarity: RARE\nFoo\nGold Amulet<ModRange range="0.5" id="1"/>\n+10 to Spirit</Item>
  <Item id="2">Rarity: UNIQUE\nBar\nSapphire</Item>
  <ItemSet id="1">
   <Slot name="Amulet" itemId="1"/>
   <Slot name="Weapon 1 Swap" itemId="2"/>
   <Slot name="Boots" itemId="0"/>
  </ItemSet>
 </Items>
 <Config activeConfigSet="1"><ConfigSet id="1">
  <Input name="conditionEnemyChilled" boolean="true"/>
  <Input name="enemyLevel" number="83"/>
 </ConfigSet></Config>
</PathOfBuilding2>
"""


def _restored():
    return spec_from_pob_xml(_XML)


def test_전직은_내부_코드로_돌린다() -> None:
    """실명("Martial Artist")은 카탈로그가 거부한다 — 코드는 Spec에 있다."""
    assert _restored().spec["ascendancy"] == "Monk1"


def test_클래스_전직_시작_노드를_뺀다() -> None:
    """PoB가 자동 할당하는 노드다. 스펙에 실으면 `pruned_nodes`가 서고, 델타
    측정기는 pruned가 있는 결과를 **통째로 버린다** — 복원한 빌드로 아무것도 못 잰다
    (실측 2026-08-12: 전 빌드에서 2개씩 잘렸다)."""
    nodes = _restored().spec["tree_nodes"]
    assert 11495 not in nodes and 44683 not in nodes
    assert {21984, 13828, 10131} <= set(nodes)
    assert 999999 not in nodes, "KB가 모르는 노드도 빠져야 한다(수집 갭 신호)"


def test_아이템_텍스트가_ModRange에서_잘리지_않는다() -> None:
    """`.text`만 읽으면 자식 태그 뒤 줄이 사라져 **옵션 없는 아이템**이 된다 —
    PoB는 아무 효과도 안 붙인 채 계산한다."""
    amulet = next(i for i in _restored().spec["items"] if i["slot"] == "Amulet")
    assert "+10 to Spirit" in amulet["text"]


def test_주얼은_할당된_소켓만_싣는다() -> None:
    """PoB는 할당 안 한 소켓의 매핑도 남긴다 — 그대로 실으면 조립이 거부된다."""
    jewels = _restored().spec["jewels"]
    assert [j["socket_node_id"] for j in jewels] == [21984]


def test_능력치_택1_선택을_복원한다() -> None:
    """실측: 택1 35개를 빼자 Str 184→79 · Dex 165→104. 빌드 능력치 절반이 여기서 나온다."""
    assert sorted(map(tuple, _restored().spec["attribute_choices"])) == [
        (10131, "dex"),
        (13828, "str"),
    ]


def test_config를_복원한다() -> None:
    """빼면 버프·적 상태가 꺼진 채 계산된다 — 실측: EHP가 최대 44% 낮게 나왔다."""
    cfg = dict(map(tuple, _restored().spec["config"]))
    assert cfg["conditionEnemyChilled"] is True and cfg["enemyLevel"] == 83


def test_nil을_기본값으로_읽는다() -> None:
    """PoB는 빈 값을 문자열 `"nil"`로 적는다 — float()에 넣으면 터진다
    (실측: 300벌 중 291벌이 이 한 줄로 실패했다)."""
    assert _restored().spec["skills"][0]["gems"][0]["level"] == 20
    assert _restored().spec["main_socket_group"] == 1


def test_아이템이_준_스킬_그룹은_싣지_않는다() -> None:
    """PoB가 `source`로 표시한다. 젬으로 다시 실으면 이중 계산이다."""
    r = _restored()
    assert len(r.spec["skills"]) == 1
    assert any("아이템이 준 스킬" in n for n in r.notes)


def test_못_되돌린_것을_말한다() -> None:
    """조용히 빼면 「복원했다」고 믿은 채 다른 빌드를 재게 된다."""
    r = _restored()
    assert any("교체 무기" in n for n in r.notes), "버린 슬롯을 안 밝혔다"
    assert any("stat_set_index" in n for n in r.needs_decision), "가정을 안 밝혔다"
    assert r.faithful is False


def test_공유_코드로도_받는다() -> None:
    from pok.pob.restore import spec_from_pob

    code = base64.urlsafe_b64encode(zlib.compress(_XML.encode())).decode()
    assert spec_from_pob(code).spec["ascendancy"] == "Monk1"


def test_source_없는_그룹은_보존한다() -> None:
    """⚠ 이 시험은 **정반대를 잠그고 있었다** — 「그룹을 빼고 잃은 보조를 센다」였다.

    전제가 틀렸다. `source` 없는 그룹은 PoB가 만든 것이 아니라 **플레이어가 구성한
    것**이고, 아이템(또는 트리)이 준 스킬에 주얼러 오브로 보조를 붙인 바로 그 구성이다.
    실측 2026-08-13(블러드 메이지 래더 코드): 그룹을 빼자 같은 빌드가 **DPS
    1,935,569 → 12,334**(157배)가 됐다. 주력 스킬 그룹이었다.

    이중 계산도 아니다 — 원본 XML은 `source` 있는 그룹과 없는 그룹을 **둘 다** 들고
    저 수치를 낸다. `source` 있는 것만 빼면 PoB가 그것을 되만들어 원본 구조가 된다.

    지키려는 것은 그대로다: **보조 젬이 조용히 사라지면 안 된다.**
    """
    xml = _XML.replace(
        '<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20" quality="0"/>',
        '<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Purity of Fire" level="20"'
        ' quality="0"/><Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark"'
        ' level="20" quality="0"/>',
    ).replace('source="Item" ', "")
    r = spec_from_pob_xml(xml)

    assert r.dropped_item_granted == (), "source 없는 그룹을 빼면 안 된다"
    assert r.damage_comparable is True
    names = [g.get("name") for grp in r.spec["skills"] for g in grp["gems"]]
    assert "Purity of Fire" in names, "아이템 부여 스킬이 실려야 보조가 따라온다"
    assert "Spark" in names, "함께 있던 보조가 사라졌다 — 157배 사고의 형태다"


def test_부패_젬_정보를_싣는다() -> None:
    """부패는 젬 **레벨을 올려** 딜에 직접 든다 — 버리면 조용히 빠진다.

    실측 2026-08-13(블러드 메이지 래더 코드): `corrupted`/`corruptLevel`을 버리자
    같은 빌드가 **DPS 1,362,791 → 1,014,216**(74.4%)이 됐다. 경고도 없이 4분의 1이
    사라지는 종류라 복원기가 반드시 들고 있어야 한다.
    """
    xml = _XML.replace(
        '<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20" quality="0"/>',
        '<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20"'
        ' quality="0" corrupted="true" corruptLevel="1"/>',
    ).replace('source="Item" ', "")
    gem = next(
        g
        for grp in spec_from_pob_xml(xml).spec["skills"]
        for g in grp["gems"]
        if g["name"] == "Spark"
    )
    assert gem["corrupted"] is True
    assert gem["corrupt_level"] == 1


def test_부패_정보가_XML로_되나간다() -> None:
    """복원해 놓고 직렬화에서 떨구면 같은 손실이다 — 왕복으로 잠근다."""
    from pok.pob.buildxml import spec_from_dict, to_xml

    xml = to_xml(
        spec_from_dict(
            {
                "class_name": "Sorceress",
                "ascendancy": "Sorceress1",
                "level": 90,
                "skills": [
                    {
                        "gems": [
                            {
                                "gem_id": "Metadata/Items/Gems/SkillGemSpark",
                                "name": "Spark",
                                "stat_set_index": 1,
                                "corrupted": True,
                                "corrupt_level": 2,
                            }
                        ]
                    }
                ],
            }
        )
    )
    assert 'corrupted="true"' in xml and 'corruptLevel="2"' in xml


def test_customMods의_줄바꿈이_살아남는다() -> None:
    """여러 줄 config가 한 줄로 붙으면 PoB가 **전부 파싱 실패**한다 (#134).

    PoB는 여러 줄을 리터럴 개행이 든 속성값으로 적는데(자기 파서가 `&#10;`를 모른다),
    표준 XML 리더는 속성 안 개행을 공백으로 정규화한다. `modLib.parseMod`는 줄 단위로
    돌기 때문에 한 줄이 되면 전부 못 읽고, 결과는 **델타 0**이라 「효과 없음」과
    구별되지 않는다(실측 2026-08-28: 원시 XML은 DPS +14.8%·EHP +65.5%, 왕복 뒤 ±0).
    """
    body = "15% more Attack Damage\n40% less Damage taken"
    xml = _XML.replace(
        '<Input name="enemyLevel" number="83"/>',
        f'<Input name="enemyLevel" number="83"/><Input name="customMods" string="{body}"/>',
    )
    config = dict((k, v) for k, v in spec_from_pob_xml(xml).spec["config"])
    assert config["customMods"] == body


def test_속성_보존이_아이템_raw_텍스트를_안_건드린다() -> None:
    """치환은 **태그 안에서만** 한다 — 아이템 텍스트는 원소 text라 정규화 대상이 아니다."""
    item = next(i for i in spec_from_pob_xml(_XML).spec["items"] if i["slot"] == "Amulet")
    assert item["text"].splitlines()[0] == "Rarity: RARE"
    assert "+10 to Spirit" in item["text"]


def test_모드_색인을_코드에서_되돌린다() -> None:
    """`<StatSetIndex>`가 있으면 **그 값**을 쓴다 — 있는 값을 버리고 1번을 가정했었다.

    `SkillsTab.lua:508`이 grantedEffect별 자식 원소로 저장한다. 버리면 복원본이 원본과
    다른 모드로 계산된다(실측 2026-08-10: 파트 1/2/3이 2,387 / 32,231 / 47,329).
    """
    xml = _XML.replace(
        '<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20" quality="0"/>',
        '<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20" quality="0">'
        '<StatSetIndex grantedEffect="SparkPlayer" index="3"/>'
        '<StatSetCalcsIndex grantedEffect="SparkPlayer" index="3"/></Gem>',
    ).replace('source="Item" ', "")
    gem = next(
        g
        for grp in spec_from_pob_xml(xml).spec["skills"]
        for g in grp["gems"]
        if g["name"] == "Spark"
    )
    assert gem["stat_set_index"] == 3


def test_색인이_없을_때만_1번을_가정한다() -> None:
    """가정은 남기되, **코드에 있는 것을 가정으로 덮지 않는다**."""
    r = spec_from_pob_xml(_XML)  # 픽스처엔 StatSetIndex가 없다
    assert r.spec["skills"][0]["gems"][0]["stat_set_index"] == 1
    assert any("stat_set_index" in n for n in r.needs_decision)


# ── #144 — 그룹을 빼면서 main_socket_group을 재매핑하지 않던 자리 ────────────────

_SPEAR_GRANTED = (
    '<Skill enabled="true" source="Item" mainActiveSkill="1">'
    '<Gem gemId="Metadata/Items/Gems/SkillGemSpearThrow" nameSpec="Spear Throw" level="20"'
    ' quality="0"/></Skill>'
)
_SPEAR_PLAYER = _SPEAR_GRANTED.replace(' source="Item"', "")
_DANCER = (
    '<Skill enabled="true" mainActiveSkill="1">'
    '<Gem gemId="Metadata/Items/Gem/SkillGemWindDancer" nameSpec="Wind Dancer" level="20"'
    ' quality="0"/></Skill>'
)
_SPARK = (
    '<Skill enabled="true" mainActiveSkill="1">'
    '<Gem gemId="Metadata/Items/Gems/SkillGemSpark" nameSpec="Spark" level="20" quality="0"/>'
    "</Skill>"
)


def _with_skills(main: int, *skills: str) -> str:
    import re

    xml = re.sub(
        r"<Skills>.*?</Skills>",
        "<Skills><SkillSet>" + "".join(skills) + "</SkillSet></Skills>",
        _XML,
        flags=re.S,
    )
    return xml.replace('mainSocketGroup="1"', f'mainSocketGroup="{main}"')


def test_그룹을_빼면_main_socket_group을_재매핑한다() -> None:
    """#144 — PoB `mainSocketGroup`은 **<Skill> 전체**(아이템 부여 포함)의 1-based 색인이다.

    부여 그룹을 빼면서 목록이 당겨지는데 값은 그대로 복사했다 — 빠진 그룹이 주력 **앞**에
    있으면 조용히 다른 스킬을 잰다(실측 2026-09-04: 한 칸 어긋나자 `Ghost Dance`를 가리켜
    CombinedDPS 0). 이번 표본은 빠진 그룹이 전부 주력 뒤라 우연히 맞았을 뿐이다.
    """
    r = spec_from_pob_xml(_with_skills(3, _SPEAR_GRANTED, _DANCER, _SPARK))
    assert [g["gems"][0]["name"] for g in r.spec["skills"]] == ["Wind Dancer", "Spark"]
    assert r.spec["main_socket_group"] == 2, "빠진 그룹만큼 당겨져야 Spark를 가리킨다"
    assert not any("main_socket_group" in n for n in r.needs_decision)


def test_빠진_그룹이_주력_뒤면_그대로다() -> None:
    r = spec_from_pob_xml(_with_skills(1, _DANCER, _SPEAR_GRANTED, _SPARK))
    assert r.spec["main_socket_group"] == 1
    assert not any("main_socket_group" in n for n in r.needs_decision)


def test_주력_그룹_자체가_빠지면_이웃을_조용히_재지_않는다() -> None:
    """주력이 아이템 부여(`source`) 그룹이면 우리 목록엔 그 그룹이 없다.

    같은 스킬을 플레이어가 젬으로 다시 실은 그룹이 있으면 그리로 옮기고 **말한다**;
    없으면 `needs_decision`으로 묻는다 — 어느 쪽도 이웃 그룹을 침묵 속에 재지 않는다.
    """
    unresolved = spec_from_pob_xml(_with_skills(1, _SPEAR_GRANTED, _DANCER, _SPARK))
    assert any("main_socket_group" in n for n in unresolved.needs_decision), (
        unresolved.needs_decision
    )
    remade = spec_from_pob_xml(_with_skills(1, _SPEAR_GRANTED, _DANCER, _SPEAR_PLAYER))
    assert remade.spec["main_socket_group"] == 2, "같은 스킬을 다시 실은 그룹으로 옮긴다"
    assert any("main_socket_group" in n for n in remade.notes), remade.notes
    assert not any("main_socket_group" in n for n in remade.needs_decision)


# ── #143 — 웨폰셋 교체 빌드를 무기 없이 복원하고도 비교 가능이라 하던 자리 ─────────

_SPEAR_TEXT = (
    "Rarity: RARE\nViper Edge\nAkoyan Spear\nItem Level: 80\nAdds 10 to 20 Physical Damage"
)


def _with_weapon_sets(use_second: bool, *, main: str = "0", swap: str = "3") -> str:
    xml = _XML.replace('<Item id="2">', f'<Item id="3">{_SPEAR_TEXT}</Item><Item id="2">')
    xml = xml.replace(
        '<ItemSet id="1">', f'<ItemSet id="1" useSecondWeaponSet="{str(use_second).lower()}">'
    )
    return xml.replace(
        '<Slot name="Weapon 1 Swap" itemId="2"/>',
        f'<Slot name="Weapon 1" itemId="{main}"/><Slot name="Weapon 1 Swap" itemId="{swap}"/>',
    )


def test_교체_세트가_활성이면_그_무기를_주무기_슬롯으로_접어_싣는다() -> None:
    """#143 — `useSecondWeaponSet="true"`면 주무기는 **Swap 슬롯**에 있다(래더 창 젬링 실측).

    빈 채로 복원하면 창 공격 빌드가 창 없이 계산되는데 `damage_comparable`은 True였다.
    PoB가 활성 세트로 계산하는 것을 그대로 옮긴다 — 단 **근사**임을 말한다(세트 전용 트리
    할당·「양 세트에서 활성」 젬은 재현 못 한다).
    """
    r = spec_from_pob_xml(_with_weapon_sets(True))
    weapon = next(i for i in r.spec["items"] if i["slot"] == "Weapon 1")
    assert "Akoyan Spear" in weapon["text"]
    assert not any(i["slot"].endswith("Swap") for i in r.spec["items"])
    assert any("근사" in n for n in r.notes), r.notes
    assert r.damage_comparable is True


def test_교체_세트가_활성이면_1세트_무기는_뺀다() -> None:
    """PoB도 비활성 세트는 계산에 안 쓴다 — 둘 다 실으면 없는 빌드가 된다."""
    r = spec_from_pob_xml(_with_weapon_sets(True, main="1"))  # 1세트 슬롯에 목걸이 텍스트
    weapons = [i for i in r.spec["items"] if i["slot"] == "Weapon 1"]
    assert len(weapons) == 1 and "Akoyan Spear" in weapons[0]["text"]
    assert any("비활성" in n for n in r.notes), r.notes


def test_교체_세트가_비활성이면_종전과_같다() -> None:
    r = spec_from_pob_xml(_with_weapon_sets(False))
    assert not any(i["slot"] == "Weapon 1" for i in r.spec["items"])
    assert any("교체 무기" in n for n in r.notes)
    assert r.damage_comparable is True, "비활성 세트의 무기는 PoB도 계산에 안 쓴다"


def test_교체_세트가_활성이면_그_슬롯의_스킬_그룹도_따라온다() -> None:
    """무기만 옮기고 그룹의 slot을 `Weapon 1 Swap`으로 두면 PoB가 빈 슬롯의 그룹으로 보고 끈다.
    반대로 1세트 무기에 꽂힌 그룹은 PoB처럼 끈다(`CalcSetup.lua:1729`, 주력 그룹은 예외)."""
    xml = _with_weapon_sets(True).replace(
        '<Skill enabled="true" mainActiveSkill="nil">',
        '<Skill enabled="true" slot="Weapon 1 Swap" mainActiveSkill="nil">',
    )
    r = spec_from_pob_xml(xml)
    assert r.spec["skills"][0]["slot"] == "Weapon 1" and r.spec["skills"][0]["enabled"] is True


def test_활성_세트의_무기가_코드에_없으면_비교_불가다() -> None:
    """무기 슬롯이 가리키는 아이템이 코드에 없으면 조용히 빠지던 자리 — 딜 축 비교 불가로 내린다."""
    r = spec_from_pob_xml(_with_weapon_sets(True, swap="99"))
    assert r.damage_comparable is False
    assert any("Weapon 1" in n for n in r.notes), r.notes
