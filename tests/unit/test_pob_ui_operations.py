"""pok-ui가 쓰는 PoB 원본 XML/아이템 원문 경계."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pok.mcp.tools.build import compute_pob_xml
from pok.pob import ui_operations
from pok.pob.runner import PobResult
from pok.pob.ui_operations import active_spec_nodes, compute_xml, render_pob_item


def test_compute_xml_sends_supplied_xml_directly(monkeypatch: Any) -> None:
    """계산 입력은 복원 스펙이 아니라 받은 XML 그대로여야 한다."""
    seen: dict[str, Any] = {}
    xml = (
        '<PathOfBuilding2><Build/><Tree activeSpec="1">'
        '<Spec id="1" treeVersion="0_5" nodes="4739,22419"/>'
        "</Tree></PathOfBuilding2>"
    )

    def fake_run_xml(text: str, *, requested_nodes: tuple[int, ...]) -> PobResult:
        seen["xml"] = text
        seen["requested_nodes"] = requested_nodes
        return PobResult(
            stats={"Life": 1187.0},
            meta={"class": "Sorceress"},
            allocated_nodes=(4739,),
            pruned_nodes=(22419,),
            cached=False,
        )

    monkeypatch.setattr("pok.pob.ui_operations.run_xml", fake_run_xml)

    out = compute_xml(xml)

    assert seen == {"xml": xml, "requested_nodes": (4739, 22419)}
    assert out.result.stats["Life"] == 1187.0
    assert out.result.pruned_nodes == (22419,)
    assert out.diagnostics["calculation_path"] == "direct_xml"
    assert out.diagnostics["xml_preserved"] is True


def test_active_spec_nodes_reports_active_spec_metadata() -> None:
    xml = (
        '<PathOfBuilding2><Build/><Tree activeSpec="second">'
        '<Spec id="first" treeVersion="0_4" nodes="1"/>'
        '<Spec id="second" treeVersion="0_5" nodes="2,3"/>'
        "</Tree></PathOfBuilding2>"
    )

    nodes, meta = active_spec_nodes(xml)

    assert nodes == (2, 3)
    assert meta == {
        "requested": "second",
        "matched": "second",
        "tree_version": "0_5",
        "node_count": 2,
    }


def test_active_spec_nodes_accepts_pob_one_based_index() -> None:
    xml = (
        '<PathOfBuilding2><Build/><Tree activeSpec="2">'
        '<Spec treeVersion="0_4" nodes="1"/>'
        '<Spec treeVersion="0_5" nodes="2,3"/>'
        "</Tree></PathOfBuilding2>"
    )

    nodes, meta = active_spec_nodes(xml)

    assert nodes == (2, 3)
    assert meta["matched"] == "first"


@pytest.mark.parametrize(
    ("xml", "message"),
    [
        ("<!DOCTYPE x><PathOfBuilding2/>", "DTD/entity"),
        (" " * 3000 + "<!DOCTYPE x><PathOfBuilding2/>", "DTD/entity"),
        ("<NotPob/>", "PathOfBuilding2"),
        ("<PathOfBuilding2><Tree><Spec/></Tree></PathOfBuilding2>", "<Build>"),
    ],
)
def test_active_spec_nodes_rejects_malformed_or_unsafe_xml(xml: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        active_spec_nodes(xml)


def test_compute_pob_xml_refuses_known_procedure_gap_before_compute(monkeypatch: Any) -> None:
    xml = '<PathOfBuilding2><Build/><Tree><Spec nodes=""/></Tree></PathOfBuilding2>'

    def fake_restore(_: str) -> Any:
        return SimpleNamespace(
            spec={"items": [{"slot": "Ring 1", "text": "Rarity: RARE\nA\nIron Ring"}]},
            faithful=True,
            notes=(),
            needs_decision=(),
            dropped_item_granted=(),
            damage_comparable=True,
        )

    def fail_compute(_: str) -> Any:
        raise AssertionError("guard 실패 후 계산을 호출하면 안 된다")

    monkeypatch.setattr("pok.pob.restore.spec_from_pob_xml", fake_restore)
    monkeypatch.setattr(
        "pok.mcp.tools.build._procedure_refusal",
        lambda _: {"ok": False, "reason": "blocked", "blocking": ["manual rare"]},
    )
    monkeypatch.setattr("pok.pob.ui_operations.compute_xml", fail_compute)

    out = compute_pob_xml(xml)

    assert out["ok"] is False
    assert out["reason"] == "blocked"
    assert out["blocking"] == ["manual rare"]
    assert out["diagnostics"]["checks"]["procedure_checks"]["status"] == "failed"


def test_render_unique_returns_explicit_error_per_request(monkeypatch: Any) -> None:
    def fake_render_unique(name: str, variant: str | None = None) -> str | None:
        assert name == "Morior Invictus"
        assert variant == "Life"
        return "Rarity: UNIQUE\nMorior Invictus\nGrand Regalia\nSelected Variant: 2"

    monkeypatch.setattr("pok.pob.uniques.render_unique", fake_render_unique)

    out = render_pob_item(
        {"kind": "unique", "id": "unique:Morior Invictus:Grand Regalia", "variants": ["Life"]}
    )

    assert out["ok"] is True
    assert out["id"] == "unique:Morior Invictus:Grand Regalia"
    assert "Selected Variant: 2" in out["text"]
    assert render_pob_item({"kind": "unique", "id": ""})["ok"] is False


def test_render_rare_uses_pob_build_items_and_reports_failure(monkeypatch: Any) -> None:
    calls: dict[str, str] = {}

    def fake_build_items(specs: dict[str, str]) -> dict[str, str]:
        calls.update(specs)
        return {"ui": "Rarity: RARE\nNew Item\nLapis Amulet\n+174 to maximum Life"}

    def fake_load_catalog() -> dict[str, Any]:
        return {
            "entries": [
                {
                    "id": "IncreasedLife10",
                    "type": "mod",
                    "raw": {"type": "Prefix"},
                }
            ]
        }

    ui_operations._catalog_mod_types.cache_clear()
    monkeypatch.setattr("pok.pob.roundtrip.build_items", fake_build_items)
    monkeypatch.setattr("pok.pob.ui_export.load_catalog", fake_load_catalog)

    out = render_pob_item(
        {
            "kind": "rare",
            "id": "Lapis Amulet",
            "mods": ["IncreasedLife10"],
            "rolls": {"IncreasedLife10": 0.5},
            "quality": 20,
        }
    )

    assert out["ok"] is True
    assert "Prefix: {range:0.5}IncreasedLife10" in out["spec_text"]
    assert "Quality: 20" in calls["ui"]
    failed = render_pob_item({"kind": "rare", "id": "Lapis Amulet", "mods": ["bad"]})
    assert failed == {
        "ok": False,
        "kind": "rare",
        "id": "Lapis Amulet",
        "reason": "ValueError: 알 수 없는 PoB mod id: 'bad'",
        "error": "ValueError: 알 수 없는 PoB mod id: 'bad'",
    }
    ui_operations._catalog_mod_types.cache_clear()
