"""주얼 되배치 계약 (사용자 지시 2026-08-18).

트리를 다시 짜면 소켓 구성이 달라진다. 스냅샷해 둔 주얼을 되돌려 놓되, **자리가
모자랄 때 무엇을 살리는가**가 규율이다 — 고유가 먼저다(빌드 필수 기재일 확률).
반경 주얼은 어디 앉느냐가 곧 값이라 밀집도로 고른다.
"""

from __future__ import annotations

from pok.common.paths import knowledge_dir
from pok.engine.jewel_placement import Placement, open_sockets, place_jewels
from pok.engine.jewels import is_timeless
from pok.engine.tree.graph import TreeGraph
from pok.engine.tree.optimize import _restore_jewels, _timeless_notes
from pok.pob.buildxml import BuildSpec, JewelSpec

_graph = TreeGraph(knowledge_dir())

_UNIQUE = "Rarity: UNIQUE\nMageblood Jewel\nEmerald\nGrants Something"
_RARE = "Rarity: RARE\nFoo Bar\nRuby\n+10 to Strength"
_RADIUS = (
    "Rarity: RARE\nTime-Lost Diamond\nDiamond\nRadius: Large\n"
    "Notable Passive Skills in Radius also grant 10% increased Critical Hit Chance"
)
_RADIUS_NO_DECL = (
    "Rarity: RARE\nTime-Lost Diamond\nDiamond\n"
    "Notable Passive Skills in Radius also grant 10% increased Critical Hit Chance"
)


def _sockets(n: int) -> list[int]:
    got = [nid for nid, node in _graph.nodes.items() if node.kind == "jewel-socket"]
    assert len(got) >= n, "트리에 주얼 소켓이 모자란다 — 표본 선택을 다시 할 것"
    return sorted(got)[:n]


def _spec(socket_ids: list[int], jewels: tuple[JewelSpec, ...] = ()) -> BuildSpec:
    return BuildSpec(
        class_name="Witch",
        ascendancy="Witch1",
        tree_nodes=tuple(socket_ids),
        jewels=jewels,
    )


def test_빈_소켓만_센다() -> None:
    """이미 주얼이 든 소켓에 또 넣으면 안 된다."""
    a, b = _sockets(2)
    spec = _spec([a, b], jewels=(JewelSpec(socket_node_id=a, text=_RARE),))
    assert open_sockets(_graph, spec) == [b]


def test_할당_안_된_소켓은_자리가_아니다() -> None:
    """할당 안 된 소켓의 주얼은 인게임에서 효과가 없고 조립도 거부한다."""
    a, b = _sockets(2)
    spec = _spec([a])  # b는 트리에 없다
    assert b not in open_sockets(_graph, spec)


def test_자리가_모자라면_고유가_먼저다() -> None:
    """소켓 1개에 주얼 2개 — 고유가 살아남아야 한다(빌드 필수 기재일 확률)."""
    (a,) = _sockets(1)
    spec = _spec([a])
    _placed, rows, notes = place_jewels(_graph, spec, (_RARE, _UNIQUE))
    got = {r.kind: r.socket_node_id for r in rows}
    assert got["unique"] == a, "고유가 자리를 못 얻었다"
    assert got["rare"] is None
    assert any("못 놓았다" in n for n in notes), "못 놓은 사실을 조용히 넘겼다"


def test_반경_주얼은_밀집도로_고른다() -> None:
    """반경 안 노드에 옵션을 부여하므로 **어디 앉느냐가 곧 값**이다."""
    sockets = _sockets(3)
    # 한 소켓 주변에만 할당 노드를 몰아 둔다
    dense = sockets[0]
    pos = _graph.nodes[dense].position
    assert pos is not None
    near = [
        nid
        for nid, node in _graph.nodes.items()
        if node.position is not None
        and nid not in sockets
        and abs(node.position[0] - pos[0]) < 400
        and abs(node.position[1] - pos[1]) < 400
    ][:20]
    spec = _spec(sockets + near)
    _placed, rows, _notes = place_jewels(_graph, spec, (_RADIUS,))
    (row,) = rows
    assert row.socket_node_id == dense, "밀집한 소켓을 안 골랐다"
    assert "촘촘한" in row.why


def test_반경_선언이_없으면_고르지_않고_사유를_낸다() -> None:
    """⛔ 선언이 없으면 어느 소켓에서도 0이다 — 밀집도로 고를 근거 자체가 없다.
    조용히 「최적 자리」인 척하면 그게 거짓말이 된다(engine.jewels와 같은 원칙)."""
    sockets = _sockets(3)
    spec = _spec(sockets)
    _placed, rows, notes = place_jewels(_graph, spec, (_RADIUS_NO_DECL,))
    (row,) = rows
    assert row.socket_node_id is not None
    assert "선언이 없어" in row.why
    assert any("Radius" in n for n in notes)


def test_배치_결과가_스펙에_실린다() -> None:
    a, b = _sockets(2)
    spec = _spec([a, b])
    placed, rows, _notes = place_jewels(_graph, spec, (_UNIQUE, _RARE))
    assert len(placed.jewels) == 2
    assert {j.socket_node_id for j in placed.jewels} == {a, b}
    assert all(isinstance(r, Placement) for r in rows)


def test_레어는_재배치_후보로_남는다() -> None:
    """레어의 자리는 **빌드 파워로** 정해야 한다(PoB 실측). 규칙으로 정하지 않고
    사유에 그 사실을 남긴다 — 안 남기면 임의 배치가 최적인 척한다."""
    a, b = _sockets(2)
    _placed, rows, _notes = place_jewels(_graph, _spec([a, b]), (_RARE,))
    (row,) = rows
    assert "빌드 파워" in row.why


# ── 최적화 흐름과의 접합 (`optimize_tree` 안에서 불린다) ──


def test_정품이_가정_탐침을_밀어낸다() -> None:
    """탐침은 소켓 **값을 재려고** 넣은 가짜다. 자리를 다투면 정품이 이기고,
    밀려난 탐침은 산출물에 남지 않는다 — 산출물은 설계지 탐침이 아니다."""
    (a,) = _sockets(1)
    probe = "Rarity: MAGIC\n탐침\nRuby\n+1 to Strength"
    spec = _spec([a], jewels=(JewelSpec(socket_node_id=a, text=probe),))
    placed, rows, notes = _restore_jewels(_graph, spec, (_UNIQUE,))
    assert [j.text for j in placed.jewels] == [_UNIQUE], "탐침이 정품 자리를 지켰다"
    assert rows and rows[0].socket_node_id == a
    assert any("탐침" in n for n in notes)


def test_자리를_지킨_주얼은_안_건드린다() -> None:
    """소켓이 그대로면 되배치할 게 없다 — 괜히 옮기면 실측이 무의미해진다."""
    a, b = _sockets(2)
    spec = _spec([a, b], jewels=(JewelSpec(socket_node_id=b, text=_UNIQUE),))
    placed, rows, notes = _restore_jewels(_graph, spec, (_UNIQUE,))
    assert placed is spec and rows == [] and notes == []


def test_같은_텍스트_주얼은_1대1로_센다() -> None:
    """똑같은 레어 2개 중 하나만 살아남았으면 **하나만** 되배치한다."""
    a, b = _sockets(2)
    spec = _spec([a, b], jewels=(JewelSpec(socket_node_id=a, text=_RARE),))
    placed, rows, _notes = _restore_jewels(_graph, spec, (_RARE, _RARE))
    assert len(rows) == 1
    assert len(placed.jewels) == 2


def test_자리를_옮긴_사실을_말한다() -> None:
    """동반 제거는 **옳다**(소켓 없이 주얼 모드가 계산에 들어가면 측정이 거짓이 된다).
    잘못이었던 건 침묵이다 — 못 놓은 것만 알리면 「조용히 이사」가 남는다."""
    a, b = _sockets(2)
    spec = _spec([a, b])  # 원래 소켓이 트리에서 빠져 주얼이 통째로 떨어진 상태
    _placed, rows, notes = _restore_jewels(_graph, spec, (_UNIQUE,))
    assert rows[0].socket_node_id in (a, b)
    assert any("자리를 옮겼다" in n for n in notes), "옮긴 사실이 조용하다"


# ── 타임리스 주얼: 옵션을 얹는 게 아니라 **노드를 바꾼다** ──

_TIMELESS = (
    "Rarity: UNIQUE\nUndying Hate\nTimeless Jewel\nRadius: Very Large\n"
    "Passives in radius are Conquered by the Abyssals"
)


def test_타임리스는_반경_주얼과_구별한다() -> None:
    """옵션을 얹는 반경 주얼과 종류가 다르다 — 노드의 **의미**가 달라진다."""
    assert is_timeless(_TIMELESS)
    assert not is_timeless(_RADIUS)
    assert not is_timeless(_UNIQUE)


def test_타임리스가_있으면_델타가_그_노드_값이_아니라고_말한다() -> None:
    """실측 2026-08-18: `Undying Hate` 하나로 래더 타이탄 EHP의 93%가 서 있었다
    (16,507 → 1,093). 주얼을 뗀 채 최적화하면 그 트리는 다른 트리다."""
    (a,) = _sockets(1)
    spec = _spec([a], jewels=(JewelSpec(socket_node_id=a, text=_TIMELESS),))
    (note,) = _timeless_notes(spec, _graph)
    assert "Undying Hate" in note and "할당됨" in note
    assert "다른 것으로 바꾼다" in note


def test_타임리스가_없으면_조용하다() -> None:
    (a,) = _sockets(1)
    spec = _spec([a], jewels=(JewelSpec(socket_node_id=a, text=_RARE),))
    assert _timeless_notes(spec, _graph) == ()
