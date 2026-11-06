"""Acquisition is a lookup axis, independent of tree reachability and node kind."""
import pytest

from pok.common.paths import knowledge_dir
from pok.engine.legality import ItemLegalityChecker
from pok.index.search import diagnose_empty, search


def test_anoint_only_includes_disconnected_socket():
    hits = search(type_="Passive", acquisition="anoint-only", limit=100)
    assert hits and all(h.acquisition == "anoint-only" for h in hits)
    gift = next(h for h in hits if h.id == "passive.zarokhs-gift-11184")
    assert gift.passive_kind == "jewel-socket"


def test_acquisition_filter_precedes_limit_and_combines_with_query():
    assert len(search(acquisition="anoint-only", limit=1)) == 1
    hit, = search(query="Zarokh", acquisition="anoint-only", limit=1)
    assert hit.id == "passive.zarokhs-gift-11184"
    assert not search(query="Unforgiving", acquisition="anoint-only", limit=1)


def test_all_anoints_are_union_not_notable_only():
    normal = {h.id for h in search(acquisition="anointable", limit=2000)}
    only = {h.id for h in search(acquisition="anoint-only", limit=2000)}
    both = {h.id for h in search(acquisition="anoint", limit=2000)}
    assert normal and only and not normal.intersection(only)
    assert both == normal | only


@pytest.mark.parametrize("args", [{"acquisition": "hidden"},
                                 {"acquisition": "anoint-only", "type_": "Item"}])
def test_invalid_acquisition_request_is_explicit(args):
    with pytest.raises(ValueError):
        search(**args)


def test_empty_text_query_explains_structured_route():
    assert any("acquisition" in why for why in diagnose_empty(
        query="anoint-only", type_="Passive").reasons)


def test_public_search_exposes_route_and_kind():
    from pok.mcp import server

    fn = getattr(server.search_kb, "fn", getattr(server.search_kb, "__wrapped__", server.search_kb))
    hits = fn(query="Zarokh", type="Passive", acquisition="anoint-only", limit=1)
    assert hits[0]["acquisition"] == "anoint-only"
    assert hits[0]["passive_kind"] == "jewel-socket"


@pytest.fixture(scope="module")
def checker():
    return ItemLegalityChecker(knowledge_dir())


def amulet(*names):
    return "Rarity: RARE\nAnoint Probe\nAmber Amulet\nItem Level: 82\n" + "\n".join(
        "Allocates " + name for name in names)


def test_all_catalog_anoint_only_allocations_are_recognized(checker):
    hits = search(acquisition="anoint-only", limit=100)
    assert hits
    for hit in hits:
        report = checker.check(amulet(hit.name_en))
        assert report.is_legal, (hit.id, report)


def test_regular_anoint_and_invalid_allocations_keep_their_rules(checker):
    assert checker.check(amulet("Unforgiving")).is_legal
    assert not checker.check(amulet("Pok Nonexistent Passive")).is_legal
    assert not checker.check(amulet("Chaos Inoculation")).is_legal
    assert not checker.check(amulet("Unforgiving", "Zarokh's Gift")).is_legal


def test_anoint_only_socket_can_be_granted_by_megalomaniac(checker):
    text = ("Rarity: UNIQUE\nMegalomaniac\nDiamond\nItem Level: 80\n"
            "Allocates Zarokh's Gift\nAllocates Controlling Magic\nCorrupted")
    report = checker.check(text)
    assert report.is_legal, report
    gift = next(v for v in report.verdicts if v.line == "Allocates Zarokh's Gift")
    assert gift.status == "CONDITIONAL"
    assert gift.modifier_id == "passive.zarokhs-gift-11184"
    # Classification stays jewel-socket; eligibility is a separate question.
    assert "zarokh's gift" not in checker._notables


def test_megalomaniac_keeps_unknown_and_ascendancy_restrictions(checker):
    base = ("Rarity: UNIQUE\nMegalomaniac\nDiamond\nItem Level: 80\n"
            "Allocates Controlling Magic\nAllocates NAME\nCorrupted")
    assert not checker.check(base.replace("NAME", "Pok Unknown Passive")).is_legal
    assert not checker.check(base.replace("NAME", "Chaos Inoculation")).is_legal
    asc = next(row for row in checker._notables.values() if row["data"].get("ascendancy"))
    name = asc["name"]["en"]
    report = checker.check(base.replace("NAME", name))
    assert not report.is_legal
    assert any(v.status == "ILLEGAL" and "어센던시" in v.reason for v in report.verdicts)


def test_autonomous_context_supplies_exclusive_candidates_without_a_name_query(monkeypatch):
    import importlib
    from pathlib import Path

    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "skills/build-generation"))
    runner = importlib.import_module("autonomous_run")
    context = runner.anoint_discovery_context(3, "pok-primary")
    candidates = context["anoint_only_catalogue"]
    assert {r["entity_id"] for r in candidates} == {
        h.id for h in search(acquisition="anoint-only", limit=10000)}
    assert next(r for r in candidates if r["entity_id"] == "passive.zarokhs-gift-11184")[
        "kind"] == "jewel-socket"
    assert "not recommendations" in context["anoint_catalogue_scope"]
    assert runner.anoint_discovery_context(1, "pok-primary") == {}
    assert runner.anoint_discovery_context(3, "web-reference") == {}
