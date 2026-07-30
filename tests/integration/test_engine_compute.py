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
