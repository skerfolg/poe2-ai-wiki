"""pob/ 통합 — 실제 LuaJIT + PoB 스냅샷으로 계산 왕복 (환경 없으면 skip).

기대값은 P3 Phase 0 스파이크·CI(pob-smoke, Windows·macOS 동일 출력)로 고정된
회귀 기준이다. PoB 스냅샷을 올리면 값이 바뀔 수 있다 — 그때는 manifest의
pob_commit과 함께 갱신할 것.
"""

from __future__ import annotations

import pytest

from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec
from pok.pob.runner import run_build
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

SPEC = BuildSpec(
    class_name="Sorceress",
    ascendancy="Sorceress1",
    level=90,
    tree_nodes=(4739, 22419),
    skills=(
        SkillGroupSpec(
            gems=(GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark", level=20),)
        ),
    ),
)


def test_계산_왕복_스파이크_기준값() -> None:
    result = run_build(SPEC, use_cache=False)
    assert result.meta["class"] == "Sorceress"
    assert result.meta["level"] == 90
    assert result.is_tree_legal
    assert result.allocated_nodes == (4739, 22419)
    assert result.stats["Life"] == 1187
    assert result.stats["TotalDPS"] == pytest.approx(97.3214, abs=0.01)
    assert result.stats["FireResist"] == -50


def test_비연결_노드는_적법성_실패로_드러난다() -> None:
    # 5642(Behemoth)는 Sorceress 시작점과 무연결 — PoB가 소리 없이 해제하는 걸
    # pruned_nodes로 승격시키는 것이 이 어댑터의 핵심 안전장치다.
    spec = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        tree_nodes=(5642,),
    )
    result = run_build(spec, use_cache=False)
    assert not result.is_tree_legal
    assert result.pruned_nodes == (5642,)


def test_캐시_왕복() -> None:
    first = run_build(SPEC)  # 캐시에 기록 (이전 테스트와 다른 키 — use_cache 기본값)
    second = run_build(SPEC)
    assert second.cached
    assert second.stats == first.stats
