"""BuildSpec → PathOfBuilding2 XML 직렬화 — 스파이크로 실증한 계약의 코드화.

계약 (Phase 0 실측, scripts/pob_smoke.lua 머리주석과 동일 근거):
- 루트는 `PathOfBuilding2`, `targetVersion`은 **빌드 포맷 버전 "0_1" 고정**
  (게임 버전 아님 — 다른 값이면 변환 팝업으로 조기 return, Tree/Skills 무증상 유실).
- 클래스는 신형식 `classInternalId`(아래 표) + `ascendancyInternalId`
  ("Sorceress1" 등 — KB Passive 레코드의 `ascendancy` 코드와 동일 체계).
- `characterLevelAutoMode="false"` 로 명시 레벨 고정.
- 트리 노드 id는 KB(poe2db)·PoB 공통 id 공간 (실측: 5642=Behemoth 일치).
  시작점과 연결되지 않은 노드는 PoB가 로드 시 소리 없이 해제 → runner가
  POK_ALLOC과 요청 집합을 비교해 적법성을 판정한다.

아이템: `<Item id="N">raw 텍스트</Item>` + `<ItemSet><Slot name=… itemId=…/>`
(Phase 2 스파이크 실측 — Altar Robe에 '+100 to maximum Life'가 Life에 반영됨).
텍스트의 적법성(모드 풀·ilvl)은 engine의 몫 — 여기는 직렬화만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any
from xml.sax.saxutils import escape, quoteattr

TARGET_VERSION = "0_1"  # 빌드 포맷 버전 (게임 버전 아님!)
TREE_VERSION = "0_5"

# PoB latestTree.classIntegerIdMap 실측 (0.5 트리) — 항등이지만 이름 매핑이 목적
CLASS_INTERNAL_ID = {
    "Witch": 1,
    "Ranger": 2,
    "Warrior": 6,
    "Sorceress": 7,
    "Huntress": 8,
    "Mercenary": 9,
    "Monk": 10,
    "Druid": 11,
}


@dataclass(frozen=True)
class GemSpec:
    """스킬 그룹 내 젬 하나. gem_id는 PoB gemId (예: Metadata/.../SkillGemSpark)."""

    gem_id: str
    name: str  # nameSpec (표시명)
    level: int = 20
    quality: int = 0
    enabled: bool = True


@dataclass(frozen=True)
class SkillGroupSpec:
    """소켓 그룹 — 액티브 젬 + 서포트 젬들. slot은 PoB 슬롯명."""

    gems: tuple[GemSpec, ...]
    slot: str = "Weapon 1"
    enabled: bool = True
    main_active_skill: int = 1


@dataclass(frozen=True)
class ItemSpec:
    """장착 아이템 하나 — PoB raw 텍스트 형식 (실측 2026-07-30).

    text 형식: `Rarity: RARE|UNIQUE|MAGIC|NORMAL` 줄, 이름 줄, 베이스 줄,
    이후 `Item Level: N`·모드 줄들. 베이스명은 PoB uniques/bases DB와 일치해야
    파싱된다(KB base-items의 name.en 그대로 사용 가능 — id 공간 일치 실측).
    slot은 PoB 슬롯명: Weapon 1|Weapon 2|Helmet|Body Armour|Gloves|Boots|
    Amulet|Ring 1|Ring 2|Belt|Charm 1…
    """

    slot: str
    text: str


@dataclass(frozen=True)
class BuildSpec:
    """PoB에 계산을 맡길 빌드 정의 — KB id 공간과 호환되는 최소 스펙."""

    class_name: str  # CLASS_INTERNAL_ID 키
    ascendancy: str  # KB 어센던시 코드 = PoB ascendancyInternalId ("Sorceress1"…)
    level: int = 90
    tree_nodes: tuple[int, ...] = ()  # KB node_id 그대로 (연결성은 호출자 책임)
    skills: tuple[SkillGroupSpec, ...] = ()
    items: tuple[ItemSpec, ...] = ()
    main_socket_group: int = 1
    config: tuple[tuple[str, str | int | bool], ...] = field(default=())  # Input name→value


def spec_from_dict(data: dict[str, Any]) -> BuildSpec:
    """JSON 친화 dict → BuildSpec (MCP 도구 입력 경로). 모르는 키는 즉시 거부."""
    allowed = {f.name for f in fields(BuildSpec)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"모르는 키: {sorted(unknown)} (허용: {sorted(allowed)})")
    skills = tuple(
        SkillGroupSpec(
            gems=tuple(GemSpec(**g) for g in grp.get("gems", [])),
            **{k: v for k, v in grp.items() if k != "gems"},
        )
        for grp in data.get("skills", [])
    )
    items = tuple(ItemSpec(**it) for it in data.get("items", []))
    config = tuple((str(k), v) for k, v in dict(data.get("config", {})).items())
    return BuildSpec(
        class_name=data["class_name"],
        ascendancy=data["ascendancy"],
        level=int(data.get("level", 90)),
        tree_nodes=tuple(int(n) for n in data.get("tree_nodes", [])),
        skills=skills,
        items=items,
        main_socket_group=int(data.get("main_socket_group", 1)),
        config=config,
    )


def _config_value_attrs(value: str | int | bool) -> str:
    if isinstance(value, bool):
        return f'boolean="{"true" if value else "false"}"'
    if isinstance(value, int):
        return f'number="{value}"'
    return f"string={quoteattr(value)}"


def to_xml(spec: BuildSpec) -> str:
    """BuildSpec → PoB가 그대로 로드하는 PathOfBuilding2 XML."""
    if spec.class_name not in CLASS_INTERNAL_ID:
        raise ValueError(
            f"알 수 없는 클래스: {spec.class_name!r} (허용: {sorted(CLASS_INTERNAL_ID)})"
        )
    if not 1 <= spec.level <= 100:
        raise ValueError(f"레벨 범위 밖: {spec.level}")

    skill_groups: list[str] = []
    for group in spec.skills:
        gems = "\n".join(
            f"        <Gem gemId={quoteattr(g.gem_id)} variantId={quoteattr(g.name)} "
            f'level="{g.level}" quality="{g.quality}" '
            f'enabled="{"true" if g.enabled else "false"}" nameSpec={quoteattr(g.name)}/>'
            for g in group.gems
        )
        skill_groups.append(
            f'      <Skill enabled="{"true" if group.enabled else "false"}" label="" '
            f'slot={quoteattr(group.slot)} mainActiveSkill="{group.main_active_skill}">\n'
            f"{gems}\n      </Skill>"
        )
    skills_xml = "\n".join(skill_groups)

    config_inputs = "\n".join(
        f"    <Input name={quoteattr(name)} {_config_value_attrs(value)}/>"
        for name, value in spec.config
    )

    # 아이템: <Item id=N>raw</Item> + ItemSet/Slot 연결 (텍스트는 escape만 — PoB가 파싱)
    seen_slots: set[str] = set()
    for item in spec.items:
        if item.slot in seen_slots:
            raise ValueError(f"슬롯 중복: {item.slot!r}")
        seen_slots.add(item.slot)
    item_els = "\n".join(
        f'    <Item id="{i}">{escape(item.text)}</Item>'
        for i, item in enumerate(spec.items, start=1)
    )
    slot_els = "\n".join(
        f'      <Slot name={quoteattr(item.slot)} itemId="{i}"/>'
        for i, item in enumerate(spec.items, start=1)
    )
    items_xml = (
        f'  <Items activeItemSet="1">\n{item_els}\n'
        f'    <ItemSet id="1" title="pok">\n{slot_els}\n    </ItemSet>\n  </Items>'
        if spec.items
        else "  <Items/>"
    )

    nodes = ",".join(str(n) for n in spec.tree_nodes)
    build_attrs = (
        f'level="{spec.level}" characterLevelAutoMode="false" '
        f'targetVersion="{TARGET_VERSION}" className={quoteattr(spec.class_name)} '
        f'mainSocketGroup="{spec.main_socket_group}"'
    )
    spec_attrs = (
        f'title="pok" treeVersion="{TREE_VERSION}" '
        f'classInternalId="{CLASS_INTERNAL_ID[spec.class_name]}" '
        f"ascendancyInternalId={quoteattr(spec.ascendancy)} nodes={quoteattr(nodes)}"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding2>
  <Build {build_attrs}/>
  <Skills sortGemsByDPS="true" activeSkillSet="1">
    <SkillSet id="1">
{skills_xml}
    </SkillSet>
  </Skills>
  <Tree activeSpec="1">
    <Spec {spec_attrs}/>
  </Tree>
{items_xml}
  <Config>
{config_inputs}
  </Config>
</PathOfBuilding2>
"""
