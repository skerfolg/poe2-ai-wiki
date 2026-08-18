"""여유분 측정 — 「전부 찍고 소거」의 성패를 미리 안다 (철칙 5).

실측 2026-08-18: 그 방식을 네 번 돌려 1승 3패였고, 갈린 지점은 **깎아야 할 양 대
여유분의 비** 하나였다. 23을 깎을 때(여유 17, 1.4배) 1.203배로 이겼고 74를 깎을
때(4.4배) 0.72배·0.41배로 졌다. 그 비를 세션이 한 시간 쓰기 전에 보게 한다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pok.engine.tree.graph import TreeGraph
from pok.engine.tree.trim import REPORTED_AXES, SlackReport, radius_bundles, removable_nodes


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(Path("knowledge"))


@pytest.mark.parametrize(
    "need,free,expect",
    [
        (0, 5, "깎을 것이 없다"),
        (3, 5, "여유분 안에서"),
        (23, 17, "값을 치른다"),
        (74, 17, "구조를 판다"),
    ],
)
def test_verdict_matches_the_measured_record(need: int, free: int, expect: str) -> None:
    assert expect in SlackReport(removable=30, free=free, costs=(), need=need).verdict


def test_the_losing_case_names_its_evidence() -> None:
    """경고가 근거를 안 들면 다음 세션이 또 무시한다."""
    v = SlackReport(removable=30, free=17, costs=(), need=74).verdict
    assert "4.4배" in v and "1.203x" in v


def test_radius_jewels_are_guarded_as_a_bundle(graph: TreeGraph) -> None:
    """묶음은 개별로 재면 항상 과소평가된다 — 반경 주얼의 노터블을 통째로 지킨다."""
    jewels = [
        {
            "socket_node_id": 26196,
            "text": "Rarity: UNIQUE\nAgainst the Darkness\nTime-Lost Diamond\n"
            "Notable Passive Skills in Radius also grant 4% increased Strength\n",
        }
    ]
    guarded = radius_bundles(graph, jewels)
    assert len(guarded) >= 10, "반경 안 노터블을 못 모았다 — 묶음 보호가 무력하다"
    assert all(graph.nodes[n].kind == "notable" for n in guarded)


def test_non_radius_jewels_guard_nothing(graph: TreeGraph) -> None:
    jewels = [
        {
            "socket_node_id": 26196,
            "text": "Rarity: UNIQUE\nGrand Spectrum\nRuby\n2% increased Maximum Life\n",
        }
    ]
    assert radius_bundles(graph, jewels) == set()


def test_ehp_is_always_reported(graph: TreeGraph) -> None:
    """가중치에 없어도 보고한다 — 안 재는 축은 조용히 팔린다(EHP 22% 사고)."""
    assert "TotalEHP" in REPORTED_AXES


def test_floating_nodes_do_not_block_removal(graph: TreeGraph) -> None:
    """주얼이 연결 없이 띄운 노드를 고립으로 오해하면 후보가 0이 된다(실제로 걸렸다)."""
    start = graph.start_of("Witch")
    nb = sorted(graph.adj[start])[:2]
    allocated = {start, *nb, 999999}
    got = removable_nodes(graph, allocated, start, protect=set(), floating={999999})
    assert got, "고립 취급 때문에 제거 후보가 사라졌다"
