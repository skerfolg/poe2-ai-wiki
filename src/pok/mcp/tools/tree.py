"""트리 최적화 MCP 도구 — P4 (connect_anchors·optimize_tree). 얇은 어댑터."""

from __future__ import annotations

from typing import Any

from pok.common.paths import knowledge_dir
from pok.engine.objective import Target
from pok.engine.tree.corpus import compare_tree
from pok.engine.tree.graph import TreeGraph
from pok.engine.tree.optimize import Objective
from pok.engine.tree.optimize import optimize_tree as _optimize
from pok.pob.buildxml import spec_from_dict

_graph: TreeGraph | None = None


def _get_graph() -> TreeGraph:
    global _graph
    if _graph is None:
        _graph = TreeGraph(knowledge_dir())
    return _graph


def connect_anchors(
    class_name: str, targets: list[int], ascendancy: str | None = None
) -> dict[str, Any]:
    """타깃 노드들(KB node_id)을 클래스 시작점에서 최소 포인트로 연결
    (그리디 슈타이너 — 근사). 반환: 할당 노드 전체와 타깃별 경로·총 포인트.

    `class_name`은 **기본 클래스**다("Monk"·"Witch"). `ascendancy`("Martial Artist")를
    함께 주면 반환값에 **래더 표본과의 대조**(`corpus`)가 붙는다 — 표본 전원이 찍는
    목적지를 빠뜨렸으면 `missing_unanimous`에 나온다(실측 2026-08-12: 어센던시 22종
    전부에 전원 공통 노드가 1~11개 있고 주얼 소켓이 거기 자주 낀다). 안 주면
    트리의 전직 전용 노드로 추론하고, 그마저 없으면 **대조하지 않았다고 밝힌다**.
    주면 **남의 전직 노드도 거부한다**(인게임 할당 불가 트리 방지).
    ⛔ 대조이지 판정이 아니다(빼려면 근거를 남길 것).
    """
    graph = _get_graph()
    allocated, paths = graph.connect_anchors(class_name, targets, ascendancy=ascendancy)
    # 포인트는 **두 풀**이다 — 합쳐 내면 세션이 일반 예산을 그만큼 쓴 것으로 읽는다(#68).
    # 공짜 노드(관문 하위·조건부 개방·선택 시 부여)는 칸은 차지해도 포인트가 아니다.
    free = graph.free_nodes(ascendancy, set(allocated))
    asc_nodes = [
        n
        for n in allocated
        if n not in free and (nd := graph.nodes.get(n)) is not None and nd.ascendancy
    ]
    return {
        "allocated": allocated,
        "points": len(allocated) - len(asc_nodes),  # 일반 패시브만
        "ascendancy_points": len(asc_nodes),  # 별도 풀 — 일반 예산을 갉지 않는다
        "paths": {str(t): p for t, p in paths.items()},
        # 자동 부착 — 세션이 프로파일·passed_over의 존재를 몰라도 여기서 본다.
        # 문서에만 적는 방식은 이 레포에서 실패가 증명됐다(철칙 5).
        "corpus": compare_tree(graph, class_name, set(allocated), ascendancy=ascendancy),
    }


def _with_item(spec: dict[str, Any], slot: str, text: str) -> dict[str, Any]:
    """슬롯 텍스트를 갈아 끼운 스펙 사본 — 도장을 **적용 후** 문맥에 찍기 위해서다."""
    items = [dict(i) for i in (spec.get("items") or []) if str(i.get("slot")) != slot]
    items.append({"slot": slot, "text": text})
    return {**spec, "items": items}


def _stamp(
    spec_after: dict[str, Any],
    component: str,
    *,
    tool: str,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """`derived_from` 한 칸 — 생산자가 **자동으로** 박는다 (#58 ③).

    수동이면 안 지켜진다(보고자: "제가 이번에 증명했습니다"). 기존 도장은 보존하고
    이 축만 덮어쓴다 — 트리를 다시 돌렸다고 장비 출처가 사라지면 안 된다.
    """
    from pok.engine.provenance import stamp

    existing = dict(spec_after.get("derived_from") or {})
    existing[component] = stamp(spec_after, component, tool=tool, weights=weights)
    return existing


def optimize_tree(
    build_spec: dict[str, Any],
    weights: dict[str, float],
    point_budget: int,
    candidate_radius: int = 8,
    max_candidates_per_round: int = 40,
    jewel_templates: list[str] | None = None,
    exclude_nodes: list[int] | None = None,
    unconnected_regions: list[dict[str, Any]] | None = None,
    cluster_include: list[list[Any]] | None = None,
    cluster_exclude: list[str] | None = None,
    targets: list[dict[str, Any]] | None = None,
    required_anchors: list[int] | None = None,
    time_budget_s: float | None = 600.0,
) -> dict[str, Any]:
    """현재 빌드 문맥에서 포인트 예산만큼 트리를 개선한다. 후보 노드 효율은
    전부 PoB 델타 실측 — 채택된 각 수(step)에 근거 델타가 담긴다.
    weights = 다축 정책(RC3), 예: {"CombinedDPS": 1.0, "Life": 0.6}.
    jewel_templates = 소켓 평가용 **가정 탐침**(설계물이 아니다). 빈 소켓은 델타 0이라
    그리디가 영영 안 찍으므로, 값을 재려면 무언가 꽂아 봐야 한다 — 소켓 후보를
    템플릿별로 실측해 최선을 채택하고 steps의 jewel_text·결과 jewels에 기록한다.
    ⚠ **모두에게 맞는 주얼은 없다.** 실제 주얼 내용은 아이템 층의 일이다 —
    소켓을 할당한 뒤 `optimize_rare(slot="Jewel@<소켓 node_id>", radius=…)`로 이 빌드
    문맥에서 접사 풀을 실측해 뽑고, 그 text를 여기 넣어 다시 돌린다(2패스).
    닭·달걀은 그렇게 끊는다: **소켓 할당은 코퍼스 근거로**(래더 표본 중앙 5개),
    **주얼 내용은 측정으로**.
    max_candidates_per_round = 라운드당 평가할 후보 수(거리순 상한). 시작점 주변이
    빌드와 무관한 노터블뿐이면(예: 물리 공격 빌드의 마녀 권역) 40개가 전부 델타 <= 0이라
    `stopped_no_positive`로 즉시 멈춘다 — 그럴 때 늘려서 더 먼 후보까지 본다.
    소요: 라운드당 후보 수 x ~0.1초 — 예산 30이면 수 분.

    `targets` = **사전식 목표**(D28) — `[{"metric":"TotalEHP","op":">=","value":8000,
    "label":"EHP 하한"}, {"metric":"CombinedDPS","op":">=","value":2e6}]`. 주면
    weights 가중 합산 대신 **순서대로** 민다: 첫 미충족 목표가 병목이고 그 축에
    점수를 몰아주며, 충족되는 순간 다음 목표로 넘어간다. **이미 충족한 경계를
    깨뜨리는 수는 채택하지 않는다.** 가중 합산은 한 축이 지배해 "한쪽으로 쏠리지
    않게"를 표현하지 못한다 — 균형은 가중치를 손으로 맞춰서가 아니라 경계 충족으로
    얻는다. ⚠ PoB가 못 재는 축을 목표로 걸면 그 축으로는 한 걸음도 못 민다
    (델타가 0이 아니라 측정이 없다) — `notes`에 그 사실이 실린다.

    `required_anchors` = **메커니즘상 반드시 필요한 노드**(KB node_id). 그리디를 돌리기
    전에 먼저 연결하고 그 포인트를 예산에서 뺀다. 가중치를 크게 주는 방식과 다르다 —
    가중치는 여전히 경쟁이라 점수 높은 다른 노드에 밀린다. 필수는 경쟁 대상이 아니라
    **통과점**이다. 특히 **PoB가 못 재는 메커니즘 노드는 델타 0이라 그리디가 절대
    안 뽑는다** — 여기 넣지 않으면 영영 안 들어온다. 연결된 앵커와 그 경로는
    가지치기도 건드리지 않는다. 후보는 `corpus.missing_unanimous`(표본 전원이 찍는
    목적지)와 컨셉상 필수 노드에서 고른다.

    `time_budget_s` = **시간 상한(기본 600초)**. 후보 하나가 PoB 계산 1회(실측 0.16초)라
    예산·후보 수에 비례해 는다 — 실측 2026-08-12: 예산 156·후보 40이 가지치기 재실행까지
    합쳐 **40분을 넘겼다**(진행 표시도 없었다). 넘기면 그 자리에서 멈추고 **남은 예산과
    함께 notes에 밝힌다** — 덜 최적화된 트리이지 완성된 트리가 아니다. `None`이면 무제한.

    `exclude_nodes` = **설계 판단으로 뺀 노드**. 그리디는 배타 관계를 모르므로 손으로
    빼도 그냥 다시 뽑는다 — 실측 2026-08-09: 원소 집정관 축을 위해 「검은화염 계약」
    (화염 주문 100%를 카오스로 전환 — 집정관의 `Cannot deal Non-Elemental Damage with
    Spells`와 정면 충돌)을 뺐는데 재실행하자 **그것과 「피의 제물」을 그대로 재채택**했다.
    PoB가 집정관을 모델링하지 않아(#3) 충돌이 점수에 안 보이기 때문이다.

    `cluster_include` = `[["ignite", 1.0], ["critical", 0.5]]` 꼴. 주면 **후보 반경 밖**의
    관련 노터블 뭉치를 `far_clusters`로 함께 낸다 — 그리디는 반경 안만 보므로 먼 뭉치를
    구조적으로 못 본다(실측: 예산 87에 43포인트 조기 종료, 병목을 푸는 노터블이 전부
    반경 밖). 안 주면 스캔하지 않고 그 사실을 `notes`에 남긴다 — **관련성 필터 없는
    밀집도는 쓰레기**라서다(실측: 반경 1000의 노터블 9개 중 3개가 도리깨 노드).

    `unconnected_regions` = `[{"center": [-1682, -9147], "radius": 2520}]` 꼴.
    비연결 할당 주얼(제어된 변형·허무의 산물)이 덮는 원 — 그 안의 노드는 통행 비용
    없이 **자기 1포인트만** 든다. ⚠ 반경은 실측 목록에서: 실효 최대 **2,520**이고
    Variable은 **도넛**이다. 임의의 큰 값은 "주얼 하나로 덮인다"는 틀린 결론을 만든다."""
    spec = spec_from_dict(build_spec)
    out = _optimize(
        spec,
        _get_graph(),
        Objective(
            weights=weights,
            targets=tuple(
                Target(
                    metric=str(t["metric"]),
                    op=str(t.get("op", ">=")),
                    value=float(t["value"]),
                    label=str(t.get("label", "")),
                )
                for t in (targets or [])
            ),
        ),
        point_budget=point_budget,
        candidate_radius=candidate_radius,
        max_candidates_per_round=max_candidates_per_round,
        jewel_templates=tuple(jewel_templates or ()),
        exclude_nodes=tuple(exclude_nodes or ()),
        unconnected_regions=tuple(unconnected_regions or ()),
        cluster_include=tuple((str(k), float(w)) for k, w in (cluster_include or ())),
        cluster_exclude=tuple(cluster_exclude or ()),
        required_anchors=tuple(required_anchors or ()),
        time_budget_s=time_budget_s,
    )
    return {
        # 후보 반경 **밖**의 관련 뭉치 — 효과 문구째로 낸다. 점수만 내면 두 축을
        # 동시에 봐야 보이는 조합(「힘 소진」 + 「지배」 성유)을 영원히 못 찾는다.
        "far_clusters": [
            {
                "label": c.label,
                "center": list(c.center),
                "radius": c.radius,
                "inner": c.inner,
                "total_score": c.total_score,
                "hits": [
                    {
                        "node_id": h.node_id,
                        "name": h.name_ko or h.name_en,
                        "score": h.score,
                        "position": list(h.position),
                        "stats_en": list(h.stats_en),
                        **({"locked_to": h.locked_to} if h.locked_to else {}),
                    }
                    for h in c.hits
                ],
            }
            for c in out.far_clusters
        ],
        "notes": list(out.notes),
        "steps": [
            {
                "node_id": s.node_delta.node_id,
                "name": s.node_delta.name_ko or s.node_delta.name_en,
                "kind": s.node_delta.kind,
                "points": s.node_delta.points,
                "path": list(s.node_delta.path),
                "deltas": {k: round(v, 2) for k, v in s.node_delta.deltas.items()},
                "score": round(s.score, 5),
                "jewel_text": s.node_delta.jewel_text,
            }
            for s in out.steps
        ],
        "jewels": [{"socket_node_id": j.socket_node_id, "text": j.text} for j in out.spec.jewels],
        # connect_anchors와 같은 이유로 자동 부착 — 최적화가 끝난 트리에서
        # 「표본 전원이 찍는 목적지」가 빠져 있으면 여기서 드러난다(철칙 5).
        "corpus": compare_tree(
            _get_graph(),
            spec.class_name,
            set(out.spec.tree_nodes),
            ascendancy=spec.ascendancy,
        ),
        # 이 트리가 **어느 문맥에서 나왔나** — 스펙에 그대로 옮겨 두면 다음 세션의
        # `compute_pob`이 낡음을 문장으로 알려 준다(#58 ③)
        "derived_from": _stamp(
            {**build_spec, "tree_nodes": list(out.spec.tree_nodes)},
            "tree",
            tool="optimize_tree",
            weights=dict(weights),
        ),
        "pruned_branches": [
            {
                "endpoint": p.endpoint_id,
                "name": p.endpoint_name,
                "removed_nodes": list(p.nodes),
                # 끝단 1개 기준 — **가지 전체 손실은 chain_removal_deltas를 보라**
                # 끝단 1개 기준 (죽음의 증거). **가지 전체 손실은 chain_removal_deltas**
                "endpoint_removal_deltas": {
                    k: round(v, 2) for k, v in p.endpoint_removal_deltas.items()
                },
                "chain_removal_deltas": {k: round(v, 2) for k, v in p.chain_removal_deltas.items()},
                "chain_truncated": p.chain_truncated,
            }
            for p in out.pruned
        ],
        # **헛돈 예산을 앞에 낸다** — 회수는 되지만 "이 지출이 무효였다"가 신호로
        # 읽히지 않아 세션이 예산을 다 쓴 트리를 정상 산출물로 받았다(이관 4 C5)
        "wasted_points": out.wasted_points,
        "waste_notes": list(out.waste_notes),
        "spent_points": sum(s.node_delta.points for s in out.steps)
        - sum(len(p.nodes) for p in out.pruned),
        "stopped_no_positive": bool(out.rejected_rounds),
        "tree_nodes": list(out.spec.tree_nodes),
        "final_stats": {k: out.result.stats[k] for k in weights if k in out.result.stats},
        # 공유 코드·기록은 assemble_pob(최종 tree_nodes로 재조립)에서 — 기록 일원화
    }


def evaluate_bundles(
    build_spec: dict[str, Any],
    bundles: list[dict[str, Any]],
    stats: list[str] | None = None,
) -> dict[str, Any]:
    """묶음을 **통째로** 실측한다 — `optimize_tree`의 노드 단위 그리디가 놓치는 축.

    "치명타 90% 달성"처럼 무기 접미·주얼·노터블을 **동시에** 갖춰야 값이 나오는
    조합이 있다. 하나씩 넣어 보는 그리디는 각각의 델타가 작으면 전부 버리므로
    곱연산 축이 구조적으로 탈락한다(실측 2026-08-05: 가산 99포인트보다 치명타 축
    하나가 8.6배 컸는데 그리디로는 열리지 않았다).

    bundles = [{"name": "치명타 90% 달성", "nodes": [123, 456]}]

    묶음 **구성은 호출자가 한다** — "어떤 조합이 말이 되는가"는 판단이다(AD-3).
    반환의 `synergy`(묶음 델타 - 개별 합)가 양수면 묶어야 열리는 축이라는 신호다.
    """
    from pok.engine.tree.deltas import evaluate_bundles as _bundles

    keys = tuple(stats or ("CombinedDPS", "Life", "TotalEHP"))
    results = _bundles(spec_from_dict(build_spec), _get_graph(), bundles, stats=keys)
    return {
        "bundles": [
            {
                "name": b.name,
                "nodes": list(b.nodes),
                "points": b.points,
                "path": list(b.path),
                "deltas": b.deltas,
                "sum_of_parts": b.sum_of_parts,
                "synergy": {k: b.synergy(k) for k in keys},
                "per_point": {k: round(b.per_point(k), 4) for k in keys},
                # 가는 길에 딸려 온 목적지 — 유저가 길을 고를 때 실제로 세는 값이다.
                # 포인트와 델타가 같아 보이는 두 길이 여기서 갈린다.
                "incidental": [{"node": n, "name": nm} for n, nm in b.incidental],
                "unreachable": list(b.unreachable),
            }
            for b in results
        ],
        # **길의 가치 비교** — 묶음을 나란히 놓지 않으면 "포기하고 대안" 판단이 안 된다.
        # 순위는 첫 stat의 포인트당 효율이고, 부수 획득은 순위에 **안** 넣는다
        # (그 값어치는 이미 델타에 들어 있거나 나중 축이라 이중 계산이 된다).
        "comparison": {
            "ranked_by": f"per_point[{keys[0]}]",
            "rows": [
                {
                    "name": b.name,
                    "points": b.points,
                    "delta": round(b.deltas.get(keys[0], 0.0), 2),
                    "per_point": round(b.per_point(keys[0]), 4),
                    "incidental": len(b.incidental),
                }
                for b in sorted(results, key=lambda x: -x.per_point(keys[0]))
            ],
            "note": "포인트당 효율 순. 델타가 큰 쪽이 아니라 **싼 쪽**이 이길 수 있다 — "
            "포기 판단은 여기서 나온다. 부수 획득 수는 참고이고 순위에 넣지 않았다",
        },
    }


def evaluate_change_bundle(
    build_spec: dict[str, Any],
    changes: list[dict[str, Any]],
    name: str = "",
    stats: list[str] | None = None,
) -> dict[str, Any]:
    """아이템·주얼·트리 노드를 **섞어** 묶음으로 실측한다 (이관 4 C4).

    `evaluate_bundles`가 트리 노드만 받는 데 비해 여기는 장비 조합을 다룬다.
    실측 2026-08-05: 눈알 왕관과 래스피스 구체가 각각 단독 델타 **정확히 0**인데
    함께 넣으면 **1.44배**였다 — 아이템 단위 평가로는 둘 다 탈락한다.

    changes = [{"item": {"slot": "Helmet", "text": "Rarity: UNIQUE\n…"}},
               {"item": {"slot": "Amulet", "text": "…"}},
               {"nodes": [12345]}, {"jewel": {"socket_node_id": 1, "text": "…"}}]

    반환의 `synergy`(묶음 델타 - 개별 합)가 양수면 **함께여야 열리는 조합**이다.
    묶음 구성은 호출자가 한다 — 어떤 조합이 말이 되는가는 판단이다(AD-3).
    """
    from pok.engine.tree.deltas import evaluate_change_bundle as _bundle

    keys = tuple(stats or ("CombinedDPS", "Life", "TotalEHP"))
    result = _bundle(spec_from_dict(build_spec), _get_graph(), changes, name=name, stats=keys)
    return {
        "name": result.name,
        "parts": list(result.parts),
        "deltas": result.deltas,
        "sum_of_parts": result.sum_of_parts,
        "synergy": {k: result.synergy(k) for k in keys},
    }


def optimize_items(
    build_spec: dict[str, Any],
    slots: list[str],
    weights: dict[str, float],
    rare_templates: dict[str, list[str]] | None = None,
    floors: dict[str, float] | None = None,
    max_rounds: int = 3,
    max_candidates_per_slot: int | None = None,
    jewel_sockets: list[int] | None = None,
    max_chain: int = 4,
) -> dict[str, Any]:
    """아이템 그리디 최적화 — `optimize_tree`의 아이템판 (사용자 지시 2026-08-06).

    라운드마다 각 슬롯의 후보(**KB 유니크 전수 열거** + `rare_templates`의 희귀안 —
    최선 희귀는 `optimize_rare`로 만들 수 있다)를 현재 문맥에서 PoB 실측하고, 정책
    점수 최고의 양수 채택을 반영한 뒤 재측정하며 돈다. **전수가 기본**이다(사용자
    승인 2026-08-06) — max_candidates_per_slot을 주면 자르되 notes로 알린다.

    ⏱ **오래 걸린다 — 정지가 아니다.** 유니크 전수가 8슬롯 303종이라 2라운드면
    600회 이상을 잰다. 상주 데몬으로 **약 2분 20초**(실측 2026-08-11, 8슬롯·2라운드·
    floors 4종). 그동안 부모 프로세스는 자식을 기다려 **CPU 0%·출력 0**으로 보인다 —
    한 세션이 이 모습을 정지로 판단해 29분 46초 만에 강제 종료했다(그때는 데몬을 안
    써서 실제로 30분짜리였다). 결과 `notes` 마지막 줄에 **실측 횟수**가 실린다.

    슬롯은 PoB 슬롯명 + `"Charm 1"`(호신부)·`"Flask 1"`(플라스크)·`"Jewel"`(유니크
    주얼 — `jewel_sockets`에 트리에 할당된 소켓 node_id를 줘야 실측되고, 안 주면
    미측정으로 보고된다).

    **착용 가능성**: 요구 속성 미달(`ReqStr` 등) 후보는 1판 델타가 낙관이므로 채택
    금지 — 속성 탐침 2판으로 "지불 시 이득"만 낸다. **2판 측정**: 스케일 문구
    (`per N maximum Life`) 보유 유니크는 그 축을 탐침으로 올린 문맥에서도 잰다.
    1판에서 밀려도 2판 우세면 `conditional_peaks`로 나온다 — 실측: 래스피스의 구체
    1판 DPS +68(희귀 +71에 밀림) / 2판 +134. 탐침 기반은 채택하지 않되(AD-3),
    **수요 축을 실제로 공급하는 다른 슬롯 후보와의 연쇄 실측**(`chains`)이 단독
    최선을 이기면 채택한다 — 가정이 아니라 측정이다. 연쇄는 쌍에서 멈추지 않고
    개선되는 한 `max_chain`(기본 4)까지 이어 붙는다(사용자 지시 2026-08-06 —
    "쌍만으로는 고차원 빌드 불가"). 시드·공급자 모두 유니크·희귀를 가리지 않아
    고유+희귀·희귀+희귀 연쇄가 같은 경로로 나온다. 각 연쇄의 `synergy`(연쇄 -
    단독합)가 곱연산 맞물림의 수치다.

    `floors`(예: {"FireResist": 75})를 깨는 채택은 하지 않는다. 롤은 mid 고정.
    소요: 후보당 PoB 1~2회(~1.4초) — 전 슬롯 전수는 라운드당 ~10분.

    ⚠ **`weights`에 딜 축만 주면 순수 방어 유니크는 점수가 정확히 0이라 절대
    채택되지 않는다.** 그래서 방어 축은 가중치와 무관하게 **항상 재고**(PoB가 한 번에
    전 스탯을 주므로 비용 0), 가중 축 0 · 방어 양수인 후보를 `defensive_only`로 실어
    보낸다 — 채택은 여전히 가중치가 정하되(AD-3) **안 보이지는 않게** 한다.
    실측 2026-08-09(허리띠 20종·딜 가중): 채택 가능 **0건**인데 12종이 EHP를 올렸다.
    방어를 실제로 반영하려면 `weights`에 `TotalEHP` 같은 축을 함께 준다.
    """
    from pok.engine.items import optimize_items as _optimize

    result = _optimize(
        build_spec,
        slots,
        weights,
        rare_templates=rare_templates,
        floors=floors,
        max_rounds=max_rounds,
        max_candidates_per_slot=max_candidates_per_slot,
        jewel_sockets=tuple(jewel_sockets or ()),
        max_chain=max_chain,
    )
    return {
        "spec": {
            **result.spec,
            "derived_from": _stamp(
                result.spec, "items", tool="optimize_items", weights=dict(weights)
            ),
        },
        "steps": [
            {"slot": s.slot, "adopted": s.adopted, "deltas": s.deltas, "replaced": s.replaced}
            for s in result.steps
        ],
        "conditional_peaks": [
            {
                "label": p.candidate.label,
                "slot": p.candidate.slot,
                "scaling_axes": list(p.scaling_axes),
                "probe": p.probe,
                "delta_now": p.delta_now,
                "delta_probed": p.delta_probed,
                "req_shortfall": p.req_shortfall,
            }
            for p in result.conditional_peaks
        ],
        "chains": [
            {
                "members": [{"label": m[0], "slot": m[1]} for m in c.members],
                "axis_path": list(c.axis_path),
                "delta_chain": c.delta_chain,
                "synergy": c.synergy,
                "blocked": c.blocked,
            }
            for c in result.chains
        ],
        # 가중 축은 0인데 방어는 개선하는 후보 — **점수로는 절대 안 올라온다**(#18).
        # 채택하지 않되 보이게 한다: 딜 가중이 기본 사용 패턴이라, 그 패턴에서
        # 한 부류가 통째로 안 보이는 것이 결함이었다.
        "defensive_only": [
            {
                "label": d.candidate.label,
                "slot": d.candidate.slot,
                "delta_now": d.delta_now,
            }
            for d in result.defensive_only
        ],
        # 후보가 **움직였는데 가중치에 없는** 축 (10차 이관). #18·#22·#25가 전부
        # 이 형태였고 셋 다 사용자가 지적해줘야 발견됐다 — 도구가 안 내면 안 보인다.
        # 계열 대표만 낸다(실측 57축 → 20계열): 같은 사실이 9줄로 나오기 때문이다.
        "unscored_axes": [
            {
                "axis": a.axis,
                "family": a.family,
                "delta": a.delta,
                "relative": a.relative,
                "siblings": list(a.siblings),
            }
            for a in result.unscored_axes
        ],
        "notes": list(result.notes),
    }


def optimize_rare(
    build_spec: dict[str, Any],
    slot: str,
    base_type: str,
    weights: dict[str, float],
    floors: dict[str, float] | None = None,
    prefix_count: int | None = None,
    suffix_count: int | None = None,
    top_table: int = 15,
    radius: str | None = None,
) -> dict[str, Any]:
    """이 빌드의 최선 희귀를 결정적으로 생성 (사용자 승인 2026-08-06 — 사고 4·5).

    베이스의 접사 풀 — 표준 크래프트(item) + **desecrated(뼈 무덤 제작)·훼손(corrupted)**
    (사용자 요구: 모든 속성 부여 경로) — 을 **이 빌드 문맥에서 접사별 단독 실측**하고,
    점수 상위 접두3·접미3(+훼손 1)을 조립해 재실측 + 합법성 검사(RC4)까지 낸다.
    반환 text를 `optimize_items`의 rare_templates에 넣으면 유니크와 같은 조건에서
    비교된다 — 비교 기준이 세션 판단이 아니라 측정이 된다. chosen의 `origin`이
    획득 경로다(desecrated=뼈 무덤 제작 조달, 훼손=바알 오브 도박 — notes에 명시).
    ⚠ desecrated는 접사 출처이지 스킬 '신성 모독'(Blasphemy, 정신력 점유)이 아니다.
    ⚠ 완벽 에센스 전용 모드 82건은 부위 매핑이 KB 미수록이라 열거 불가(ingest 갭
    보고됨, 2026-08-06) — 일반 에센스는 표준 풀 보장이라 item에 포함돼 있다.

    ⚠ **`unmeasurable`을 반드시 읽을 것** — PoB가 문구를 못 읽는 접사는 단독 델타가
    0이라 그리디가 **절대 고르지 않는다.** 그러면 조립 결과는 그 축을 뺀 **바닥값**인데
    말하지 않으면 "이 베이스의 고점"으로 읽힌다. 실측 2026-08-09: `Amber Amulet` 접사
    풀 82건 중 **32건(39%)**이 여기 해당한다. 등가 문구로 바꿔 `ItemSpec.substitutes`에
    넣으면 **추산**으로는 잴 수 있다(`skills/build-generation` §대리 측정).

    **주얼은 `slot="Jewel@<소켓 node_id>"`로 부른다** — 그 소켓이 build_spec의
    tree_nodes에 할당돼 있어야 PoB가 반영한다. 아니면 델타가 전부 0으로 나오고,
    엔진이 그것을 notes에 '측정 무효' 신호로 낸다(실측 2026-08-06: 0을 '효과 없음'
    으로 읽어 주얼이 저스펙 출고됐다). 접사 한도는 정본 판 규칙에서 읽는다
    (장비 3/3 · 주얼 2/2) — prefix_count/suffix_count는 덮어쓸 때만 준다.

    한계도 반환에 있다: 단독 점수 그리디(접사 상호작용은 조립 실측에만 반영),
    롤 mid 고정. 소요: 접사 풀 크기 x ~1.4초 — 슬롯당 1~2분.
    """
    # ⚠ **반경 주얼(Time-Lost 계열)은 `radius`를 줘야 한다** — 선언이 없으면 PoB가
    # 반경을 정하지 못해 반경 부여 접사의 델타가 **전부 0**이 된다(제안 B 실측:
    # 10.44 → 15.84). 안 주면 결과 `notes`가 그 사실을 말한다.
    from pok.engine.rares import optimize_rare as _optimize

    result = _optimize(
        build_spec,
        slot,
        base_type,
        weights,
        floors=floors,
        prefix_count=prefix_count,
        suffix_count=suffix_count,
        radius=radius,
    )
    return {
        "text": result.text,
        "derived_from": _stamp(
            _with_item(build_spec, slot, result.text),
            "rares",
            tool="optimize_rare",
            weights=dict(weights),
        ),
        # **PoB 명세**(모드 id) — 문구가 아니다(#34 A). `text`는 이 명세를 PoB에
        # 태워 되받은 정본이고, `pob_rendered: false`면 아직 우리가 쓴 문구다.
        "spec_text": result.spec_text,
        "pob_rendered": result.pob_rendered,
        "delta": result.delta,
        "legal": result.legal,
        "legality_errors": list(result.legality_errors),
        "floor_violations": list(result.floor_violations),
        "req_shortfall": result.req_shortfall,
        # PoB가 문구를 못 읽어 **점수를 못 매기는** 접사 (#22). 있으면 이 조립은
        # 그 축을 뺀 **바닥값**이지 고점이 아니다 — 말하지 않으면 고점으로 읽힌다.
        "unmeasurable": [
            {"id": o.label, "type": o.affix_type, "origin": o.origin, "text": o.text}
            for o in result.unmeasurable
        ],
        "chosen": [
            {
                "id": r.option.label,
                "type": r.option.affix_type,
                "origin": r.option.origin,
                "text": r.option.text,
                "delta": r.delta,
            }
            for r in result.chosen
        ],
        "table_top": [
            {
                "id": r.option.label,
                "type": r.option.affix_type,
                "origin": r.option.origin,
                "delta": r.delta,
            }
            for r in result.table[:top_table]
        ],
        "table_size": len(result.table),
        "notes": list(result.notes),
    }


def optimize_runes(
    build_spec: dict[str, Any],
    slot: str,
    weights: dict[str, float],
    sockets: int,
    exclude_legacy: bool = False,
) -> dict[str, Any]:
    """슬롯의 **룬 칸을 실측 그리디로 채운다** (백로그 #33).

    룬은 이 프로젝트에서 **두 번** 통째로 빠졌다 — 16칸 0% 사용으로 검사 5종을 통과했고
    (나중에 채우자 DPS +37~47%), 21칸을 채우자 **IgniteDPS +69.6%**였다.
    `check_constraints(exhaustion.sockets)`는 미사용을 **보고만** 하고 채워 주지 않는다.

    ⚠ **반환 `text`를 그대로 쓸 것.** 룬을 손으로 `{rune}` 줄만 적으면 모드는 들어가고
    **증폭이 조용히 빠진다** — PoB는 `Sockets:`/`Rune:` 선언을 읽어야
    `socketedRuneEffectModifier`를 곱한다(`Item.lua:2192-2209`). 실측 2026-08-09
    (룬 효과 +200% 완드): 손기입 Δ+26.5 vs 선언 형식 Δ+79.4 — **3.00배**.

    규칙(사용자 확인): 유산은 **전 장비 통틀어 1개**(다른 슬롯이 이미 썼으면
    `exclude_legacy=True`) · 고유명은 같은 이름 1개 · 일반(Lesser/Greater/Perfect)은 중복 가능.

    `measured`는 룬별 단독 델타 **전량**이다(절단 없음) — 0인 것들이 대부분이라
    "이 부위엔 쓸 룬이 없다"도 근거로 남는다.
    """
    from pok.engine.runes import optimize_runes as _optimize

    fill = _optimize(
        build_spec,
        slot,
        weights,
        sockets=sockets,
        exclude_legacy=exclude_legacy,
    )
    if fill is None:
        return {
            "filled": False,
            "why": (
                f"{slot}: 룬 후보가 없거나 소켓이 0이다 — 슬롯에 아이템이 있는지, "
                f"sockets를 줬는지 확인할 것"
            ),
        }
    return {
        "filled": True,
        "slot": fill.slot,
        "derived_from": _stamp(
            _with_item(build_spec, fill.slot, fill.text),
            "runes",
            tool="optimize_runes",
            weights=dict(weights),
        ),
        "chosen": [{"id": r.label, "name": r.name, "lines": list(r.lines)} for r in fill.chosen],
        "text": fill.text,
        "delta": fill.delta,
        "measured": [{"id": rid, "delta": d} for rid, d in fill.measured],
    }


def find_clusters(
    include: list[list[Any]],
    exclude: list[str] | None = None,
    radii: list[float] | None = None,
    min_score: float = 0.0,
    top: int = 5,
    centers_per_band: int = 3,
    for_ascendancy: str | None = None,
) -> dict[str, Any]:
    """관련 노터블이 가장 촘촘한 트리 좌표를 찾는다 (백로그 제안 A).

    `optimize_tree`는 현재 트리 **반경 안**만 보므로 먼 뭉치를 구조적으로 못 본다 —
    실측: 예산 87로 돌려 43포인트에서 조기 종료했고, 손으로 밀집도를 보니 병목을 정면
    으로 푸는 노터블(인화성 강도 80% 등)이 **전부 후보 반경 밖**이었다.

    `include` = `[["ignite", 1.0], ["critical", 0.5]]` 꼴 (키워드·가중치).
    ⚠ **필수다.** 관련성 필터 없는 밀집도는 쓰레기다 — 실측: 필터 없이 돌리니
    "반경 1000에 노터블 9개"가 나왔고 그중 **3개가 도리깨 노드**였다.
    `exclude`로 컨셉 밖 축(무기 계열·소환수 등)을 쳐낸다.

    `radii`를 생략하면 **실측 주얼 반경**을 쓴다(실효 = 표기의 1.2배):
    Small 1,200 · Medium 1,380 · Large 1,560 · Very Large 1,800 ·
    Variable 2,160~2,520(**도넛** — inner 안쪽은 안 덮는다). 임의의 큰 값을 넣으면
    "주얼 하나로 덮인다"는 틀린 결론이 난다(발의 세션이 3,800 가정으로 두 번 철회했다).

    `for_ascendancy`를 주면 **다른 전직 전용 해금 노드를 뺀다** — 안 빼면 인게임에서
    못 찍는 노드가 점수를 부풀린다(B-13에서 실제로 「힘 소진」이 설계 근거로 올라갔다).

    노터블을 **효과 문구째로** 낸다 — 점수만 보면 두 축을 동시에 봐야 보이는 조합을
    영원히 못 찾는다.
    """
    from pok.engine.tree.clusters import find_clusters as _find

    clusters = _find(
        _get_graph(),
        include=[(str(k), float(w)) for k, w in include],
        exclude=tuple(exclude or ()),
        radii=tuple(radii) if radii else None,
        min_score=min_score,
        top=top,
        centers_per_band=centers_per_band,
        for_ascendancy=for_ascendancy,
    )
    return {
        "clusters": [
            {
                "label": c.label,
                "center": list(c.center),
                "radius": c.radius,
                "inner": c.inner,
                "total_score": c.total_score,
                "hits": [
                    {
                        "node_id": h.node_id,
                        "name": h.name_ko or h.name_en,
                        "score": h.score,
                        "position": list(h.position),
                        "stats_en": list(h.stats_en),
                        **({"locked_to": h.locked_to} if h.locked_to else {}),
                    }
                    for h in c.hits
                ],
            }
            for c in clusters
        ]
    }


def list_implicits(base_type: str, root_dir: str | None = None) -> dict[str, Any]:
    """베이스가 가질 수 있는 **임플리싯 경로** 전량 (백로그 #22).

    `optimize_rare`는 접사 풀만 열거하므로 임플리싯 축이 **구조적으로 안 보인다** —
    사용자가 짚은 「에센스로 최대 퀄리티 +20% → 기폭제로 40% → 옵션 교체」의 부품이
    전부 임플리싯이라 후보에 오르지 못했다.

    ⚠ **값을 재 주지 않는다.** 실측 2026-08-09: `+20% to Maximum Quality`는 PoB가
    문구 자체를 못 읽는다(`pob_measurable: false`). 그런 후보의 델타 0은 "값어치
    없음"이 아니라 **"측정 안 됨"**이다 — 대리 측정은 `ItemSpec.substitutes`로.

    ⚠ `slot_certain: false`는 **이 슬롯 것인지 확실하지 않다**는 뜻이다(임플리싯
    Modifier 264건 전부 `applicable_pages`가 비어 있어 `pob_key` 이름이 유일한
    신호다). 빼지 않고 뒤로 미뤄 둔다 — 빼면 조용한 누락이 된다.
    """
    from pathlib import Path

    from pok.engine.implicits import (
        enumerate_implicits,
        load_records,
        uncertain_note,
        unmeasurable_note,
    )

    root = Path(root_dir) if root_dir else None
    options = enumerate_implicits(base_type, load_records(root))
    notes = [n for n in (uncertain_note(options), unmeasurable_note(options)) if n]
    return {
        "base_type": base_type,
        "options": [
            {
                "source": o.source,
                "label": o.label,
                "lines": list(o.lines),
                "slot_certain": o.slot_certain,
                "pob_measurable": o.pob_measurable,
                **({"pob_gap": o.pob_gap} if o.pob_gap else {}),
            }
            for o in options
        ],
        "certain_count": sum(1 for o in options if o.slot_certain),
        "notes": notes,
    }


def passed_over_nodes(
    concept: str,
    include: list[list[Any]],
    season: str = "0-5",
    within: int = 3,
    top: int = 25,
) -> dict[str, Any]:
    """래더 표본이 **닿는 거리에 두고도 안 찍은** 목적지 노드 (포기 판단의 근거).

    채택률 표는 찍은 것만 보여 준다. 그런데 트리 설계의 절반은 「필수처럼 보이는데
    동선 비용이 가치를 넘어서 포기한 것」이고, **부재는 세어지지 않아** 그 판단의
    근거가 어디에도 없었다. 이 도구가 그 반대편을 센다.

    `passed_by`가 표본 수에 가깝고 `taken_by`가 0이면 **전원이 코앞에서 지나쳤다** —
    앵커로 삼으려던 노드가 거기 있으면 앵커를 다시 고르라는 신호다. 반대로
    `taken_by`가 높은데 `passed_by`도 높으면 **갈리는 선택**이라 자유석에 가깝다.

    `within`은 이미 찍은 노드에서의 BFS 거리(= 더 써야 할 포인트). 기본 3은 실측으로
    정했다 — 2는 좁아 놓치고 4부터는 「닿는 거리」가 아닌 것이 섞인다.
    `include` = `[["Totem", 2.0], ["Spirit", 1.0]]` 꼴. ⚠ **필수다** — 관련성 필터가
    없으면 무관한 노터블이 표를 덮는다(토템 표본이 소환수 노터블을 지나친 것은
    포기가 아니라 무관이다).

    `concept`은 수집 디렉터리 이름이다(`skillmodes-Totem`·`class-Blood_Mage`).
    ⛔ 왜 지나쳤는지는 **판정하지 않는다** — 비용인지 중복인지 조건 미달인지는
    해석이고, 표본이 작을 때 조용히 틀린다.
    """
    from pok.artifacts.ladder import LadderError
    from pok.engine.ladder_aggregate import passed_over as _passed

    if not include:
        raise ValueError(
            "include가 비었다 — 관련성 필터 없이는 무관한 노터블이 표를 덮는다"
            "(실측: 토템 표본 상위에 소환수 노터블이 올라왔다)"
        )
    try:
        out = _passed(
            season,
            concept,
            within=within,
            include=[(str(k), float(w)) for k, w in include],
        )
    except LadderError as exc:
        return {"error": str(exc), "how": "수집 디렉터리 이름을 확인할 것(공백은 `_`)"}
    total = len(out["rows"])
    out["rows"] = out["rows"][:top]
    out["truncated"] = {"shown": len(out["rows"]), "total": total}
    return out


def suggest_anchors(
    ascendancy: str,
    include: list[list[Any]] | None = None,
    axes: dict[str, Any] | None = None,
    top: int = 20,
    min_ci_low: float | None = None,
) -> dict[str, Any]:
    """트리를 짜기 전에 **목적지 후보를 한 번에 모은다** (#67 6차).

    이걸 먼저 부르고 `required`를 `optimize_tree(required_anchors=…)`에 넣는 것이
    표준 순서다. 안 부르면 앵커 없이 그리디만 돌게 되고, 그게 「필요한 노드를 안
    찍는」 결과로 돌아온다(실측: 어센던시 22종 전부에 전원 공통 노드가 1~11개 있다).

    출처가 넷이고 **성격이 달라 섞으면 안 된다**:

    - `required` — 채택률의 **95% 신뢰 하한이 `min_ci_low`(기본 80) 이상**인 목적지.
      옛 기준은 「표본 전원」(count == n)이었는데 **문턱이 표본 크기에 매여 있었다** —
      10/10의 전원은 하한 72.2짜리, 50/50은 92.9짜리다. 표본을 10 → 50으로 올리자
      클래스 22종 합계가 86 → 37개로 줄고 3개 클래스는 0이 됐다(같은 코퍼스인데
      「필수가 사라진」 것처럼 보인다). 반환값의 `min_ci_low`가 기준을 밝힌다.
    - `common` — 나머지를 채택 순으로. 자유석 후보이고 넣을지는 판단이다.
    - `off_corpus` — 표본이 안 갔지만 관련 노터블이 촘촘한 곳(`find_clusters`).
      **새 선택의 재료**다. `include`를 줘야 나온다.
    - `cautions` — 표본이 **코앞에 두고도 버린** 노드(`passed_over`). 앵커로 삼으려던
      게 여기 있으면 다시 생각할 것. 실측: 마셜 아티스트 표본 10벌이 Hollow Palm
      Technique을 전원 지나쳤다 — 문구만 보면 1순위로 보이는 키스톤이다.

    **`axes` = 컨셉 논의에서 나온 축을 그대로 넘긴다** — 이게 「먼 노드를 못 찍는」
    문제의 답이다. 그리디는 먼 목적지로 **출발하지 않으므로**(첫 걸음 점수가 낮다)
    축마다 앵커를 미리 잡아 줘야 한다. 축을 **따로** 찾는 것이 요점이다 — 한 뭉치로
    섞으면 점수 높은 축이 목록을 독점하고 나머지 축은 앵커를 못 받는다.

    ```
    axes = {
      "주문 치명타": {"include": [["critical", 2.0], ["spell", 1.5]],
                     "exclude": ["attack", "melee", "bow"]},
      "회피":        {"include": [["evasion", 2.0]]},
      "로우라이프":  {"include": [["low life", 3.0], ["reserved", 1.0]]},
    }
    ```
    → `by_axis.proposed_anchors`를 `optimize_tree(required_anchors=…)`에 그대로 넣는다.
    `by_axis.cost`가 **몇 포인트가 드는지**를 미리 알려 준다(실측: 위 3축 74포인트 ·
    대각선 22,730 · 경유 목적지 4개 덤).
    ⚠ **제외어가 있어야 쓸 만하다** — 주문 빌드에 「치명타」만 주면 근접 공격
    노터블이 상위를 차지한다(문구 매칭은 피해 유형을 모른다). 축 선정 자체는
    **판단**이라 컨셉과 대조해 쓸 것.

    `include` = `[["Critical", 2.0], ["Attack Speed", 1.0]]` 꼴(효과 문구 키워드x가중치).
    ⛔ 코퍼스는 탐색 **순서**이지 **범위**가 아니다 — `common`에 없다고 배제 근거가
    되지 않는다. `tree_shape`는 표본의 목적지:동선 비율이라 우리 트리가 동선에
    과하게 썼는지 보는 기준선이다.
    """
    from pok.engine.tree.corpus import suggest_anchors as _suggest

    kwargs: dict[str, Any] = {}
    if min_ci_low is not None:
        kwargs["min_ci_low"] = float(min_ci_low)
    return _suggest(
        _get_graph(),
        ascendancy,
        include=[(str(k), float(w)) for k, w in (include or [])],
        axes=axes,
        top=top,
        **kwargs,
    )
