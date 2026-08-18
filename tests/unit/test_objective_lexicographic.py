"""사전식 목표가 그리디를 미는 방식을 잠근다 (#67 6차, 사용자 승인 2026-08-12).

가중 합산은 **한 축이 지배한다** — DPS 가중치가 크면 EHP가 바닥이어도 DPS 수가
항상 이긴다. "한쪽으로 쏠리지 않게"는 가중치를 손으로 맞춰서가 아니라 **경계를
채우면 다음 축으로 넘어가게** 해서 얻는다.
"""

from __future__ import annotations

from pok.engine.objective import Target
from pok.engine.tree.deltas import NodeDelta
from pok.engine.tree.optimize import Objective, _target_notes

_TARGETS = (
    Target("TotalEHP", ">=", 8000, "EHP 하한"),
    Target("CombinedDPS", ">=", 2_000_000, "딜 목표"),
)
_OBJ = Objective(weights={"CombinedDPS": 1.0, "TotalEHP": 0.5}, targets=_TARGETS)


def _nd(points: int = 1, **deltas: float) -> NodeDelta:
    return NodeDelta(
        node_id=1, name_en="x", name_ko="x", kind="notable", points=points, path=(1,), deltas=deltas
    )


def test_병목_축이_다른_축을_압도한다() -> None:
    """EHP가 하한 아래면 DPS 50% 증가보다 EHP 20% 증가가 이겨야 한다.

    가중 합산이었다면 DPS 가중치가 두 배라 정반대로 뽑는다.
    """
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 5000}
    assert _OBJ.focus(base).metric == "TotalEHP"
    assert _OBJ.score(_nd(TotalEHP=1000.0), base) > _OBJ.score(_nd(CombinedDPS=500_000.0), base)


def test_충족되면_다음_축으로_넘어간다() -> None:
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 8200}
    assert _OBJ.focus(base).metric == "CombinedDPS"
    assert _OBJ.score(_nd(CombinedDPS=500_000.0), base) > _OBJ.score(_nd(TotalEHP=1000.0), base)


def test_충족한_경계를_깨는_수는_배제된다() -> None:
    """이게 없으면 그리디가 EHP 경계를 헐어 DPS로 옮긴다 — 쏠림의 전형이다."""
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 8200}
    assert _OBJ.score(_nd(TotalEHP=-500.0, CombinedDPS=900_000.0), base) == float("-inf")
    # 경계를 안 깨는 만큼만 내주는 수는 살아 있다
    assert _OBJ.score(_nd(TotalEHP=-100.0, CombinedDPS=900_000.0), base) > 0


def test_전부_충족하면_가중합으로_돌아간다() -> None:
    base = {"CombinedDPS": 3_000_000, "TotalEHP": 9000}
    assert _OBJ.focus(base) is None
    plain = Objective(weights=_OBJ.weights)
    assert _OBJ.score(_nd(CombinedDPS=100.0), base) == plain.score(_nd(CombinedDPS=100.0), base)


def test_못_재는_축은_건너뛰고_그_사실을_말한다() -> None:
    """PoB가 못 재는 축을 목표로 걸면 델타가 전부 0이라 **한 걸음도 못 민다**.

    조용히 넘어가면 "최적화했는데 안 올랐다"로 읽힌다 — 안 오른 게 아니라
    안 재진 것이다(BACKLOG 형태 ②·#44).
    """
    obj = Objective(
        weights={"CombinedDPS": 1.0},
        targets=(Target("TriggerRate", ">=", 5, "발동률"), Target("CombinedDPS", ">=", 2e6)),
    )
    base = {"CombinedDPS": 1_000_000}  # TriggerRate 없음 = 측정 불가
    assert obj.focus(base).metric == "CombinedDPS", "못 재는 축에 걸려 멈추면 안 된다"
    notes = _target_notes(obj, base)
    assert any("재지 못했다" in n for n in notes), "못 잰 사실을 말하지 않으면 0으로 읽힌다"


def test_첫_목표_미달이면_사전식이_퇴화했다고_말한다() -> None:
    """미달로 끝났다 = **아래 축은 순서에 한 번도 안 들어왔다**.

    사전식은 「경계를 채운 뒤 다음 축」인데, 못 채우면 끝까지 첫 축만 민다. 미달
    사실만 말하고 이걸 안 말하면 세션은 두 축을 다 최적화한 결과로 읽는다.
    실측 2026-08-18(데드아이): 트리만으로 닿는 EHP가 정답지의 59%라 바닥
    60·80·100%가 전부 미달 — 서로 다른 바닥이 아니라 서로 다른 세기의 가중치였다.
    """
    obj = Objective(
        weights={"CombinedDPS": 1.0, "TotalEHP": 0.6},
        targets=(Target("TotalEHP", ">=", 13_459, "정답지 EHP"),),
    )
    notes = _target_notes(obj, {"CombinedDPS": 1_200_000, "TotalEHP": 7_900})
    assert any("미충족 목표" in n for n in notes)
    assert any("한 번도" in n for n in notes), "퇴화 사실이 조용하다"
    assert any("도달 가능한지" in n for n in notes), "도달 가능성을 확인하라고 안 한다"


def test_목표를_채웠으면_퇴화_경고는_안_뜬다() -> None:
    """침묵이 나쁘다고 과잉으로 가면 경고가 배경 소음이 된다."""
    obj = Objective(
        weights={"CombinedDPS": 1.0},
        targets=(Target("TotalEHP", ">=", 5_000, "바닥"),),
    )
    assert _target_notes(obj, {"CombinedDPS": 1e6, "TotalEHP": 6_000}) == ()


def test_목표가_없으면_기존_동작_그대로() -> None:
    plain = Objective(weights={"CombinedDPS": 1.0, "TotalEHP": 0.5})
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 5000}
    assert plain.score(_nd(CombinedDPS=100_000.0), base) == 0.1
    assert plain.focus(base) is None


# ────────────── 필수 앵커는 점수 경쟁 밖이다 ──────────────


def _graph():
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.graph import TreeGraph

    return TreeGraph(knowledge_dir())


def _spec():
    from pok.pob.buildxml import BuildSpec

    return BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=())


def test_앵커는_기준선에_들어가_가지치기에서_보호된다() -> None:
    """메커니즘 노드는 PoB가 못 재는 경우가 많아 델타 0으로 잡힌다.

    보호하지 않으면 가지치기가 곧바로 회수한다 — 넣자마자 사라지는 셈이다.
    `_prune_dead_branches`는 `original.tree_nodes`를 보호 집합으로 쓰므로,
    앵커를 **원래 스펙에 편입**하는 것이 그대로 보호가 된다.
    """
    from pok.engine.tree.optimize import _seed_anchors

    graph = _graph()
    # 전직 **시작** 노드는 스펙에 안 실린다(PoB가 자동 할당) — 일반 노터블로 확인한다
    anchor = next(
        n.node_id for n in graph.nodes.values() if n.kind == "notable" and not n.ascendancy
    )
    seeded, notes, cost = _seed_anchors(_spec(), graph, (anchor,), 20)
    assert anchor in seeded.tree_nodes and cost.general > 0
    assert any("가지치기도 건드리지 않는다" in n for n in notes)


def test_연결_불가_앵커를_조용히_빼지_않는다() -> None:
    """조용히 빼면 「앵커를 넣었다」고 믿은 채 없는 트리를 받는다."""
    from pok.engine.tree.optimize import _seed_anchors

    _, notes, _ = _seed_anchors(_spec(), _graph(), (999_999,), 20)
    assert any("연결 불가" in n for n in notes)


def test_앵커가_예산을_넘으면_말한다() -> None:
    """설계가 성립하지 않는다는 신호다 — 조용히 넘어가면 예산 0인 그리디를 돌린다."""
    from pok.engine.tree.optimize import _seed_anchors

    _, notes, cost = _seed_anchors(_spec(), _graph(), (11495, 21984), 1)
    # 전직 노드(11495)는 **별도 풀**이라 일반 예산 초과 판정에 안 들어간다(#68).
    assert cost.general > 1
    assert any("초과" in n for n in notes)


def test_앵커가_없으면_스펙이_그대로다() -> None:
    from pok.engine.tree.optimize import _seed_anchors

    spec = _spec()
    seeded, notes, cost = _seed_anchors(spec, _graph(), (), 20)
    assert seeded is spec and notes == () and cost == (0, 0)


def test_묶음도_노드와_같은_저울에_오른다() -> None:
    """#70: 먼 뭉치가 그리디 후보로 들어가려면 `Objective`가 **둘 다** 받아야 한다.

    실패 형태가 조용하다 — 타입을 `NodeDelta`로 좁혀 두면 뭉치를 재는 순간 막히고,
    막히면 긴 점프가 통째로 빠진 채 "후보가 없어 멈췄다"로 읽힌다. 계약을 여기서 잠근다.
    """
    from pok.engine.tree.deltas import BundleDelta
    from pok.engine.tree.optimize import Objective

    obj = Objective(weights={"CombinedDPS": 1.0})
    base = {"CombinedDPS": 1000.0}

    # 같은 이득이면 **포인트가 적은 쪽**이 높다 — 묶음도 같은 규칙을 따른다
    cheap = BundleDelta(
        name="가까운 뭉치",
        nodes=(1,),
        path=(1, 2),
        points=2,
        deltas={"CombinedDPS": 100.0},
        sum_of_parts={},
    )
    dear = BundleDelta(
        name="먼 뭉치",
        nodes=(3,),
        path=(3, 4, 5, 6),
        points=4,
        deltas={"CombinedDPS": 100.0},
        sum_of_parts={},
    )
    assert obj.score(cheap, base) > obj.score(dear, base) > 0

    # 경로가 길어도 **도착지 값이 크면** 이긴다 — 이게 긴 점프가 성립하는 근거다.
    # 노드 단위로는 첫 걸음(델타 0)에서 탈락해 여기까지 오지도 못한다.
    far_but_rich = BundleDelta(
        name="멀고 값진 뭉치",
        nodes=(7,),
        path=tuple(range(7, 17)),
        points=10,
        deltas={"CombinedDPS": 2000.0},
        sum_of_parts={},
    )
    assert obj.score(far_but_rich, base) > obj.score(cheap, base)
