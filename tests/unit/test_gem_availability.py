"""Exclusion evidence is scoped, identity-resolved, and never a calculation gate."""

import json

import pytest

from pok.engine import gem_availability as availability
from pok.kb.exclusions import fold_gem_name

SHOCK = "Metadata/Items/Gems/SkillGemEnergyShieldOnShockKillSupport"
SPARK = "Metadata/Items/Gems/SkillGemSpark"


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    directory = tmp_path / "knowledge/ingest"
    directory.mkdir(parents=True)
    row = {
        "patch": "0.5.4b",
        "approved": "2026-08-04 user",
        "slugs": ["Shock_Siphon"],
        "removed_ids": ["support.shock-siphon"],
        "evidence": "approved catalogue history",
    }
    (directory / "exclusions.json").write_text(
        json.dumps(
            {
                "version": 1,
                "unobtainable_gems": [row],
            }
        ),
        encoding="utf-8",
    )
    (directory / "manifest.json").write_text(json.dumps({"patch": "0.5.4b"}), encoding="utf-8")
    monkeypatch.setattr(
        availability, "gem_names", lambda root: {"Shock Siphon": SHOCK, "Spark": SPARK}
    )
    monkeypatch.setattr(
        availability,
        "canonical_gem_id",
        lambda identity, root: SHOCK if identity == "game-id" else identity,
    )
    return tmp_path


def spec(identity=SHOCK, name="Shock Siphon"):
    return {"skills": [{"gems": [{"gem_id": identity, "name": name}]}]}


@pytest.mark.parametrize("identity", [SHOCK, "game-id"])
def test_native_identity_and_game_alias_report_approved_scope(ledger, identity):
    result = availability.audit_gem_availability(spec(identity, "renamed"), root=ledger)
    finding = result["findings"][0]
    assert finding["catalog_name"] == "Shock Siphon"
    assert finding["scope"] == "matches_kb_patch"
    assert finding["approval"] == "2026-08-04 user"
    assert finding["removed_ids"] == ["support.shock-siphon"]
    assert finding["classification"] == "approved_exclusion"
    assert finding["ledger_entry_path"] == "/unobtainable_gems/0"
    assert finding["group_index"] == finding["gem_index"] == 0
    assert result["calculation_blocked"] is False


def test_display_name_cannot_override_another_native_identity(ledger):
    result = availability.audit_gem_availability(spec(SPARK), root=ledger)
    assert result["findings"] == []
    assert result["unresolved"] == []
    unknown = availability.audit_gem_availability(spec("unknown-id"), root=ledger)
    assert unknown["findings"] == []
    assert unknown["unresolved"][0]["reason"] == "native_identity_unresolved"
    assert unknown["absence_is_not_exclusion"] is True


def test_old_patch_and_missing_approval_are_not_current_approved_exclusion(ledger):
    path = ledger / "knowledge/ingest/manifest.json"
    path.write_text(json.dumps({"patch": "0.6"}), encoding="utf-8")
    result = availability.audit_gem_availability(spec(), root=ledger)
    assert result["findings"][0]["scope"] == "different_or_unknown_patch"
    path = ledger / "knowledge/ingest/exclusions.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["unobtainable_gems"][0]["approved"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert availability.audit_gem_availability(spec(), root=ledger)["findings"][0][
        "classification"
    ] == ("unapproved_ledger_entry")
    data["unobtainable_gems"][0]["approved"] = True
    path.write_text(json.dumps(data), encoding="utf-8")
    assert (
        availability.audit_gem_availability(spec(), root=ledger)["findings"][0]["classification"]
        == "unapproved_ledger_entry"
    )


def test_missing_ledger_and_missing_catalog_are_separate(ledger, monkeypatch):
    def unavailable(root):
        raise FileNotFoundError("missing calculator catalogue")

    monkeypatch.setattr(availability, "gem_names", unavailable)
    assert (
        availability.audit_gem_availability(spec(), root=ledger)["status"] == "catalog_unavailable"
    )
    (ledger / "knowledge/ingest/exclusions.json").unlink()
    assert (
        availability.audit_gem_availability(spec(), root=ledger)["status"] == "ledger_unavailable"
    )


def test_slug_and_diacritic_normalization():
    assert fold_gem_name("Shock_Siphon") == fold_gem_name("SHOCK Siphon")
    assert fold_gem_name("Mórrigan’s_Insight") == fold_gem_name("Morrigan's Insight")  # noqa: RUF001


def test_actual_fixed_ledger_and_native_catalog_have_the_reported_shock_siphon():
    result = availability.audit_gem_availability(spec())
    assert result["status"] == "inspected"
    assert any(
        row["catalog_name"] == "Shock Siphon"
        and row["classification"] == "approved_exclusion"
        and row["entry_patch"] == "0.5.4b"
        for row in result["findings"]
    )


def test_calculation_and_restore_adapters_report_without_blocking(monkeypatch):
    from types import SimpleNamespace

    from pok.mcp.tools import build
    from pok.pob import restore
    from pok.pob.runner import PobResult

    source = spec()
    measured = build._pick(PobResult({"Life": 123}, {}, (), (), False), ["Life"], source)
    assert measured["stats"] == {"Life": 123}
    assert measured["gem_availability"]["findings"][0]["catalog_name"] == "Shock Siphon"
    monkeypatch.setattr(
        restore,
        "spec_from_pob",
        lambda *args, **kwargs: SimpleNamespace(
            spec=source,
            notes=(),
            needs_decision=(),
            faithful=True,
            dropped_item_granted=(),
            damage_comparable=True,
            selection={},
        ),
    )
    from pok.pob.codec import encode

    restored = build.restore_pob_spec(encode("<PathOfBuilding2/>"))
    assert restored["build_spec"] == source
    assert restored["gem_availability"]["findings"] == measured["gem_availability"]["findings"]
