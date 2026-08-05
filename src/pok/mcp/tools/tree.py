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
        "spent_points": sum(s.node_delta.points for s in out.steps)
        - sum(len(p.nodes) for p in out.pruned),
        "stopped_no_positive": bool(out.rejected_rounds),
        "tree_nodes": list(out.spec.tree_nodes),
        "final_stats": {k: out.result.stats[k] for k in weights if k in out.result.stats},
        # 공유 코드·기록은 assemble_pob(최종 tree_nodes로 재조립)에서 — 기록 일원화
    }
