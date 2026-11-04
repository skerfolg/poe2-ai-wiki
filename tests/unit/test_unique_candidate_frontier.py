"""Excluded catalogue options stay visible without being measured or adopted."""

from types import SimpleNamespace

from pok.engine import items


def record(name, **data):
    return SimpleNamespace(
        type="Item",
        name_en=name,
        raw={
            "name": {"en": name},
            "data": {"rarity": "unique", "category": "belt", **data},
        },
    )


def test_frontier_exposes_templates_aliases_and_choices_without_rendering_them(monkeypatch):
    records = {
        "item.regular": record("Regular", variants=["First", "Second"]),
        "item.unresolved": record("Unresolved", pob_computable=False),
        "item.regular-cultivated": record("Regular"),
    }
    monkeypatch.setattr(items, "_kb_records", lambda root: records)
    rendered = []

    def render(value):
        rendered.append(value)
        return "Rarity: UNIQUE\nRegular\nUtility Belt"

    monkeypatch.setattr(items, "render_unique", render)
    pool = items.enumerate_slot_uniques("Belt")
    assert [candidate.label for candidate in pool] == ["item.regular"]
    assert len(rendered) == 1
    assert {row["id"] for row in pool.deferred} == {
        "item.unresolved",
        "item.regular-cultivated",
    }
    assert pool.variant_choices[0]["next_tool"] == "prepare_unique_item"
    assert pool.variant_choices[0]["catalogue_labels"] == ["First", "Second"]
    assert all(row["measurement_status"] == "not_measured_not_zero_value" for row in pool.deferred)


def test_frontier_does_not_spend_measurements_or_change_selection(monkeypatch):
    pool = items._UniqueCandidatePool()
    pool.deferred.append(
        {"id": "item.unresolved", "measurement_status": "not_measured_not_zero_value"}
    )
    monkeypatch.setattr(items, "enumerate_slot_uniques", lambda *args: pool)
    visited = []

    def compute(spec):
        visited.append(spec)
        return {"TotalDPS": 100.0, "Life": 1000.0}

    result = items.optimize_items(
        {"class_name": "Sorceress", "ascendancy": "Sorceress1", "items": []},
        ["Belt"],
        {"TotalDPS": 1},
        max_rounds=1,
        compute=compute,
    )
    assert result.steps == ()
    frontier = result.search_evidence["candidate_frontiers"]["Belt"]
    assert frontier["deferred_templates"][0]["id"] == "item.unresolved"
    assert result.search_evidence["scope"]["candidate_counts"]["Belt"]["evaluated"] == 0
    assert result.search_evidence["termination"]["measurements"] == len(visited)
    assert all(not item.get("items") for item in visited)
