"""트리 최적화 MCP 도구 — P4 (connect_anchors·optimize_tree). 얇은 어댑터."""

from __future__ import annotations

from typing import Any

from pok.common.paths import knowledge_dir
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


def connect_anchors(class_name: str, targets: list[int]) -> dict[str, Any]:
    """타깃 노드들(KB node_id)을 클래스 시작점에서 최소 포인트로 연결
    (그리디 슈타이너 — 근사). 반환: 할당 노드 전체와 타깃별 경로·총 포인트."""
    allocated, paths = _get_graph().connect_anchors(class_name, targets)
    return {
        "allocated": allocated,
        "points": len(allocated),
        "paths": {str(t): p for t, p in paths.items()},
    }


def optimize_tree(
    build_spec: dict[str, Any],
    weights: dict[str, float],
    point_budget: int,
    candidate_radius: int = 8,
    max_candidates_per_round: int = 40,
    jewel_templates: list[str] | None = None,
) -> dict[str, Any]:
    """현재 빌드 문맥에서 포인트 예산만큼 트리를 개선한다. 후보 노드 효율은
    전부 PoB 델타 실측 — 채택된 각 수(step)에 근거 델타가 담긴다.
    weights = 다축 정책(RC3), 예: {"CombinedDPS": 1.0, "Life": 0.6}.
    jewel_templates = 소켓 평가용 가정 주얼 raw 텍스트들(빌드 컨셉에서 도출,
    check_item_legality 통과분만) — 소켓 후보를 템플릿별 실측해 최선을 채택하고
    steps의 jewel_text·결과 jewels에 기록한다(조달 가정임을 남길 것).
    max_candidates_per_round = 라운드당 평가할 후보 수(거리순 상한). 시작점 주변이
    빌드와 무관한 노터블뿐이면(예: 물리 공격 빌드의 마녀 권역) 40개가 전부 델타 <= 0이라
    `stopped_no_positive`로 즉시 멈춘다 — 그럴 때 늘려서 더 먼 후보까지 본다.
    소요: 라운드당 후보 수 x ~0.1초 — 예산 30이면 수 분."""
    spec = spec_from_dict(build_spec)
    out = _optimize(
        spec,
        _get_graph(),
        Objective(weights=weights),
        point_budget=point_budget,
        candidate_radius=candidate_radius,
        max_candidates_per_round=max_candidates_per_round,
        jewel_templates=tuple(jewel_templates or ()),
    )
    return {
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
                "unreachable": list(b.unreachable),
            }
            for b in results
        ]
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
        "spec": result.spec,
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
    from pok.engine.rares import optimize_rare as _optimize

    result = _optimize(
        build_spec,
        slot,
        base_type,
        weights,
        floors=floors,
        prefix_count=prefix_count,
        suffix_count=suffix_count,
    )
    return {
        "text": result.text,
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
