"""engine/compute 통합 — PoB 델타 실측이 실제로 방향을 가리키는지 (환경 없으면 skip)."""

from __future__ import annotations

import pytest

from pok.engine.compute import compute_pob, evaluate_delta
from pok.pob.buildxml import BuildSpec, ItemSpec
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

BASE = BuildSpec(class_name="Sorceress", ascendancy="Sorceress1")
LIFE_ROBE = ItemSpec(
    slot="Body Armour",
    text=("Rarity: RARE\nPok Robe\nAltar Robe\nItem Level: 80\n+100 to maximum Life"),
)


def test_compute_pob_단발() -> None:
    result = compute_pob(BASE, use_cache=False)
    assert result.stats["Life"] == 1187


def test_evaluate_delta_아이템_델타_실측() -> None:
    base_result, deltas = evaluate_delta(
        BASE,
        {
            "생명력 로브": BuildSpec(
                class_name="Sorceress", ascendancy="Sorceress1", items=(LIFE_ROBE,)
            )
        },
        stats=("Life", "EnergyShield"),
    )
    assert base_result.stats["Life"] == 1187
    (delta,) = deltas
    assert delta.diff("Life") == 105  # +100 모드 + 베이스 부수 효과 실측값
    assert delta.diff("EnergyShield") == 95  # Altar Robe 베이스 ES
    assert delta.diff("TotalDPS") is None  # stats 선별 밖 — 측정 안 한 것은 None


def test_package_review_장비와_트리_동시_변경_실측() -> None:
    """Joint reallocation reaches the same oracle and records both changed domains."""
    from pok.mcp.tools import build

    base = {"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90}
    variant = {
        **base,
        "tree_nodes": [4739, 22419],
        "items": [
            {
                "slot": "Ring 1",
                "text": (
                    "Rarity: RARE\nPok Ring\nIron Ring\nItem Level: 80\n"
                    "Adds 1 to 3 Cold damage to Attacks"
                ),
            }
        ],
    }
    output = build.evaluate_delta(
        base,
        {"joint": variant},
        ["Life", "Mana"],
        review_components=["items", "tree"],
        include_variant_reviews=True,
    )
    assert output["comparison"]["measurements_complete"] is True
    assert output["review"]["measurements_complete"] is True
    assert output["base"]["stats"]["Life"] == 1187
    assert output["variants"]["joint"]["items_legal"] is True
    assert output["variants"]["joint"]["tree_connected"] is True
    evidence = output["review"]["search_evidence"]
    assert evidence["items"]["scope"]["slots"] == ["Ring 1"]
    assert set(evidence["tree"]["scope"]["tree_nodes"]) == {4739, 22419}
    for component in ("items", "tree"):
        assert evidence[component]["measurement_scope"] == "package"
        assert evidence[component]["scope"]["candidates"] == ["joint"]
        assert evidence[component]["termination"]["converged"] is False
    # A post-result choice can carry the already-measured variant's own
    # provenance. The original baseline receipt is deliberately different.
    from pok.engine.provenance import stamp

    adopted = output["variant_reviews"]["joint"]
    assert adopted["measurements_complete"] is True
    assert adopted["search_evidence"]["tree"]["scope"]["candidates"] == ["baseline"]
    for component in ("items", "tree"):
        expected = stamp(variant, component, tool="test")
        for key, value in expected.items():
            if key.endswith("_sig"):
                assert adopted["derived_from"][component][key] == value
        assert (
            adopted["search_evidence"][component]["baseline_stats"]
            == (output["variants"]["joint"]["stats"])
        )
