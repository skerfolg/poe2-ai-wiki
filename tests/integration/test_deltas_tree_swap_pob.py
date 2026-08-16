"""`compute_tree` 경로가 `compute_build`과 **같은 값**을 내는가 (실제 PoB, #70 후속).

단위 시험은 「언제 어느 명령을 부르는가」를 잠근다. 여기서 잠그는 것은 다른 것이다 —
**두 경로의 값이 같은가.** 이게 이 최적화의 유일한 위험이다: 첫 구현은 7.2배 빨랐지만
DPS가 1.4% 낮았고(Accuracy 846 → 636) 원인은 `hashOverrides` 소실이었다. 1.4%는
눈에 안 띄고, 안 띄면 그리디의 모든 선택이 조용히 어긋난다.

⚠ 파일명 끝의 `_pob`는 `tests/unit`과 basename이 겹치지 않게 하려는 것이다
(형제 통합 시험의 머리주석 참조 — CI가 `pytest tests`로 둘을 한 번에 부른다).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree.deltas import _Measurer
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec
from pok.pob.daemon import PobDaemon
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

_TARGET = 51184  # Raw Power (주문 피해 노터블)
_STATS = ("CombinedDPS", "Life", "TotalEHP", "Accuracy")


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(knowledge_dir())


@pytest.fixture(scope="module")
def daemon() -> Iterator[PobDaemon]:
    with PobDaemon() as d:
        yield d


@pytest.fixture(scope="module")
def spec(graph: TreeGraph) -> BuildSpec:
    path = graph.shortest_path({graph.start_of("Sorceress")}, _TARGET)
    assert path, "경로를 못 잡았다"
    return BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        tree_nodes=tuple(path),
        skills=(
            SkillGroupSpec(
                gems=(GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark", level=20),)
            ),
        ),
    )


def test_두_경로가_같은_값을_낸다(spec: BuildSpec, daemon: PobDaemon) -> None:
    """잎을 뺀 트리를 두 방법으로 잰다 — 스탯이 어긋나면 이 최적화는 무효다."""
    smaller = dataclasses.replace(spec, tree_nodes=tuple(spec.tree_nodes[:-1]))

    daemon.compute_build(spec)  # 토대를 올린다
    via_tree = daemon.compute_tree(tuple(smaller.tree_nodes))
    via_build = daemon.compute_build(smaller)

    assert set(via_tree.allocated_nodes) == set(via_build.allocated_nodes)
    for stat in _STATS:
        a, b = via_tree.stats.get(stat), via_build.stats.get(stat)
        assert (a is None) == (b is None), stat
        if a is None or b is None:
            continue
        # 1.4%짜리 어긋남을 잡는 것이 목적이라 허용 오차를 크게 두지 않는다.
        assert abs(a - b) <= max(abs(b) * 1e-6, 1e-6), f"{stat}: tree={a} build={b}"


def test_측정기가_두_경로를_섞어도_값이_유지된다(spec: BuildSpec, daemon: PobDaemon) -> None:
    """`_Measurer`를 거쳐도 같은 값이 나오는가 — 토대 재로드 판정까지 함께 탄다."""
    smaller = dataclasses.replace(spec, tree_nodes=tuple(spec.tree_nodes[:-1]))
    m = _Measurer(daemon, spec)
    m.base()
    measured = m.measure(smaller)

    direct = daemon.compute_build(smaller)
    for stat in _STATS:
        a, b = measured.stats.get(stat), direct.stats.get(stat)
        if a is None or b is None:
            continue
        assert abs(a - b) <= max(abs(b) * 1e-6, 1e-6), f"{stat}: measurer={a} build={b}"


def test_데몬이_로드된_스펙을_기억한다(spec: BuildSpec, daemon: PobDaemon) -> None:
    """호출자가 여러 겹일 때 토대를 아는 것은 데몬뿐이다."""
    daemon.compute_build(spec)
    assert daemon.loaded_spec == spec
