"""Small contract regressions for native selector configuration; no full-KB load."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP

from pok.engine import unique_items
from pok.mcp.tools import build
from pok.pob import uniques

RAW = """Fixture Unique
Utility Belt
Has Alt Variant: true
Has Alt Variant Two: true
Has Alt Variant Three: true
Allow Duplicate Variants: true
Variant: First
Variant: Second
Variant: Third
Variant: Fourth
Selected Variant: 1
Selected Alt Variant: 2
Selected Alt Variant Two: 3
Selected Alt Variant Three: 4
+(10-20) to Spirit"""


@pytest.fixture
def native(monkeypatch, tmp_path):
    (tmp_path / "Data/Uniques").mkdir(parents=True)
    monkeypatch.setattr(unique_items, "pob_src_dir", lambda root=None: tmp_path)
    monkeypatch.setattr(
        uniques, "unique_raw", lambda name, root=None: RAW if name == "Fixture" else None
    )


def test_native_controls_preserve_defaults_validate_inputs_and_materialize_requested_roll(native):
    prepared = unique_items.prepare_unique_item(
        "Fixture", {"Selected Variant": "Third", "Selected Alt Variant Two": 3}, "max"
    )
    state = {row["key"]: row for row in prepared["configured_selectors"]}
    assert state["Selected Variant"]["encoded_index"] == 3
    assert state["Selected Variant"]["origin"] == "caller_selected"
    assert state["Selected Alt Variant"]["encoded_index"] == 2
    assert state["Selected Alt Variant Three"]["encoded_index"] == 4
    assert "+20 to Spirit" in prepared["item_text"]
    assert prepared["calculation_performed"] is False
    assert uniques.render_configuration("Fixture", {}) == RAW
    choices = {"Selected Variant": "Third", "Selected Alt Variant Two": 3}
    assert uniques.render_configuration("Fixture", choices) == uniques.render_configuration(
        "Fixture", dict(reversed(list(choices.items())))
    )
    for choices in ({"Unknown": 1}, {"Selected Variant": True}, {"Selected Variant": 99}):
        with pytest.raises(ValueError):
            unique_items.prepare_unique_item("Fixture", choices)
    assert unique_items.prepare_unique_item("Missing")["status"] == "native_template_missing"


def test_native_explicit_duplicate_prohibition_is_distinct_from_unknown_policy(monkeypatch, native):
    raw = RAW.replace("Allow Duplicate Variants: true", "Allow Duplicate Variants: false")
    monkeypatch.setattr(uniques, "unique_raw", lambda *args: raw)
    with pytest.raises(ValueError, match="disallows duplicate"):
        uniques.render_configuration("Fixture", {"Selected Variant": 2})


def test_actual_mcp_adapter_accepts_configuration_and_reports_native_scope(native):
    api = FastMCP("native-configuration-contract")
    api.tool(build.prepare_unique_item)

    async def call():
        async with Client(api) as client:
            result = await client.call_tool(
                "prepare_unique_item",
                {
                    "name": "Fixture",
                    "selections": {"Selected Variant": "Fourth"},
                },
            )
            assert result.data["ok"]
            assert result.data["requested_selectors"] == {"Selected Variant": "Fourth"}
            assert result.data["source"]["identity_scope"].startswith("native_name_template")

    asyncio.run(call())
