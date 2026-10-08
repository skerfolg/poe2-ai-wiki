from __future__ import annotations

import json

from pok.pob.runtime_identity import runtime_identity
from pok.pob.ui_export import (
    _tree_version_key,
    catalog_data,
    default_tree_version_for,
    export_catalog,
    supported_tree_versions,
)


def test_ui_catalog_exports_raw_pob_tables(tmp_path) -> None:
    catalog = catalog_data()

    assert catalog["schemaVersion"] == 1
    assert catalog["extractorVersion"] == "1"
    assert catalog["defaultTreeVersion"] in catalog["supportedTreeVersions"]
    assert catalog["defaultTreeVersion"] == default_tree_version_for()
    assert supported_tree_versions() == ["0_1", "0_2", "0_3", "0_4", "0_5"]
    assert catalog["source"]["exporterVersion"] == "1"
    assert catalog["source"]["pobCommit"].startswith("5d173cb")
    identity = runtime_identity()
    assert catalog["source"]["pokSourceDigest"] == identity["pok"]["sourceDigest"]
    assert catalog["source"]["pobSourceDigest"] == identity["pob"]["sourceDigest"]
    assert catalog["source"]["kbManifestSha256"] == identity["kb"]["manifestSha256"]
    assert catalog["source"]["kbContentSha256"] == identity["kb"]["contentSha256"]

    witch = next(c for c in catalog["classes"] if c["id"] == "Witch")
    assert witch["internalId"] == 1
    assert witch["legacyId"] == 6
    abyssal = next(a for a in witch["ascendancies"] if a["id"] == "Witch3b")
    assert abyssal == {"id": "Witch3b", "name": "Abyssal Lich", "legacyId": 4}

    by_id = {entry["id"]: entry for entry in catalog["entries"]}
    assert by_id["Metadata/Items/Gems/SkillGemIceNova"]["type"] == "gem"
    assert by_id["Metadata/Items/Gems/SkillGemIceNova"]["gameId"] == (
        "Metadata/Items/Gems/SkillGemIceNova"
    )
    assert 20 in by_id["Metadata/Items/Gems/SkillGemIceNova"]["levels"]
    assert by_id["ArcPlayer"]["type"] == "skill"
    assert "statSets" in by_id["ArcPlayer"]["raw"]
    assert by_id["ArcPlayer"]["raw"]["skillTypes"]["2"] is True  # Original SkillType.Spell.
    assert by_id["Crimson Amulet"]["type"] == "base"
    assert "implicit" in by_id["Crimson Amulet"]["raw"]
    assert by_id["Strength1"]["type"] == "mod"
    assert by_id["Strength1"]["raw"]["group"] == "Strength"
    assert any(d["kind"] == "unsupported-lua-function" for d in catalog["diagnostics"])
    assert all(d.get("handling") == "delegated-to-pob" for d in catalog["diagnostics"])
    assert all(d.get("severity") == "info" for d in catalog["diagnostics"])

    anvil = next(
        e for e in catalog["entries"] if e["type"] == "unique" and e["name"] == "The Anvil"
    )
    assert anvil["variants"][0] == {"id": "1", "name": "Pre 0.2.0"}
    assert "Variant: Current" in anvil["raw"]["text"]

    out = export_catalog(tmp_path)
    assert out == tmp_path / "catalog.json"
    written = json.loads(out.read_text(encoding="utf-8"))
    assert written["schemaVersion"] == 1
    assert written == catalog_data()


def test_tree_version_order_is_numeric_and_playable_only() -> None:
    assert _tree_version_key("0_10") > _tree_version_key("0_5")
    assert _tree_version_key("legion") is None
