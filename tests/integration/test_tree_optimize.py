"""engine/tree 통합 — 델타 실측·최적화 루프 (환경 없으면 skip). 소예산으로 빠르게."""

from __future__ import annotations

import dataclasses

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree.deltas import evaluate_node_deltas
from pok.engine.tree.graph import TreeGraph
from pok.engine.tree.optimize import Objective, optimize_tree
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(knowledge_dir())


SPEC = BuildSpec(
    class_name="Sorceress",
    ascendancy="Sorceress1",
    tree_nodes=(),
    skills=(
        SkillGroupSpec(
            gems=(GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark", level=20),)
        ),
    ),
)


def test_노드_델타_실측(graph: TreeGraph) -> None:
    # Raw Power(51184, 주문 피해 노터블)는 Spark 빌드에서 DPS 양의 델타여야 한다
    deltas = evaluate_node_deltas(SPEC, graph, [51184], stats=("CombinedDPS", "Life"))
    (d,) = deltas
    assert d.node_id == 51184
    assert d.points == 5  # 시작점에서 거리 5 (경로 포함 소모 포인트)
    assert d.deltas["CombinedDPS"] > 0
    assert d.per_point("CombinedDPS") > 0


_SOCKET = 61419  # Sorceress 시작에서 최단 10포인트인 jewel-socket (KB 실측)
_JEWEL_TMPL = (
    "Rarity: RARE\nPok Jewel\nSapphire\nItem Level: 81\n"
    "15% increased Spell Damage\n15% increased Critical Hit Chance for Spells"
)


def test_소켓은_가정_주얼과_함께_실측된다(graph: TreeGraph) -> None:
    """빈 소켓은 델타 0 — jewel_templates가 있으면 가정 장착 델타로 평가된다."""
    empty = evaluate_node_deltas(SPEC, graph, [_SOCKET], stats=("CombinedDPS",))
    (e,) = empty
    assert e.kind == "jewel-socket" and e.jewel_text is None

    with_jewel = evaluate_node_deltas(
        SPEC, graph, [_SOCKET], stats=("CombinedDPS",), jewel_templates=(_JEWEL_TMPL,)
    )
    (d,) = with_jewel
    assert d.jewel_text == _JEWEL_TMPL, "채택된 템플릿이 NodeDelta에 기록된다"
    assert d.deltas["CombinedDPS"] > e.deltas["CombinedDPS"], "주문 피해 주얼은 실측 우위"


def test_최적화가_소켓을_채택하면_주얼이_스펙에_편입된다(graph: TreeGraph) -> None:
    """소켓 직전까지 할당된 트리 + 강한 템플릿 → 소켓(1포인트)이 채택돼야 한다."""
    allocated, _paths = graph.connect_anchors("Sorceress", [_SOCKET])
    spec = dataclasses.replace(SPEC, tree_nodes=tuple(n for n in allocated if n != _SOCKET))
    obj = Objective(weights={"CombinedDPS": 1.0})
    out = optimize_tree(
        spec,
        graph,
        obj,
        # 반경 1 후보는 둘: Raw Power(실측 17.5)·소켓+주얼(실측 14.6) — 예산 2면 둘 다 채택
        point_budget=2,
        candidate_radius=1,
        jewel_templates=(_JEWEL_TMPL,),
    )
    jewel_steps = [s for s in out.steps if s.node_delta.jewel_text is not None]
    assert jewel_steps, "가정 주얼 델타가 양수면 소켓이 채택돼야 한다"
    assert jewel_steps[0].node_delta.node_id == _SOCKET
    # 채택된 소켓의 JewelSpec 편입 + buildxml 계약(소켓이 tree_nodes에 존재)
    assert [j.socket_node_id for j in out.spec.jewels] == [_SOCKET]
    assert out.spec.jewels[0].text == _JEWEL_TMPL
    assert _SOCKET in out.spec.tree_nodes
    assert not out.result.pruned_nodes


def test_최적화_소예산(graph: TreeGraph) -> None:
    obj = Objective(weights={"CombinedDPS": 1.0, "Life": 0.5})
    out = optimize_tree(
        SPEC, graph, obj, point_budget=6, candidate_radius=6, max_candidates_per_round=8
    )
    assert out.steps, "예산 6이면 최소 1수는 채택돼야 한다"
    spent = sum(s.node_delta.points for s in out.steps)
    assert spent <= 6
    # 모든 채택 수에 실측 근거(델타)와 양의 점수가 있다 — Exit 기준의 단위 검증
    for step in out.steps:
        assert step.score > 0
        assert step.node_delta.deltas
    assert not out.result.pruned_nodes  # 최종 트리 전체 연결
