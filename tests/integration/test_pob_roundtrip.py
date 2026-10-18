"""pob/ 통합 — 실제 LuaJIT + PoB 스냅샷으로 계산 왕복 (환경 없으면 skip).

기대값은 P3 Phase 0 스파이크·CI(pob-smoke, Windows·macOS 동일 출력)로 고정된
회귀 기준이다. PoB 스냅샷을 올리면 값이 바뀔 수 있다 — 그때는 manifest의
pob_commit과 함께 갱신할 것.
"""

from __future__ import annotations

import pytest

from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec
from pok.pob.daemon import PobDaemon
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


ROBE = ItemSpec(
    slot="Body Armour",
    text=(
        "Rarity: RARE\n"
        "Pok Test Robe\n"
        "Altar Robe\n"  # KB item.altar-robe — 베이스명 그대로 (id 공간 일치)
        "Item Level: 80\n"
        "+100 to maximum Life\n"
        "+50% to Fire Resistance"
    ),
)


def test_아이템이_계산에_반영된다() -> None:
    # Phase 2 스파이크 실측: +100 생명력 → Life 1187→1292 (베이스 부수 효과 포함),
    # +50% 화염 저항 → -50→0, Altar Robe 베이스 ES 95.
    result = run_build(
        BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(ROBE,)),
        use_cache=False,
    )
    assert result.stats["Life"] == 1292
    assert result.stats["FireResist"] == 0
    assert result.stats["EnergyShield"] == 95


def test_데몬_다회_계산() -> None:
    with PobDaemon() as d:
        base = d.compute_build(BuildSpec(class_name="Sorceress", ascendancy="Sorceress1"))
        with_items = d.compute_build(
            BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(ROBE,))
        )
        tree = d.compute_build(SPEC)
    assert base.stats["Life"] == 1187
    assert with_items.stats["Life"] == 1292
    assert tree.is_tree_legal
    assert tree.stats["TotalDPS"] == pytest.approx(97.3214, abs=0.01)


def test_주얼이_계산에_반영된다() -> None:
    from pok.pob.buildxml import JewelSpec

    # 시작점→소켓 61419 연결 경로 (비연결 소켓은 PoB가 잘라 주얼도 무시된다)
    path = (44871, 56216, 9485, 60685, 1826, 39037, 57710, 8616, 46819, 61419)
    base_spec = BuildSpec(class_name="Witch", ascendancy="Witch2", tree_nodes=path)
    jewel_spec = BuildSpec(
        class_name="Witch",
        ascendancy="Witch2",
        tree_nodes=path,
        jewels=(
            JewelSpec(
                socket_node_id=61419,
                text="Rarity: RARE\nPok Jewel\nSapphire\nItem Level: 81\n7% increased maximum Life",
            ),
        ),
    )
    base = run_build(base_spec, use_cache=False)
    withj = run_build(jewel_spec, use_cache=False)
    assert 61419 in withj.allocated_nodes
    assert withj.stats["Life"] > base.stats["Life"]  # 7% 증가 반영


def test_late_gold_rarity_preserves_native_output_across_driver_daemon_and_tree() -> None:
    """Gold is applied after native rarity output; keep both observations visible."""
    from dataclasses import replace

    from pok.pob.runner import PobRunError

    # Four real legacies, one duplicate. Native midpoint (25-50) rounds to38.
    gold = ItemSpec(
        slot="Belt",
        text=(
            "Rarity: UNIQUE\nMageblood\nUtility Belt\n"
            "Implicits: 2\nHas 2 Charm Slots\n20% of Flask Recovery applied Instantly\n"
            "All Mage's Legacies have (25-50)% increased effect per duplicate Mage's Legacy "
            "you have\nLegacy of Bismuth\nLegacy of Gold\n"
            "Legacy of Quicksilver\nLegacy of Quicksilver"
        ),
    )
    gold_spec = replace(SPEC, items=(gold,))
    baseline = run_build(SPEC, use_cache=False)
    direct = run_build(gold_spec, use_cache=False)
    assert baseline.stats["EffectiveLootRarityMod"] == 1
    assert baseline.stats["LateLootRarityInc"] == 0
    assert baseline.stats["LateLootRarityMore"] == 1
    assert baseline.stats["LateLootRarityMod"] == 1
    assert direct.stats["EffectiveLootRarityMod"] == 1  # Original pinned output is preserved.
    assert direct.stats["LateLootRarityInc"] == 62
    assert direct.stats["LateLootRarityMore"] == 1
    assert direct.stats["LateLootRarityMod"] == pytest.approx(1.62)
    with PobDaemon() as daemon:
        streamed = daemon.compute_build(gold_spec)
        via_tree = daemon.compute_tree(gold_spec.tree_nodes)
        for key in (
            "EffectiveLootRarityMod",
            "LateLootRarityInc",
            "LateLootRarityMore",
            "LateLootRarityMod",
            "Life",
            "TotalDPS",
        ):
            assert streamed.stats[key] == pytest.approx(direct.stats[key])
            assert via_tree.stats[key] == pytest.approx(direct.stats[key])
        # POWER has a private candidate environment: fail instead of reporting false zeroes.
        with pytest.raises(PobRunError, match="unavailable in POWER"):
            daemon.node_power(("LateLootRarityMod",))
        assert daemon.compute_tree(gold_spec.tree_nodes).stats["LateLootRarityMod"] == 1.62
        # The raw protocol also rejects it, even without the Python preflight.
        assert daemon._proc is not None and daemon._proc.stdin is not None
        daemon._proc.stdin.write("POWER\tLateLootRarityMod\n")
        daemon._proc.stdin.flush()
        response = []
        while True:
            line = daemon._readline().strip()
            assert line
            if line == "POK_DONE":
                break
            response.append(line)
        assert response == [
            "POK_ERR:LateLootRarityMod is unavailable in POWER; use full XML or TREE computation"
        ]
        assert daemon.compute_tree(gold_spec.tree_nodes).stats["LateLootRarityMod"] == 1.62
