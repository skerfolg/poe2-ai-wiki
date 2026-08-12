"""트리 대조가 강제 지점에서 자동으로 붙는지 잠근다 (#67 6차).

새 도구를 만들고 문서에 "쓰세요"라고 적는 방식은 이 레포에서 실패가 증명됐다.
그래서 **트리를 짜려면 반드시 지나가는 지점**의 반환값에 붙였고, 그게 유지되는지
여기서 잠근다 — 이 부착이 조용히 빠지면 규율이 통째로 사라진다.
"""

from __future__ import annotations

from typing import ClassVar

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


def test_실제_경로에서_부수_획득을_뽑는다(monkeypatch) -> None:
    """앞 시험은 자료구조만 봤다 — 실제 경로에서 추출되는지는 별개 문제다.

    PoB 데몬 없이 돌리려고 계산만 가짜로 세운다(경로·부수 획득은 진짜 그래프에서 나온다).
    """
    from pok.engine.tree.deltas import evaluate_bundles
    from pok.pob.buildxml import BuildSpec

    spec = BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=())

    class _Result:
        stats: ClassVar[dict[str, float]] = {"CombinedDPS": 100.0}
        pruned_nodes = ()

    class _Daemon:
        def compute_build(self, _spec):
            return _Result()

        def close(self) -> None:
            pass

    # 주얼 소켓(목적지)을 경유해야 닿는 노드를 타깃으로 고른다
    socket = 21984
    neighbours = [n for n in _graph.adj[socket] if _graph.nodes[n].kind == "small"]
    assert neighbours, "주얼 소켓에 인접한 스몰이 없다 — 표본 선택을 다시 할 것"

    out = evaluate_bundles(
        spec,
        _graph,
        [{"name": "t", "nodes": [socket]}],
        stats=("CombinedDPS",),
        daemon=_Daemon(),
    )
    assert out and out[0].points > 0
    got = {n for n, _ in out[0].incidental}
    assert socket not in got, "요청한 타깃 자신은 부수 획득이 아니다"
    assert got <= set(out[0].path), "경로 밖 노드가 부수 획득으로 잡혔다"


def test_표본_밖_목적지를_지적하지_않는다() -> None:
    """한때 넣었다가 뺀 필드다 — 되돌아오면 정상 트리를 깎는 압력이 된다.

    프로파일 목록은 `min_count`(기본 3)로 꼬리가 잘려 있어 「표본에 없다」를 판정할 수
    없다. 실측 2026-08-12: 잘린 목록으로 대조하니 **표본 밖의 멀쩡한 래더 빌드가
    목적지 41개 중 20개(49%)**를 「표본 밖」으로 찍혔다. 경고 꼴 필드는 지워서 없애고
    싶어지는 법이라, 그 상태로 뒀으면 좋은 노드를 빼는 방향으로 작동했을 것이다.
    """
    out = compare_tree(_graph, "Monk", {13828, 10131}, ascendancy="Martial Artist")
    assert "off_corpus_destinations" not in out
    assert "범위" in out["note"], "코퍼스가 범위가 아니라는 선언이 사라졌다"


def test_잘린_목록임을_레코드가_밝힌다() -> None:
    """안 밝히면 읽는 쪽이 전량으로 읽는다(BACKLOG 형태 ①). 스키마가 강제하지만,
    **왜** 필수인지는 여기 남긴다 — 스키마만 보면 지워도 되는 필드처럼 보인다."""
    from pok.kb.store import load

    profiles = [r for r in load().records.values() if r.type == "UsageProfile"]
    assert profiles
    for record in profiles:
        assert "min_count" in record.raw["data"]["observed"]["sample"], record.id


def test_앵커_후보를_출처별로_갈라_낸다() -> None:
    """성격이 다른 넷을 한 목록으로 합치면 「표본이 찍은 것」과 「우리가 발굴한 것」이
    구별되지 않는다 — 그러면 근거를 남길 수 없다."""
    from pok.engine.tree.corpus import suggest_anchors

    out = suggest_anchors(
        _graph, "Martial Artist", include=[("Critical", 2.0), ("Attack Speed", 1.0)]
    )
    assert out["required"], "표본 전원이 찍는 목적지가 비었다"
    assert all(r["count"].endswith(f"/{out['sample_n']}") for r in out["required"])
    assert out["off_corpus"], "코퍼스 밖 후보가 비면 새 선택의 재료가 없다"
    listed = {r["node"] for r in out["required"]} | {r["node"] for r in out["common"]}
    assert not (listed & {r["node"] for r in out["off_corpus"]}), "표본 노드가 밖으로 샜다"
    assert out["listed_from_count"] >= 1, "잘린 목록임을 안 밝히면 전량으로 읽힌다"


def test_관련성_필터가_없으면_스캔하지_않고_말한다() -> None:
    """관련성 없는 밀집도는 쓰레기다 — 조용히 빈 목록을 주면 「없다」로 읽힌다."""
    from pok.engine.tree.corpus import suggest_anchors

    out = suggest_anchors(_graph, "Martial Artist")
    assert "off_corpus" not in out and "off_corpus_skipped" in out


def test_원시가_없으면_경고를_비우지_않고_사유를_남긴다() -> None:
    """`cautions`가 빈 배열이면 「지나친 것 없음」으로 읽힌다 — 못 읽은 것과 다르다."""
    from pok.engine.tree.corpus import _cautions

    out = _cautions({"query": {"class": "Nope"}, "season": "0.5"}, [("Cold", 1.0)])
    assert isinstance(out, dict) and "skipped" in out


def test_전직_시작_노드는_스펙에_싣지_않는다() -> None:
    """PoB가 전직 선택으로 **자동 할당**하므로 tree_nodes에 있으면 잘라낸다
    (`pruned_nodes`). 그런데 델타·묶음 측정은 pruned가 있으면 결과를 **통째로
    버린다** — 노드 하나 때문에 그 트리의 모든 측정이 무효가 되고, 그리디는
    후보가 전부 사라져 한 수도 못 뽑는다.

    실측 2026-08-12 e2e: 마셜 아티스트 앵커 11개를 박았더니 그리디가 0수였고,
    원인은 경로가 지나간 전직 시작 노드 11495 하나였다. **통행은 시키되 산출물에는
    싣지 않는다.**
    """
    from pok.engine.tree.optimize import _seed_anchors
    from pok.pob.buildxml import BuildSpec

    spec = BuildSpec(class_name="Monk", ascendancy="Monk1", tree_nodes=())
    # Way of the Stonefist 같은 전직 노터블은 전직 시작 노드를 통해서만 닿는다
    asc_notable = next(
        n.node_id for n in _graph.nodes.values() if n.ascendancy == "Monk1" and n.kind == "notable"
    )
    seeded, _, _ = _seed_anchors(spec, _graph, (asc_notable,), 30)
    assert asc_notable in seeded.tree_nodes, "전직 노터블 자체는 들어가야 한다"
    starts = [n for n in seeded.tree_nodes if _graph.nodes[n].kind == "ascendancy-start"]
    assert not starts, f"전직 시작 노드가 스펙에 섞였다: {starts}"

    allocated, _ = _graph.connect_anchors("Monk", [asc_notable])
    assert not [n for n in allocated if _graph.nodes[n].kind == "ascendancy-start"], (
        "connect_anchors의 allocated에도 섞이면 안 된다 — "
        "그걸 스펙에 넣는 세션이 같은 함정에 빠진다"
    )


def test_표본보다_좁은_트리를_알린다() -> None:
    """사용자 지적 2026-08-12: "빌드에 따라 좌측 끝과 우측 끝으로 넓게 찍어야 하는
    경우가 있다"(로우라이프 「고통의 조율」 + 회피 「강화 반사신경」은 좌표상
    (-8288,-6379)과 (+9390,+580) — 정반대다. 주문·공격·일반 치명타 3계열도 마찬가지).

    그리디는 도중 노드 점수가 낮으면 **출발하지 않으므로** 시작점 근처만 훑는다.
    실측: 래더 대각선 중앙 27,041인데 우리 산출물은 20,005였고, 그리디는 30포인트를
    더 쓰고 폭을 11%만 늘렸다. 좁다고 틀린 건 아니지만 **말은 해야 한다**.
    """
    tiny = {13828, 10131, 21984}
    out = compare_tree(_graph, "Monk", tiny, ascendancy="Martial Artist")
    assert out["compared"] is True
    width = out["width"]
    assert width["ours"] < width["sample"]["min"], "표본보다 좁은 트리를 골랐어야 한다"
    assert "narrower_than_every_sample" in width
    assert "required_anchors" in width["narrower_than_every_sample"], (
        "좁다고만 하면 뭘 해야 할지 모른다 — 먼 목적지는 앵커로 지정해야 한다고 알려야 한다"
    )


def test_폭_기준선이_프로파일에_실려_있다() -> None:
    """`tree_shape.diagonal`이 없으면 대조기가 폭을 판정할 수 없다 —
    스키마가 강제하지만 **왜** 필요한지는 여기 남긴다."""
    from pok.kb.store import load

    for record in load().records.values():
        if record.type != "UsageProfile":
            continue
        diag = record.raw["data"]["tree_shape"]["diagonal"]
        assert diag["min"] <= diag["median"] <= diag["max"], record.id
        assert diag["min"] > 0, f"{record.id}: 폭이 0이면 기준선으로 못 쓴다"
