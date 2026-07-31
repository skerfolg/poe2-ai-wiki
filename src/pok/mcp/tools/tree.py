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
) -> dict[str, Any]:
    """현재 빌드 문맥에서 포인트 예산만큼 트리를 개선한다. 후보 노드 효율은
    전부 PoB 델타 실측 — 채택된 각 수(step)에 근거 델타가 담긴다.
    weights = 다축 정책(RC3), 예: {"CombinedDPS": 1.0, "Life": 0.6}.
    소요: 라운드당 후보 ~40회 계산(각 ~0.1초) — 예산 30이면 수 분."""
    spec = spec_from_dict(build_spec)
    out = _optimize(
        spec,
        _get_graph(),
        Objective(weights=weights),
        point_budget=point_budget,
        candidate_radius=candidate_radius,
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
            }
            for s in out.steps
        ],
        "pruned_branches": [
            {
                "endpoint": p.endpoint_id,
                "name": p.endpoint_name,
                "removed_nodes": list(p.nodes),
                "endpoint_removal_deltas": {
                    k: round(v, 2) for k, v in p.endpoint_removal_deltas.items()
                },
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
