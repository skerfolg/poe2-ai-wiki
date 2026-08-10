"""트리 밀집도 스캔 (백로그 제안 A).

`optimize_tree`는 현재 트리 **반경 안**만 보므로 먼 뭉치를 구조적으로 못 본다 —
실측: 예산 87로 돌려 43포인트에서 조기 종료했고, 병목을 정면으로 푸는 노터블
(인화성 강도 80% 등)이 **전부 후보 반경 밖**이었다.
"""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree.clusters import JEWEL_RADII, find_clusters, relevance
from pok.engine.tree.graph import TreeGraph


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(knowledge_dir())


def test_relevance_zeroes_excluded_nodes() -> None:
    """`exclude`가 걸리면 가중치가 아무리 높아도 0 — 컨셉 밖은 후보가 아니다."""
    stats = ["25% increased Ignite Magnitude", "10% increased Flail Damage"]
    assert relevance(stats, [("ignite", 1.0)], []) == 1.0
    assert relevance(stats, [("ignite", 1.0)], ["flail"]) == 0.0


def test_relevance_sums_multiple_axes() -> None:
    """한 노드가 여러 축을 건드리면 그만큼 값이 크다."""
    stats = ["Ignite Magnitude and Critical Hit Chance"]
    assert relevance(stats, [("ignite", 1.0), ("critical", 0.5)], []) == 1.5


def test_include_is_required() -> None:
    """관련성 필터 없는 밀집도는 **쓰레기**다 — 조용히 기본값을 지어내지 않는다.

    실측: 필터 없이 돌리니 "반경 1000에 노터블 9개"가 나왔고 그중 3개가 도리깨였다.
    """
    with pytest.raises(ValueError, match="관련성 필터"):
        find_clusters(TreeGraph(knowledge_dir()), include=[])


def test_radii_default_to_measured_jewel_list() -> None:
    """반경은 **실측 목록**에서 온다 — 임의의 큰 값은 틀린 결론을 만든다.

    발의 세션이 3,800을 가정해 「42포인트 절약」을 두 번 보고했다가 철회했다.
    실효 최대는 2,520(= 2,100의 1.2배)이고 Variable은 **도넛**이다.
    """
    labels = {label for label, _, _ in JEWEL_RADII}
    assert labels == {"Small", "Medium", "Large", "Very Large", "Variable(최대)"}
    outers = [outer for _, _, outer in JEWEL_RADII]
    assert max(outers) == 2520.0, "실효 최대"
    donut = next(inner for label, inner, _ in JEWEL_RADII if label.startswith("Variable"))
    assert donut > 0, "Variable은 도넛 — inner 안쪽은 안 덮는다"


def test_scan_finds_the_flammability_cluster(graph: TreeGraph) -> None:
    """실사용 사례 — 점화 축을 주면 「부싯돌」(인화성 강도 80%)이 잡혀야 한다.

    이 노드가 후보 반경 밖에 있어서 그리디가 못 봤다는 것이 제안 A의 발단이다.
    """
    clusters = find_clusters(
        graph,
        include=[("ignite", 1.0), ("flammability", 1.5), ("fire damage", 0.8)],
        exclude=["flail", "minion", "companion"],
        top=6,
    )
    assert clusters
    names = {hit.name_ko for cluster in clusters for hit in cluster.hits}
    assert "부싯돌" in names, names


def test_hits_carry_effect_text(graph: TreeGraph) -> None:
    """점수만 내면 **두 축을 동시에 봐야 보이는 조합**을 영원히 못 찾는다."""
    clusters = find_clusters(graph, include=[("critical", 1.0)], exclude=["minion"], top=3)
    hits = [hit for cluster in clusters for hit in cluster.hits]
    assert hits and all(hit.stats_en for hit in hits), "효과 문구가 비면 조합을 못 읽는다"


def test_other_ascendancy_locked_nodes_are_excluded(graph: TreeGraph) -> None:
    """다른 전직 전용 해금 노드는 점수를 부풀린다 — 인게임에서 못 찍는다(B-13)."""
    clusters = find_clusters(
        graph,
        include=[("critical", 1.0)],
        for_ascendancy="Infernalist",
        top=20,
    )
    locked = [h for c in clusters for h in c.hits if h.locked_to and h.locked_to != "Infernalist"]
    assert not locked, f"다른 전직 전용이 섞였다: {[h.name_ko for h in locked]}"


def test_hits_carry_positions(graph: TreeGraph) -> None:
    """좌표가 없으면 세션이 **파일을 뒤진다** (제안 C — 도구 갭이 규율 위반을 강제한다).

    클러스터 중심만으로는 "이 노터블이 내 트리에서 얼마나 먼가"를 못 재는데,
    그 질문이 실제로 나온다(`unconnected_regions`의 center를 정할 때).
    """
    clusters = find_clusters(graph, include=[("ignite", 1.0)], exclude=["minion"], top=3)
    hits = [hit for cluster in clusters for hit in cluster.hits]
    assert hits
    assert all(len(hit.position) == 2 for hit in hits)
    # 중심은 그대로 `unconnected_regions`에 넣을 수 있는 꼴이어야 한다
    assert all(len(cluster.center) == 2 for cluster in clusters)


def test_other_ascendancy_tree_nodes_are_excluded(graph: TreeGraph) -> None:
    """다른 어센던시 **트리에 속한** 노드는 애초에 못 찍는다 (백로그 #35).

    필터가 `unlock_constraint`(= 「다른 전직 **전용 해금**」)만 보고 `data.ascendancy`
    (= 「다른 어센던시 **트리 소속**」)를 안 봤다. 두 축은 다르다 — 후자가 더 명백한
    배제 대상인데 그물을 통과했다.

    실측 2026-08-09: `26383 살점 가르기`(`Witch2` = 블러드 메이지, `unlock_constraint`
    없음)가 인퍼널리스트 호출에 나와 **치명타 병목의 해법으로 채택 직전까지** 갔다.
    기계가 못 잡은 것을 사용자가 잡았다.
    """
    hits = [
        h
        for cluster in find_clusters(
            graph, include=[("critical", 1.0), ("spell", 0.5)], for_ascendancy="Infernalist", top=60
        )
        for h in cluster.hits
    ]
    intruders = [
        (h.node_id, h.name_ko)
        for h in hits
        if graph.nodes[h.node_id].ascendancy
        and graph.resolve_ascendancy(graph.nodes[h.node_id].ascendancy) != "Infernalist"
    ]
    assert not intruders, f"다른 어센던시 트리 노드가 섞였다: {intruders}"


def test_own_ascendancy_nodes_still_pass(graph: TreeGraph) -> None:
    """⚠ **게이트가 정상을 막으면 신호가 죽는다**(§0 ⑤) — 자기 것은 남아야 한다.

    만들다 실제로 전부 막혔다: `node.ascendancy`는 **코드**("Witch2")이고
    `resolve_ascendancy`는 **표시명**("Blood Mage")을 내는데 그대로 비교했다.
    두 이름 공간이라 항상 불일치였다 — 노드 쪽도 해소해야 한다.
    """

    def ascendancy_hits(for_ascendancy: str | None) -> list[str]:
        return [
            h.name_ko
            for cluster in find_clusters(
                graph, include=[("life cost", 1.0)], for_ascendancy=for_ascendancy, top=30
            )
            for h in cluster.hits
            if graph.nodes[h.node_id].ascendancy
        ]

    assert "혈액술" in ascendancy_hits("Blood Mage"), "자기 어센던시 노드가 사라졌다"
    assert "혈액술" not in ascendancy_hits("Infernalist"), "남의 것은 안 나온다"
    # 전직을 안 밝히면 어센던시 노드를 **전부** 뺀다 — 못 찍는 것을 권하지 않는다(B-13)
    assert not ascendancy_hits(None)
