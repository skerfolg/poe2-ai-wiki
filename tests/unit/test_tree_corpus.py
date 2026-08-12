"""트리 대조가 강제 지점에서 자동으로 붙는지 잠근다 (#67 6차).

새 도구를 만들고 문서에 "쓰세요"라고 적는 방식은 이 레포에서 실패가 증명됐다.
그래서 **트리를 짜려면 반드시 지나가는 지점**의 반환값에 붙였고, 그게 유지되는지
여기서 잠근다 — 이 부착이 조용히 빠지면 규율이 통째로 사라진다.
"""

from __future__ import annotations

from pok.common.paths import knowledge_dir
from pok.engine.tree.corpus import ascendancy_in, compare_tree
from pok.engine.tree.graph import TreeGraph

_graph = TreeGraph(knowledge_dir())


def test_전원_공통_노드_누락이_드러난다() -> None:
    """「꼭 필요한 노드를 안 찍는다」가 정확히 이 형태로 나타난다."""
    out = compare_tree(_graph, "Monk", {13828, 10131}, ascendancy="Martial Artist")
    assert out["compared"] is True
    assert out["missing_unanimous"], "표본 10/10 노드를 하나도 안 넣었는데 조용하다"
    assert all(r["count"].endswith(f"/{out['sample_n']}") for r in out["missing_unanimous"])


def test_전직을_모르면_대조하지_않았다고_밝힌다() -> None:
    """기본 클래스만으로는 표본을 특정할 수 없다(Monk → 전직 3종).

    조용히 건너뛰면 「문제 없음」으로 읽힌다 — 이 레포가 반복해 데인 꼴이다.
    """
    out = compare_tree(_graph, "Monk", {13828})
    assert out["compared"] is False and "전직을 모른다" in out["why"]


def test_전직_전용_노드가_있으면_추론한다() -> None:
    asc_node = next(n for n in _graph.nodes.values() if n.ascendancy == "Monk1")
    assert ascendancy_in(_graph, {asc_node.node_id}) == "Martial Artist"


def test_connect_anchors가_대조를_자동으로_붙인다() -> None:
    """부착이 빠지면 세션은 프로파일의 존재조차 모른다."""
    from pok.mcp.tools.tree import connect_anchors

    out = connect_anchors("Monk", [13828, 10131], ascendancy="Martial Artist")
    assert "corpus" in out, "강제 지점에서 대조가 사라졌다"
    assert out["corpus"]["compared"] is True
