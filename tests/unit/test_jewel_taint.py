"""집계 오염 판정 계약 (사용자 판정 2026-08-18).

1층은 주얼을 꽂은 채 쟀으므로 **빌드별로는 옳다**. 여기서 막는 것은 2층 —
같은 node_id로 묶을 때 「노드의 값」과 「주얼이 만든 값」이 한 칸에 들어가는 것.
"""

from __future__ import annotations

from pok.common.paths import knowledge_dir
from pok.engine.jewel_taint import classify
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, JewelSpec

_graph = TreeGraph(knowledge_dir())

_TIMELESS = (
    "Rarity: UNIQUE\nUndying Hate\nTimeless Jewel\nRadius: Very Large\n"
    "Passives in radius are Conquered by the Abyssals"
)
_GRANT = (
    "Rarity: UNIQUE\nAgainst the Darkness\nTime-Lost Diamond\nRadius: Very Large\n"
    "Notable Passive Skills in Radius also grant Gain 5% of Damage as Extra Fire Damage"
)
_GRANT_NO_RADIUS = (
    "Rarity: UNIQUE\nAgainst the Darkness\nTime-Lost Diamond\n"
    "Notable Passive Skills in Radius also grant Gain 5% of Damage as Extra Fire Damage"
)
_NOCONN = (
    "Rarity: UNIQUE\nFrom Nothing\nDiamond\nRadius: Small\n"
    "Passives in Radius can be Allocated without being connected to your tree"
)
_PLAIN = "Rarity: RARE\n평범\nRuby\n+10 to Strength"


def _socket_with_neighbours(min_near: int) -> tuple[int, list[int]]:
    """반경 안에 할당 노드가 충분히 있는 소켓 하나."""
    import math

    for nid, node in sorted(_graph.nodes.items()):
        if node.kind != "jewel-socket" or node.position is None:
            continue
        cx, cy = node.position
        near = [
            other
            for other, n2 in _graph.nodes.items()
            if n2.position is not None
            and other != nid
            and math.dist((cx, cy), n2.position) <= 1800.0
        ]
        if len(near) >= min_near:
            return nid, near[:min_near]
    raise AssertionError("반경 안에 노드가 충분한 소켓이 없다 — 트리 수집을 의심할 것")


def _spec(jewels: tuple[JewelSpec, ...], nodes: list[int]) -> BuildSpec:
    return BuildSpec(
        class_name="Witch", ascendancy="Witch1", tree_nodes=tuple(nodes), jewels=jewels
    )


def test_타임리스도_반경_안만_뺀다() -> None:
    """⚠ 처음엔 빌드째 뺐다가 좁혔다(사용자 승인 2026-08-18).

    실측: 타임리스 298벌의 관측 7,296행 중 **반경 안은 387행(5.3%)**뿐이라 나머지
    94.7%를 근거 없이 버리고 있었다. 타임리스가 바꾸는 것은 반경 안 패시브이지
    그 빌드의 다른 노드가 아니다.
    """
    socket, near = _socket_with_neighbours(5)
    spec = _spec((JewelSpec(socket_node_id=socket, text=_TIMELESS),), [socket, *near])
    got = classify(spec, _graph)
    assert got.timeless == ("Undying Hate",), "보고는 남는다"
    assert got.usable, "빌드째 버리면 94.7%를 근거 없이 버린다"
    assert got.tainted_nodes, "반경 안 노드는 빼야 한다"


def test_반경을_못_읽은_타임리스는_빌드째_뺀다() -> None:
    """⚠ **fail-closed.** 오염이 어디까지인지 모르면서 「깨끗한 부분만 썼다」고 하면
    그게 거짓말이 된다. 모를 때만 빌드째 뺀다."""
    socket, near = _socket_with_neighbours(5)
    blind = _TIMELESS.replace("Radius: Very Large\n", "")
    spec = _spec((JewelSpec(socket_node_id=socket, text=blind),), [socket, *near])
    got = classify(spec, _graph)
    assert not got.usable and got.unresolved == ("Undying Hate",)
    assert got.tainted_nodes == frozenset(), "모르면서 짚으면 안 된다"


def test_반경_부여는_그_노드만_뺀다() -> None:
    """옵션을 **얹는다** — 얹힌 노드만 제 값이 아니다."""
    socket, near = _socket_with_neighbours(5)
    spec = _spec((JewelSpec(socket_node_id=socket, text=_GRANT),), [socket, *near])
    got = classify(spec, _graph)
    assert got.usable, "빌드까지 버리면 안 된다"
    assert got.tainted_nodes, "반경 안 노드를 못 짚었다"
    assert all(got.reasons[n] == "Against the Darkness" for n in got.tainted_nodes)


def test_연결_불요는_오염이_아니다() -> None:
    """⛔ 옵션을 안 얹고 **길 제약만** 푼다 — 노드는 제 값 그대로다.
    이걸 오염으로 세면 코퍼스의 48.8%를 근거 없이 버린다(별개 문제는 #83)."""
    socket, near = _socket_with_neighbours(5)
    spec = _spec((JewelSpec(socket_node_id=socket, text=_NOCONN),), [socket, *near])
    got = classify(spec, _graph)
    assert got.tainted_nodes == frozenset()
    assert got.usable and got.trustworthy


def test_평범한_주얼은_아무것도_안_한다() -> None:
    socket, near = _socket_with_neighbours(3)
    spec = _spec((JewelSpec(socket_node_id=socket, text=_PLAIN),), [socket, *near])
    got = classify(spec, _graph)
    assert got.tainted_nodes == frozenset() and got.usable and got.trustworthy


def test_반경을_못_읽으면_그렇다고_말한다() -> None:
    """⛔ 조용히 「오염 없음」으로 넘기면 오염된 노드가 깨끗한 얼굴로 정본에 들어간다."""
    socket, near = _socket_with_neighbours(5)
    spec = _spec((JewelSpec(socket_node_id=socket, text=_GRANT_NO_RADIUS),), [socket, *near])
    got = classify(spec, _graph)
    assert got.unresolved == ("Against the Darkness",)
    assert not got.trustworthy, "판정을 못 믿는데 믿을 수 있다고 한다"
    assert got.tainted_nodes == frozenset(), "모르면서 짚으면 안 된다"


def test_안_찍은_소켓의_주얼은_안_센다() -> None:
    """인게임에서 효과가 없고 PoB 조립도 거부한다 — 세면 오염을 **지어내는** 것이다."""
    socket, near = _socket_with_neighbours(5)
    spec = _spec((JewelSpec(socket_node_id=socket, text=_GRANT),), near)  # socket 미할당
    assert classify(spec, _graph).tainted_nodes == frozenset()
