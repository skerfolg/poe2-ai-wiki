"""pok-ui XML 계산 경로가 기존 PoB 직접 계산과 같은 값을 내는가."""

from __future__ import annotations

import pytest

from pok.mcp.tools.build import compute_pob_xml
from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec, to_xml
from pok.pob.runner import run_xml
from pok.pob.ui_operations import render_pob_item
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


def test_compute_pob_xml_matches_direct_pob_run() -> None:
    spec = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        level=90,
        tree_nodes=(4739,),
        skills=(
            SkillGroupSpec(
                gems=(GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark"),)
            ),
        ),
    )
    xml = to_xml(spec)

    direct = run_xml(xml, requested_nodes=spec.tree_nodes, use_cache=False)
    via_tool = compute_pob_xml(xml, stats=["Life", "TotalDPS", "FireResist"])

    assert via_tool["calculation_path"] == "direct_xml"
    assert via_tool["stats"]["Life"] == direct.stats["Life"]
    assert via_tool["stats"]["TotalDPS"] == pytest.approx(direct.stats["TotalDPS"], abs=0.01)
    assert via_tool["stats"]["FireResist"] == direct.stats["FireResist"]
    assert via_tool["tree_connected"] is True
    assert via_tool["diagnostics"]["xml_preserved"] is True
    assert via_tool["diagnostics"]["checks"]["restore_for_diagnostics"]["status"] == "passed"


def test_render_base_item_can_be_equipped_and_read_by_pob() -> None:
    rendered = render_pob_item({"kind": "base", "id": "Iron Ring"})

    assert rendered["ok"] is True, rendered
    assert "Iron Ring" in rendered["text"]

    result = run_xml(
        to_xml(
            BuildSpec(
                class_name="Sorceress",
                ascendancy="Sorceress1",
                items=(ItemSpec(slot="Ring 1", text=rendered["text"]),),
            )
        ),
        use_cache=False,
    )

    assert result.dropped_items == ()
    assert any(row.get("base") == "Iron Ring" for row in result.items), result.items


def test_catalog_unique_variant_id_is_rendered_and_read_by_pob() -> None:
    rendered = render_pob_item(
        {"kind": "unique", "id": "unique:The Anvil:Bloodstone Amulet", "variants": ["3"]}
    )
    assert rendered["ok"] is True, rendered
    assert rendered["text"].startswith("Rarity: UNIQUE\nThe Anvil\n")
    assert "Selected Variant: 3" in rendered["text"]
    result = run_xml(
        to_xml(
            BuildSpec(
                class_name="Sorceress", ascendancy="",
                items=(ItemSpec(slot="Amulet", text=rendered["text"]),),
            )
        ),
        use_cache=False,
    )
    assert result.dropped_items == ()
    assert any(row.get("base") == "Bloodstone Amulet" for row in result.items), result.items


def test_catalog_rare_mod_id_and_fractional_roll_affect_pob_stats() -> None:
    rendered = render_pob_item(
        {"kind": "rare", "id": "Iron Ring", "mods": ["Strength1"], "rolls": {"Strength1": 0.5}}
    )
    assert rendered["ok"] is True, rendered
    assert "to Strength" in rendered["text"]
    baseline = run_xml(to_xml(BuildSpec(class_name="Sorceress", ascendancy="")), use_cache=False)
    equipped = run_xml(
        to_xml(
            BuildSpec(
                class_name="Sorceress", ascendancy="",
                items=(ItemSpec(slot="Ring 1", text=rendered["text"]),),
            )
        ),
        use_cache=False,
    )
    assert equipped.dropped_items == ()
    assert equipped.stats["Str"] > baseline.stats["Str"]
