"""Internal condition diagnostics must not repeat public indexed KB lookups."""

from types import SimpleNamespace

from pok.mcp.tools.build import _condition_sources


def test_condition_stats_use_one_current_validated_snapshot_and_preserve_fallback(monkeypatch):
    from pok.index import search
    from pok.kb import store

    calls = []
    records = {
        "support.snipers-mark": SimpleNamespace(raw={"data": {"stats": []}}),
        "skill.snipers-mark": SimpleNamespace(
            raw={"data": {"stats": ["Mark the Enemy"], "cooldown_s": 4}}
        ),
    }

    def load():
        calls.append(True)
        return SimpleNamespace(records=records)

    def forbidden(*args, **kwargs):
        raise AssertionError("Internal stat collection must not perform public indexed lookups")

    monkeypatch.setattr(store, "load", load)
    monkeypatch.setattr(search, "get_entry", forbidden)
    spec = {
        "skills": [
            {
                "gems": [
                    {"name": "Sniper's Mark"},
                    {"name": "Sniper's Mark"},
                    {"name": "Absent Name"},
                ]
            }
        ]
    }
    texts, cooldowns = _condition_sources(spec)
    assert texts == {"skill.snipers-mark": ["Mark the Enemy"]}
    assert cooldowns == {"skill.snipers-mark": 4.0}
    assert len(calls) == 1
    records["skill.snipers-mark"].raw["data"]["stats"] = ["Updated condition"]
    updated, _ = _condition_sources(spec)
    assert updated["skill.snipers-mark"] == ["Updated condition"]
    assert texts["skill.snipers-mark"] == ["Mark the Enemy"]
    assert len(calls) == 2


def test_empty_skill_sources_do_not_load_kb(monkeypatch):
    from pok.kb import store

    def forbidden(*args, **kwargs):
        raise AssertionError("No gem names require no KB load")

    monkeypatch.setattr(store, "load", forbidden)
    assert _condition_sources({"skills": [{"gems": [{"name": ""}]}]}) == ({}, {})
