"""engine/tree/graph — 실제 KB 트리(5,130 노드)로 경로 도구 검증."""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree.graph import TreeGraph


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(knowledge_dir())


def test_로드_규모(graph: TreeGraph) -> None:
    # KB 수록분 실측 4,553 (원시 트리 5,130에서 제외 기준 적용 후 + 시드 승격분)
    assert len(graph.nodes) > 4500
    # 실측 고정값: Behemoth(5642)는 노터블
    assert graph.nodes[5642].name_en == "Behemoth"
    assert graph.nodes[5642].kind == "notable"


def test_시작점_인접이_양방향(graph: TreeGraph) -> None:
    start = graph.start_of("Witch")
    assert start == 54447
    assert 4739 in graph.adj[start]
    assert start in graph.adj[4739]


def test_최단_경로(graph: TreeGraph) -> None:
    # P3 실증 경로와 동일해야 한다: 시작→61419 소켓 = 10칸
    path = graph.shortest_path({graph.start_of("Witch")}, 61419)
    assert path is not None
    assert len(path) == 10
    assert path[-1] == 61419


def test_connect_anchors_전체_연결(graph: TreeGraph) -> None:
    # P3 빌드의 타깃 13개 — 스크래치 스크립트 실측(본 트리 62pt)과 동일 규모
    targets = [
        51184,
        36302,
        57110,
        5501,
        19125,
        2138,
        14934,
        10398,
        57204,
        34168,
        38614,
        44293,
        49220,
    ]
    allocated, paths = graph.connect_anchors("Witch", targets)
    assert set(targets) <= set(allocated)
    assert len(allocated) == 62  # 그리디 결과 재현 (결정적)
    # 모든 경로의 끝은 해당 타깃
    for t, p in paths.items():
        assert p == [] or p[-1] == t


def test_connect_anchors_비연결은_거부(graph: TreeGraph) -> None:
    with pytest.raises(ValueError, match="연결 불가"):
        graph.connect_anchors("Witch", [8415])  # 어센던시 노드는 본 트리와 무연결


def test_candidates_거리와_종류(graph: TreeGraph) -> None:
    out = graph.candidates({graph.start_of("Witch")}, max_dist=5)
    assert out, "반경 5 안에 노터블이 있어야 한다"
    kinds = {n.kind for _, n, _ in out}
    assert kinds <= {"notable", "keystone", "jewel-socket"}
    # 실측: Raw Power(51184)는 거리 5
    by_id = {nid: d for nid, _, d in out}
    assert by_id.get(51184) == 5
