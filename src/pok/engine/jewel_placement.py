"""트리 최적화 **뒤** 주얼을 되돌려 놓는다 (사용자 지시 2026-08-18).

## 왜 필요한가

트리를 다시 짜면 **소켓 구성이 달라진다** — 원래 주얼이 앉아 있던 소켓이 사라질 수
있다. 지금까지는 최적화 전에 주얼을 떼어(`jewel_templates`로 가정 탐침만 넘기고)
끝나면 그대로 버렸다. 그러면 산출물이 **주얼 없는 빌드**가 된다.

절차: 최적화 전에 스냅샷 → 최적화 → 남은 소켓에 되배치.

## 배치 우선순위 (사용자 지시)

1. **고유 주얼 먼저** — 빌드의 필수 기재일 확률이 높다. 소켓이 모자라면 고유가
   자리를 갖는다.
2. **반경 주얼(오래된 기억류)은 밀집도로** — 반경 안 노드에 옵션을 부여하므로
   **어디 앉느냐가 곧 값**이다. 할당 노드가 촘촘한 소켓에 넣는다.
3. **레어는 빌드 파워로** — 실측(PoB 델타)으로 정한다. 규칙으로 정하지 않는다.

⛔ **반경을 추측하지 않는다**(`engine.jewels`와 같은 원칙). 반경 선언이 없는 반경
주얼은 어느 소켓에서든 델타 0이므로, 밀집도로 자리를 골라도 값이 안 난다 —
그 사실을 사유로 낸다.
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from pok.engine.jewels import declared_radius, needs_radius_declaration
from pok.engine.tree.clusters import JEWEL_RADII
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, JewelSpec

_UNIQUE = "rarity: unique"
_RADIUS_GRANT = "passive skills in radius"


@dataclass(frozen=True)
class Placement:
    """주얼 하나의 배치 결과 — **왜 거기인지**가 함께 남는다."""

    text: str
    socket_node_id: int | None  # None = 자리를 못 찾음
    kind: str  # unique | radius | rare
    why: str


def _kind(text: str) -> str:
    low = text.lower()
    if _RADIUS_GRANT in low:
        return "radius"
    if _UNIQUE in low:
        return "unique"
    return "rare"


def _radius_of(text: str) -> float:
    """선언된 반경 라벨 → 실효 반경. 선언이 없으면 0(= 아무 노드도 안 걸린다)."""
    label = (declared_radius(text) or "").strip().lower()
    for name, _inner, outer in JEWEL_RADII:
        if name.lower() == label:
            return float(outer)
    return 0.0


def density(graph: TreeGraph, socket: int, allocated: set[int], radius: float) -> int:
    """소켓 반경 안에 **할당된** 노드가 몇 개인가 — 반경 주얼의 값은 여기서 난다."""
    here = graph.nodes.get(socket)
    if here is None or here.position is None or radius <= 0:
        return 0
    cx, cy = here.position
    hits = 0
    for nid in allocated:
        node = graph.nodes.get(nid)
        if node is None or node.position is None or nid == socket:
            continue
        if math.dist((cx, cy), node.position) <= radius:
            hits += 1
    return hits


def open_sockets(graph: TreeGraph, spec: BuildSpec) -> list[int]:
    """할당된 주얼 소켓 중 **비어 있는** 것.

    ⚠ 할당 안 된 소켓은 세지 않는다 — 거기 꽂은 주얼은 인게임에서 효과가 없고,
    조립도 거부한다(`pob/restore.py`의 orphan 소켓 주석과 같은 사유).
    """
    used = {j.socket_node_id for j in spec.jewels}
    return sorted(
        nid
        for nid in spec.tree_nodes
        if nid not in used
        and (node := graph.nodes.get(nid)) is not None
        and node.kind == "jewel-socket"
    )


def place(
    graph: TreeGraph,
    spec: BuildSpec,
    snapshot: tuple[str, ...],
) -> tuple[BuildSpec, list[Placement], list[str]]:
    """스냅샷해 둔 주얼을 새 트리의 빈 소켓에 되배치한다.

    `snapshot`은 최적화 **전에** 떼어 둔 주얼 텍스트들이다. 반환은
    (주얼이 실린 스펙, 배치 내역, 사유 메모).

    ⚠ 레어의 「빌드 파워로 결정」은 **여기서 하지 않는다** — PoB 실측이 필요하고,
    그건 판단이 아니라 측정이라 호출자가 데몬을 들고 돌려야 한다(AD-8·철칙 3).
    이 함수는 고유·반경까지만 결정적으로 놓고, 레어는 남은 자리에 넣은 뒤
    **재배치 후보를 사유로 낸다**.
    """
    allocated = set(spec.tree_nodes)
    free = open_sockets(graph, spec)
    notes: list[str] = []
    out: list[Placement] = []

    # 1) 고유 먼저 — 소켓이 모자라면 고유가 자리를 갖는다(빌드 필수 기재일 확률)
    #    2) 반경 주얼은 밀집도로 3) 레어는 남은 자리
    order = {"unique": 0, "radius": 1, "rare": 2}
    ranked = sorted(snapshot, key=lambda t: order[_kind(t)])

    for text in ranked:
        kind = _kind(text)
        if not free:
            out.append(Placement(text, None, kind, "빈 소켓이 없다 — 트리에 자리가 줄었다"))
            continue
        if kind == "radius":
            radius = _radius_of(text)
            if radius <= 0:
                # 선언이 없으면 어느 소켓이든 델타 0이다 — 자리를 고를 근거 자체가 없다
                socket = free.pop(0)
                out.append(
                    Placement(
                        text,
                        socket,
                        kind,
                        "⚠ `Radius:` 선언이 없어 **어느 소켓에서도 0**이다 — 밀집도로 "
                        "고를 근거가 없어 남은 자리에 넣었다(engine.jewels 참조)",
                    )
                )
                continue
            best = max(free, key=lambda s: density(graph, s, allocated, radius))
            free.remove(best)
            hits = density(graph, best, allocated, radius)
            out.append(
                Placement(text, best, kind, f"반경 안 할당 노드 {hits}개로 가장 촘촘한 소켓")
            )
        else:
            socket = free.pop(0)
            why = (
                "고유 — 빌드 필수 기재일 확률이 높아 우선 배치"
                if kind == "unique"
                else "레어 — 남은 자리. **빌드 파워로 재배치할 후보**(PoB 실측 필요)"
            )
            out.append(Placement(text, socket, kind, why))

    placed = tuple(
        JewelSpec(socket_node_id=p.socket_node_id, text=p.text)
        for p in out
        if p.socket_node_id is not None
    )
    dropped = [p for p in out if p.socket_node_id is None]
    if dropped:
        notes.append(
            f"⚠ 주얼 {len(dropped)}개를 **못 놓았다** — 새 트리의 빈 소켓이 모자란다. "
            "소켓을 늘리거나 어느 주얼을 버릴지는 판단이다"
        )
    unradius = [p for p in out if p.kind == "radius" and needs_radius_declaration(p.text)]
    if unradius:
        notes.append(f"⚠ 반경 주얼 {len(unradius)}개에 `Radius:` 선언이 없다 — 조용히 0으로 잰다")
    return dataclasses.replace(spec, jewels=placed), out, notes
