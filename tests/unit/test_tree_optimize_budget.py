"""#161 — `optimize_tree`의 `point_budget`은 **총 예산**이다: 기반 트리 + 앵커 + 그리디 ≤ 예산.

실측 2026-09-10(보고 `[빌드]` 세션): `point_budget=123`에 기반 트리 23포인트를 준 회차가
「앵커 62 + 그리디 61」로 **146포인트짜리 트리를 정상 반환**했다(23+62+61). 예산에서 뺀
것은 앵커뿐이었고 기반은 세지 않았다 — 호출자가 기반 크기를 손으로 빼 줘야 맞는 회계인데
그 사실이 어디에도 없었다. 잡은 것은 조립 게이트(`compute_pob.points.over_budget`)뿐이었고,
반환된 `final_stats`는 **레벨 90에서 만들 수 없는 트리의 수치**였다(철칙 4).

⚠ 기반이 빈 회차만 시험하면 이 결함이 그대로 통과한다 — 아래는 전부 **기반이 있는** 회차다.
가짜 PoB는 스탯이 트리 크기에 선형이라(노드 1개 = Life +10) 모든 후보가 양수이고 죽은
노드가 없다 — 그리디는 예산이 허락하는 만큼 **끝까지** 산다. 그래서 예산 회계가 틀리면
반드시 초과한다.
"""

from __future__ import annotations

import dataclasses
import inspect
from typing import Any

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree import optimize as opt
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec

_graph = TreeGraph(knowledge_dir())
_START = _graph.start_of("Sorceress")
# 소서리스 시작 → Raw Power(51184) 최단 경로 5노드 — 전부 일반 패시브(KB 실측)
_BASE = tuple(_graph.shortest_path({_START}, 51184) or ())
assert len(_BASE) == 5, _BASE


class _Result:
    def __init__(self, stats: dict[str, float]) -> None:
        self.stats = stats
        self.pruned_nodes: tuple[int, ...] = ()
        self.allocated_nodes: tuple[int, ...] = ()


class _Daemon:
    """가짜 PoB — Life가 트리 크기에 선형이다. 데몬 계약(`loaded_spec`·`compute_tree`)을 지킨다."""

    def __init__(self) -> None:
        self.loaded_spec: BuildSpec | None = None
        self.calls = 0

    @staticmethod
    def _stats(nodes: tuple[int, ...]) -> dict[str, float]:
        return {"Life": 10.0 * len(nodes)}

    def compute_build(self, spec: BuildSpec) -> _Result:
        self.calls += 1
        self.loaded_spec = spec
        return _Result(self._stats(tuple(spec.tree_nodes)))

    def compute_tree(self, nodes: tuple[int, ...]) -> _Result:
        self.calls += 1
        assert self.loaded_spec is not None
        return _Result(self._stats(tuple(nodes)))

    def close(self) -> None:
        pass

    def __enter__(self) -> _Daemon:
        return self

    def __exit__(self, *exc: object) -> None:
        pass


@pytest.fixture
def daemon(monkeypatch: pytest.MonkeyPatch) -> _Daemon:
    fake = _Daemon()
    monkeypatch.setattr(opt, "PobDaemon", lambda: fake)
    return fake


def _spec(tree: tuple[int, ...] = _BASE) -> BuildSpec:
    return BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", tree_nodes=tree)


def _general(spec: BuildSpec) -> int:
    """`compute_pob`이 `points`에 싣는 것과 **같은 셈법**(`TreeGraph.point_split`)."""
    return int(_graph.point_split(spec.ascendancy, spec.tree_nodes)["general"])


def _run(spec: BuildSpec, budget: int, *, radius: int = 3, **kw: Any) -> opt.OptimizeResult:
    return opt.optimize_tree(
        spec,
        _graph,
        opt.Objective(weights={"Life": 1.0}),
        point_budget=budget,
        candidate_radius=radius,
        max_candidates_per_round=6,
        time_budget_s=None,
        **kw,
    )


def test_기반_트리를_포함해_예산을_넘지_않는다(daemon: _Daemon) -> None:
    """기반 5 + 예산 여유 2 → 반환 트리의 일반 포인트 ≤ 7. 옛 회계는 5 + 7 = 12를 냈다."""
    budget = _general(_spec()) + 2
    out = _run(_spec(), budget)
    assert out.steps, "가짜 PoB는 모든 후보가 양수다 — 한 수도 못 뒀으면 시험 전제가 깨졌다"
    assert _general(out.spec) <= budget, (
        f"반환 트리 일반 {_general(out.spec)}포인트 > 예산 {budget} — 기반 트리를 안 셌다"
    )
    ledger = out.budget
    assert ledger is not None and ledger.base_general == 5 and ledger.anchor_general == 0
    assert ledger.total_general == _general(out.spec) and ledger.over_budget == 0


def test_기반과_앵커만으로_넘치면_그리디를_돌리지_않고_밝힌다(daemon: _Daemon) -> None:
    """조용히 초과하는 것보다 **안 사고 말하는 것**이 낫다 — 만들 수 없는 트리는 산출물이 아니다."""
    out = _run(_spec(), 3)  # 기반 5 > 예산 3
    assert not out.steps, "예산이 이미 넘쳤는데 그리디가 더 샀다"
    assert set(out.spec.tree_nodes) == set(_BASE), "기반 트리는 그대로여야 한다"
    assert out.budget is not None and out.budget.over_budget == 2
    assert any("초과" in n and "기반" in n for n in out.notes), out.notes


def test_앵커_포인트도_총예산_안에서_센다(daemon: _Daemon) -> None:
    """기반 5 + 앵커 경로 + 여유 1 — 앵커는 예전부터 뺐지만 기반과 **함께** 빼야 한다."""
    anchor = 36302  # 기반 트리에서 2포인트 거리(KB 실측)
    anchor_cost = len(_graph.shortest_path(set(_BASE) | {_START}, anchor) or ())
    assert anchor_cost == 2
    budget = _general(_spec()) + anchor_cost + 1
    out = _run(_spec(), budget, required_anchors=(anchor,))
    assert anchor in out.spec.tree_nodes
    assert _general(out.spec) <= budget, f"{_general(out.spec)} > {budget}"
    assert out.budget is not None
    assert (out.budget.base_general, out.budget.anchor_general) == (5, 2)
    assert out.budget.greedy_general <= 1


def test_기반이_비면_종전과_같다(daemon: _Daemon) -> None:
    """기반 0이면 총 예산 = 그리디 몫이다 — 기존 통합 시험들이 재던 회계 그대로."""
    out = _run(_spec(()), 6, radius=6)  # 시작점에서 Raw Power까지 5 — 반경 6이어야 후보가 있다
    assert out.steps and _general(out.spec) <= 6
    assert out.budget is not None and out.budget.base_general == 0
    assert out.budget.total_general == out.budget.greedy_general


def test_mcp_반환에_예산_원장이_실린다() -> None:
    """`spent_points`만 보면 「예산 안」으로 읽힌다 — 원장(기반·앵커·그리디·총·초과)이 필요하다."""
    from pok.mcp.tools import tree as mcp_tree

    source = inspect.getsource(mcp_tree.optimize_tree)
    assert '"budget"' in source, "MCP 반환에 예산 원장이 없다"
    assert "총 예산" in (mcp_tree.optimize_tree.__doc__ or ""), "도구 설명이 회계를 말해야 한다"
    assert dataclasses.is_dataclass(opt.OptimizeResult)
