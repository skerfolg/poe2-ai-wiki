"""「전부 찍고 소거」 — 초과 배치한 트리를 예산까지 깎는다.

`optimize_tree`의 그리디 **덧셈**이 못 여는 구성이 있다(곱연산 축·먼 뭉치). 그럴 때
사람은 「관련 노드를 전부 찍고 소거법으로 지운다」로 접근하는데, 그 방식은 실측
2026-08-18에 **1승 3패**였다. 진 세 번의 원인이 전부 같아서 여기에 안전장치로 넣는다.

**① 여유분(slack)을 먼저 잰다.** 깎아야 할 양이 여유분을 크게 넘으면 소거는 구조를
   판다 — 실측: 23을 깎을 때(여유 17, 1.4배) 1.203배로 이겼고, 74를 깎을 때(4.4배)
   0.72배·0.41배로 졌다. **한 시간 쓰기 전에 알 수 있는 수치다.**

**② 묶음을 보호한다.** 상호작용하는 노드 집합은 개별 기여로 재면 **항상** 과소평가된다
   — 반경 주얼(「반경 내 노터블이 …도 부여」)의 반경 노터블은 각각 4%로 보이지만 15개가
   모여 60%다. 개별 점수로 깎으면 그것부터 헐린다.

**③ 안 재는 축은 조용히 팔린다.** 손실 함수에 EHP를 안 넣었더니 방어 소형 9개가
   「손실 0」으로 판정돼 EHP가 22% 빠졌다. 그래서 **가중치와 무관하게 전 축을 보고한다.**

⛔ 무엇을 지킬지·얼마를 깎을지는 판정하지 않는다(철칙 3). 재고 알린다.
"""

from __future__ import annotations

import collections
import dataclasses
from collections.abc import Callable, Sequence
from typing import Any

from pok.engine.tree.graph import TreeGraph

# 가중치에 없어도 **항상** 보고하는 축 — 조용히 팔리는 것을 막는다.
REPORTED_AXES: tuple[str, ...] = ("CombinedDPS", "Life", "TotalEHP", "Str", "Int", "Dex")


@dataclasses.dataclass(frozen=True)
class NodeCost:
    node_id: int
    name: str
    deltas: dict[str, float]  # 축 → 상대 변화(제거했을 때). 0에 가까울수록 자유석

    @property
    def loss(self) -> float:
        """가중 손실 — 작을수록 먼저 뺀다."""
        return -sum(self.deltas.values())


@dataclasses.dataclass(frozen=True)
class SlackReport:
    """이 트리가 **잃어도 되는 양**. 소거법의 성립 여부를 미리 알려 준다."""

    removable: int  # 연결을 끊지 않고 뺄 수 있는 노드 수
    free: int  # 그중 손실 ~0 (자유석)
    costs: tuple[NodeCost, ...]  # 손실이 작은 순
    need: int = 0  # 예산까지 깎아야 할 양

    @property
    def ratio(self) -> float:
        return float("inf") if self.free == 0 else self.need / self.free

    @property
    def verdict(self) -> str:
        if self.need <= 0:
            return "예산 안 — 깎을 것이 없다"
        if self.need <= self.free:
            return "여유분 안에서 해결된다"
        if self.ratio <= 1.5:
            return "여유분을 조금 넘는다 — 마지막 몇 개는 값을 치른다"
        return (
            f"⚠ 여유분의 {self.ratio:.1f}배를 깎아야 한다 — 소거는 **구조를 판다**. "
            "실측 2026-08-18: 1.4배는 이겼고(1.203x) 4.4배는 졌다(0.72x·0.41x). "
            "초과 배치를 줄이거나, 애초에 다른 구성을 고를 것"
        )


def removable_nodes(
    graph: TreeGraph,
    allocated: set[int],
    start: int,
    *,
    protect: set[int],
    floating: set[int],
) -> list[int]:
    """빼도 나머지가 시작점과 이어지는 노드들. `floating`은 주얼이 연결 없이 띄운 것."""

    def reach(keep: set[int]) -> set[int]:
        seen = {start}
        queue = collections.deque([start])
        while queue:
            cur = queue.popleft()
            for nb in graph.adj[cur]:
                if nb in keep and nb not in seen:
                    seen.add(nb)
                    queue.append(nb)
        return seen

    asc = {n for n in allocated if (nd := graph.nodes.get(n)) is not None and nd.ascendancy}
    out = []
    for n in allocated - protect - asc:
        keep = allocated - {n}
        if ((keep - asc) - floating) <= reach(keep):
            out.append(n)
    return out


def radius_bundles(graph: TreeGraph, jewels: Sequence[dict[str, Any]]) -> set[int]:
    """반경 주얼이 값을 매기는 노드 집합 — **통째로 지킨다**(②).

    「in Radius」를 말하는 주얼은 반경 안 노터블 **수**로 값이 정해진다. 개별로 재면
    각각이 작아 먼저 쓸려나가고, 그 순간 묶음 전체가 사라진다.
    """
    import math

    guarded: set[int] = set()
    for jewel in jewels:
        text = str(jewel.get("text") or "")
        if "in Radius" not in text and "in radius" not in text:
            continue
        socket = jewel.get("socket_node_id")
        node = graph.nodes.get(int(socket)) if socket is not None else None
        if node is None or node.position is None:
            continue
        # 반경 표기가 없으면 가장 좁은 것으로 잡는다 — 넓게 잡아 과보호하는 쪽이
        # 묶음을 헐어 측정을 망치는 것보다 낫다(과보호는 예산 초과로 드러난다).
        radius = 1200.0
        for label, value in (("Very Large", 1800.0), ("Large", 1560.0), ("Medium", 1380.0)):
            if label in text:
                radius = value
        cx, cy = node.position
        for other in graph.nodes.values():
            if other.kind != "notable" or other.ascendancy or other.position is None:
                continue
            if math.hypot(other.position[0] - cx, other.position[1] - cy) <= radius:
                guarded.add(other.node_id)
    return guarded


def measure_slack(
    graph: TreeGraph,
    allocated: set[int],
    start: int,
    measure: Callable[[set[int]], dict[str, float]],
    *,
    protect: set[int],
    floating: set[int],
    need: int = 0,
    weights: dict[str, float] | None = None,
) -> SlackReport:
    """노드마다 단독 제거 비용을 재서 여유분을 낸다 (①·③).

    `measure`는 노드 집합 → 축별 실측치. `weights`가 없으면 `REPORTED_AXES`를 균등하게
    본다 — **가중치에 없는 축도 항상 보고한다**(③).
    """
    base = measure(allocated)
    axes = list(weights or {k: 1.0 for k in REPORTED_AXES if k in base})
    cands = removable_nodes(graph, allocated, start, protect=protect, floating=floating)
    costs: list[NodeCost] = []
    for n in cands:
        after = measure(allocated - {n})
        deltas = {
            k: ((after.get(k, 0.0) - base[k]) / base[k] if base.get(k) else 0.0)
            for k in set(axes) | set(REPORTED_AXES) & set(base)
        }
        node = graph.nodes.get(n)
        costs.append(NodeCost(n, node.name_ko if node else "?", deltas))
    costs.sort(key=lambda c: c.loss)
    free = sum(1 for c in costs if all(v >= -1e-9 for v in c.deltas.values()))
    return SlackReport(removable=len(cands), free=free, costs=tuple(costs), need=need)
