"""스펙 자체의 설계 무결성 — **적법성과 별개 축** (백로그 #58 ①, 2026-08-11).

지금까지의 강제 지점은 전부 "이 스펙이 **지금 적법한가**"를 봤다(`items_legal` ·
`req_shortfall` · `pruned_nodes` · statSet 선언 · 룬 표기 · 색 원장). 전부 잘
동작했는데도 한 세션이 **같은 실패를 3연속**했고 세 번 다 도구가 통과시켰다 —
빌드가 「적법」한데 **애초에 빌드가 아니었기** 때문이다.

실측 2026-08-11(이관 5차): 주력기가 스펙에 없는 채로 3회차가 돌았고
`CombinedDPS`가 2,562였다. 주력기를 넣자 **24,436** — 10배가 조용히 빠져 있었다.
`items_legal ✅` · `pruned []`였다.

여기 있는 것은 **결정적 구조 검사**뿐이다(AD-3): 무엇을 만들지는 판단하지 않고,
"딜을 낼 수 있는 구성인가"라는 기계적 질문만 한다. 거부하지 않는다 — 낡은/부분
구성으로 A/B를 재는 것이 정상 작업이고, 막으면 게이트가 정상을 죽인다(§0 ⑤).
대신 **매 반환에 싣는다**: 1회성 경고는 문서와 동급이라 사라진다(#29).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from pok.kb.store import Store
from pok.pob.selection import resolve_xml_selection

_CLASSIFICATIONS: tuple[Store, dict[str, str]] | None = None

# These two controls were independently reproduced against native PoB (#211).
# They are buff counters in ConfigOptions.lua, not skillStageCount inputs.
_BUFF_STACK_CONFIG = {
    "Metadata/Items/Gems/SkillGemWindDancer": ("Wind Dancer", "windDancerStacks"),
    "Metadata/Items/Gems/SkillGemScavengedPlating": ("Scavenged Plating", "scavengedPlatingStacks"),
}


def _buff_stack_control(gem: dict[str, Any]) -> tuple[str, str] | None:
    identity = gem.get("gem_id")
    if identity:
        return _BUFF_STACK_CONFIG.get(str(identity))
    name = str(gem.get("name", "")).strip().lower()
    return next((entry for entry in _BUFF_STACK_CONFIG.values() if entry[0].lower() == name), None)


def _buff_stage_diagnostics(spec_data: dict[str, Any]) -> list[str]:
    """Report ineffective stage inputs without changing any upkeep assumption."""
    problems: list[str] = []
    # Public JSON is a mapping; dataclasses.asdict(BuildSpec) retains pairs.
    config = dict(spec_data.get("config") or ())
    for gi, group in enumerate(spec_data.get("skills") or []):
        if not group.get("enabled", True):
            continue
        for gem_i, gem in enumerate(group.get("gems") or []):
            if not gem.get("enabled", True) or gem.get("stages") is None:
                continue
            control = _buff_stack_control(gem)
            if control is None:
                continue
            name, key = control
            supplied = repr(config[key]) if key in config else "미지정"
            problems.append(
                f"skills[{gi}].gems[{gem_i}] {name}: stages={gem['stages']}는 "
                f"이 버프의 중첩 수를 제어하지 않는다. 실제 입력은 config.{key} "
                f"(현재 {supplied})다. stages 무변화를 PoB 미지원으로 판단하지 말 것. "
                "유지 가능한 중첩 수를 확인해 명시할 것 — 값을 자동 적용하지 않았다"
            )
    return problems


def xml_buff_stage_diagnostics(xml: str) -> tuple[str, ...]:
    """Inspect saved active sets without restoring or rewriting the document."""
    try:
        tree = ET.fromstring(xml)
    except ET.ParseError:
        return ("XML 버프 단계 진단에서 원문을 해석할 수 없다 — 계산 입력은 변경하지 않았다",)
    candidates = [
        gem
        for gem in tree.iter("Gem")
        if (gem.get("skillStageCount") is not None or gem.get("skillStageCountCalcs") is not None)
        and _buff_stack_control({"gem_id": gem.get("gemId"), "name": gem.get("nameSpec", "")})
    ]
    if not candidates:
        return ()
    try:
        chosen = resolve_xml_selection(tree)
    except ValueError as exc:
        return (f"XML 버프 단계 진단의 저장 세트 선택을 확인할 수 없다: {exc}",)
    if chosen.notes:
        return (
            "XML 버프 단계 진단의 저장 세트 선택에 대체가 필요하다: " + "; ".join(chosen.notes),
        )
    if chosen.skills is None:
        return ()
    groups = [
        {
            "enabled": group.get("enabled") != "false",
            "gems": [
                {
                    "name": gem.get("nameSpec", ""),
                    "gem_id": gem.get("gemId", ""),
                    "enabled": gem.get("enabled") != "false",
                    "stages": gem.get("skillStageCount", gem.get("skillStageCountCalcs")),
                }
                for gem in group.findall("Gem")
            ],
        }
        for group in chosen.skills.findall("Skill")
    ]
    config = {
        entry.get("name", ""): entry.get("number", entry.get("string", entry.get("boolean")))
        for entry in (chosen.config.findall("Input") if chosen.config is not None else [])
    }
    prefix = (
        f"XML skill_set={chosen.resolved.get('skill_set')}, "
        f"config_set={chosen.resolved.get('config_set')}: "
    )
    return tuple(
        prefix + warning
        for warning in _buff_stage_diagnostics({"skills": groups, "config": config})
    )


def _record_kind(tags: frozenset[str], effects: list[dict[str, Any]]) -> str:
    """Explicit meta containers still need a payload, even with ancillary effects."""
    types = {
        str(value)
        for effect in effects
        if not effect.get("support")
        for value in effect.get("types", [])
    }
    if "meta" in tags or "Meta" in types:
        return "meta"
    if "InbuiltTrigger" in types:
        return "active"
    # Retain the existing external-trigger fallback when no internal effect is
    # recorded. Triggerable (can be triggered) is not a container marker.
    return "meta" if "trigger" in tags else "active"


def _skill_kinds() -> dict[str, str]:
    """KB identity-scoped classifications by native gem id and display name."""
    from pok.kb.store import load as store_load

    global _CLASSIFICATIONS
    store = store_load()
    if _CLASSIFICATIONS is not None and _CLASSIFICATIONS[0] is store:
        return _CLASSIFICATIONS[1]
    out: dict[str, str] = {}
    for record in store.records.values():
        if record.type != "Skill":
            continue
        tags = record.raw.get("tags") or []
        pob = record.raw.get("data", {}).get("pob", {})
        kind = _record_kind(frozenset(str(x).lower() for x in tags), pob.get("effects", []))
        out[record.name_en.lower()] = kind
        if identity := pob.get("gem_id"):
            out[str(identity)] = kind
    _CLASSIFICATIONS = (store, out)
    return out


def _is_support(gem: dict[str, Any]) -> bool:
    """보조 젬인가 — PoB gemId가 정본이다(`…Support`)."""
    return str(gem.get("gem_id", "")).endswith("Support")


def _classify(gem: dict[str, Any], kinds: dict[str, str]) -> str:
    """`support` | `meta` | `active` | `unknown`."""
    if _is_support(gem):
        return "support"
    return kinds.get(
        str(gem.get("gem_id", "")),
        kinds.get(str(gem.get("name", "")).strip().lower(), "unknown"),
    )


def spec_integrity(
    spec_data: dict[str, Any], *, native_selection: dict[str, Any] | None = None
) -> tuple[str, ...]:
    """스펙의 구조적 결함 — 적법성이 아니라 **설계가 성립하는가**.

    돌려주는 것은 사람이 읽을 문장이다. 어느 그룹의 몇 번째인지까지 짚어야
    호출자가 고칠 수 있다(#29: 어디를 고칠지 모르는 경고는 안 고쳐진다).
    """
    problems: list[str] = _buff_stage_diagnostics(spec_data)
    groups = list(spec_data.get("skills") or [])
    if not groups:
        return ("스킬 그룹이 하나도 없다 — 딜을 낼 수 있는 구성이 아니다",)

    classifications = _skill_kinds()
    kinds = [[_classify(g, classifications) for g in (grp.get("gems") or [])] for grp in groups]

    # ① 주력기 부재 — `main_socket_group`이 가리키는 곳에 딜을 낼 스킬이 없다.
    #    실측: `CombinedDPS` 2,562(주력기 없음) → 24,436(투입). **10배**.
    main_index = int(spec_data.get("main_socket_group") or 1)
    if not 1 <= main_index <= len(groups):
        problems.append(
            f"main_socket_group={main_index}인데 스킬 그룹은 {len(groups)}개다 — "
            f"PoB가 다른 그룹을 주력으로 잡는다"
        )
    else:
        main = groups[main_index - 1]
        main_kinds = kinds[main_index - 1]
        active_at = [i for i, k in enumerate(main_kinds) if k == "active"]
        if not active_at:
            gems = [str(g.get("name", "?")) for g in (main.get("gems") or [])]
            problems.append(
                f"skills[{main_index - 1}]는 **주력 그룹인데 딜을 낼 스킬이 없다** "
                f"(젬: {gems or '(비어 있음)'}) — 메타 젬·보조만으로는 딜이 나오지 않는다. "
                f"실측 2026-08-11: 이 상태로 3회차가 돌았고 `CombinedDPS` 2,562 vs "
                f"주력기 투입 시 24,436(**10배**)"
            )
        else:
            # mainActiveSkill indexes the native active-effect list, not gems.
            # Without an observation, do not manufacture a slot-based verdict.
            actual_value = (native_selection or {}).get("actual")
            actual: dict[str, Any] = actual_value if isinstance(actual_value, dict) else {}
            observed = (
                native_selection is not None
                and native_selection.get("format") == "pok.native-selection.v1"
                and native_selection.get("status") == "observed"
                and actual.get("selected") is True
            )
            if observed and actual.get("meta_container") is True:
                problems.append(
                    "PoB의 실제 주력 활성 효과가 메타 컨테이너다: "
                    f"{actual.get('effect_id')} (활성 효과 순번 {actual.get('active_index')}, "
                    f"젬 슬롯 {actual.get('gem_index')}) — 의도한 피해 효과인지 확인할 것"
                )
            if observed and actual.get("group_index") == main_index:
                pointer = int(main.get("main_active_skill") or 1)
                index = actual.get("active_index")
                if isinstance(index, int) and pointer != index:
                    problems.append(
                        f"main_active_skill={pointer} 요청과 PoB 실제 활성 효과 순번 {index}가 "
                        "다르다 — 젬 슬롯 번호와 혼동하지 말고 nativeSelection을 확인할 것"
                    )

    # ③ 트리거 미연결 — 메타 젬이 있는데 **발동될 스킬**이 같은 그룹에 없다.
    #    PoB는 오류를 내지 않는다. 조립도 성공이고 젬도 `enabled="true"`다.
    for gi, (grp, kind_list) in enumerate(zip(groups, kinds, strict=True)):
        metas = [
            str(g.get("name", "?"))
            for g, k in zip(grp.get("gems") or [], kind_list, strict=True)
            if k == "meta"
        ]
        if metas and "active" not in kind_list:
            problems.append(
                f"skills[{gi}]: 트리거 젬 {metas}이 있는데 **발동될 스킬이 없다** — "
                f"그 그룹은 정신력만 점유하고 아무것도 하지 않는다. 같은 그룹에 "
                f"발동시킬 액티브 스킬을 넣을 것"
            )
    return tuple(problems)


def granted_reservation_diagnostics(
    items: list[dict[str, Any]], stats: dict[str, Any]
) -> dict[str, Any]:
    """Attach the existing #167 IN_GAME fact at measurement time, without corrections.

    Only Absent/Lament base grants were verified. A manually socketed instance
    remains separate and can reserve Spirit. Never subtract its cost or excuse
    unrelated reservation deficits.
    """
    grants: list[dict[str, Any]] = []
    for item in items:
        if item.get("slot") != "Amulet":
            continue
        lines = [re.sub(r"\{[^}]*\}", "", line).strip()
                 for line in str(item.get("text", "")).splitlines()]
        if not {"Absent Amulet", "Lament Amulet"}.intersection(lines):
            continue
        for line in lines:
            match = re.fullmatch(r"Grants Skill: Level \d+ (.+)", line)
            if match:
                grants.append({
                    "slot": "Amulet", "skill": match.group(1),
                    "granted_instance_spirit_reservation": 0,
                    "gem_instance_is_separate": True,
                    "source": "mechanic.item-granted-skills (#167, IN_GAME)",
                    "note": ("목걸이 부여 인스턴스는 무료다. "
                             "같은 스킬의 직접 등록 젬은 별도 인스턴스다."),
                })
    if not grants:
        return {}
    out: dict[str, Any] = {"granted_skill_instances": grants}
    remaining = stats.get("SpiritUnreserved")
    if isinstance(remaining, (int, float)) and remaining < 0:
        out["known_pob_limitations"] = [{
            "code": "AMULET_GRANTED_SKILL_RESERVATION_ACCOUNTING",
            "source": "mechanic.item-granted-skills (#167, IN_GAME)",
            "native_spirit_unreserved": remaining,
            "granted_skills": [grant["skill"] for grant in grants],
            "assessment": "known_calculator_accounting_limitation_not_grant_infeasibility",
            "note": (
                "목걸이 부여 스킬의 정신력 오점유는 알려진 PoB 결함이다. "
                "이 음수만으로 부여 스킬을 사용할 수 없다고 판정하거나 "
                "사용자에게 같은 사실을 재검증 요청하지 말 것. "
                "직접 젬과 무관한 점유 제약을 자동 면제하지 않았고 원래 수치는 보존했다."
            ),
        }]
    return out


def xml_granted_reservation_diagnostics(xml: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Read only the saved equipped amulet; inactive item sets cannot supply it."""
    try:
        root = ET.fromstring(xml)
        selected = resolve_xml_selection(root)
    except (ET.ParseError, ValueError):
        return {}
    if selected.notes or selected.items is None:
        return {}
    items = root.find("Items")
    if items is None:
        return {}
    by_id = {entry.get("id"): "".join(entry.itertext()) for entry in items.findall("Item")}
    equipped = [{"slot": "Amulet", "text": by_id.get(slot.get("itemId"), "")}
                for slot in selected.items.findall("Slot") if slot.get("name") == "Amulet"]
    return granted_reservation_diagnostics(equipped, stats)
