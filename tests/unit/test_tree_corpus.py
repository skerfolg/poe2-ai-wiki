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


def test_출고_지점도_대조를_얹는다() -> None:
    """설계 도구를 안 거치고 노드 목록을 손으로 써서 조립하는 경로가 있다.

    트리가 산출물에 들어가는 지점은 `assemble_pob` 하나뿐이라 여기가 마지막 관문이다
    (`check_axes`가 같은 이유로 이미 여기 붙어 있다).
    """
    from pok.engine.tree.corpus import compare_build_spec

    out = compare_build_spec(
        {"class_name": "Monk", "ascendancy": "Monk1", "tree_nodes": [13828, 10131]}
    )
    assert out["compared"] is True, "전직 코드(Monk1)를 실명으로 못 풀었다"
    assert out["missing_unanimous"]


def test_대조가_출고_반환에_실제로_실린다() -> None:
    """부착 지점이 사라지면 규율이 조용히 없어진다 — 반환 계약으로 잠근다."""
    import inspect

    from pok.mcp.tools import build

    src = inspect.getsource(build.assemble_pob)
    assert '"corpus": compare_build_spec(build_spec)' in src


def test_경로에서_주운_것을_센다() -> None:
    """「하나의 길에서 찍을 수 있는 노드가 많은 게 가치 높은 길」(사용자 정리).

    포인트와 델타만 보면 같아 보이는 두 길이 부수 획득에서 갈린다. 이걸 안 세면
    길의 가치를 비교할 수단이 없다.
    """
    import dataclasses

    from pok.engine.tree import deltas as mod

    # 목적지 하나로 가는 길에 노터블 하나가 딸려 오는 상황
    target, incidental_id = 13828, 21984  # 21984 = 주얼 소켓(목적지 종류)
    graph = _graph
    assert graph.nodes[incidental_id].kind in ("notable", "keystone", "jewel-socket")

    fields = {f.name for f in dataclasses.fields(mod.BundleDelta)}
    assert "incidental" in fields, "부수 획득 필드가 사라지면 길의 가치를 못 잰다"

    bundle = mod.BundleDelta(
        name="x",
        nodes=(target,),
        path=(target, incidental_id),
        points=2,
        deltas={"CombinedDPS": 100.0},
        sum_of_parts={"CombinedDPS": 80.0},
        incidental=((incidental_id, graph.nodes[incidental_id].name_en),),
    )
    assert bundle.per_point("CombinedDPS") == 50.0
    assert bundle.synergy("CombinedDPS") == 20.0
