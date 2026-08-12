"""짠 트리를 **래더 코퍼스와 대조**한다 (#67 6차, 사용자 승인 2026-08-12).

**왜 별도 도구가 아니라 대조인가**: 새 도구를 만들고 "이걸 쓰세요"라고 문서에 적는
방식은 이 레포에서 이미 실패가 증명됐다(문서에만 있던 규율은 인용까지 하고도
어겨졌다 — 철칙 5). 세션은 새 도구를 **몰라서 안 부른다**. 그래서 여기 있는 것을
`connect_anchors`처럼 **트리를 짜려면 반드시 지나가는 지점**의 반환값에 자동으로
붙인다. 그러면 프로파일의 존재를 몰라도 경고를 본다.

⛔ **판정이 아니라 대조다.** "표본 10벌 전원이 찍는 노드를 당신은 안 넣었다"까지가
출력이고, 넣을지 말지는 설계 세션이 정한다. 임계값을 코드에 박으면 그게 곧 해석이고,
표본 10벌에서 조용히 틀린다(철칙 3).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from pok.engine.tree.graph import TreeGraph


def _profiles_by_class(records: dict[str, Any], graph: TreeGraph) -> dict[str, Any]:
    """전직 실명(casefold) → 가장 최근 시즌의 C군 프로파일 레코드.

    시즌을 코드에 박지 않는다 — 0.6이 오면 프로파일이 새로 쌓이는데 박아 두면
    조용히 옛 시즌과 대조한다.
    """
    out: dict[str, tuple[str, Any]] = {}
    for record in records.values():
        if record.type != "UsageProfile":
            continue
        data = record.raw.get("data") or {}
        name = (data.get("query") or {}).get("class")
        if not name:
            continue
        key = str(graph.resolve_ascendancy(str(name))).casefold()
        season = str(data.get("season") or "")
        if key not in out or season > out[key][0]:
            out[key] = (season, record)
    return {k: v[1] for k, v in out.items()}


_graph: TreeGraph | None = None


def _shared_graph() -> TreeGraph:
    """대조용 그래프 1벌. 출고 경로에서 매번 새로 만들면 KB를 통째로 다시 읽는다."""
    global _graph
    if _graph is None:
        from pok.common.paths import knowledge_dir

        _graph = TreeGraph(knowledge_dir())
    return _graph


def compare_build_spec(build_spec: dict[str, Any]) -> dict[str, Any]:
    """빌드 스펙(클래스·전직·트리)을 그대로 받아 대조한다 — 출고 지점용 얇은 입구."""
    nodes = build_spec.get("tree_nodes") or ()
    return compare_tree(
        _shared_graph(),
        str(build_spec.get("class_name") or ""),
        {int(n) for n in nodes},
        ascendancy=str(build_spec.get("ascendancy") or "") or None,
    )


def _cautions(data: dict[str, Any], include: Sequence[tuple[str, float]]) -> Any:
    """「코앞에 두고도 버려진 것」 — 앵커 후보에 헛다리가 섞이는 걸 막는다.

    원시 코퍼스(`artifacts/`)를 읽으므로 다른 PC에는 없을 수 있다. 없다고 조용히
    비우면 "경고 없음"으로 읽히므로 사유를 담아 돌려준다.
    """
    if not include:
        return {"skipped": "include가 없어 관련성 필터를 못 걸었다"}
    query = data.get("query") or {}
    if not query:
        return {"skipped": "프로파일에 질의가 없어 원시 폴더를 특정할 수 없다"}
    key, value = next(iter(query.items()))
    concept = f"{key}-{str(value).replace(' ', '_')}"
    season = str(data.get("season", "")).replace(".", "-")
    try:
        from pok.engine.ladder_aggregate import passed_over

        rows = passed_over(season, concept, include=list(include))["rows"]
    except Exception as exc:  # 원시 없음·폴더명 불일치 등 — 조용히 비우지 않는다
        return {"skipped": f"원시 코퍼스를 못 읽었다: {type(exc).__name__} {exc}"}
    return [
        {
            "node": r["node"],
            "name": r["name"],
            "passed_by": r["passed_by"],
            "taken_by": r["taken_by"],
        }
        for r in rows
        if r["taken_by"] == 0
    ][:10]


def _base_class(graph: TreeGraph, ascendancy: str) -> str | None:
    """전직 실명 → 기본 클래스("Martial Artist" → "Monk").

    `connect_anchors`는 기본 클래스에서 출발하는데 컨셉 논의는 전직 이름으로 한다.
    전직 시작 노드의 내부 코드("Monk1")에서 숫자를 떼면 그게 기본 클래스다.
    """
    from pok.engine.tree.graph import CLASS_START

    want = str(graph.resolve_ascendancy(ascendancy)).casefold()
    for node in graph.nodes.values():
        if node.kind != "ascendancy-start" or not node.ascendancy:
            continue
        if node.name_en.casefold() != want:
            continue
        base = str(node.ascendancy).rstrip("0123456789")
        return base if base in CLASS_START else None
    return None


def anchors_for_axes(
    graph: TreeGraph,
    ascendancy: str,
    axes: Mapping[str, Any],
    *,
    per_axis: int = 3,
) -> dict[str, Any]:
    """**컨셉 키워드 → 앵커 후보.** 축마다 따로 찾아 하나도 빠뜨리지 않는다.

    사용자 지적 2026-08-12: "유저가 매번 어떤 노드를 포함하라고 직접 알려줄 수는
    없다. 컨셉 논의에서 「치명타」·「회피」·「로우라이프」가 나왔으면 그걸로 필수
    노드를 잡을 수 없나."

    할 수 있고, 이게 그 층이다. **경계는 지킨다** — *어떤 축이 중요한가*는 판단
    (컨셉 논의)이라 호출자가 주고, *그 축이 트리 어디에 있나*는 결정적 계산이라
    여기서 한다(AD-3).

    ⚠ **축마다 따로 찾는 것이 요점이다.** 한 뭉치로 섞어 점수순으로 자르면 점수가
    높은 축이 목록을 독점하고 나머지 축은 앵커를 못 받는다 — 그리디가 시작점
    근처만 훑던 것과 같은 실패가 후보 단계에서 재현된다.

    축은 두 꼴을 받는다:
    - `{"치명타": [("critical", 2.0)]}` — 포함어만
    - `{"치명타": {"include": [("critical", 2.0)], "exclude": ["attack", "melee"]}}`

    **제외어가 있어야 쓸 만해진다.** 실측 2026-08-12: 주문 빌드(블러드 메이지)에
    「치명타」만 주니 근접 공격 노터블(Blade Flurry·Martial Artistry)이 상위를
    차지했다 — 문구 매칭은 빌드의 피해 유형을 모른다.

    ⛔ 효과 문구는 **영어로만** 매칭된다(KB 한글 보유율: Passive 19%). 키워드는
    게임 표기 영어로 줄 것.
    """
    who = str(graph.resolve_ascendancy(ascendancy))
    from pok.engine.tree.clusters import find_clusters

    per_axis_hits: dict[str, list[dict[str, Any]]] = {}
    chosen: list[int] = []
    empty: list[str] = []
    for axis, spec in axes.items():
        terms = spec.get("include", ()) if isinstance(spec, Mapping) else spec
        exclude = tuple(spec.get("exclude", ())) if isinstance(spec, Mapping) else ()
        if not terms:
            empty.append(axis)
            continue
        seen: dict[int, dict[str, Any]] = {}
        for cluster in find_clusters(
            graph,
            include=[(str(k), float(w)) for k, w in terms],
            exclude=exclude,
            top=3,
            for_ascendancy=who,
            min_score=0.5,
        ):
            for hit in cluster.hits:
                seen.setdefault(
                    hit.node_id,
                    {"node": hit.node_id, "name": hit.name_en, "score": hit.score},
                )
        ranked = sorted(seen.values(), key=lambda h: (-h["score"], h["node"]))[:per_axis]
        per_axis_hits[axis] = ranked
        if not ranked:
            empty.append(axis)
        chosen.extend(h["node"] for h in ranked if h["node"] not in chosen)

    out: dict[str, Any] = {
        "ascendancy": who,
        "per_axis": per_axis_hits,
        "proposed_anchors": chosen,
    }
    if empty:
        # 조용히 빠지면 "그 축은 트리에 없다"로 읽힌다 — 키워드가 안 맞은 것일 수 있다.
        out["axes_with_no_hit"] = empty
    base = _base_class(graph, who)
    if base and chosen:
        # **값을 매겨서 준다.** 몇 포인트가 드는지 모르면 앵커를 고를 수 없다 —
        # 실측: 치명타 3계열 6개가 86포인트(래더 중앙 폭과 동급)였다.
        allocated, _paths = graph.connect_anchors(base, chosen)
        points = [
            graph.nodes[n].position
            for n in allocated
            if graph.nodes.get(n) is not None and graph.nodes[n].position is not None
        ]
        out["cost"] = {
            "class": base,
            "points": len(allocated),
            "diagonal": (
                int(
                    math.dist(
                        (min(p[0] for p in points), min(p[1] for p in points)),
                        (max(p[0] for p in points), max(p[1] for p in points)),
                    )
                )
                if len(points) >= 2
                else 0
            ),
            "incidental_destinations": sum(
                1
                for n in allocated
                if n not in chosen
                and graph.nodes.get(n) is not None
                and graph.nodes[n].kind in ("notable", "keystone", "jewel-socket")
            ),
        }
    out["note"] = (
        "`proposed_anchors`를 `optimize_tree(required_anchors=…)`에 넣으면 축마다 "
        "목적지가 보장된다 — 그리디는 먼 목적지로 **출발하지 않으므로**(첫 걸음 점수가 "
        "낮다) 이 단계를 건너뛰면 시작점 근처만 찍는다. `cost.points`가 예산에서 "
        "먼저 나가고, 남은 예산이 그리디 몫이다. 축 선정은 판단이니 그대로 쓰지 말고 "
        "컨셉과 대조할 것"
    )
    return out


def suggest_anchors(
    graph: TreeGraph,
    ascendancy: str,
    *,
    include: Sequence[tuple[str, float]] = (),
    axes: Mapping[str, Sequence[tuple[str, float]]] | None = None,
    top: int = 20,
    root: Any = None,
) -> dict[str, Any]:
    """트리를 짜기 전에 **목적지 후보를 한 번에 모은다**.

    지금까지는 세션이 프로파일 JSON을 직접 열어 N/N 노드의 KB id를 찾고 그걸 다시
    노드 번호로 바꿔야 했다 — 손이 많이 가는 일은 안 하게 되고, 안 하면 앵커 없이
    그리디만 돌린다. 그게 「필요한 노드를 안 찍는」 결과로 돌아온다.

    출처를 셋으로 갈라 낸다. **섞으면 안 된다** — 성격이 다르다:

    - `required` — 표본 **전원**이 찍은 목적지. `optimize_tree(required_anchors=…)`에
      그대로 넣는 후보다. 임계값이 아니라 정의(count == n)라 해석이 안 들어간다.
    - `common` — 나머지를 채택 순으로. **자유석 후보**이고, 넣을지는 판단이다.
    - `off_corpus` — 코퍼스와 무관하게 관련 노터블이 촘촘한 좌표(`find_clusters`).
      **표본이 안 간 곳**이라 새 선택의 재료다. `include`를 줘야 나온다.

    `cautions`는 「코앞에 두고도 버려진 것」이다(`passed_over`) — 앵커로 삼으려던
    노드가 여기 있으면 다시 생각할 것. 원시 코퍼스가 없으면 못 내고, 그 사실을 밝힌다.
    """
    from pok.engine.tree.clusters import find_clusters
    from pok.kb.store import load

    records = load(root).records
    who = str(graph.resolve_ascendancy(ascendancy))
    profile = _profiles_by_class(records, graph).get(who.casefold())
    out: dict[str, Any] = {"ascendancy": who}
    if profile is None:
        out["profile"] = None
        out["why"] = f"'{who}'의 래더 프로파일이 KB에 없다 — 코퍼스 쪽 후보는 비어 있다"
    else:
        data = profile.raw["data"]
        n = data["observed"]["sample"]["n"]
        node_of = {
            rid: int(r.raw["data"]["node_id"])
            for rid, r in records.items()
            if r.type == "Passive" and (r.raw.get("data") or {}).get("node_id") is not None
        }
        required, common = [], []
        sampled_nodes: set[int] = set()
        for entry in data["observed"]["passives"]:
            nid = node_of.get(entry["ref"])
            node = graph.nodes.get(nid) if nid else None
            if node is None:
                continue
            row = {
                "node": nid,
                "name": node.name_en,
                "kind": node.kind,
                "count": f"{entry['count']}/{n}",
            }
            sampled_nodes.add(nid)
            (required if entry["count"] == n else common).append(row)
        out.update(
            profile=profile.id,
            sample_n=n,
            # 목록은 min_count로 꼬리가 잘려 있다 — 안 밝히면 전량으로 읽힌다.
            listed_from_count=data["observed"]["sample"].get("min_count", 1),
            required=required,
            common=common[:top],
            common_total=len(common),
            tree_shape=data.get("tree_shape", {}).get("per_build", {}),
        )
        out["_sampled"] = sampled_nodes
        out["cautions"] = _cautions(data, include)

    if include:
        clusters = find_clusters(
            graph, include=list(include), top=3, for_ascendancy=who, min_score=0.5
        )
        # 잘리기 전 전량으로 걸러야 한다 — `common[:top]`으로 거르면 꼬리가
        # 「코퍼스 밖」으로 새어 나와 없던 신선함을 만든다.
        seen = out.get("_sampled", set())
        out["off_corpus"] = [
            {"node": h.node_id, "name": h.name_en, "score": h.score, "stats": list(h.stats_en)[:2]}
            for c in clusters
            for h in c.hits
            if h.node_id not in seen
        ][:top]
    else:
        out["off_corpus_skipped"] = (
            "include를 안 줘서 코퍼스 밖 후보를 스캔하지 않았다 — "
            '관련성 필터 없는 밀집도는 쓰레기라서다. 예: [["Cold", 2.0], ["Freeze", 1.0]]'
        )

    out.pop("_sampled", None)
    if axes:
        out["by_axis"] = anchors_for_axes(graph, who, axes)
    out["note"] = (
        "`required`만 optimize_tree(required_anchors=…) 후보다(전원 채택 = 정의). "
        "`common`·`off_corpus`는 **판단 대상**이지 목록이 아니다 — 특히 코퍼스는 탐색 "
        "**순서**이지 범위가 아니다. 앵커로 삼기 전에 `passed_over_nodes`로 「코앞에서 "
        "버려진 것」인지 보고, PoB 델타로 값을 재라"
    )
    return out


def ascendancy_in(graph: TreeGraph, allocated: set[int]) -> str | None:
    """할당 노드에서 전직을 읽어낸다.

    `connect_anchors`는 **기본 클래스**("Monk")를 받는다 — 거기서 전직은 안 나온다
    (Monk → 인보커·차율라·마셜 아티스트). 전직 전용 노드가 트리에 있으면 그것이
    답이고, 없으면 모른다고 말한다(추측해서 엉뚱한 표본과 대조하면 더 나쁘다).
    """
    codes = {
        graph.nodes[nid].ascendancy for nid in allocated if graph.nodes.get(nid) is not None
    } - {None}
    if len(codes) != 1:
        return None
    resolved = graph.resolve_ascendancy(str(next(iter(codes))))
    return resolved


def compare_tree(
    graph: TreeGraph,
    class_name: str,
    allocated: set[int],
    *,
    ascendancy: str | None = None,
    root: Any = None,
) -> dict[str, Any]:
    """할당 트리를 그 전직의 래더 표본과 대조한다.

    KB만 읽는다 — 원시 코퍼스(`artifacts/`)는 다른 PC에 없을 수 있고, 없다고
    조용히 대조를 건너뛰면 "문제 없음"으로 읽힌다.
    """
    from pok.kb.store import load

    who = ascendancy or ascendancy_in(graph, allocated)
    if not who:
        return {
            "compared": False,
            "why": f"전직을 모른다 — '{class_name}'은 기본 클래스라 표본을 특정할 수 없고, "
            "트리에도 전직 전용 노드가 없다. `ascendancy`를 주면 대조한다",
        }

    records = load(root).records
    profile = _profiles_by_class(records, graph).get(str(graph.resolve_ascendancy(who)).casefold())
    if profile is None:
        return {
            "compared": False,
            "why": f"'{who}'의 래더 프로파일이 KB에 없다 — 대조하지 않았다"
            "(없다고 정상인 것이 아니다: skills/ladder-corpus 절차로 수집할 수 있다)",
        }

    data = profile.raw["data"]
    n = data["observed"]["sample"]["n"]
    # KB id → 노드 번호. 프로파일은 id로 싣고 트리는 번호로 돈다.
    node_of: dict[str, int] = {}
    for rid, record in records.items():
        nid = (record.raw.get("data") or {}).get("node_id")
        if record.type == "Passive" and nid is not None:
            try:
                node_of[rid] = int(nid)
            except (TypeError, ValueError):
                continue

    unanimous: list[dict[str, Any]] = []
    covered: list[dict[str, Any]] = []
    for entry in data["observed"]["passives"]:
        if entry.get("count") != n:
            continue
        nid = node_of.get(entry["ref"])
        if nid is None:
            continue
        node = graph.nodes.get(nid)
        row = {
            "node": nid,
            "name": node.name_en if node else entry["ref"],
            "count": f"{n}/{n}",
        }
        (covered if nid in allocated else unanimous).append(row)

    # 트리 **폭** 대조 — 사용자 지적 2026-08-12: "빌드에 따라 좌측 끝과 우측 끝으로
    # 넓게 찍어야 하는 경우가 있다"(로우라이프 고통의 조율 + 회피 강화 반사신경,
    # 주문·공격·일반 치명타 3계열…). 그리디는 시작점 근처만 훑으므로 **좁은 트리를
    # 정상으로 착각**한다. 실측: 래더 중앙 27,041인데 우리 산출물은 20,005였고,
    # 그리디는 30포인트를 더 쓰고도 폭을 11%만 늘렸다.
    #
    # ⚠ 좁다고 틀린 건 아니다 — 컨셉에 따라 좁은 게 맞을 수도 있다. **표본 최소보다
    #   좁으면 알린다**까지가 여기 몫이고, 넓힐지는 설계 판단이다.
    width: dict[str, Any] = {}
    baseline = (data.get("tree_shape") or {}).get("diagonal") or {}
    if baseline:
        points = [
            graph.nodes[n].position
            for n in allocated
            if graph.nodes.get(n) is not None and graph.nodes[n].position is not None
        ]
        if len(points) >= 2:
            xs = [p[0] for p in points]
            ys = [p[1] for p in points]
            ours = int(math.dist((min(xs), min(ys)), (max(xs), max(ys))))
            width = {"ours": ours, "sample": baseline}
            if ours < int(baseline.get("min", 0)):
                width["narrower_than_every_sample"] = (
                    f"표본 {n}벌 중 가장 좁은 것보다도 좁다({ours:,} < "
                    f"{int(baseline['min']):,}) — 앵커 없이 그리디만 돌리면 시작점 "
                    "근처에 머문다. 멀리 있는 목적지는 `required_anchors`로 직접 "
                    "지정해야 연결된다(그리디는 도중 노드 점수가 낮아 출발하지 않는다)"
                )

    # ⛔ 「표본 밖 목적지」는 **내지 않는다.** 한때 넣었다가 뺐다(2026-08-12).
    #
    # 프로파일의 목록은 `min_count`로 꼬리가 잘려 있다(기본 3). 그래서 "목록에 없다"가
    # "아무도 안 찍었다"가 아니라 "1~2벌만 찍었다"까지 포함한다. 실측: 마셜 아티스트
    # 표본의 목적지는 실제 106종인데 레코드엔 53종뿐이었고, 그 목록으로 대조하니
    # **표본 밖의 멀쩡한 래더 빌드가 목적지 41개 중 20개(49%)**를 「표본 밖」으로
    # 찍혔다. 경고 꼴로 생긴 필드는 지워서 없애고 싶어지는 법이라, 그대로 뒀으면
    # 정상 트리를 깎는 압력이 됐을 것이다.
    #
    # 잘리지 않은 목록이 생기면(min_count=1) 그때 다시 넣을 수 있다.
    truncated = int(data["observed"]["sample"].get("min_count", 1))
    return {
        "compared": True,
        "profile": profile.id,
        "sample_n": n,
        # 표본 전원이 찍는데 우리 트리엔 없는 것. **가장 강한 신호다** —
        # 「꼭 필요한 노드를 안 찍는다」가 정확히 이 형태로 나타난다.
        "missing_unanimous": unanimous,
        "has_unanimous": len(covered),
        "width": width,
        "note": (
            "대조이지 판정이 아니다. `missing_unanimous`는 표본 전원이 찍는데 이 트리엔 "
            "없는 목적지다 — 빼려면 근거를 남길 것. **표본에 없는 노드를 찍은 것은 "
            "여기서 지적하지 않는다**: 목록이 count≥"
            f"{truncated}로 잘려 있어 「표본에 없다」를 판정할 수 없고, 애초에 표본 밖 "
            "선택은 결함이 아니다(코퍼스는 탐색 **순서**이지 **범위**가 아니다). "
            "특정 노드가 미심쩍으면 `passed_over_nodes`로 「코앞에서 버려진 것」인지 "
            "확인하고 PoB 델타로 값을 재라"
        ),
    }
