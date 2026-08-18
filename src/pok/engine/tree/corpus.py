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
import re
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


# 효과 문구에서 축을 뽑을 때 걸러낼 잡음. 게임 문구는 조사·연결어가 반복되는데
# 그걸 놔두면 "to"·"of"가 최상위 축이 된다.
_AXIS_STOP = frozenset(
    [
        "to",
        "of",
        "the",
        "a",
        "an",
        "and",
        "or",
        "increased",
        "reduced",
        "more",
        "less",
        "per",
        "with",
        "while",
        "your",
        "you",
        "have",
        "has",
        "gain",
        "gains",
        "on",
        "if",
        "by",
        "for",
        "from",
        "all",
        "is",
        "are",
        "be",
        "this",
        "that",
        "when",
        "nearby",
        "other",
        "than",
        "each",
    ]
)


def discover_axes(
    graph: TreeGraph,
    ascendancy: str,
    *,
    top_terms: int = 6,
    root: Any = None,
) -> dict[str, Any]:
    """**표본이 실제로 쫓은 축**을 코퍼스에서 뽑는다 — 사람이 키워드를 대지 않아도.

    사용자 지적 2026-08-12: "결국 사용자가 어떤 노드를 찍어라 지시해야만 동작하고
    자발적으로 찾지는 못하는 것 아닌가." 맞는 지적이었다 — `anchors_for_axes`는
    **축을 선언하면** 노드로 바꿔 주는 변환기이지 축을 발견하지 못했다.

    축은 코퍼스에 있다. 표본이 찍은 목적지들의 효과 문구를 **채택 수로 가중해**
    세면 그 전직이 무엇을 챙기는지가 그대로 나온다(실측 2026-08-12):

    - 마셜 아티스트 → damage · critical · chance · speed · attack · evasion
    - 블러드 메이지 → damage · critical · mana · chance · life · spell
    - 스톰위버     → damage · maximum · mana · critical · elemental · shield

    피해 유형(attack/spell)까지 자연히 갈리므로 **제외어를 손으로 넣을 필요도 준다**.

    ⛔ **이건 「표본이 쫓은 축」이지 「당신 컨셉의 축」이 아니다.** 그대로 쓰면 답지
    복사다 — 출발점으로 쓰고 컨셉과 대조해 더하거나 뺄 것(코퍼스는 탐색 순서이지
    범위가 아니다).
    """
    from pok.kb.store import load

    records = load(root).records
    profile = _profiles_by_class(records, graph).get(
        str(graph.resolve_ascendancy(ascendancy)).casefold()
    )
    if profile is None:
        return {"axes": {}, "why": f"'{ascendancy}'의 래더 프로파일이 KB에 없다"}
    node_of = {
        rid: int(r.raw["data"]["node_id"])
        for rid, r in records.items()
        if r.type == "Passive" and (r.raw.get("data") or {}).get("node_id") is not None
    }
    weight: dict[str, int] = {}
    for entry in profile.raw["data"]["observed"]["passives"]:
        node = graph.nodes.get(node_of.get(entry["ref"], -1))
        if node is None or node.kind not in ("notable", "keystone"):
            continue
        words = {
            w
            for w in re.findall(r"[a-z]+", " ".join(node.stats_en).lower())
            if len(w) > 3 and w not in _AXIS_STOP
        }
        for word in words:
            weight[word] = weight.get(word, 0) + int(entry.get("count", 1))
    ranked = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))[:top_terms]
    if not ranked:
        return {"axes": {}, "why": "표본 목적지에서 축을 못 뽑았다"}
    top = ranked[0][1]

    # **피해 유형도 코퍼스가 말해 준다.** 단어 하나짜리 축("critical")은 유형 문맥이
    # 없어 주문 빌드에 근접 공격 노터블을 물어 온다(실측 2026-08-12: 블러드 메이지의
    # `critical` 축 상위가 Blade Flurry·Martial Artistry였다). 표본이 `spell`을 챙기면
    # 공격 계열을, `attack`을 챙기면 주문 계열을 **전 축에서 뺀다** — 손으로 넣던
    # 제외어가 여기서 나온다.
    spell_w, attack_w = weight.get("spell", 0), weight.get("attack", 0)
    kind_exclude: tuple[str, ...] = ()
    if spell_w > attack_w * 1.2:
        kind_exclude = ("attack", "melee", "bow", "crossbow", "strike")
    elif attack_w > spell_w * 1.2:
        kind_exclude = ("spell", "minion")

    # 축 하나에 몰아 주면 그 축이 후보를 독점한다 — 상대 가중으로 편다.
    return {
        "axes": {
            term: {
                "include": [(term, round(count / top * 2, 2))],
                # 유형 단어 자체가 축이면 자기를 빼면 안 된다
                "exclude": [x for x in kind_exclude if x != term],
            }
            for term, count in ranked
        },
        "damage_kind_exclude": list(kind_exclude),
        "basis": f"{profile.id} 표본 {profile.raw['data']['observed']['sample']['n']}벌의 "
        "목적지 효과 문구를 채택 수로 가중",
        "note": "표본이 쫓은 축이지 당신 컨셉의 축이 아니다 — 출발점으로 쓰고 대조할 것",
    }


def _socket_anchors(
    data: dict[str, Any], node_of: dict[str, int], graph: TreeGraph
) -> dict[str, Any]:
    """주얼 소켓을 **채택률 근거로** 앵커에 올린다 (사용자 지시 2026-08-12).

    빈 소켓은 델타가 0이라 **점수 경쟁으로는 영영 안 뽑힌다** — 먼 목적지와 같은
    성질이고, 같은 해법(근거를 들어 먼저 박기)이 필요하다.

    전원 공통(count == n)만 쓰면 모자란다. 소켓은 자리마다 갈려서 개별 채택률이
    낮아도 **빌드당 개수는 일정**하기 때문이다(실측 2026-08-12):

    | 전직 | 표본 중앙 개수 | 전원 공통 | 부족 |
    |---|---|---|---|
    | 마셜 아티스트 | 4 | 3 | 1 |
    | 스톰위버 | 5 | 3 | 2 |
    | 블러드 메이지 | 8 | 4 | **4** |

    그래서 **표본 중앙 개수까지** 채택률 순으로 채운다. 임계값을 지어낸 게 아니라
    표본이 실제로 쓰는 개수다.

    ⛔ **값을 보장하지 않는다.** 소켓은 포인트를 쓰고 주얼이 들어오기 전까지 아무것도
    주지 않는다 — 내용은 `optimize_rare(slot="Jewel@<node>")`가 정하고, 그 뒤에야
    이 자리가 값을 하는지 잴 수 있다(2패스).
    """
    n = data["observed"]["sample"]["n"]
    median = int(
        (data.get("tree_shape") or {}).get("per_build", {}).get("jewel-socket", {}).get("median", 0)
    )
    ranked: list[tuple[int, int]] = []
    for entry in data["observed"]["passives"]:
        nid = node_of.get(entry["ref"])
        if not nid:
            continue
        node = graph.nodes.get(nid)
        if node is not None and node.kind == "jewel-socket":
            ranked.append((int(entry["count"]), nid))
    ranked.sort(key=lambda kv: (-kv[0], kv[1]))
    unanimous = [nid for count, nid in ranked if count == n]
    proposed = [nid for _c, nid in ranked[: max(median, len(unanimous))]]
    out: dict[str, Any] = {
        "sample_median": median,
        "unanimous": unanimous,
        "proposed": proposed,
        "adoption": [{"node": nid, "count": f"{c}/{n}"} for c, nid in ranked[:10]],
    }
    if median > len(ranked):
        # 목록이 min_count로 잘려 있어 중앙값을 못 채울 수 있다 — 조용히 모자라지 않게.
        out["short_of_median"] = (
            f"표본은 중앙 {median}개를 찍는데 목록에는 {len(ranked)}종뿐이다"
            f"(count≥{data['observed']['sample'].get('min_count', 1)}로 잘린 목록) — "
            "부족분은 원시 코퍼스를 봐야 나온다"
        )
    out["note"] = (
        "빈 소켓은 델타 0이라 **점수로는 절대 안 뽑힌다** — `proposed`를 "
        "`required_anchors`에 넣어 자리를 먼저 잡고, 내용은 "
        '`optimize_rare(slot="Jewel@<node>")`로 만든 뒤 그 text를 `jewel_templates`에 '
        "넣어 다시 재라(2패스). ⛔ 이 제안은 **코퍼스 근거지 측정이 아니다** — "
        "포인트를 쓰고도 주얼이 없으면 아무것도 주지 않는다"
    )
    return out


def _positions(graph: TreeGraph, node_ids: Sequence[int] | set[int]) -> list[tuple[float, float]]:
    """좌표가 있는 노드들의 (x, y). 좌표 없는 노드(가상 노드 등)는 떨군다."""
    out: list[tuple[float, float]] = []
    for nid in node_ids:
        node = graph.nodes.get(nid)
        if node is not None and node.position is not None:
            out.append(node.position)
    return out


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
        # 닿지 않는 후보가 섞일 수 있다(다른 전직 권역 등). 그대로 넘기면
        # `connect_anchors`가 예외로 터져 **제안 전체가 날아간다** — 걸러 내고 밝힌다.
        reachable = graph.distances_from({graph.start_of(base), *graph.granted_nodes(who)}, 200)
        unreachable = [n for n in chosen if n not in reachable]
        if unreachable:
            chosen = [n for n in chosen if n in reachable]
            out["unreachable"] = unreachable
            out["proposed_anchors"] = chosen
    if base and chosen:
        # **값을 매겨서 준다.** 몇 포인트가 드는지 모르면 앵커를 고를 수 없다 —
        # 실측: 치명타 3계열 6개가 86포인트(래더 중앙 폭과 동급)였다.
        allocated, _paths = graph.connect_anchors(base, chosen, ascendancy=who)
        points = _positions(graph, allocated)
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


# 「필수 앵커」의 문턱 — 채택률의 95% 신뢰 하한(%). 사용자 판정 2026-08-16.
#
# ⚠ 이것은 **해석값이지 상수가 아니다**. 여기 박아 두는 이유는 기본값이 곧 정책이기
# 때문이고(절단 기본값을 1로 뒤집은 것과 같은 이유), 바꿀 때 소리가 나도록 인자로도
# 노출한다. 「몇 %부터 필수인가」의 판단 자체는 여전히 해석 층의 몫이다(철칙 3).
_REQUIRED_MIN_CI_LOW = 80.0


# ── 제거 실측(NodeValue)을 앵커 후보에 붙인다 (#77 · M4) ─────────────────────
#
# 채택률은 「많이 찍혔다」까지만 말한다 — 남들이 찍어서 찍는 것일 수 있다(#62).
# NodeValue는 반대편이다: 실제로 빼 보고 PoB로 잰 손실. 둘을 나란히 놓으면
# 「전원이 찍지만 빼도 안 아픈」 메타 습관이 드러난다 — 갈아탈 수 있는 예산이다.
#
# ⛔ 여기서 required/common을 **재분류하지 않는다.** 「아프지 않으니 필수가 아니다」는
#    해석이고(철칙 3), NodeValue는 전 빌드 집계라 이 전직의 사정과 해상도가 다르다.
#    표시만 달고 판단은 호출자가 한다.

# 「빼도 안 아프다」의 문턱(손실률 %). 해석 층의 몫이라 인자로도 노출한다.
_HABIT_MAX_LOSS = 0.5
# 「작동할 땐 아프다」의 문턱 — #88 실측에서 조건부 27종이 전부 2% 위였다.
_CONDITIONAL_MIN_LOSS = 2.0


def _node_values(records: Mapping[str, Any]) -> dict[int, dict[str, Any]]:
    """KB의 NodeValue 레코드 → node_id 색인. 없으면 빈 dict(호출자가 선언한다)."""
    out: dict[int, dict[str, Any]] = {}
    for record in records.values():
        if record.type != "NodeValue":
            continue
        data = record.raw.get("data") or {}
        node_id = (data.get("node") or {}).get("node_id")
        if node_id is not None:
            out[int(node_id)] = data
    return out


def _removal_summary(
    value: dict[str, Any], *, habit_max_loss: float
) -> tuple[dict[str, Any], str | None]:
    """행에 붙일 요약 + 표시(habit/conditional/None).

    ⚠ **뭉친 중앙값만 보면 조건부를 습관으로 오독한다**(#88): Mind Over Matter는
    전체 중앙 0%인데 작동할 땐 36.6%다. 그래서 `when_active`까지 봐야 갈린다:

    - habit       — 어느 빌드에서도 안 아프다(작동해도 문턱 미만). 갈아탈 예산.
    - conditional — 뭉치면 0이지만 **쓰는 빌드에선 아프다**. 이 전직이 그 메커니즘을
                    쓰는지 확인하기 전엔 습관으로 읽지 말 것.
    """
    axes: dict[str, Any] = {}
    verdicts: list[str] = []
    for stat, ax in (value.get("axes") or {}).items():
        n = int(ax.get("n") or 0)
        if n < 10:
            continue  # 표본이 적으면 판정을 안 낸다 — 값은 싣되 표시는 유보
        when_active = (ax.get("when_active") or {}).get("median", 0.0)
        axes[stat] = {
            "n": n,
            "loss_median": (ax.get("loss_pct") or {}).get("median", 0.0),
            "active_share": ax.get("active_share", 0.0),
            "when_active_median": when_active,
        }
        hurts_overall = abs(axes[stat]["loss_median"]) >= habit_max_loss
        hurts_when_active = (
            int(ax.get("n_active") or 0) > 0 and abs(when_active) >= _CONDITIONAL_MIN_LOSS
        )
        if hurts_overall:
            verdicts.append("hurts")
        elif hurts_when_active:
            verdicts.append("conditional")
        else:
            verdicts.append("habit")
    summary = {"n": int((value.get("sample") or {}).get("n") or 0), "axes": axes}
    if not axes:
        return summary, None  # 판정할 축이 없다 — 표시 없음이지 「습관 아님」이 아니다
    if all(v == "habit" for v in verdicts):
        return summary, "habit"
    if "hurts" not in verdicts:
        return summary, "conditional"
    return summary, None


def suggest_anchors(
    graph: TreeGraph,
    ascendancy: str,
    *,
    include: Sequence[tuple[str, float]] = (),
    axes: Mapping[str, Sequence[tuple[str, float]]] | None = None,
    top: int = 20,
    min_ci_low: float = _REQUIRED_MIN_CI_LOW,
    root: Any = None,
) -> dict[str, Any]:
    """트리를 짜기 전에 **목적지 후보를 한 번에 모은다**.

    지금까지는 세션이 프로파일 JSON을 직접 열어 N/N 노드의 KB id를 찾고 그걸 다시
    노드 번호로 바꿔야 했다 — 손이 많이 가는 일은 안 하게 되고, 안 하면 앵커 없이
    그리디만 돌린다. 그게 「필요한 노드를 안 찍는」 결과로 돌아온다.

    출처를 셋으로 갈라 낸다. **섞으면 안 된다** — 성격이 다르다:

    - `required` — 채택률의 **95% 신뢰 하한이 `min_ci_low` 이상**인 목적지.
      `optimize_tree(required_anchors=…)`에 그대로 넣는 후보다.

      ⚠ 예전 기준은 `count == n`(표본 전원)이었는데 **문턱이 표본 크기에 매여 있었다**.
      10/10의 「전원」은 하한 72.2짜리이고 50/50은 92.9짜리다 — 후자가 옳지만 훨씬
      드물어서, 표본을 10 → 50으로 올리자 클래스 22종 합계 앵커가 **86 → 37개**로
      줄었다(워브링어·위치헌터·크로노맨서는 0개). 같은 코퍼스가 표본만 커졌다고
      「필수가 사라진」 것처럼 보이는 것이라, 규모 불변인 하한으로 바꿨다
      (사용자 판정 2026-08-16: `ci_low >= 80`).

      문턱값은 **인자로 노출한다** — 「몇 %부터 필수인가」는 해석 층의 몫이고(철칙 3)
      코드에 박으면 되돌릴 때 소리가 안 난다. 반환값에 `min_ci_low`로 함께 낸다.
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
        required: list[dict[str, Any]] = []
        common: list[dict[str, Any]] = []
        sampled_nodes: set[int] = set()
        for entry in data["observed"]["passives"]:
            nid = node_of.get(entry["ref"])
            if not nid:
                continue
            node = graph.nodes.get(nid)
            if node is None:
                continue
            row = {
                "node": nid,
                "name": node.name_en,
                "kind": node.kind,
                "count": f"{entry['count']}/{n}",
                # 하한을 함께 낸다 — 「왜 이게 required인가」를 되짚을 수 있어야 한다.
                # 옛 레코드엔 없을 수 있어 기본 0(=required에 안 들어감)으로 떨어진다.
                "ci_low": entry.get("ci_low", 0.0),
            }
            sampled_nodes.add(nid)
            (required if row["ci_low"] >= min_ci_low else common).append(row)
        out.update(
            profile=profile.id,
            sample_n=n,
            # 목록은 min_count로 꼬리가 잘려 있다 — 안 밝히면 전량으로 읽힌다.
            listed_from_count=data["observed"]["sample"].get("min_count", 1),
            # `required`가 무슨 기준으로 갈렸나. 안 밝히면 「표본 전원」으로 읽힌다
            # (그게 옛 기준이었다). 문턱이 바뀌면 목록도 바뀌므로 함께 낸다.
            min_ci_low=min_ci_low,
            required=required,
            common=common[:top],
            common_total=len(common),
            tree_shape=data.get("tree_shape", {}).get("per_build", {}),
        )
        out["_sampled"] = sampled_nodes
        out["cautions"] = _cautions(data, include)

        # ── 제거 실측을 붙인다 (#77) — 채택률 옆에 「빼면 아픈가」를 나란히 ──
        values = _node_values(records)
        if values:
            habits: list[str] = []
            for row in (*required, *common):
                value = values.get(row["node"])
                if value is None:
                    # 측정이 없는 것과 안 아픈 것은 다르다 — 비워 두면 0으로 읽힌다
                    row["removal"] = None
                    continue
                summary, mark = _removal_summary(value, habit_max_loss=_HABIT_MAX_LOSS)
                row["removal"] = summary
                if mark:
                    row["removal_mark"] = mark
                if mark == "habit" and row["ci_low"] >= min_ci_low:
                    habits.append(f"{row['name']}({row['node']})")
            out["removal_source"] = (
                f"NodeValue {len(values):,}종 — 제거 반사실 실측(래더 전 빌드 집계). "
                f"habit 문턱 손실 {_HABIT_MAX_LOSS}% · conditional 문턱 {_CONDITIONAL_MIN_LOSS}%"
            )
            if habits:
                out["meta_habits"] = habits
                out["meta_habits_why"] = (
                    "⚠ **required인데 어느 빌드에서도 빼서 안 아팠다** — 전원이 찍지만 "
                    "값은 실측되지 않는 「메타 습관」 후보다(#62). 앵커에서 빼는 판단은 "
                    "호출자 몫이지만, 여기 있는 포인트는 갈아탈 수 있는 예산일 수 있다. "
                    "⚠ conditional 표시가 붙은 것은 다르다 — 쓰는 빌드에선 아프다(#88)"
                )
        else:
            # ⛔ 조용한 0 금지 — 없으면 채택률만으로 고른 것임을 말한다
            out["removal_source"] = None
            out["removal_why"] = (
                "NodeValue 레코드가 KB에 없다 — 이 후보들은 **채택률만으로** 골랐다. "
                "「많이 찍혔다」는 「빼면 아프다」가 아니다(#77). M3 재측정 후 2층 집계가 "
                "승격되면 제거 실측이 함께 붙는다"
            )

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
    if profile is not None:
        out["sockets"] = _socket_anchors(data, node_of, graph)
    if axes is None and profile is not None:
        # **사람이 키워드를 대지 않아도** 축이 나오게 한다. 안 그러면 이 도구는
        # "축을 선언하면 변환해 주는" 물건에 머문다(사용자 지적 2026-08-12).
        found = discover_axes(graph, who, root=root)
        if found.get("axes"):
            out["discovered_axes"] = {k: v for k, v in found.items() if k != "axes"}
            axes = found["axes"]
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
        points = _positions(graph, allocated)
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
