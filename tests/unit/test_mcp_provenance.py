"""최적화 생산자의 출처는 실제 산출 후 문맥이며, 개별 장비에 전체 도장을 복제하지 않는다."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from pok.engine.provenance import stale_components, stamp
from pok.mcp.tools import tree as tools
from pok.pob.buildxml import BuildSpec, JewelSpec


def _spec() -> dict[str, Any]:
    spec: dict[str, Any] = {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "level": 100,
        "tree_nodes": [1, 2],
        "items": [{"slot": "Weapon 1", "text": "old weapon"}],
        "jewels": [{"socket_node_id": 2, "text": "old jewel", "allocates": [99]}],
        "attribute_choices": {1: "str"},
    }
    spec["derived_from"] = {"tree": stamp(spec, "tree", tool="optimize_tree")}
    return spec


@pytest.mark.parametrize("slot", ["Weapon 1", "Jewel@2"])
def test_rare_output_contains_only_its_own_fresh_component(
    monkeypatch: pytest.MonkeyPatch,
    slot: str,
) -> None:
    from pok.engine import rares

    result = SimpleNamespace(
        text="new rare",
        spec_text="recipe",
        pob_rendered=True,
        delta={},
        legal=True,
        legality_errors=(),
        floor_violations=(),
        req_shortfall={},
        unmeasurable=(),
        chosen=(),
        table=(),
        notes=(),
    )
    monkeypatch.setattr(rares, "optimize_rare", lambda *args, **kwargs: result)
    spec = _spec()
    original = deepcopy(spec)
    output = tools.optimize_rare(spec, slot, "Ruby", {"IgniteDPS": 1})
    assert set(output["derived_from"]) == {"rares"}
    after = tools._with_item(spec, slot, output["text"])
    after.pop("derived_from")  # retained old top tree is a separate component, not this receipt
    if slot == "Weapon 1":
        after["items"][0]["derived_from"] = output["derived_from"]
    else:
        after["jewels"][0]["derived_from"] = output["derived_from"]
        assert len(after["jewels"]) == 1
        assert after["items"] == spec["items"]
    assert stale_components(after) == []
    assert spec == original


def test_rune_output_does_not_copy_the_build_tree_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    from pok.engine import runes

    result = runes.RuneFill(slot="Weapon 1", text="new runes", chosen=(), delta={}, measured=())
    monkeypatch.setattr(runes, "optimize_runes", lambda *args, **kwargs: result)
    spec = _spec()
    output = tools.optimize_runes(spec, "Weapon 1", {"IgniteDPS": 1}, sockets=1)
    assert set(output["derived_from"]) == {"runes"}
    after = tools._with_item(spec, "Weapon 1", output["text"])
    after.pop("derived_from")
    after["items"][0]["derived_from"] = output["derived_from"]
    assert stale_components(after) == []


def test_tree_output_preserves_jewel_allocates_and_stamps_actual_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _spec()
    # Force a different result from the input: newly selected jewel contents and attribute choice.
    out_spec = BuildSpec(
        class_name="Mercenary",
        ascendancy="Mercenary3",
        level=100,
        tree_nodes=(1, 2, 3),
        jewels=(JewelSpec(socket_node_id=2, text="new jewel", allocates=(99,)),),
        attribute_choices=((1, "dex"),),
    )
    result = SimpleNamespace(
        spec=out_spec,
        result=SimpleNamespace(stats={}),
        budget=None,
        termination_reason="point_budget",
        far_clusters=(),
        notes=(),
        steps=(),
        pruned=(),
        rejected_rounds=0,
        wasted_points=0,
        waste_notes=(),
    )
    monkeypatch.setattr(tools, "spec_from_dict", lambda raw: out_spec)
    monkeypatch.setattr(tools, "_get_graph", lambda: object())
    monkeypatch.setattr(tools, "_optimize", lambda *args, **kwargs: result)
    monkeypatch.setattr(tools, "compare_tree", lambda *args, **kwargs: {})
    output = tools.optimize_tree(spec, {"IgniteDPS": 1}, point_budget=123)
    assert output["jewels"] == [{"socket_node_id": 2, "text": "new jewel", "allocates": [99]}]
    assert output["attribute_choices"] == {1: "dex"}
    after = {
        **spec,
        **{k: output[k] for k in ["tree_nodes", "jewels", "attribute_choices", "derived_from"]},
    }
    assert stale_components(after) == []
    assert output["derived_from"]["tree"]["search_evidence"] == output["search_evidence"]


def test_whole_build_stamp_preserves_other_components() -> None:
    spec = _spec()
    marks = tools._stamp(spec, "items", tool="optimize_items")
    assert set(marks) == {"tree", "items"}
    assert marks["tree"] == spec["derived_from"]["tree"]
