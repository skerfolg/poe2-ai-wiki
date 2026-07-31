"""engine/tree 통합 — 델타 실측·최적화 루프 (환경 없으면 skip). 소예산으로 빠르게."""

from __future__ import annotations

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
