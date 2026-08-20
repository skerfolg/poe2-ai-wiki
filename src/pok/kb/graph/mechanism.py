"""메커니즘 상태 그래프 — 「무엇이 무엇을 만들고 무엇이 그것을 먹나」 (#92, #91 자매).

`supply.py`가 **스탯→스탯** 비례 엣지를 다뤘다면 여기는 **상태→상태** 전이를 다룬다.
빌드의 연쇄(동결→소비→주입 생성→주입 페이오프 같은 사슬)는 어느 레코드 문구
하나에도 없고 **여러 담체의 생산·소비를 그래프로 엮어야** 나온다.

## 왜 기존 도구로 안 되나 (실측 2026-08-20)

- `scan_synergies`는 **쌍만** 낸다 — 다단 순회가 없어 사슬이 안 나온다.
- `discover_mechanics`는 사전 매칭이라 문구에 키워드가 없으면 못 찾는다(자기 고백).
- 정본 typed edge는 **사실상 비어 있다** — 관계 448건 중 Mechanic은 3건뿐(전부 한
  레코드). AGENTS.md는 "시너지는 관계 그래프로 판단"이라 적혀 있는데 그 그래프가 없다.

## 두 소스를 융합한다 (어느 한쪽도 절반만 안다)

  · **구조화 타입** (`data.pob.effects[].types`) — `GeneratesInfusion`·
    `SkillConsumesFreeze` 같은 토큰 33종. 소비/생산 **의미론이 정확**하지만
    상태이상 *생산*은 여기 없다(냉기 스킬이 얼린다는 건 타입이 아니다).
  · **텍스트 술어** (`predicates.py`) — 상태이상 생산·페이오프를 읽는다. 대신
    통제 어휘(KD-2) 안에서만 본다.

실측: 타입만 쓰면 20축 중 2축만 생산·소비가 둘 다 있고, 융합하면 18종 전이가 나온다.

## 소비(consume)와 페이오프(payoff)는 다른 엣지다

동결을 **소비**하는 스킬은 그 동결을 없애고(다음 소비자가 못 먹는다), 동결에
**페이오프**하는 효과는 상태를 남긴다. 사슬을 이을 때 이 구분이 없으면 같은 상태를
두 번 먹는 불가능한 연쇄가 나온다. 그래서 엣지 종류를 싣는다.

## 판단 없음 (AD-3)

전이를 열거하고 근거를 달 뿐, 어느 연쇄가 좋은지는 답하지 않는다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from pok.kb.graph.predicates import extract_predicates, record_texts
from pok.kb.store import Record, Store

# ── 구조화 타입 토큰 → 상태 축 ──────────────────────────────────────────
# PoB `data.pob.effects[].types`의 토큰이다. 문구가 아니라 **타입 시스템**이라
# 표기 흔들림이 없다(#62 hosting과 같은 재료).
PRODUCE_TYPES: dict[str, str] = {
    "GeneratesCharges": "charge",
    "GeneratesRemnants": "remnant",
    "GeneratesEnergy": "meta_energy",
    "GeneratesInfusion": "infusion",
    "CreatesGroundEffect": "ground_effect",
    "CreatesFissure": "fissure",
    "CreatesGroundRune": "hazard",
    "CreatesMinion": "minion",
    "CreatesSkeletonMinion": "minion",
    "CreatesUndeadMinion": "minion",
    "CreatesDemonMinion": "minion",
    "CanCreateStoneElementals": "minion",
    "CreatesCompanion": "companion",
    "GainsStages": "stage",
    "HasSeals": "seal",
    "ComboStacking": "combo",
}
CONSUME_TYPES: dict[str, str] = {
    "ConsumesCharges": "charge",
    "SkillConsumesPowerChargesOnUse": "charge",
    "SkillConsumesFrenzyChargesOnUse": "charge",
    "SkillConsumesEnduranceChargesOnUse": "charge",
    "SkillConsumesFreeze": "freeze",
    "SkillConsumesShock": "shock",
    "SkillConsumesIgnite": "ignite",
    "SkillConsumesBleeding": "bleeding",
    "SkillConsumesParried": "parried",
    "ConsumesRage": "rage",
    "ConsumesFullyBrokenArmour": "broken_armour",
}
# 텍스트 술어의 subject → 상태 축. 두 소스가 **같은 축 이름**을 써야 융합된다.
_STATUS_AXIS: dict[str, str] = {
    "shocked": "shock",
    "ignited": "ignite",
    "chilled": "chill",
    "frozen": "freeze",
    "electrocuted": "electrocute",
    "poisoned": "poison",
    "bleeding": "bleeding",
    "stunned": "stun",
    "cursed": "curse",
    "blinded": "blind",
    "immobilised": "immobilise",
    "dazed": "daze",
    "hindered": "hinder",
    "burning": "burning",
    "marked": "marked",
    "maimed": "maim",
}
_SUBJECT_AXIS: dict[str, str] = {
    "self.charge.power": "charge",
    "self.charge.frenzy": "charge",
    "self.charge.endurance": "charge",
    "self.infusion.count": "infusion",
    "self.combo.count": "combo",
    "self.ward.pct": "ward",
    "self.seal.count": "seal",
    "env.remnant.available": "remnant",
    "env.fissure.count": "fissure",
    "env.ground-effect": "ground_effect",
    "self.rage.count": "rage",
}


@dataclass(frozen=True)
class StateEdge:
    """상태 축 하나에 대한 담체의 관계 1건. 근거 문구가 판정의 전부다(AD-8)."""

    axis: str
    kind: str  # "produce" | "consume" | "payoff"
    carrier_id: str
    carrier_name: str
    carrier_type: str  # Skill | Support | Passive | Item | Modifier | Mechanic
    source: str  # "type"(구조화 토큰) | "text"(술어) — 신뢰도 구분
    evidence: str


@dataclass(frozen=True)
class AxisSummary:
    axis: str
    producers: int
    consumers: int
    payoffs: int


@dataclass(frozen=True)
class StateScan:
    edges: tuple[StateEdge, ...]
    axes: tuple[AxisSummary, ...]
    # 소비·페이오프는 있는데 **생산자가 없는** 축. 수집 갭이거나 어휘 갭이다 —
    # 조용히 두면 "이 축은 못 쓴다"로 오독된다(#21·B-11과 같은 형태).
    unproduced_axes: tuple[str, ...] = ()


def _carrier_types(record: Record) -> set[str]:
    out: set[str] = set()
    for effect in record.raw.get("data", {}).get("pob", {}).get("effects", []) or ():
        out.update(str(t) for t in effect.get("types", []) or ())
        out.update(str(t) for t in effect.get("adds", []) or ())
    return out


def scan_state_edges(store: Store) -> StateScan:
    """정본 전수에서 상태 생산·소비·페이오프 엣지를 뽑는다 (구조화 타입 + 텍스트 융합)."""
    edges: list[StateEdge] = []

    for record in store.records.values():
        name, rtype = record.name_en, record.type
        # ① 구조화 타입 — 의미론이 정확한 쪽
        for token in _carrier_types(record):
            if token in PRODUCE_TYPES:
                edges.append(
                    StateEdge(
                        axis=PRODUCE_TYPES[token],
                        kind="produce",
                        carrier_id=record.id,
                        carrier_name=name,
                        carrier_type=rtype,
                        source="type",
                        evidence=f"PoB 타입 토큰 `{token}`",
                    )
                )
            if token in CONSUME_TYPES:
                edges.append(
                    StateEdge(
                        axis=CONSUME_TYPES[token],
                        kind="consume",
                        carrier_id=record.id,
                        carrier_name=name,
                        carrier_type=rtype,
                        source="type",
                        evidence=f"PoB 타입 토큰 `{token}`",
                    )
                )
        # ② 텍스트 술어 — 상태이상 생산·페이오프를 읽는 쪽
        texts = record_texts(record.raw)
        if not texts:
            continue
        for predicate in extract_predicates(texts, store.subjects):
            axis = (
                _STATUS_AXIS.get(predicate.value or "")
                if predicate.subject == "enemy.status"
                else _SUBJECT_AXIS.get(predicate.subject)
            )
            if axis is None:
                continue
            edges.append(
                StateEdge(
                    axis=axis,
                    # 텍스트는 「없앤다」를 구분하지 못한다 — 요구는 payoff로 싣고,
                    # 소비 판정은 구조화 타입에만 맡긴다(잘못 이으면 불가능한 연쇄가 난다).
                    kind="produce" if predicate.direction == "supply" else "payoff",
                    carrier_id=record.id,
                    carrier_name=name,
                    carrier_type=rtype,
                    source="text",
                    evidence=predicate.evidence,
                )
            )

    by_axis: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for edge in edges:
        idx = {"produce": 0, "consume": 1, "payoff": 2}[edge.kind]
        by_axis[edge.axis][idx] += 1
    axes = tuple(
        AxisSummary(axis=a, producers=v[0], consumers=v[1], payoffs=v[2])
        for a, v in sorted(by_axis.items(), key=lambda kv: -sum(kv[1]))
    )
    return StateScan(
        edges=tuple(edges),
        axes=axes,
        unproduced_axes=tuple(
            a.axis for a in axes if a.producers == 0 and (a.consumers or a.payoffs)
        ),
    )


# ── 전이·사슬 ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Transition:
    """상태 A를 먹고 상태 B를 내놓는 담체 — 사슬의 마디."""

    from_axis: str
    to_axis: str
    carrier_id: str
    carrier_name: str
    carrier_type: str
    in_kind: str  # 들어오는 쪽이 consume인가 payoff인가 (소비면 상태가 사라진다)
    evidence_in: str
    evidence_out: str


@dataclass(frozen=True)
class MechanismChain:
    axes: tuple[str, ...]
    # 마디마다 **쓸 수 있는 담체 전부**. 같은 축 경로를 담체 수만큼 복제하면
    # 출력이 중복으로 뒤덮인다(실측 2026-08-20: 사슬 200건 중 대부분이 같은 경로).
    transitions: tuple[Transition, ...]  # 마디당 대표 1개
    hop_options: tuple[tuple[str, ...], ...] = ()  # 마디당 담체 이름 전량
    # 사슬 끝 축의 페이오프 수 — 「여기까지 오면 무엇을 먹나」
    terminal_payoffs: int = 0
    # 사슬 안에서 같은 상태를 두 번 소비하려 드는지 등 발견된 문제
    warnings: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class ChainTrace:
    transitions: tuple[Transition, ...]
    chains: tuple[MechanismChain, ...]
    truncated: bool = False


def find_transitions(scan: StateScan) -> tuple[Transition, ...]:
    """한 담체가 A를 먹고(consume/payoff) B를 만들면(produce) A→B 전이다."""
    ins: dict[str, list[StateEdge]] = defaultdict(list)
    outs: dict[str, list[StateEdge]] = defaultdict(list)
    for edge in scan.edges:
        if edge.kind == "produce":
            outs[edge.carrier_id].append(edge)
        else:
            ins[edge.carrier_id].append(edge)
    transitions: list[Transition] = []
    for carrier_id, in_edges in ins.items():
        for in_edge in in_edges:
            for out_edge in outs.get(carrier_id, ()):
                if in_edge.axis == out_edge.axis:
                    continue  # 자기 자신을 먹고 만드는 것은 전이가 아니다(재생)
                transitions.append(
                    Transition(
                        from_axis=in_edge.axis,
                        to_axis=out_edge.axis,
                        carrier_id=carrier_id,
                        carrier_name=in_edge.carrier_name,
                        carrier_type=in_edge.carrier_type,
                        in_kind=in_edge.kind,
                        evidence_in=in_edge.evidence,
                        evidence_out=out_edge.evidence,
                    )
                )
    return tuple(transitions)


def trace_mechanism_chains(
    store: Store,
    from_axis: str | None = None,
    depth: int = 4,
    max_chains: int = 60,
) -> ChainTrace:
    """상태 전이를 이어 다단 사슬을 편다.

    `from_axis`를 주면 그 축에서 출발하는 사슬만, 생략하면 전이가 있는 모든 축에서
    출발한다. 사슬 끝 축의 페이오프 수를 함께 내 「어디까지 가면 보상이 있나」를
    보인다 — 어느 사슬이 좋은지는 답하지 않는다(AD-3).
    """
    scan = scan_state_edges(store)
    transitions = find_transitions(scan)
    payoffs = {a.axis: a.payoffs for a in scan.axes}
    # 같은 (A→B)를 여러 담체가 하면 **한 마디에 선택지가 여럿**인 것이지 사슬이
    # 여럿인 게 아니다. 축 쌍으로 묶어 대표 1개 + 담체 목록을 들고 다닌다.
    by_pair: dict[tuple[str, str], list[Transition]] = defaultdict(list)
    for transition in transitions:
        by_pair[(transition.from_axis, transition.to_axis)].append(transition)
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for pair in by_pair:
        adjacency[pair[0]].append(pair)

    chains: list[MechanismChain] = []
    truncated = False

    def walk(axes: tuple[str, ...], path: tuple[tuple[str, str], ...]) -> None:
        nonlocal truncated
        if len(chains) >= max_chains:
            truncated = True
            return
        if path:
            hops = [by_pair[p] for p in path]
            consumed = [h[0].from_axis for h in hops if any(t.in_kind == "consume" for t in h)]
            chains.append(
                MechanismChain(
                    axes=axes,
                    transitions=tuple(h[0] for h in hops),
                    hop_options=tuple(tuple(sorted({t.carrier_name for t in h})) for h in hops),
                    terminal_payoffs=payoffs.get(axes[-1], 0),
                    warnings=tuple(
                        f"같은 상태를 두 번 소비한다: {axis}"
                        for axis in {a for a in consumed if consumed.count(a) > 1}
                    ),
                )
            )
        if len(axes) > depth:
            return
        for pair in sorted(adjacency.get(axes[-1], ()), key=lambda p: p[1]):
            if pair[1] in axes:
                continue  # 순환은 사슬로 펴지 않는다(무한 확장 방지)
            walk((*axes, pair[1]), (*path, pair))

    starts = [from_axis] if from_axis else sorted({t.from_axis for t in transitions})
    for start in starts:
        walk((start,), ())
    return ChainTrace(transitions=transitions, chains=tuple(chains), truncated=truncated)
