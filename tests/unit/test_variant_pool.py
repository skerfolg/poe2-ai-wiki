"""Pool access is factual discovery, never an item eligibility certificate."""

import json
import sqlite3

import pytest

from pok.index import search


@pytest.fixture
def catalog(monkeypatch, tmp_path):
    path = tmp_path / "pool.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE records (id TEXT, type TEXT, json TEXT)")
    records = [
        {"id": "item.example", "type": "Item", "data": {"rarity": "unique"}},
        {"id": "item.example-cultivated", "type": "Item", "data": {"class_group": "cultivated"}},
        {"id": "item.normal", "type": "Item", "data": {"rarity": "normal"}},
        *[
            {
                "id": f"modifier.{i}",
                "type": "Modifier",
                "data": {
                    "carrier_route": "vaal-orb-mutated-unique",
                    "texts": [f"Example payoff {i}"],
                },
            }
            for i in range(3)
        ],
        {"id": "modifier.other", "type": "Modifier", "data": {"texts": ["Example payoff other"]}},
        {
            "id": "modifier.tagged",
            "type": "Modifier",
            "data": {"mod_tags": ["mutatedunique_vaal"], "texts": ["Tagged variant"]},
        },
    ]
    con.executemany(
        "INSERT INTO records VALUES (?,?,?)", [(r["id"], r["type"], json.dumps(r)) for r in records]
    )
    con.commit()
    con.close()
    monkeypatch.setattr(search, "_connect", lambda *a, **k: sqlite3.connect(path))


def test_template_warns_even_when_only_name_is_requested(catalog):
    for id_ in ["item.example", "item.example-cultivated"]:
        context = search.get_entry(id_, fields=["name"])["variant_context"]
        assert context["pool_tool"] == "get_variant_pool"
        assert context["eligibility"] == "unknown_for_this_item"
        assert context["template_is_final_mutated_item"] is False
    assert "variant_context" not in search.get_entry("item.normal")


def test_pool_pages_filters_and_does_not_certify_eligibility(catalog):
    result = search.get_variant_pool(limit=2)
    assert result["total"] == 4 and result["next_offset"] == 2
    assert not result["item_eligibility_verified"]
    assert search.get_variant_pool(offset=2, limit=2)["next_offset"] is None
    assert search.get_variant_pool(query="PAYOFF 1")["entries"][0]["id"] == "modifier.1"
    assert search.get_variant_pool(query="absent")["total"] == 0
    assert search.get_variant_pool(query="Tagged")["entries"][0]["route_basis"] == "mod_tags"
    with pytest.raises(ValueError):
        search.get_variant_pool(route="invented")
    with pytest.raises(ValueError):
        search.get_variant_pool(limit=0)
