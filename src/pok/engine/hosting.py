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

## 재료는 KB에서 읽는다 (#63 P2)

처음 구현은 런타임에 `external/pob/**/Data/Skills`를 직독했다 — gitignore된
**파생물**에 판정이 걸려 있었고(철칙 2), CI엔 그 데이터가 없어 통합 테스트 5건이
통째로 깨졌다. 지금은 `kb/ingest/skill_types.py`가 수록한 KB `data.pob`를
`kb/skill_facts.py`로 읽는다 — 정본은 git이라 어디서나 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pok.kb.skill_facts import SkillGate, skill_gates

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
    # ⚠ 이 두 줄의 판정 기준은 `from_item`이 **아니라** 소켓 가부다 — PoB도 여기서
    # `activeSkill.activeEffect.gemData` 유무를 본다. `from_item`을 대리로 쓰면
    # 젬으로도 얻는 스킬(살아있는 폭탄)이 거짓 차단된다(`[빌드]` 이관 D1, 2026-08-11).
    if carrier.support_gems_only and not payload.socketable:
        return HostVerdict(False, f"{carrier.name}은 젬만 지원한다 — {payload.name}은 젬이 아니다")
    # PoB: `grantedEffect.fromItem and grantedEffect.support and (활성 스킬도 아이템 유래)`
    if carrier.from_item and carrier.is_support and not payload.socketable:
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
    """사람이 읽을 이름 — 보조 반쪽도 KB 레코드의 젬 표시 이름을 물려받는다."""
    return gate.name or gate.skill_id


def _candidates(query: str, gates: dict[str, SkillGate]) -> list[SkillGate]:
    """스킬 id · 표시 이름(한/영) · `gem_id` · KB 레코드 id 무엇으로 물어도 **반쪽 전량**.

    메타 젬은 소환 반쪽과 보조 반쪽이 다른 스킬이라, 이름 하나가 둘을 가리킨다.
    """
    if query in gates:
        return [gates[query]]
    found = [g for g in gates.values() if query in (g.gem_id, g.record_id)]
    if found:
        return found
    lowered = query.casefold()
    return [g for g in gates.values() if lowered in (g.name.casefold(), g.name_ko)]


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
    """젬으로 소켓 가능한 활성 스킬인가 — 판정은 `SkillGate.socketable`(D8)."""
    return gate.socketable


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
    if not payload.socketable:
        # ⚠ **단정하지 않는다.** 예전 문구는 "메타 젬·토템에 넣지 못한다"고 못박았는데,
        # 정작 같은 반환값의 `carriers`에 주문 토템이 들어 있어 **자기모순**이었다
        # (`[빌드]` 이관 D1). 아이템 부여 스킬도 그 아이템에 박힌 보조 젬의 지원은
        # 받으므로 담체가 0인 것도 아니다 — 사실만 말하고 판정은 넘긴다.
        out["warning"] = (
            f"{payload.name}은 젬으로 소켓하지 않는 스킬이다"
            f"(poe2db 획득 경로 {payload.catalog_source or '미표기'} · PoB `fromItem`) — "
            "부여 아이템을 착용해야 쓸 수 있고, 아래 담체는 **그 아이템에 함께 박은 보조**로 "
            "읽어야 한다. 별도 소켓의 메타 젬에 넣는 구성은 성립하지 않는다"
        )
    elif payload.from_item:
        # 젬이면서 아이템 부여도 되는 이중 경로 — 차단이 아니라 정보다
        out["note_dual_path"] = (
            f"{payload.name}은 **이중 경로**다 — poe2db는 젬(`{payload.catalog_source}`)이라 "
            "하고 PoB는 `fromItem`도 표시한다. 젬으로 소켓해 쓸 수 있다"
        )
    if include_blocked:
        out["blocked"] = sorted(blocked, key=lambda r: r["carrier"])
    out["notes"] = [
        "판정은 PoB `CalcTools.lua`의 타입 식 평가를 전사한 것이다 — 레코드 문구가 "
        "아니라 타입 시스템이다. 범위는 KB 수록분이며, PoB에만 있는 나머지는 전량 "
        "**제외 원장 근거**(잔재·미획득 — `exclusions.json`)라 커버리지에 구멍이 없다",
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
    item_only: set[str] = set()
    for gate in gates.values():
        if gate.is_support or not can_host(host, gate).ok:
            continue
        if not _socketable(gate):
            # 조용히 버리지 않는다 — 몇 건을 왜 뺐는지 반환값에 남긴다(#63 계열의 교훈)
            item_only.add(label_of(gate).strip() or gate.skill_id)
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
    out["excluded_item_granted"] = sorted(item_only)
    out["notes"] = [
        f"타입 판정은 통과하지만 **젬으로 소켓하지 않는 스킬 {len(item_only)}건**을 뺐다 "
        "(`excluded_item_granted`). 소켓 가부는 poe2db 획득 경로로 가른다 — PoB의 "
        "`fromItem`만 보면 젬으로도 얻는 스킬이 거짓 배제된다(이관 D1)",
    ]
    return out
