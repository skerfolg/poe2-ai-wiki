"""3층 교차 순회 — 스탯·상태·객체를 **한 사슬로** 잇는다 (#95).

세 그래프가 각각은 잘 도는데 **경계에서 끊겼다**:

    #91 `supply.py`     스탯 → 스탯 (비례 공급)          예: 힘 → 생명
    #92 `mechanism.py`  상태 → 상태 (생산/소비)          예: 동결 → 주입
    #95 (같은 모듈)      객체 → 객체 (대상·조건)          예: 구형 번개 → 잔류물

실측 2026-08-21: 두 축 어휘가 28종 vs 32종인데 **공유가 2종뿐**(`combo`·`rage`)이라
「생명을 쌓으면 → 어떤 상태가 열리고 → 그 페이오프는?」 같은 질문에 답할 수 없었다.
이름 드리프트도 있었다(`curse_count`↔`curse`, `minion_count`↔`minion`) — 어휘를
통일한 뒤 이 모듈이 **두 전이 목록을 합쳐** 순회한다.

## 새 그래프를 만들지 않는다

여기는 **조인(join)** 계층이다. 엣지는 각 그래프가 이미 낸 것을 그대로 쓰고, 층
꼬리표(`layer`)만 붙인다 — 판정 로직을 복제하면 두 곳이 어긋난다.

## 층마다 전이의 뜻이 다르다 (합치되 뭉개지 않는다)

  · `supply`  — A가 늘면 B가 **비례해서** 는다(담체가 그 변환을 제공)
  · `state`   — 한 담체가 A를 **먹고** B를 만든다(A는 소모될 수 있다)

사슬을 읽는 사람이 이 차이를 알아야 하므로 마디마다 `layer`를 싣는다. 판단은 하지
않는다(AD-3) — 어느 사슬이 좋은지는 호출자 몫이다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pok.kb.graph.mechanism import find_transitions, scan_state_edges
from pok.kb.graph.supply import scan_supply_edges
from pok.kb.store import Store


@dataclass(frozen=True)
class CrossEdge:
    """층을 가리지 않는 전이 1건 — 어느 그래프에서 왔는지(`layer`)를 달고 다닌다."""

    from_axis: str
    to_axis: str
    layer: str  # "supply"(스탯 비례) | "state"(상태·객체 생산/소비)
    carrier_id: str
    carrier_name: str
    evidence: str
    # 상태 층에서만: 들어오는 쪽이 소비인가(그러면 그 상태는 사라진다)
    consumes_input: bool = False


@dataclass(frozen=True)
class CrossChain:
    axes: tuple[str, ...]
    layers: tuple[str, ...]  # 마디별 층 — 층이 바뀌는 지점이 곧 교차점이다
    hops: tuple[CrossEdge, ...]  # 마디당 대표 1개
    hop_options: tuple[tuple[str, ...], ...]  # 마디당 담체 이름 전량
    terminal_payoffs: int  # 사슬 끝 축의 페이오프 수 (두 그래프 합산)
    crosses_layers: bool  # 층을 실제로 넘나드는가 — 이 모듈의 존재 이유


@dataclass(frozen=True)
class CrossTrace:
    chains: tuple[CrossChain, ...]
    edge_count: int
    shared_axes: tuple[str, ...]  # 두 층이 함께 쓰는 축 — 교차가 일어나는 자리
    truncated: bool = False


def cross_edges(store: Store) -> tuple[tuple[CrossEdge, ...], dict[str, int], tuple[str, ...]]:
    """두 그래프의 전이를 합친다. 반환: (엣지, 축별 페이오프 수, 공유 축)."""
    supply = scan_supply_edges(store)
    state = scan_state_edges(store)
    edges: list[CrossEdge] = []
    payoffs: dict[str, int] = defaultdict(int)

    for edge in supply.edges:
        if edge.kind == "supply" and edge.target_axis and edge.scope == "global":
            edges.append(
                CrossEdge(
                    from_axis=edge.source_axis,
                    to_axis=edge.target_axis,
                    layer="supply",
                    carrier_id=edge.carrier_id,
                    carrier_name=edge.carrier_name,
                    evidence=edge.evidence,
                )
            )
        elif edge.kind == "payoff":
            payoffs[edge.source_axis] += 1
    for transition in find_transitions(state):
        edges.append(
            CrossEdge(
                from_axis=transition.from_axis,
                to_axis=transition.to_axis,
                layer="state",
                carrier_id=transition.carrier_id,
                carrier_name=transition.carrier_name,
                evidence=transition.evidence_in,
                consumes_input=transition.in_kind == "consume",
            )
        )
    for summary in state.axes:
        payoffs[summary.axis] += summary.payoffs

    supply_axes = {a.axis for a in supply.axes}
    state_axes = {a.axis for a in state.axes}
    return tuple(edges), dict(payoffs), tuple(sorted(supply_axes & state_axes))


def trace_cross_chains(
    store: Store,
    from_axis: str | None = None,
    depth: int = 4,
    max_chains: int = 60,
    cross_only: bool = False,
) -> CrossTrace:
    """층을 넘나드는 사슬을 편다.

    `cross_only=True`면 **층이 바뀌는 사슬만** 낸다 — 한 층 안의 사슬은 이미
    `trace_chains`·`trace_mechanism_chains`가 내므로, 이 모듈의 고유 산출만 보고
    싶을 때 쓴다.
    """
    edges, payoffs, shared = cross_edges(store)
    by_pair: dict[tuple[str, str], list[CrossEdge]] = defaultdict(list)
    for edge in edges:
        by_pair[(edge.from_axis, edge.to_axis)].append(edge)
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for pair in by_pair:
        adjacency[pair[0]].append(pair)

    chains: list[CrossChain] = []
    truncated = False

    def walk(axes: tuple[str, ...], path: tuple[tuple[str, str], ...]) -> None:
        nonlocal truncated
        if len(chains) >= max_chains:
            truncated = True
            return
        if path:
            hops = [by_pair[p] for p in path]
            layers = tuple(h[0].layer for h in hops)
            crosses = len(set(layers)) > 1
            if not cross_only or crosses:
                chains.append(
                    CrossChain(
                        axes=axes,
                        layers=layers,
                        hops=tuple(h[0] for h in hops),
                        hop_options=tuple(tuple(sorted({e.carrier_name for e in h})) for h in hops),
                        terminal_payoffs=payoffs.get(axes[-1], 0),
                        crosses_layers=crosses,
                    )
                )
        if len(axes) > depth:
            return
        for pair in sorted(adjacency.get(axes[-1], ()), key=lambda p: p[1]):
            if pair[1] in axes:
                continue  # 순환은 펴지 않는다(무한 확장 방지)
            walk((*axes, pair[1]), (*path, pair))

    starts = [from_axis] if from_axis else sorted({e.from_axis for e in edges})
    for start in starts:
        walk((start,), ())
    return CrossTrace(
        chains=tuple(chains),
        edge_count=len(edges),
        shared_axes=shared,
        truncated=truncated,
    )
