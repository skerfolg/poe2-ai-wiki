"""일반/전직 포인트 분리 — 합산하면 예산 판정이 조용히 틀린다.

전직은 별도 풀이고 관문 노드(혈액술 등)는 무료라, 노드 수와 포인트 수가 다르다.
분리 수치가 어느 반환값에도 없던 동안 호출자가 전직 node_id를 손으로 하드코딩해
빼고 있었다 — 그래서 문서가 아니라 반환값에 붙인다(철칙 5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pok.engine.tree.graph import ASCENDANCY_POINTS, GENERAL_POINTS, TreeGraph


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(Path("knowledge"))


BLOOD_MAGE = [8415, 26383, 30117, 3165, 50192, 31223, 56162, 59342, 23416]


def test_gateway_node_is_free(graph: TreeGraph) -> None:
    """혈액술은 관문이라 무료 — 9노드가 8포인트다."""
    out = graph.point_split("Witch2", BLOOD_MAGE)
    assert out["ascendancy_nodes"] == 9
    assert out["ascendancy"] == 8
    assert out["ascendancy_free"] == 1
    assert out["general"] == 0


def test_general_and_ascendancy_are_separate_pools(graph: TreeGraph) -> None:
    general = [n for n in list(graph.nodes)[:5] if not graph.nodes[n].ascendancy]
    out = graph.point_split("Witch2", BLOOD_MAGE + general)
    assert out["general"] == len(general)
    assert out["ascendancy"] == 8
    assert out["total_nodes"] == len(BLOOD_MAGE) + len(general)
    assert out["general_budget"] == GENERAL_POINTS
    assert out["ascendancy_budget"] == ASCENDANCY_POINTS


def test_over_budget_is_reported(graph: TreeGraph) -> None:
    general = [n for n in graph.nodes if not graph.nodes[n].ascendancy][: GENERAL_POINTS + 1]
    out = graph.point_split("Witch2", general)
    assert "over_budget" in out
    assert f"{GENERAL_POINTS + 1}/{GENERAL_POINTS}" in out["over_budget"]
