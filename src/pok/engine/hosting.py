"""담체↔페이로드 질의 — 「이 스킬을 무엇에 넣을 수 있나」 (사용자 요청 2026-08-11).

## 왜 필요한가

엔진은 *"내가 맞게 만들었나"* 에는 잘 답하는데 *"무엇을 만들 수 있나"* 에는 못 답한다.
이관 6차가 전부 검사·게이트였고 발상 도구는 한 번도 손대지 않았다. 사용자 판정:

> "새로운 아이디어는 내가 계속 내고 너는 검증 정도밖에 도움이 안 되고 있어.
>  엔진 구현 후 지금까지 주문 토템쪽 기재는 한 번도 추천받지 못했다."

`discover_mechanics`는 **사전 매칭**이라 문구에 없는 것을 못 찾는다(그 도구가 스스로
밝힌 한계). 그런데 **「주문 토템에 무엇을 넣을 수 있나」는 어느 레코드 문구에도 없다** —
PoB의 `requireSkillTypes`/`excludeSkillTypes`에만 있다. 그래서 구조적으로 안 나왔다.

실측 2026-08-11: 구형 번개를 점화 소스로 채택하고도 **주문 토템이 후보에 오른 적이
없었다.** 손으로 PoB 타입을 읽고서야 알았고, 같은 자리에서 **까부르는 화염이
`fromItem`이라 젬 소켓 자체가 불가**하다는 것을 놓쳐 설계가 한 바퀴 헛돌았다.

## 판정은 재구현이 아니라 **전사**다

`Modules/CalcTools.lua`의 `doesTypeExpressionMatch`·`canGrantedEffectSupportActiveSkill`을
그대로 옮겼다. AD-1(계산 재구현 금지)은 **계산**에 대한 것이고 이것은 카탈로그 질의다 —
쌍마다 PoB를 돌리면 수만 회가 되어 쓸 수 없다. 대신 `tests/`가 알려진 사례로 대조한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pok.pob.catalog import (
    SkillGate,
    effect_display_names,
    gem_effect_ids,
    skill_gates,
)

# `requireSkillTypes`/`excludeSkillTypes`의 스택 연산자 (나머지는 전부 피연산자)
_OPERATORS = frozenset({"AND", "OR", "NOT"})


def _expression_matches(
    expression: tuple[str, ...],
    types: frozenset[str],
    minion_types: frozenset[str] = frozenset(),
) -> bool:
    """후위 식 평가 — `CalcTools.lua:doesTypeExpressionMatch` 전사.

    ⚠ 집합 포함 검사가 아니다. `{Spell, Totemable, AND}`는 "둘 다"지만
    `{Spell, Totemable}`는 **둘 중 하나**다(스택에 참이 하나라도 남으면 통과).

    `minion_types`는 PoB의 3번째 인자다 — 소환수 스킬의 타입도 참으로 친다.
    **요구 판정에만** 넘어간다(배제엔 안 넘어간다): PoB가
    `doesTypeExpressionMatch(exclude, effectiveSkillTypes)`와
    `doesTypeExpressionMatch(require, effectiveSkillTypes, effectiveMinionTypes)`로
    비대칭이다. 빠뜨리면 소환수 빌드에서 **거짓 배제**가 난다(스킬 42종 해당).
    """
    stack: list[bool] = []
    for token in expression:
        if token == "OR" and len(stack) >= 2:
            other = stack.pop()
            stack[-1] = stack[-1] or other
        elif token == "AND" and len(stack) >= 2:
            other = stack.pop()
            stack[-1] = stack[-1] and other
        elif token == "NOT" and stack:
            stack[-1] = not stack[-1]
        elif token not in _OPERATORS:
            stack.append(token in types or token in minion_types)
    return any(stack)


@dataclass(frozen=True)
class HostVerdict:
    ok: bool
    reason: str


def can_host(carrier: SkillGate, payload: SkillGate) -> HostVerdict:
    """`carrier`(보조·메타·토템)가 `payload`(활성 스킬)를 담을 수 있는가.

    순서는 `canGrantedEffectSupportActiveSkill` 그대로다 — 배제가 요구보다 먼저다.
    """
    if payload.cannot_be_supported:
        return HostVerdict(False, f"{payload.name}은 보조를 받지 못한다 (cannotBeSupported)")
    if carrier.support_gems_only and payload.from_item:
        return HostVerdict(False, f"{carrier.name}은 젬만 지원한다 — {payload.name}은 아이템 부여")
    if carrier.from_item and payload.from_item:
        return HostVerdict(False, "아이템 부여 보조는 아이템 부여 스킬을 지원하지 못한다")
    if carrier.exclude and _expression_matches(carrier.exclude, payload.types):
        hit = sorted(t for t in carrier.exclude if t not in _OPERATORS and t in payload.types)
        return HostVerdict(False, f"배제 타입에 걸린다: {', '.join(hit)}")
    # PoB: `effectiveMinionTypes = not grantedEffect.ignoreMinionTypes and (...)`
    minion = frozenset() if carrier.ignore_minion_types else payload.minion_types
    if carrier.require and not _expression_matches(carrier.require, payload.types, minion):
        seen = payload.types | minion
        missing = sorted(t for t in carrier.require if t not in _OPERATORS and t not in seen)
        return HostVerdict(False, f"요구 타입 미충족: {', '.join(missing)}")
    return HostVerdict(True, "")


def label_of(gate: SkillGate) -> str:
    """사람이 읽을 이름 — 보조 반쪽의 내부 id 대신 젬 표시 이름을 쓴다."""
    return effect_display_names().get(gate.skill_id) or gate.name


def _candidates(query: str, gates: dict[str, SkillGate]) -> list[SkillGate]:
    """스킬 id · 젬 표시 이름 · `gem_id` 중 무엇으로 물어도 **반쪽 전량**을 낸다.

    메타 젬은 소환 반쪽과 보조 반쪽이 다른 스킬이라, 이름 하나가 둘을 가리킨다.
    """
    if query in gates:
        return [gates[query]]
    found: list[SkillGate] = []
    for gem_id, effects in gem_effect_ids().items():
        if gem_id != query:
            continue
        found.extend(gates[e] for e in effects if e in gates)
    if found:
        return found
    lowered = query.casefold()
    for effect, label in effect_display_names().items():
        if label.casefold() == lowered and effect in gates:
            found.append(gates[effect])
    if found:
        return found
    return [g for g in gates.values() if g.name.casefold() == lowered]


def _resolve(query: str, gates: dict[str, SkillGate]) -> SkillGate | None:
    """페이로드(활성 스킬) 쪽 해석 — 보조 반쪽이 아니라 실제 스킬을 고른다."""
    found = _candidates(query, gates)
    for gate in found:
        if not gate.is_support:
            return gate
    return found[0] if found else None


def _resolve_carrier(query: str, gates: dict[str, SkillGate]) -> SkillGate | None:
    """담체 쪽 해석 — 메타 젬이면 **보조 반쪽**을 고른다."""
    found = _candidates(query, gates)
    for gate in found:
        if gate.is_support:
            return gate
    return found[0] if found else None


def _socketable(gate: SkillGate) -> bool:
    """젬으로 소켓 가능한 활성 스킬인가 — 아이템 부여는 담을 수 없다."""
    return not gate.is_support and not gate.from_item


def find_carriers(skill: str, *, include_blocked: bool = False) -> dict[str, Any]:
    """이 스킬을 담을 수 있는 보조·메타·토템·트리거 **전량**.

    `include_blocked=True`면 막힌 것도 **사유와 함께** 낸다 — 「왜 안 되는가」가
    설계 정보다(까부르는 화염이 `fromItem`이라 안 된다는 것을 그렇게 알았다).
    """
    gates = skill_gates()
    payload = _resolve(skill, gates)
    if payload is None:
        return {"ok": False, "reason": f"모르는 스킬: {skill}"}

    hosts, blocked = [], []
    for gate in gates.values():
        if not gate.is_support or gate is payload:
            continue
        verdict = can_host(gate, payload)
        row: dict[str, Any] = {"carrier": label_of(gate), "skill_id": gate.skill_id}
        if verdict.ok:
            if gate.adds:
                # 보조가 **타입을 더한다** — 다음 보조의 판정이 달라진다(연쇄 주의)
                row["adds_types"] = list(gate.adds)
            hosts.append(row)
        elif include_blocked:
            blocked.append({**row, "why": verdict.reason})

    out: dict[str, Any] = {
        "ok": True,
        "skill": label_of(payload),
        "skill_id": payload.skill_id,
        "types": sorted(payload.types),
        "carriers": sorted(hosts, key=lambda r: r["carrier"]),
        "count": len(hosts),
    }
    if payload.from_item:
        out["warning"] = (
            f"{payload.name}은 **아이템 부여 스킬**(fromItem)이다 — 젬으로 소켓할 수 없어 "
            "메타 젬·토템에 넣지 못한다. 부여 아이템을 착용해야만 쓸 수 있다"
        )
    if include_blocked:
        out["blocked"] = sorted(blocked, key=lambda r: r["carrier"])
    out["notes"] = [
        "판정은 PoB `CalcTools.lua`의 타입 식 평가를 전사한 것이다 — 레코드 문구가 "
        "아니라 타입 시스템이라 **전수이고 정확**하다",
        "담을 수 있다는 것이 값어치가 있다는 뜻은 아니다 — 성능은 따로 측정하라",
        "⚠ **젬 설명문이 타입보다 좁게 말하는 경우가 있다.** 예: `Arbiter's Ignition`은 "
        "설명이 *Supports Fire Spell Skills*인데 `requireSkillTypes`는 `(Spell, Damage, AND)`라 "
        "화염을 요구하지 않는다. 둘이 어긋나면 **인게임이 판정 주체**다",
        "⚠ **부착 여부를 PoB 델타로 시험하지 말 것.** 효과가 PoB 미모델링이면"
        "(원소 집정관·잔류물 귀속 등) 붙어도 수치가 안 변해 **거부로 오독**한다 "
        "— 실측 2026-08-11에 두 번 겪었다",
    ]
    return out


def find_payloads(carrier: str, *, limit: int = 200) -> dict[str, Any]:
    """이 담체(메타 젬·토템·보조)에 넣을 수 있는 활성 스킬 **전량**."""
    gates = skill_gates()
    host = _resolve_carrier(carrier, gates)
    if host is None:
        return {"ok": False, "reason": f"모르는 담체: {carrier}"}
    if not host.is_support:
        return {
            "ok": False,
            "reason": f"{label_of(host)}은 보조·메타 젬이 아니다 (support 플래그 없음)",
        }

    seen: set[str] = set()
    payloads: list[dict[str, str]] = []
    for gate in gates.values():
        if not _socketable(gate) or not can_host(host, gate).ok:
            continue
        label = label_of(gate).strip()
        if not label or label in seen:  # 같은 젬의 변형들이 한 이름으로 겹친다
            continue
        seen.add(label)
        payloads.append({"skill": label, "skill_id": gate.skill_id})
    payloads.sort(key=lambda r: r["skill"])
    out: dict[str, Any] = {
        "ok": True,
        "carrier": label_of(host),
        "requires": list(host.require),
        "excludes": list(host.exclude),
        "payloads": payloads[:limit],
        "count": len(payloads),
    }
    if len(payloads) > limit:
        out["truncated"] = f"{len(payloads)}건 중 {limit}건만 반환 — limit을 올려 전량을 볼 것"
    out["notes"] = [
        "**아이템 부여 스킬(fromItem)은 제외했다** — 젬 소켓이 안 되므로 담을 수 없다",
    ]
    return out
