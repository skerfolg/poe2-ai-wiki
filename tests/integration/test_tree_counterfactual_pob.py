"""반사실 측정 통합 — 실제 PoB로 제거·교체를 잰다 (환경 없으면 skip).

단위 시험은 가짜 데몬으로 **계약**을 잠근다. 여기서 잠그는 것은 다른 것이다:
그래프가 「빼도 된다」고 한 노드를 실제로 빼면 PoB가 정말 아무것도 잘라내지
않는가 — 그 대응이 깨지면 반사실 데이터셋 전체가 조용히 다른 트리를 잰 값이 된다.

⚠ 파일명 끝의 `_pob`는 장식이 아니다. `tests/unit`과 **basename이 같으면** pytest가
둘을 같은 모듈로 보고 수집을 거부한다(`tests`에 `__init__.py`가 없다). CI는
`pytest tests`로 둘을 **한 번에** 부르므로 그때만 깨진다 — 실측 2026-08-13에 걸렸다.
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
_OUTER = 36302  # Practiced Signs — 잎(Raw Power) **바깥**이라 잎을 빼면 되짚어야 닿는다


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
    """제거 1 + 추가 1이 한 빌드에 들어간다 — 순증 포인트와 델타가 함께 나온다.

    넣는 노드는 **경로 중간**에 붙은 이웃으로 고른다. 잎 바깥으로 뻗은 후보를 주면
    추가 경로가 방금 뺀 잎을 되짚어 「교체가 아니다」로 거부되는데, 그 거부가 정상이다
    (아래 시험이 그쪽을 잠근다).
    """
    inner = spec.tree_nodes[0]
    in_node = min(
        nid
        for nid in graph.adj[inner]
        if nid in graph.nodes
        and nid not in spec.tree_nodes
        and graph.nodes[nid].ascendancy is None
        and graph.nodes[nid].locked_to is None
        and not graph.nodes[nid].requires_nodes
    )
    (row,) = evaluate_swaps(
        spec, graph, [(_TARGET, in_node)], stats=("CombinedDPS", "Life"), daemon=daemon
    )
    assert row.measured is True, row.failed
    assert row.removed == (_TARGET,) and row.added == (in_node,)
    assert row.points == 0, "1개 빼고 1개 넣었으면 순증 0이다"
    assert set(row.deltas) == {"CombinedDPS", "Life"}


def test_잎_바깥_후보는_경로가_잎을_되짚어_거부된다(
    spec: BuildSpec, graph: TreeGraph, daemon: PobDaemon
) -> None:
    """실제 후보 탐색이 정확히 이 꼴을 낸다 — 실측 2026-08-13 통합 1차에서 걸렸다.

    `graph.candidates`가 거리 2로 낸 첫 후보(36302 Practiced Signs)는 잎(Raw Power)
    바깥에 있어서, 잎을 빼고 그리로 가려면 잎을 다시 찍어야 한다. 조용히 재면
    「제거 없는 교체」를 교체로 세게 된다.
    """
    assert graph.nodes[_OUTER].name_en == "Practiced Signs", "표본이 바뀌었다 — 다시 고를 것"
    (row,) = evaluate_swaps(spec, graph, [(_TARGET, _OUTER)], stats=("Life",), daemon=daemon)
    assert row.measured is False and "다시 지나간다" in row.failed
    assert row.deltas == {} and row.added == ()
