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

import functools
import re
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
    # 단계형(채널링) 스킬의 스테이지 수 — PoB는 **젬 인스턴스 속성**으로 받는다
    # (`CalcActiveSkill.lua:868` skillStageCount / skillStageCountCalcs). 안 주면
    # **조용히 1단계**로 계산된다 — 실측 2026-08-07(이관 4): 화염파가 `75% more
    # damage per Stage` · 최대 10단계인데 1.75배(1회분)만 들어갔고, 세션은 그 수치를
    # 실측으로 받아 설계 판단을 내렸다. 최대 단계는 스킬마다 다르므로 기본값을
    # 정하지 않고, 단계형인데 미지정이면 조립 단계에서 알린다.
    stages: int | None = None
    # 어느 **모드(statSet)**로 계산할지 — 1부터. PoB는 한 스킬이 모드를 여럿 가질 때
    # 안 주면 **조용히 1번**을 쓴다. 실측 2026-08-10(이관 ①): 구형 번개 `WithIgniteDPS`
    # 파트1 2,387 / 파트2 32,231 / 파트3 **47,329** — 조립은 정상으로 보이고 수치만
    # 20배 낮다. 어느 모드로 설계할지는 판단이라 기본값을 정하지 않고, 모드가 둘 이상인
    # 젬에 미지정이면 조립 단계에서 거부한다(`stages`와 같은 취급).
    stat_set_index: int | None = None


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
    # **대리 측정 주입** (백로그 #3, 2026-08-08) — PoB가 계산하지 못하는 효과를 재려고
    # 여기 적은 줄은 아이템 텍스트에 이어붙어 접사로 파싱된다. `text`에 직접 섞지 말 것:
    # 섞으면 진짜 아이템 모드와 구분되지 않아 **추산이 실측으로 둔갑한다**.
    #
    # 이 칸에 적으면 조립이 manifest `substitute_modeling.injected_lines`에 자동으로
    # 기록한다 — 산출물을 읽는 쪽이 "이 수치는 추산"임을 알 수 있어야 하는데, 그걸
    # 사람 기억에 맡기면 사라진다(철칙 5: 규율은 강제 지점이 있어야 한다).
    #
    # 쓰는 경우: `pob_modeling.kind == "tree-line-unparsed"`(트리 500건) 또는
    # `rune-slot-unmatched` 레코드의 효과를 **등가 문구로 바꿔** 재는 것.
    # ⚠ 원문 그대로 넣으면 파서가 또 떨어뜨린다 — 대상 한정어가 원인이다
    # (예: "10% increased Archon Buff duration" → PoB는 `Archon Buff`를 못 읽는다).
    substitutes: tuple[str, ...] = ()


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


# 탐침 표기 — 천장을 재기 위한 가정치임을 스펙에 남기는 태그 (회차 종결 R1).
# `compute_pob`(측정)은 통과시키고 `assemble_pob`(출고)은 거부한다.
#
# 실측 2026-08-05: `+16650 생명력` 탐침으로 천장을 재고, 적법성에 걸려 빠진 뒤
# **주 엔진(생명력)을 실물로 재건하지 않은 채 출고했다.** 부차 축(힘)에는 요구-수급
# 장부를 만들면서 주 엔진에는 안 만들었다 — 탐침에 표기가 없어서 "재건해야 할 것"
# 목록에 오르지 못했다.
PROBE_TAG = re.compile(r"\[(?:탐침|PROBE)\]", re.I)


def find_probe_lines(data: dict[str, Any]) -> list[str]:
    """스펙에 남은 탐침 줄 전량 — 아이템·주얼 텍스트를 훑는다."""
    out: list[str] = []
    for item in data.get("items") or []:
        for line in str(item.get("text", "")).splitlines():
            if PROBE_TAG.search(line):
                out.append(f"{item.get('slot', '?')}: {line.strip()}")
    for jewel in data.get("jewels") or []:
        for line in str(jewel.get("text", "")).splitlines():
            if PROBE_TAG.search(line):
                out.append(f"jewel@{jewel.get('socket_node_id', '?')}: {line.strip()}")
    return out


def strip_probe_tags(text: str) -> str:
    """PoB에 보내기 전 태그만 벗긴다 — 측정은 태그가 있어도 돼야 한다."""
    return PROBE_TAG.sub("", text)


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


def _with_substitutes(item: ItemSpec) -> str:
    """대리 측정 줄을 아이템 텍스트 끝에 붙인다 — PoB에는 평범한 접사로 보인다.

    PoB에 보내는 것은 합쳐진 텍스트지만 **스펙에는 따로 남아 있어야** 한다.
    그래야 조립이 manifest에 "이 줄들은 주입분"이라고 적을 수 있다(#3).
    """
    if not item.substitutes:
        return item.text
    return item.text.rstrip("\n") + "\n" + "\n".join(item.substitutes)


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


@functools.lru_cache(maxsize=1)
def _staged_skills() -> dict[str, str]:
    """단계형 스킬 표시명(소문자) → 근거 문구. KB 효과 문구에서 결정적으로 유도한다."""
    from pok.kb.store import load as store_load

    out: dict[str, str] = {}
    for record in store_load().records.values():
        if record.type != "Skill":
            continue
        data = record.raw.get("data") or {}
        lines = [str(x) for x in (data.get("stats") or [])] + [
            str(x) for x in (data.get("stats_en") or [])
        ]
        hit = next(
            (ln for ln in lines if "maximum Stages" in ln or "per Stage" in ln),
            "",
        )
        if hit:
            name = str((record.raw.get("name") or {}).get("en") or "").strip().lower()
            if name:
                out[name] = hit[:60]
    return out


@functools.lru_cache(maxsize=1)
def _unique_index() -> dict[str, tuple[str, ...]]:
    """유니크 표시명(소문자) → explicits — 옵션 누락 검출용."""
    from pok.kb.store import load as store_load

    out: dict[str, tuple[str, ...]] = {}
    for record in store_load().records.values():
        data = record.raw.get("data") or {}
        if record.type != "Item" or data.get("rarity") != "unique":
            continue
        name = str((record.raw.get("name") or {}).get("en") or "").strip().lower()
        if name:
            out[name] = tuple(str(x) for x in (data.get("explicits") or []))
    return out


def _unique_explicits(name: str) -> tuple[str, ...]:
    return _unique_index().get(name.strip().lower(), ())


def _norm_mod(text: str) -> str:
    """모드 문구 정규화 — 수치·범위를 지워 롤이 달라도 같은 줄로 본다.

    KB는 `Gain (40-60)% of Damage as Extra Fire Damage`, 실물은 `Gain 50% of ...`
    처럼 롤만 다르다. 앞부분만 잘라 비교하면 "Gain "처럼 너무 짧아 못 쓴다.
    """
    stripped = re.sub(r"\(\d+(?:\.\d+)?\s*[-—]\s*\d+(?:\.\d+)?\)|\d+(?:\.\d+)?", "", text)
    return " ".join(stripped.lower().replace("+", " ").split())


@functools.lru_cache(maxsize=1)
def _ascendancy_codes() -> dict[str, str]:
    """어센던시 내부 코드 → 실명 (KB 시작 노드가 곧 매핑표)."""
    from pok.kb.store import load as store_load

    out: dict[str, str] = {}
    for record in store_load().records.values():
        data = record.raw.get("data") or {}
        if data.get("kind") == "ascendancy-start" and data.get("ascendancy"):
            out[str(data["ascendancy"])] = str((data.get("ascendancy_name") or {}).get("en") or "")
    return out


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
    # statSet 게이트의 재료는 KB다(#63 P2) — `gem_ids`·`config_vars`는 "PoB에
    # 실재하는가"라는 계산기 계약 검증이라 PoB 카탈로그에 남는다.
    from pok.kb.skill_facts import stat_sets
    from pok.pob.catalog import (
        config_vars,
        gem_ids,
        suggest_config_vars,
        suggest_gem_ids,
    )

    problems: list[str] = []

    # 클래스·어센던시를 **조립 전에** 검증한다. 이 둘은 오탈자여도 조용히 통과해
    # PoB가 기본값으로 폴백했다 — 실측 2026-08-07(이관 3): `ascendancy="Infernalist"`
    # (실명)를 줬더니 오류 없이 무시되고 meta.ascendancy가 "None"이 됐다. 스펙에
    # 필요한 값은 **내부 코드**("Witch1")인데 KB의 `ascendancy_name`은 실명이라
    # 매핑을 모르면 맞힐 수가 없다. gem_id처럼 정본 후보를 함께 낸다.
    class_name = str(spec_data.get("class_name", ""))
    if class_name and class_name not in CLASS_INTERNAL_ID:
        problems.append(
            f"class_name {class_name!r}는 PoB 클래스가 아니다 — 허용: {sorted(CLASS_INTERNAL_ID)}"
        )
    ascendancy = str(spec_data.get("ascendancy", ""))
    if ascendancy:
        codes = _ascendancy_codes()
        if ascendancy not in codes:
            by_name = {name.lower(): code for code, name in codes.items() if name}
            hint = by_name.get(ascendancy.lower())
            problems.append(
                f"ascendancy {ascendancy!r}는 내부 코드가 아니다"
                + (f" — 실명이라면 코드는 {hint!r}다" if hint else f" — 허용: {sorted(codes)}")
            )

    # 유니크 이름만 적고 옵션 줄을 안 적으면 PoB는 **아무 효과도 안 붙인** 채 계산한다
    # — 오류도 경고도 없어 "그 유니크를 쓴 수치"로 읽힌다. 실측 2026-08-07(이관 3):
    # "Sacred Flame\nShrine Sceptre"만 주면 무기 없을 때와 같은 288.63, 옵션을 다 적으면
    # 433.08(+50%)였다. KB에 그 explicits가 이미 있는데도 그렇다 — unset_config의
    # 델타 0 함정이 아이템 층에서 재발한 것이다.
    for ii, item in enumerate(spec_data.get("items", [])):
        lines = [ln for ln in str(item.get("text", "")).splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # 이름 줄은 Rarity 헤더가 있으면 둘째, 없으면 첫째다
        name = lines[1] if lines[0].lower().startswith("rarity:") else lines[0]
        explicits = _unique_explicits(name)
        if not explicits:
            continue
        body_norm = _norm_mod(" ".join(lines[2:]))
        # 짧은 문구는 **줄 단위 일치**로 본다. 부분 문자열 비교에 12자 문턱을 둔 것은
        # 짧은 조각이 남의 줄 안에서 우연히 걸리는 오탐을 막으려던 것인데, 그 문턱이
        # **오거부**를 낳았다: `Onslaught`(정규화 9자)는 텍스트에 멀쩡히 있는데도
        # 비교 대상에서 통째로 빠져 "옵션 줄이 하나도 없다"가 됐고, 그 유니크가 있는
        # **Helmet 슬롯 전체가 죽었다**(실측 2026-08-09, `item.thrillsteel`).
        # 줄 단위 일치는 양쪽을 다 막는다 — 우연한 부분 일치도, 짧다는 이유의 탈락도 없다.
        line_norms = {_norm_mod(ln) for ln in lines[2:]}
        norms = [_norm_mod(e) for e in explicits]
        if not any(n and ((len(n) >= 12 and n in body_norm) or n in line_norms) for n in norms):
            problems.append(
                f"items[{ii}]: {name!r}는 KB 유니크인데 옵션 줄이 하나도 없다 — PoB는 "
                f"아무 효과도 안 붙인 채 계산한다. KB `data.explicits` {len(explicits)}줄을 "
                f"텍스트에 적을 것 (예: {explicits[0][:48]!r})"
            )

    # 한 스킬이 **모드(statSet)를 여럿** 가지면 안 줬을 때 조용히 1번이 쓰인다 —
    # `stages`와 같은 형태의 조용한 기본값이고 격차는 더 크다. 실측 2026-08-10:
    # 구형 번개 `TotalDPS` 151.2(1번) / 381.5(2번) / **497.6(3번)**, 보고자의 장비
    # 갖춘 빌드에선 `WithIgniteDPS` 2,387 vs **47,329**(20배). 어느 모드로 설계할지는
    # 판단이라 정해 주지 않고, **지정하지 않았다는 사실만** 막는다.
    for gi, group in enumerate(spec_data.get("skills", [])):
        for i, gem in enumerate(group.get("gems", [])):
            if gem.get("stat_set_index") is not None:
                continue
            _, labels = stat_sets(str(gem.get("gem_id", "")))
            if len(labels) > 1:
                numbered = ", ".join(f"{n}={lb!r}" for n, lb in enumerate(labels, 1))
                problems.append(
                    f"skills[{gi}].gems[{i}]: {gem.get('name')!r}는 모드가 {len(labels)}개인데 "
                    f"`stat_set_index`가 없다 — PoB는 **1번으로 계산**한다({numbered}). "
                    f"어느 모드로 설계하는지 정해 줄 것"
                )

    # 단계형 스킬인데 스테이지를 안 주면 PoB가 **조용히 1단계**로 잰다 — 실측
    # 2026-08-07: 화염파 1단계 288.6 vs 10단계 1402.4(**4.86배**). 어느 단계로 설계할지는
    # 판단이므로 값을 정해 주지 않고, 지정하지 않았다는 사실만 막는다.
    for gi, group in enumerate(spec_data.get("skills", [])):
        for i, gem in enumerate(group.get("gems", [])):
            if gem.get("stages") is not None:
                continue
            max_stages = _staged_skills().get(str(gem.get("name", "")).lower())
            if max_stages:
                problems.append(
                    f"skills[{gi}].gems[{i}]: {gem.get('name')!r}는 단계형 스킬인데 "
                    f"`stages`가 없다 — PoB는 **1단계로 계산**한다({max_stages}). "
                    f"몇 단계를 유지하는 설계인지 정해 `stages`로 줄 것"
                )

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
    # `source: item-granted` 스킬은 **젬으로 못 켠다** (백로그 #47). 젬 획득 경로가
    # 없는데 PoB에는 `Metadata/…/SkillGem…`이 있어 **조용히 계산된다** — 실측
    # 2026-08-10: 소켓한 Firebolt가 `TotalDPS 217.5`를 냈다. 그 수치 위에서 한 세션이
    # 전 회차를 조립했고, 인게임에선 그 무기가 Firebolt를 주지 않아 점화 소스가 아예
    # 없었다. 판정 근거는 이미 KB에 있다(#4의 `source`) — 여기선 읽기만 한다.
    #
    # ⚠ 젬 경로와 아이템 부여는 배타가 아니다(Herald 3종·Spark·Unleash…). 그 8종은
    # `source = gem`이라 걸리지 않는다 — 정상 젬을 막으면 게이트 자체가 죽는다(§0 ⑤).
    for gi, group in enumerate(spec_data.get("skills", [])):
        for i, gem in enumerate(group.get("gems", [])):
            granted = _item_granted_skill(str(gem.get("name", "")))
            if granted:
                problems.append(
                    f"skills[{gi}].gems[{i}]: {gem.get('name')!r}는 **아이템 부여 스킬**이라 "
                    f"젬으로 못 켠다(KB `source: item-granted`, 부여원: {list(granted)}). "
                    f"쓰려면 부여 아이템을 `items`에 장착할 것 — 그러면 PoB가 아이템에서 "
                    f"스킬을 만들므로 이 젬 줄은 **빼야 한다**(넣으면 두 번 센다)"
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


# 스펙 파일에는 있지만 **PoB에는 안 가는** 키 (백로그 #58 ③). 계산에 쓰지 않으므로
# `BuildSpec` 필드가 아니지만, 스펙 파일을 그대로 넘기는 것이 정상 사용이라 거부하면
# 안 된다 — 산출 출처 표기는 세션을 건너가는 것이 목적이고, 그러려면 파일에 남아야 한다.
_SPEC_ONLY_KEYS = frozenset({"derived_from"})


def spec_from_dict(data: dict[str, Any], *, validate_catalog: bool = True) -> BuildSpec:
    """JSON 친화 dict → BuildSpec (MCP 도구 입력 경로). 모르는 키는 즉시 거부.

    `validate_catalog`는 `gem_id`·`config` 키가 PoB에 실재하는지도 본다(기본 켬).
    """
    allowed = {f.name for f in fields(BuildSpec)} | _SPEC_ONLY_KEYS
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


def _gem_xml(gem: GemSpec) -> str:
    """젬 하나 → `<Gem>` 조각.

    ⚠ statSet 선택은 **자식 원소로만 먹는다.** `SkillsTab.lua:354-355`가
    `statSetIndex` 속성을 파싱하기는 하지만 **370-371행이 즉시 `{}`로 덮어쓴다** —
    속성으로 주면 조용히 무시되고 파트 1·2·3이 소수점까지 같은 값으로 나온다
    (보고자 실측 + 재현). 소비처는 `CalcSetup.lua:1888,1890`이며 키는 `grantedEffect.id`다.
    """
    from pok.pob.catalog import canonical_gem_id

    head = (
        # 게임 id로 들어온 것은 **PoB 내부 id로 바꿔** 내보낸다 — 래더 코드가
        # 게임 id를 쓰는데, 우리 도구들(gempool·statSet 게이트)은 내부 id로 키를 잡는다.
        f"        <Gem gemId={quoteattr(canonical_gem_id(gem.gem_id))} "
        f"variantId={quoteattr(gem.name)} "
        f'level="{gem.level}" quality="{gem.quality}" '
        + (
            f'skillStageCount="{gem.stages}" skillStageCountCalcs="{gem.stages}" '
            if gem.stages is not None
            else ""
        )
        + f'enabled="{"true" if gem.enabled else "false"}" nameSpec={quoteattr(gem.name)}'
    )
    if gem.stat_set_index is None:
        return head + "/>"

    from pok.kb.skill_facts import primary_effect

    effect = primary_effect(gem.gem_id)
    index = gem.stat_set_index
    return (
        head + ">\n"
        f'          <StatSetIndex grantedEffect={quoteattr(effect)} index="{index}"/>\n'
        f'          <StatSetCalcsIndex grantedEffect={quoteattr(effect)} index="{index}"/>\n'
        "        </Gem>"
    )


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
        gems = "\n".join(_gem_xml(g) for g in group.gems)
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
    # 탐침 태그는 PoB에 보내기 전에 벗긴다 — 측정은 태그가 있어도 돼야 하고,
    # 태그를 그대로 보내면 PoB가 그 줄을 접사로 파싱하지 못한다
    item_els = "\n".join(
        f'    <Item id="{i}">{escape(strip_probe_tags(_with_substitutes(item)))}</Item>'
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


@functools.lru_cache(maxsize=1)
def _item_granted_index() -> dict[str, tuple[str, ...]]:
    """스킬 표시명(소문자) → 부여원. 젬으로 못 켜는 스킬만 담는다 (#47).

    판정 근거는 #4에서 KB에 넣은 `data.source`다 — 새로 추론하지 않는다.
    """
    from pok.kb.store import load as store_load

    out: dict[str, tuple[str, ...]] = {}
    for record in store_load().records.values():
        data = record.raw.get("data") or {}
        if record.type != "Skill" or data.get("source") != "item-granted":
            continue
        givers = tuple(str(x) for x in (data.get("granted_by") or []))[:3]
        out[record.name_en.lower()] = givers or ("(부여원 미수록)",)
    return out


def _item_granted_skill(name: str) -> tuple[str, ...] | None:
    """이 이름이 아이템 부여 스킬인가 — 아니면 `None`."""
    return _item_granted_index().get(name.strip().lower())
