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

from dataclasses import MISSING, dataclass, field, fields
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
class JewelSpec:
    """트리 소켓에 장착하는 주얼 — text는 ItemSpec과 같은 raw 형식
    (베이스: Ruby|Emerald|Sapphire|Diamond|Time-Lost …).

    socket_node_id는 트리의 jewel-socket 노드 id이며 **tree_nodes에 함께
    할당돼 있어야** PoB가 반영한다(실측 2026-07-30: Sockets/Socket 요소,
    아이템이 트리보다 먼저 로드되는 PoB의 지연 트리 로드에 의존)."""

    socket_node_id: int
    text: str
    # 대체 모델링(백로그 B-3, 2026-08-02): KB `pob_computable: false` 유니크 주얼은
    # explicits가 플레이스홀더("Allocates Passive Skill")라 PoB가 실제 효과를 읽지
    # 못한다. 부여 노터블의 node_id를 여기 적으면 조립이 tree_nodes에 병합해
    # **효과만** 재현한다. 주얼 소켓 소모·랜덤 롤 조달 가정은 재현되지 않으므로
    # 계보(manifest)에 대체 모델링 사실이 기록된다 — 사실을 덮지 않는다.
    allocates: tuple[int, ...] = ()


@dataclass(frozen=True)
class BuildSpec:
    """PoB에 계산을 맡길 빌드 정의 — KB id 공간과 호환되는 최소 스펙."""

    class_name: str  # CLASS_INTERNAL_ID 키
    ascendancy: str  # KB 어센던시 코드 = PoB ascendancyInternalId ("Sorceress1"…)
    level: int = 90
    tree_nodes: tuple[int, ...] = ()  # KB node_id 그대로 (연결성은 호출자 책임)
    skills: tuple[SkillGroupSpec, ...] = ()
    items: tuple[ItemSpec, ...] = ()
    jewels: tuple[JewelSpec, ...] = ()
    main_socket_group: int = 1
    config: tuple[tuple[str, str | int | bool], ...] = field(default=())  # Input name→value
    # 능력치 택1 노드의 선택 — {node_id: "str"|"dex"|"int"} (이관 5 C13')
    #
    # `+N to any Attribute` 노드는 PoB 트리에 `isAttribute=true` + `options[]`로 있고
    # (293개, KB `attribute_choice`와 정확히 일치), 저장 자리는
    # `<Tree><Spec><Overrides><AttributeOverride …>`다. 이 자리가 없으면 **선택을
    # 표현할 수 없어** 전부 기본값으로 계산된다.
    #
    # 실측 2026-08-05: 앵커에서 택1 35개를 빼자 Str 184→79·Dex 165→104·Int 137→27.
    # **한 빌드의 능력치 절반 이상이 이 노드들에서 나온다** — 요구치 판정도, 능력치
    # 스태킹 빌드도 이걸 없이는 불가능하다.
    #
    # 미지정 노드는 PoB 기본 동작을 따른다(override에 넣지 않는다).
    attribute_choices: tuple[tuple[int, str], ...] = field(default=())


# 택1 선택 표기 — 짧은 것도 긴 것도 받는다(호출자가 어느 쪽을 쓸지 모른다)
_ATTR_KEYS = {
    "str": "str", "strength": "str", "힘": "str",
    "dex": "dex", "dexterity": "dex", "민첩": "dex",
    "int": "int", "intelligence": "int", "지능": "int",
}  # fmt: skip

_KEY_HINTS = {
    "gem_id": "PoB gemId — KB 젬 레코드의 pob 소스 ref가 그 값이다"
    " (get_entry로 sources를 보면 'Metadata/Items/Gems/…')",
}


def _make[T](cls: type[T], data: dict[str, Any], where: str) -> T:
    """dataclass 생성 — 빠진/모르는 키를 **어디서 났는지와 함께** 말한다.

    raw TypeError는 "missing 1 required positional argument: 'gem_id'"만 남긴다.
    어느 젬인지도, 무엇을 넣어야 하는지도 알 수 없어서 호출자는 추측으로 재시도한다.
    최상위 키는 이미 친절히 거부하고 있었는데 **중첩만 날것이었다** — 그 비대칭을 없앤다.
    """
    allowed = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    required = {
        f.name
        for f in fields(cls)  # type: ignore[arg-type]
        if f.default is MISSING and f.default_factory is MISSING
    }
    missing = sorted(required - set(data))
    unknown = sorted(set(data) - allowed)
    if missing or unknown:
        parts = []
        if missing:
            hints = [f"{k}({_KEY_HINTS[k]})" if k in _KEY_HINTS else k for k in missing]
            parts.append(f"빠진 키: {', '.join(hints)}")
        if unknown:
            parts.append(f"모르는 키: {unknown}")
        raise ValueError(f"{where} — {' · '.join(parts)}. 허용 키: {sorted(allowed)}")
    return cls(**data)


def _validate_catalog(spec_data: dict[str, Any]) -> None:
    """`gem_id`·`config` 키가 PoB에 실재하는지 본다 — **조용한 폴백을 막는다**.

    없는 `gem_id`를 줘도 PoB는 오류를 내지 않는다. `nameSpec`(표시 이름)으로 대체
    해석하기 때문인데, 이름까지 틀리거나 모호하면 **젬이 소리 없이 사라지고** 호출자는
    낮은 숫자를 실측으로 받는다. 실측 2026-08-05: 한 세션이 없는 id로 트리 62포인트를
    최적화한 뒤에야 발견했다.

    막다른 길로 끝내지 않는다 — `check_item_legality`의 표기 후보와 같은 방식으로
    정본 후보를 함께 낸다. 특히 표시 이름을 id 자리에 넣은 흔한 실수는 정확히 잡힌다
    ("Heavy Swing" → `SkillGemMeleePhysicalDamageSupport`).
    """
    from pok.pob.catalog import (
        config_vars,
        gem_ids,
        suggest_config_vars,
        suggest_gem_ids,
    )

    problems: list[str] = []
    valid_gems = gem_ids()
    for gi, group in enumerate(spec_data.get("skills", [])):
        for i, gem in enumerate(group.get("gems", [])):
            gid = str(gem.get("gem_id", ""))
            if gid and gid not in valid_gems:
                # **표시 이름을 먼저 본다** — 이름은 대개 맞고 id만 틀리기 때문이다.
                # id 문자열 유사도부터 재면 엉뚱한 젬이 후보로 나온다(실측).
                name = str(gem.get("name", ""))
                hints = (suggest_gem_ids(name) if name else []) or suggest_gem_ids(gid)
                problems.append(
                    f"skills[{gi}].gems[{i}]: gem_id {gid!r}가 PoB에 없다"
                    + (f" — 후보: {hints}" if hints else " (근접 후보도 없다)")
                )
    valid_config = config_vars()
    for key in dict(spec_data.get("config", {})):
        if str(key) not in valid_config:
            hints = suggest_config_vars(str(key))
            problems.append(
                f"config[{key!r}]: PoB에 없는 설정 키다" + (f" — 후보: {hints}" if hints else "")
            )
    if problems:
        raise ValueError(
            "PoB 카탈로그에 없는 값 — 그대로 계산하면 조용히 빠진 채 낮은 수치가 "
            "나온다:\n  " + "\n  ".join(problems)
        )


def spec_from_dict(data: dict[str, Any], *, validate_catalog: bool = True) -> BuildSpec:
    """JSON 친화 dict → BuildSpec (MCP 도구 입력 경로). 모르는 키는 즉시 거부.

    `validate_catalog`는 `gem_id`·`config` 키가 PoB에 실재하는지도 본다(기본 켬).
    """
    allowed = {f.name for f in fields(BuildSpec)}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f"모르는 키: {sorted(unknown)} (허용: {sorted(allowed)})")
    skills = tuple(
        _make(
            SkillGroupSpec,
            {
                **{k: v for k, v in grp.items() if k != "gems"},
                "gems": tuple(
                    _make(GemSpec, g, f"skills[{gi}].gems[{i}]")
                    for i, g in enumerate(grp.get("gems", []))
                ),
            },
            f"skills[{gi}]",
        )
        for gi, grp in enumerate(data.get("skills", []))
    )
    items = tuple(_make(ItemSpec, it, f"items[{i}]") for i, it in enumerate(data.get("items", [])))
    jewels = tuple(
        _make(JewelSpec, j, f"jewels[{i}]") for i, j in enumerate(data.get("jewels", []))
    )
    if validate_catalog:
        _validate_catalog(data)
    config = tuple((str(k), v) for k, v in dict(data.get("config", {})).items())
    # {node_id: "str"} 또는 [[node_id, "str"], …] 둘 다 받는다 — JSON에서 dict 키는
    # 문자열이 되므로 int로 되돌린다
    raw_choices = data.get("attribute_choices") or {}
    pairs = raw_choices.items() if isinstance(raw_choices, dict) else raw_choices
    attribute_choices: tuple[tuple[int, str], ...] = ()
    for node, choice in pairs:
        # **스펙을 만들 때 거부한다** — XML 직렬화까지 미루면 조립 게이트를 통과한
        # 뒤에 깨진다. 다른 카탈로그 검증과 같은 방침이다(이관 3).
        if str(choice).strip().lower() not in _ATTR_KEYS:
            raise ValueError(
                f"attribute_choices[{node}]: {choice!r}는 알 수 없다 — "
                f"허용: str|dex|int (strength·dexterity·intelligence·힘·민첩·지능도 받는다)"
            )
        attribute_choices = (*attribute_choices, (int(node), str(choice)))
    return BuildSpec(
        class_name=data["class_name"],
        ascendancy=data["ascendancy"],
        level=int(data.get("level", 90)),
        tree_nodes=tuple(int(n) for n in data.get("tree_nodes", [])),
        skills=skills,
        items=items,
        jewels=jewels,
        main_socket_group=int(data.get("main_socket_group", 1)),
        config=config,
        attribute_choices=attribute_choices,
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
    # 주얼: 아이템 뒤 이어지는 id, 슬롯 대신 Spec의 Sockets가 참조
    for jewel in spec.jewels:
        if jewel.socket_node_id not in spec.tree_nodes:
            raise ValueError(
                f"주얼 소켓 노드 {jewel.socket_node_id} 가 tree_nodes에 없음 "
                "(소켓을 트리에 할당해야 주얼이 반영된다)"
            )
    all_items = list(spec.items) + [ItemSpec(slot="", text=j.text) for j in spec.jewels]
    item_els = "\n".join(
        f'    <Item id="{i}">{escape(item.text)}</Item>'
        for i, item in enumerate(all_items, start=1)
    )
    slot_els = "\n".join(
        f'      <Slot name={quoteattr(item.slot)} itemId="{i}"/>'
        for i, item in enumerate(spec.items, start=1)
    )
    items_xml = (
        f'  <Items activeItemSet="1">\n{item_els}\n'
        f'    <ItemSet id="1" title="pok">\n{slot_els}\n    </ItemSet>\n  </Items>'
        if all_items
        else "  <Items/>"
    )
    spec_children = ""  # <Overrides>·<Sockets> — 줄 길이 때문에 미리 만든다
    sockets_xml = "".join(
        f'<Socket nodeId="{j.socket_node_id}" itemId="{len(spec.items) + i}"/>'
        for i, j in enumerate(spec.jewels, start=1)
    )

    # 능력치 택1 선택 → `<Overrides><AttributeOverride str/dex/intNodes="…"/>`
    # 타 유저 앵커 실측 형식 그대로. 미지정 노드는 넣지 않는다(PoB 기본값을 따른다).
    by_attr: dict[str, list[str]] = {"str": [], "dex": [], "int": []}
    for node_id, choice in spec.attribute_choices:
        key = _ATTR_KEYS.get(str(choice).strip().lower())
        if key is None:
            raise ValueError(
                f"attribute_choices[{node_id}]: {choice!r}는 알 수 없다 — "
                f"허용: str|dex|int (strength·dexterity·intelligence도 받는다)"
            )
        by_attr[key].append(str(node_id))
    overrides_xml = ""
    if any(by_attr.values()):
        # **세 속성을 항상 쓴다** — `PassiveSpec.lua:203`이 `attrib.strNodes:gmatch(…)`를
        # nil 검사 없이 부르므로, 빈 축을 생략하면 파싱이 깨져 선택이 엉뚱하게 들어간다
        # (실측 2026-08-05: 세 선택이 전부 같은 결과가 나왔다). PoB 자신도 저장할 때
        # 항상 셋을 쓴다(같은 파일 309행).
        attrs = " ".join(f"{k}Nodes={quoteattr(','.join(v))}" for k, v in by_attr.items())
        overrides_xml = f"<Overrides><AttributeOverride {attrs}/></Overrides>"

    spec_children = overrides_xml + (f"<Sockets>{sockets_xml}</Sockets>" if spec.jewels else "")

    # 대체 모델링 노드(JewelSpec.allocates)를 트리에 병합 — 순서 보존·중복 제거
    allocated = list(spec.tree_nodes) + [
        n for j in spec.jewels for n in j.allocates if n not in spec.tree_nodes
    ]
    nodes = ",".join(str(n) for n in dict.fromkeys(allocated))
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
    <Spec {spec_attrs}>{spec_children}</Spec>
  </Tree>
{items_xml}
  <Config>
{config_inputs}
  </Config>
</PathOfBuilding2>
"""
