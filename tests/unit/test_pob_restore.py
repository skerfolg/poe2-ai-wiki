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
