"""반사실 측정 통합 — 실제 PoB로 제거·교체를 잰다 (환경 없으면 skip).

단위 시험은 가짜 데몬으로 **계약**을 잠근다. 여기서 잠그는 것은 다른 것이다:
그래프가 「빼도 된다」고 한 노드를 실제로 빼면 PoB가 정말 아무것도 잘라내지
않는가 — 그 대응이 깨지면 반사실 데이터셋 전체가 조용히 다른 트리를 잰 값이 된다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree.counterfactual import evaluate_removals, evaluate_swaps, removable_nodes
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec
from pok.pob.daemon import PobDaemon
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

_TARGET = 51184  # Raw Power (주문 피해 노터블) — Sorceress 시작에서 5포인트


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(knowledge_dir())


@pytest.fixture(scope="module")
def daemon() -> Iterator[PobDaemon]:
    """데몬 1개로 이 파일 전량을 돈다 — 부팅(~2초)을 매 시험마다 물지 않는다."""
    with PobDaemon() as d:
        yield d


@pytest.fixture(scope="module")
def spec(graph: TreeGraph) -> BuildSpec:
    """Raw Power까지 이은 Spark 빌드 — 경로가 사슬이라 잎만 뺄 수 있다."""
    path = graph.shortest_path({graph.start_of("Sorceress")}, _TARGET)
    assert path, "경로를 못 잡았다 — 표본 선택을 다시 할 것"
    return BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        tree_nodes=tuple(path),
        skills=(
            SkillGroupSpec(
                gems=(GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark", level=20),)
            ),
        ),
    )


def test_후보_열거가_PoB_실측과_어긋나지_않는다(
    spec: BuildSpec, graph: TreeGraph, daemon: PobDaemon
) -> None:
    """그래프가 「빼도 된다」고 한 노드를 실제로 빼도 PoB가 아무것도 잘라내지 않는다."""
    candidates = removable_nodes(spec, graph)
    assert candidates.nodes == (_TARGET,), "사슬 경로인데 잎 말고 다른 것이 후보가 됐다"
    assert candidates.orphans == ()
    (row,) = evaluate_removals(spec, graph, [_TARGET], stats=("CombinedDPS",), daemon=daemon)
    assert row.measured is True, row.failed
    assert row.pruned == ()
    assert row.deltas["CombinedDPS"] < 0, "주문 피해 노터블을 뺐는데 딜이 안 줄었다"


def test_중간_노드를_빼는_것은_후보에서부터_막힌다(
    spec: BuildSpec, graph: TreeGraph, daemon: PobDaemon
) -> None:
    """PoB에 맡기면 잘라낸 트리의 값을 정상값으로 받는다 — 후보 단계가 강제 지점이다."""
    interior = spec.tree_nodes[0]
    (row,) = evaluate_removals(spec, graph, [interior], stats=("CombinedDPS",), daemon=daemon)
    assert row.measured is False and "고아" in row.failed


def test_교체를_한_계산으로_잰다(spec: BuildSpec, graph: TreeGraph, daemon: PobDaemon) -> None:
    """제거 1 + 추가 1이 한 빌드에 들어간다 — 순증 포인트와 델타가 함께 나온다."""
    near = [
        nid
        for nid, _node, _dist in graph.candidates(
            set(spec.tree_nodes), 2, ascendancy_name=spec.ascendancy
        )
        if nid != _TARGET
    ]
    assert near, "교체 대상을 못 찾았다"
    rows = evaluate_swaps(
        spec, graph, [(_TARGET, near[0])], stats=("CombinedDPS", "Life"), daemon=daemon
    )
    (row,) = rows
    assert row.measured is True, row.failed
    assert row.added and row.removed == (_TARGET,)
    assert row.points == len(row.added) - 1
    assert set(row.deltas) == {"CombinedDPS", "Life"}
