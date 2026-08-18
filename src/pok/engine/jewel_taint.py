"""어느 노드가 **주얼 때문에** 제 값이 아닌가 (사용자 판정 2026-08-18).

## 왜 필요한가

반사실 관측(1층)은 주얼을 꽂은 채 쟀다 — **빌드별로는 옳다.** 문제는 **집계**(2층)다.
같은 `node_id`로 묶어 「이 노드의 값」을 내려는데, 어떤 빌드에서는 그 노드가 주얼 때문에
다른 것이 되어 있다. 섞으면 노드의 값이 아니라 **주얼의 값**이 정본에 들어간다.

## 두 종류를 가른다 (사용자 구분)

- **타임리스(무궁)** — 반경 안 패시브를 *다른 것으로 바꾼다*. 옵션이 너무 크고 복잡해
  전용 서비스가 따로 있을 정도라 **변환표를 만들지 않는다** — 대신 **반경 안 노드를
  뺀다**. 코퍼스의 11.1%.
  ⚠ 처음엔 **빌드째** 뺐다가 좁혔다(사용자 승인 2026-08-18). 실측: 그 298벌의 관측
  7,296행 중 **반경 안은 387행(5.3%)**뿐이라 나머지 94.7%를 근거 없이 버리고 있었다.
  타임리스가 바꾸는 것은 반경 안 패시브이지 그 빌드의 다른 노드가 아니다.
- **반경 부여(오래된 기억류)** — 반경 안 노드에 옵션을 *얹는다*. 유저는 밀집 구역에서
  효과를 최대로 받으려 **빌드와 무관한 노드까지** 찍는다. 그 노드의 델타는 노드가 아니라
  주얼이 만든 값이므로 **그 노드만 뺀다**.

⛔ **연결 불요 주얼(From Nothing 등)은 오염이 아니다.** 옵션을 얹지 않고 *길 제약만*
푼다 — 노드는 제 값 그대로다. 그쪽은 후보 열거가 깨지는 별개 문제다(BACKLOG #87).

## 모르는 것은 모른다고 한다

반경을 못 읽은 부여 주얼은 `unresolved`로 낸다. 조용히 「오염 없음」으로 넘기면 오염된
노드가 깨끗한 얼굴로 정본에 들어간다 — 이 모듈이 막으려는 바로 그 일이다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from pok.engine.jewels import effective_radius, is_timeless
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, JewelSpec

# 「반경 안 노드에 옵션을 얹는다」 꼴 — 이게 있어야 값이 오염된다
_GRANTS = re.compile(r"Passive Skills in Radius\b.*\balso grant\b", re.I | re.S)


@dataclass(frozen=True)
class JewelTaint:
    """이 빌드의 관측을 집계에 넣어도 되는가."""

    timeless: tuple[str, ...]  # 이 빌드가 든 타임리스 주얼 (보고용 — 배제 기준 아님)
    tainted_nodes: frozenset[int]  # 값이 제 것이 아닌 할당 노드 (타임리스 + 반경 부여)
    reasons: dict[int, str]  # node_id → 어느 주얼 때문인가
    unresolved: tuple[str, ...]  # 반경을 못 읽은 주얼 — **조용한 0 금지**

    @property
    def usable(self) -> bool:
        """빌드 전체를 쓸 수 있나.

        ⚠ **fail-closed.** 반경을 못 읽은 주얼이 있으면 오염이 어디까지인지 모른다 —
        모르면서 「깨끗한 부분만 썼다」고 하면 그게 거짓말이 된다. 그때만 빌드째 뺀다.
        (실측 2026-08-18: 코퍼스에서 이 경우는 **0건**이다 — #71의 링 해석기 덕이다.)
        """
        return not self.unresolved

    @property
    def trustworthy(self) -> bool:
        """오염 판정을 믿을 수 있나 — `usable`과 같은 조건이다(이름만 다르다)."""
        return not self.unresolved


def _name(jewel: JewelSpec) -> str:
    lines = (jewel.text or "").splitlines()
    return lines[1] if len(lines) > 1 else "?"


def _in_ring(
    graph: TreeGraph, socket: int, nodes: frozenset[int], ring: tuple[float, float]
) -> set[int]:
    inner, outer = ring
    here = graph.nodes.get(socket)
    if here is None or here.position is None or outer <= 0:
        return set()
    cx, cy = here.position
    out = set()
    for nid in nodes:
        node = graph.nodes.get(nid)
        if node is None or node.position is None or nid == socket:
            continue
        if inner <= math.dist((cx, cy), node.position) <= outer:
            out.add(nid)
    return out


def classify(spec: BuildSpec, graph: TreeGraph) -> JewelTaint:
    """이 빌드의 주얼이 집계를 얼마나 오염시키나.

    ⚠ 소켓이 **할당돼 있을 때만** 센다 — 안 찍힌 소켓의 주얼은 인게임에서 효과가 없고
    PoB 조립도 거부한다. 세면 오염을 지어내는 것이 된다.
    """
    allocated = frozenset(spec.tree_nodes)
    timeless: list[str] = []
    tainted: set[int] = set()
    reasons: dict[int, str] = {}
    unresolved: list[str] = []

    for jewel in spec.jewels:
        text = jewel.text or ""
        if not text:
            continue
        conquers = is_timeless(text)
        if conquers:
            timeless.append(_name(jewel))
        elif not _GRANTS.search(text):
            continue  # 연결 불요·일반 옵션 주얼은 노드 값을 안 바꾼다
        if jewel.socket_node_id not in allocated:
            continue
        ring = effective_radius(text)
        if ring is None:
            unresolved.append(_name(jewel))
            continue
        hit = _in_ring(graph, jewel.socket_node_id or -1, allocated, ring)
        for nid in hit:
            reasons.setdefault(nid, _name(jewel))
        tainted |= hit

    return JewelTaint(
        timeless=tuple(timeless),
        tainted_nodes=frozenset(tainted),
        reasons=reasons,
        unresolved=tuple(unresolved),
    )
