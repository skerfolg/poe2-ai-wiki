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
