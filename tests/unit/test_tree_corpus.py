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
        # `loaded_spec`·`compute_tree`는 데몬 계약의 일부다(#70 후속) — 트리만 바뀌는
        # 변형은 `compute_tree`로 간다. 가짜가 그걸 안 흉내 내면 계약이 어긋난다.
        loaded_spec = None

        def compute_build(self, spec):
            self.loaded_spec = spec
            return _Result()

        def compute_tree(self, _nodes):
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
    assert out["required"], "필수 후보가 비었다"
    assert all(r["count"].endswith(f"/{out['sample_n']}") for r in out["required"])
    assert out["off_corpus"], "코퍼스 밖 후보가 비면 새 선택의 재료가 없다"
    listed = {r["node"] for r in out["required"]} | {r["node"] for r in out["common"]}
    assert not (listed & {r["node"] for r in out["off_corpus"]}), "표본 노드가 밖으로 샜다"
    assert out["listed_from_count"] >= 1, "잘린 목록임을 안 밝히면 전량으로 읽힌다"


def test_필수_기준은_표본_크기에_매이지_않는다() -> None:
    """옛 기준 `count == n`은 **문턱이 표본 크기에 매여 있었다**.

    10/10의 「전원」은 하한 72.2짜리이고 50/50은 92.9짜리다 — 후자가 옳지만 훨씬
    드물어서, 표본을 10 → 50으로 올리자 클래스 22종 합계 앵커가 86 → 37개로 줄고
    워브링어·위치헌터·크로노맨서는 **0개**가 됐다. 같은 코퍼스가 표본만 커졌다고
    「필수가 사라진」 것처럼 보이는 것이라 규모 불변인 하한으로 바꿨다
    (사용자 판정 2026-08-16: `ci_low >= 80`).
    """
    from pok.engine.tree.corpus import suggest_anchors

    out = suggest_anchors(_graph, "Warbringer")
    assert out["min_ci_low"] == 80.0, "기준을 안 밝히면 「표본 전원」으로 읽힌다"
    assert out["required"], "옛 기준(count == n)에서 0개가 되던 클래스다"
    assert all(r["ci_low"] >= out["min_ci_low"] for r in out["required"])
    assert all(r["ci_low"] < out["min_ci_low"] for r in out["common"])


def test_필수_문턱은_인자로_되돌릴_수_있다() -> None:
    """「몇 %부터 필수인가」는 해석 층의 몫이다(철칙 3) — 코드에 박아 두면 되돌릴 때
    소리가 안 난다. 문턱을 올리면 목록이 좁아지는지로 그 경로를 잠근다."""
    from pok.engine.tree.corpus import suggest_anchors

    loose = suggest_anchors(_graph, "Martial Artist", min_ci_low=50.0)
    strict = suggest_anchors(_graph, "Martial Artist", min_ci_low=95.0)
    assert len(loose["required"]) > len(strict["required"])
    assert loose["min_ci_low"] == 50.0 and strict["min_ci_low"] == 95.0


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

    allocated, _ = _graph.connect_anchors("Monk", [asc_notable], ascendancy="Martial Artist")
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


def test_컨셉_키워드를_축별_앵커로_바꾼다() -> None:
    """사용자 지적 2026-08-12: "유저가 매번 어떤 노드를 포함하라고 알려줄 수는 없다.
    컨셉 논의에서 「치명타」·「회피」·「로우라이프」가 나왔으면 그걸로 잡을 수 없나."

    ⚠ **축을 따로 찾는 것이 요점**이다. 한 뭉치로 섞어 점수순으로 자르면 점수 높은
    축이 목록을 독점하고 나머지 축은 앵커를 못 받는다 — 그리디가 시작점 근처만
    훑던 실패가 후보 단계에서 재현된다.
    """
    from pok.engine.tree.corpus import anchors_for_axes

    axes = {
        "주문 치명타": {
            "include": [("critical", 2.0), ("spell", 1.5)],
            "exclude": ["attack", "melee", "bow"],
        },
        "회피": {"include": [("evasion", 2.0)]},
        "로우라이프": {"include": [("low life", 3.0)]},
    }
    out = anchors_for_axes(_graph, "Blood Mage", axes)
    assert set(out["per_axis"]) == set(axes), "축 하나라도 빠지면 그 축은 앵커가 없다"
    for axis, hits in out["per_axis"].items():
        assert hits, f"{axis}에 후보가 없는데 조용하다"
    assert out.get("axes_with_no_hit") is None
    # **값을 매겨서 준다** — 몇 포인트 드는지 모르면 앵커를 고를 수 없다
    assert out["cost"]["points"] > 0 and out["cost"]["diagonal"] > 0
    assert out["cost"]["class"] == "Witch", "전직 실명에서 기본 클래스를 못 풀었다"


def test_제외어가_피해_유형을_가른다() -> None:
    """문구 매칭은 빌드의 피해 유형을 모른다 — 주문 빌드에 「치명타」만 주면
    근접 공격 노터블이 상위를 차지한다(실측 2026-08-12: Blade Flurry·Martial Artistry)."""
    from pok.engine.tree.corpus import anchors_for_axes

    plain = anchors_for_axes(_graph, "Blood Mage", {"치명타": [("critical", 2.0)]}, per_axis=6)
    filtered = anchors_for_axes(
        _graph,
        "Blood Mage",
        {"치명타": {"include": [("critical", 2.0)], "exclude": ["attack", "melee", "bow"]}},
        per_axis=6,
    )
    assert {h["node"] for h in plain["per_axis"]["치명타"]} != {
        h["node"] for h in filtered["per_axis"]["치명타"]
    }, "제외어가 후보를 전혀 바꾸지 못했다"


def test_축을_코퍼스에서_스스로_찾는다() -> None:
    """사용자 지적 2026-08-12: "결국 사용자가 어떤 노드를 찍어라 지시해야만 동작하고
    자발적으로 찾지는 못하는 것 아닌가."

    맞는 지적이었다 — `anchors_for_axes`는 축을 **선언하면** 노드로 바꾸는 변환기였다.
    축 자체는 코퍼스에 있다: 표본이 찍은 목적지의 효과 문구를 채택 수로 가중해 세면
    그 전직이 무엇을 챙기는지가 나온다(실측: 마셜 아티스트 → damage·critical·
    speed·attack·evasion / 스톰위버 → mana·elemental·energy·shield).
    """
    from pok.engine.tree.corpus import discover_axes

    out = discover_axes(_graph, "Martial Artist")
    assert out["axes"], "축을 하나도 못 뽑았다"
    assert "critical" in out["axes"], "표본이 명백히 챙기는 축이 빠졌다"
    weights = [w for a in out["axes"].values() for _, w in a["include"]]
    assert max(weights) > min(weights), "가중치가 평평하면 한 축이 후보를 독점한다"


def test_피해_유형_제외어도_코퍼스가_준다() -> None:
    """단어 하나짜리 축("critical")은 유형 문맥이 없어 주문 빌드에 근접 공격
    노터블을 물어 온다(실측: 블러드 메이지의 critical 상위가 Blade Flurry였다).
    표본이 spell을 챙기면 공격 계열을, attack을 챙기면 주문 계열을 뺀다."""
    from pok.engine.tree.corpus import discover_axes

    caster = discover_axes(_graph, "Blood Mage")["damage_kind_exclude"]
    attacker = discover_axes(_graph, "Martial Artist")["damage_kind_exclude"]
    assert "attack" in caster and "melee" in caster
    assert "spell" in attacker
    assert "attack" not in attacker


def test_키워드_없이도_앵커까지_나온다() -> None:
    """이게 「자발적으로 찾는다」의 실체다 — 전직 이름만 주면 앵커와 비용이 나온다."""
    from pok.engine.tree.corpus import suggest_anchors

    out = suggest_anchors(_graph, "Martial Artist")
    assert "discovered_axes" in out, "축을 스스로 못 찾았다"
    by_axis = out["by_axis"]
    assert by_axis["proposed_anchors"], "앵커 제안이 비었다"
    assert by_axis["cost"]["points"] > 0, "값을 안 매기면 앵커를 고를 수 없다"


def test_소켓을_채택률_근거로_앵커에_올린다() -> None:
    """빈 소켓은 델타 0이라 **점수로는 절대 안 뽑힌다** — 먼 목적지와 같은 성질이고
    같은 해법(근거를 들어 먼저 박기)이 필요하다.

    전원 공통만 쓰면 모자란다. 소켓은 자리마다 갈려 개별 채택률이 낮아도 **빌드당
    개수는 일정**하기 때문이다(실측 2026-08-12: 마셜 아티스트 중앙 4 대 전원공통 3,
    스톰위버 5 대 3, **블러드 메이지 8 대 4**). 그래서 표본 중앙 개수까지 채운다 —
    지어낸 임계값이 아니라 표본이 실제로 쓰는 개수다.
    """
    from pok.engine.tree.corpus import suggest_anchors

    for asc in ("Martial Artist", "Blood Mage", "Stormweaver"):
        s = suggest_anchors(_graph, asc)["sockets"]
        assert s["sample_median"] > 0, f"{asc}: 표본 소켓 개수를 못 읽었다"
        assert len(s["proposed"]) >= len(s["unanimous"]), "제안이 전원공통보다 적다"
        assert len(s["proposed"]) >= min(s["sample_median"], len(s["adoption"]))
        assert "optimize_rare" in s["note"], "내용을 만드는 도구를 안 가리킨다"
        assert "측정이 아니다" in s["note"], "코퍼스 근거임을 안 밝혔다"


def test_블러드_메이지_전직_노드가_연결된다() -> None:
    """실측 2026-08-12: 형제 전직 5종은 링크돼 있는데 블러드 메이지(59822)만 빠져
    있어 그 전직 노터블이 클래스 시작에서 **아예 닿지 않았다** —
    `connect_anchors`가 「연결 불가 타깃」으로 터졌다. 0.5 실가동 22종 중 유일했다.
    """
    # ⚠ 8415(Sanguimancy)는 이 전직의 **공짜 노드**라 `allocated`에 안 실린다(포인트를
    #   안 쓰므로). 도달성과 적재는 다른 질문이다 — 섞으면 공짜 노드 처리가 회귀해도
    #   이 시험이 못 잡거나, 반대로 정상 동작을 실패로 읽는다.
    for node_id in (26383, 56162):  # Sunder the Flesh · Grasping Wounds
        allocated, _paths = _graph.connect_anchors("Witch", [node_id], ascendancy="Blood Mage")
        assert node_id in allocated, f"{node_id}에 닿지 못했다"

    # Sanguimancy는 터지지 않고(=닿고) 포인트로는 세지 않는 것이 정답이다.
    allocated, _paths = _graph.connect_anchors("Witch", [8415], ascendancy="Blood Mage")
    assert 8415 not in allocated, "공짜 노드를 포인트로 세면 예산이 틀어진다"


def test_전직_포인트는_일반_예산을_갉지_않는다() -> None:
    """#68: 어센던시 포인트는 인게임에서 **별도 풀**인데 합쳐 세고 있었다.

    전직 노드를 앵커에 넣을수록 일반 트리 예산이 줄어 트리가 작아졌다 — 포인트를
    근거로 한 판단(예산 초과 경고·포인트당 효율)이 그만큼 틀렸다. 합산으로 되돌아가면
    여기서 걸린다.
    """
    from pok.engine.tree.optimize import _seed_anchors
    from pok.pob.buildxml import BuildSpec

    spec = BuildSpec(class_name="Witch", ascendancy="Blood Mage")
    asc_notable = 26383  # Sunder the Flesh — 전직 노터블
    _seeded, _notes, cost = _seed_anchors(spec, _graph, (asc_notable,), 30)

    assert cost.ascendancy >= 1, "전직 노드를 전직 풀로 세지 않았다"
    assert asc_notable not in _general_nodes(_seeded), "전직 노터블이 일반 풀에 섞였다"
    # 일반 풀에는 **본 트리 통행 노드만** 남아야 한다.
    assert cost.general == len(
        [n for n in _seeded.tree_nodes if _graph.nodes[n].ascendancy is None]
    ), "일반 포인트 수가 본 트리 노드 수와 어긋난다"


def _general_nodes(spec: object) -> set[int]:
    """스펙의 트리 노드 중 전직 소속이 아닌 것."""
    return {
        n
        for n in spec.tree_nodes  # type: ignore[attr-defined]
        if _graph.nodes[n].ascendancy is None
    }


# ── 앵커 후보에 제거 실측이 붙는다 (#77 · M4) ──
#
# 채택률은 「많이 찍혔다」까지만 말한다. NodeValue(빼면 얼마나 아픈가)를 나란히
# 놓아야 「전원이 찍지만 빼도 안 아픈」 메타 습관이 드러난다 — 갈아탈 예산이다(#62).


def _nv(node_id: int, axes: dict) -> object:
    """가짜 NodeValue 레코드 — store.Record와 같은 표면(type·raw)만 흉내낸다."""

    class _R:
        type = "NodeValue"
        raw: ClassVar[dict] = {
            "data": {"node": {"node_id": node_id}, "sample": {"n": 50}, "axes": axes}
        }

    return _R()


def _ax(median: float, when_active: float, *, n: int = 50, n_active: int = 25) -> dict:
    return {
        "n": n,
        "n_active": n_active,
        "loss_pct": {"median": median},
        "active_share": n_active / n * 100,
        "when_active": {"median": when_active},
    }


def test_습관과_조건부가_다르게_표시된다() -> None:
    """⛔ 뭉친 중앙값만 보면 조건부를 습관으로 오독한다(#88 — Mind Over Matter는
    전체 중앙 0%인데 작동할 땐 36.6%). 습관으로 읽고 빼면 그 메커니즘을 쓰는
    빌드가 무너진다."""
    from pok.engine.tree.corpus import _removal_summary

    _s, mark = _removal_summary(
        {"sample": {"n": 50}, "axes": {"CombinedDPS": _ax(0.0, 0.1)}}, habit_max_loss=0.5
    )
    assert mark == "habit"
    _s, mark = _removal_summary(
        {"sample": {"n": 50}, "axes": {"CombinedDPS": _ax(0.0, 36.6)}}, habit_max_loss=0.5
    )
    assert mark == "conditional", "조건부가 습관으로 읽힌다"
    _s, mark = _removal_summary(
        {"sample": {"n": 50}, "axes": {"CombinedDPS": _ax(12.0, 20.0)}}, habit_max_loss=0.5
    )
    assert mark is None, "아픈 노드에 표시가 붙었다"


def test_표본이_적으면_판정하지_않는다() -> None:
    """n<10이면 표시를 유보한다 — 값은 싣되 「습관」 도장은 안 찍는다."""
    from pok.engine.tree.corpus import _removal_summary

    summary, mark = _removal_summary(
        {"sample": {"n": 3}, "axes": {"CombinedDPS": _ax(0.0, 0.0, n=3, n_active=0)}},
        habit_max_loss=0.5,
    )
    assert mark is None and summary["axes"] == {}


def test_제거_실측이_정본에서_붙는다() -> None:
    """NodeValue가 정본에 승격됐다(2026-08-20) — 휴면이던 부착 경로가 실데이터로
    켜졌는지 잠근다. 없어지면(레코드 삭제 등) 부재 선언 경로가 받는다 — 그 경로는
    아래 monkeypatch 시험이 별도로 잠근다."""
    from pok.engine.tree.corpus import suggest_anchors

    out = suggest_anchors(_graph, "Blood Mage")
    assert out["removal_source"] is not None and "NodeValue" in out["removal_source"]
    rows = [r for r in out["required"] if r.get("removal")]
    assert rows, "required에 제거 실측이 하나도 안 붙었다"


def test_NodeValue가_없으면_채택률만으로_골랐다고_말한다(monkeypatch) -> None:
    """⛔ 조용한 0 금지 — NodeValue가 없는 KB(다른 시즌·초기 셋업)에서는 이 선언이
    없으면 「빼도 아픈지 확인된 후보」로 읽힌다."""
    import pok.kb.store as store
    from pok.engine.tree.corpus import suggest_anchors

    real = store.load()

    class _Bare:
        records: ClassVar[dict] = {k: v for k, v in real.records.items() if v.type != "NodeValue"}

    monkeypatch.setattr(store, "load", lambda root=None: _Bare)
    out = suggest_anchors(_graph, "Martial Artist")
    assert out["removal_source"] is None
    assert "채택률만으로" in out["removal_why"]


def test_NodeValue가_있으면_행에_붙고_습관이_모인다() -> None:
    from pok.engine.tree.corpus import _node_values, _removal_summary

    records = {"a": _nv(13828, {"CombinedDPS": _ax(0.0, 0.1)})}
    values = _node_values(records)
    assert 13828 in values
    summary, mark = _removal_summary(values[13828], habit_max_loss=0.5)
    assert mark == "habit" and summary["n"] == 50


def test_행_부착과_습관_수집이_끝까지_흐른다(monkeypatch) -> None:
    """suggest_anchors 반환에 실제로 실리는지 — 헬퍼만 통과하고 부착이 빠지면
    규율이 통째로 사라진다(이 파일 머리주석과 같은 이유)."""
    import pok.kb.store as store
    from pok.engine.tree.corpus import suggest_anchors

    real = store.load()

    # 이 전직의 실존 required 노드를 하나 집는다 — 하드코딩하면 프로파일 재생성에 깨진다
    target = suggest_anchors(_graph, "Martial Artist")["required"][0]["node"]

    class _Fake:
        # 실제 NodeValue는 뺀다 — 정본 승격(2026-08-20) 후에도 이 시험은 주입한
        # 한 건만으로 흐름을 판정해야 밀폐된다(실데이터가 바뀌면 같이 흔들린다)
        records: ClassVar[dict] = {k: v for k, v in real.records.items() if v.type != "NodeValue"}

    _Fake.records["node-value.test"] = _nv(target, {"CombinedDPS": _ax(0.0, 0.1)})  # type: ignore[index]
    monkeypatch.setattr(store, "load", lambda root=None: _Fake)

    out = suggest_anchors(_graph, "Martial Artist")
    assert out["removal_source"] is not None
    (row,) = [r for r in out["required"] if r["node"] == target]
    assert row["removal"]["n"] == 50
    assert row.get("removal_mark") == "habit"
    assert any(str(target) in h for h in out["meta_habits"]), "required인 습관이 안 모였다"
    # 측정이 없는 행은 None으로 **선언**된다 — 비워 두면 0으로 읽힌다
    others = [r for r in (*out["required"], *out["common"]) if r["node"] != target]
    assert all(r["removal"] is None for r in others)


def test_흡수_노드는_habit로_찍히지_않는다() -> None:
    """⛔ 이 도구가 낸 **가장 위험한 오류**의 회귀 고정 (사용자 지적 2026-08-20).

    `Vitality Siphon`("20% of Spell Damage Leeched as Life", 블러드 메이지 채택
    67%)이 habit으로 찍혀 「갈아탈 예산」 제안이 나갔다. 블러드 메이지는
    `Sanguimancy`로 **생명력을 내고 시전**하므로 흡수를 빼면 유지가 무너진다 —
    그런데 재는 축(DPS·최대생명·정적 EHP)엔 흡수가 안 잡혀 「빼도 0」이 된다.

    「못 쟀다」를 「가치 없다」로 뒤집는 것이 철칙 4 위반이다.
    """
    from pok.engine.tree.corpus import _removal_summary, unmeasured_axis

    leech = ["20% of Spell Damage Leeched as Life"]
    assert unmeasured_axis(leech), "흡수 문구를 못 잡았다"

    value = {"sample": {"n": 40}, "axes": {"CombinedDPS": _ax(0.0, 0.0, n_active=0)}}
    _s, mark = _removal_summary(value, habit_max_loss=0.5)
    assert mark == "habit", "문구가 없으면 예전대로 habit이어야 한다(대조군)"

    summary, mark = _removal_summary(value, habit_max_loss=0.5, stats_en=leech)
    assert mark is None, "흡수 노드가 여전히 habit으로 찍힌다"
    assert "흡수" in summary["unmeasured_axis"], "왜 봉인했는지가 안 남는다"


def test_실제_Vitality_Siphon이_봉인된다() -> None:
    """가짜 문구가 아니라 **정본 노드**로 잠근다 — KB가 바뀌면 여기서 걸린다."""
    from pok.engine.tree.corpus import unmeasured_axis

    node = _graph.nodes[23416]
    assert node.name_en == "Vitality Siphon"
    assert unmeasured_axis(node.stats_en)


def test_봉인_어휘는_넓게_잡는다() -> None:
    """⚠ 비대칭이 설계 근거다 — 잘못 봉인하면 「판정 안 함」으로 끝나지만(싸다),
    잘못 habit을 찍으면 **빌드가 무너지는 제안**이 나간다(비싸다)."""
    from pok.engine.tree.corpus import unmeasured_axis

    for text in (
        "Regenerate 2% of maximum Life per second",
        "Recoup 15% of Damage taken",
        "Reserves 25% of Spirit",
        "10% reduced Mana Cost of Skills",
        "Gain 1 Power Charge on Kill",
        "20% increased Movement Speed",
    ):
        assert unmeasured_axis([text]), f"안 걸렸다: {text}"


# ── 조건부 필요성 판정 큐 (사용자 지시 2026-08-20) ──


def test_필요성_큐가_전제를_뒤집는다() -> None:
    """⛔ 「측정 0 = 가치 없음」이 아니라 **「축을 못 잡았다」**다.

    사용자 정리: 「패시브 노드에 가치 없는 노드는 없다 — 중요도가 낮은 노드는
    있어도」. 그래서 이 큐는 **판정 대상**이지 제거 후보 목록이 아니다.
    """
    from pok.engine.node_necessity import build_queue

    queue = build_queue(min_adoption=50.0)
    assert queue, "채택 50 이상인데 측정 0인 노드가 하나도 없다 — 큐 생성이 깨졌다"
    assert all(c.adoption_ci_low >= 50.0 for c in queue)


def test_흡수_노드가_요구원과_함께_큐에_온다() -> None:
    """판정에 필요한 재료(제공 축 + 요구 기재 + 근거 문구)가 갖춰지는지."""
    from pok.engine.node_necessity import classify_supply, demand_carriers
    from pok.kb.store import load

    node = _graph.nodes[23416]  # Vitality Siphon (Witch2)
    axis = classify_supply(node.stats_en)
    assert axis == "생명력 흡수"
    got = demand_carriers(axis, load().records, for_ascendancy=node.ascendancy)
    # ⚠ 같은 전직 기재가 먼저 와야 한다 — 전 KB 사전순이면 유니크들에 밀린다
    assert got[0]["name"] == "Sanguimancy", f"요구원이 1순위가 아니다: {got[0]['name']}"
    assert "Life Cost" in got[0]["evidence"]


def test_축을_못_잡으면_그렇다고_낸다() -> None:
    """⛔ 지어내지 않는다 — 분류 실패는 **어휘 갭**이고, 그 사실이 산출물이다."""
    from pok.engine.node_necessity import classify_supply

    assert classify_supply(["완전히 새로운 무언가"]) is None


def test_근거_없는_판정은_거부한다() -> None:
    """⛔ 「기계적으로 안 되는 것은 LLM이 판단한다」(사용자 2026-08-20) — 단, 판단에는
    **출처**가 붙어야 한다. 근거 없는 판정이 정본에 굳으면 그게 오염이다."""
    import pytest

    from pok.engine.node_necessity import NecessityError, validate_verdict

    base = {
        "node_id": 23416,
        "verdict": "생명력으로 시전하는 빌드는 흡수 없이 유지가 안 된다",
        "counter": "생명력 비용 기재가 없으면 불필요",
        "evidence": [
            {
                "source": "kb",
                "ref": "passive.sanguimancy-8415",
                "quote": "Skills gain a Base Life Cost equal to Base Mana Cost",
            }
        ],
    }
    assert validate_verdict(base)["node_id"] == 23416

    for drop in ("verdict", "counter", "evidence"):
        with pytest.raises(NecessityError, match=r"근거 경로 없는|없다"):
            validate_verdict({**base, drop: None})
    with pytest.raises(NecessityError, match="모르는 출처"):
        validate_verdict({**base, "evidence": [{"source": "vibes", "ref": "x"}]})
    with pytest.raises(NecessityError, match="되짚을 수 없는"):
        validate_verdict({**base, "evidence": [{"source": "kb", "ref": ""}]})


def test_측정_가능한_축은_config로_표시된다() -> None:
    """⚠ 「못 재는 것」과 「안 켠 것」은 다르다 — 실측: `Predatory Instinct`
    ("50% more damage against Rare and Unique")는 PoB가 계산할 수 있는데 config가
    꺼져 0으로 나왔다. 묶어 버리면 켜서 잴 수 있는 것을 영영 안 잰다."""
    from pok.engine.node_necessity import build_queue

    queue = build_queue(min_adoption=20.0)
    assert all(c.ready for c in queue), "축을 못 잡은 노드가 남았다 — 어휘 갭"
    assert any(c.measurable_via == "config" for c in queue), "config 경로 표시가 사라졌다"


def test_큐가_오염_포함본까지_본다() -> None:
    """⛔ 제외본의 0이 「표본을 버린 뒤의 0」인 경우가 실제로 39건 있었다(#99) —
    Invigorating Archon은 잔존 7.4%인데 오염을 포함하면 작동률 92.0%다.

    그걸 「축을 못 잡았다」로 큐에 넣으면 에이전트가 **없는 수수께끼**를 푼다.
    실측 2026-08-21: 이 필터로 큐가 89 → 58건이 됐다.
    """
    from pok.engine.node_necessity import build_queue

    queue = build_queue(min_adoption=20.0)
    for case in queue:
        kept = case.measured.get("kept_pct")
        assert kept is None or kept >= 0
    names = {c.name_en for c in queue}
    assert "Invigorating Archon" not in names, (
        "오염 포함본에서 작동하는 노드가 「측정 0」 큐에 남았다"
    )


def test_동어반복_채택률을_안_센다() -> None:
    """⛔ `keypassives-<노드>` 프로파일은 **그 노드를 가진 빌드만** 뽑은 표본이라
    자기 채택률 100%는 정의상 참이다(판정 배치 B가 잡았다).

    실측: `Unwavering Stance`는 그 표본에서 ci_low 92.9로 「전원 채택」처럼 보이지만
    **트리 배정은 42%**이고 58%는 룬·장비로 받는다.
    """
    from pok.engine.node_necessity import build_queue

    names = {c.name_en for c in build_queue(min_adoption=90.0)}
    assert "Unwavering Stance" not in names, "동어반복 채택률이 큐에 들어왔다"


def test_면역과_제약을_가른다() -> None:
    """`Cannot be X`(면역 = 이득) vs `Cannot X`(제약 = 대가) — 수동태면 면역이다.
    구별 못 하면 대가 줄에서 축을 뽑아 **비용을 공급으로 오독**한다."""
    from pok.engine.node_necessity import classify_supply

    assert classify_supply(["Cannot be Light Stunned", "Cannot Dodge Roll or Sprint"]) == "면역"
    assert classify_supply(["20% increased Movement Speed"]) == "이동"


def test_큐가_전_축을_본다() -> None:
    """⛔ DPS·EHP만 보면 축 확장(#100)의 이득이 큐에 반영되지 않는다.

    실측 2026-08-22: 축을 13개로 넓혀 `Vitality Siphon`이 `LifeLeechGainRate`
    55벌 전부 100% 손실로 잡혔는데도, 필터가 DPS·EHP만 봐서 「측정 0」 큐에 그대로
    남았다 — 6시간 재측정의 이득이 큐에서 증발할 뻔했다. 전 축 반영으로 59 → 37건.
    """
    from pok.engine.node_necessity import build_queue

    ids = {c.node_id for c in build_queue(min_adoption=20.0)}
    assert 23416 not in ids, "흡수 축에서 값이 난 노드가 「측정 0」 큐에 남았다"
