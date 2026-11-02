"""Reference surface boundaries without model inference or native calculation."""

import importlib
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def reference(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills/build-generation")
    )
    return importlib.import_module("product_reference")


def test_reference_export_uses_explicit_inputs_and_never_calls_legacy(reference):
    calls = []

    def assemble_pob(build_spec, slug, purpose="exploration", input_policy="legacy"):
        calls.append(input_policy)
        return {"policy": input_policy, "spec": build_spec}

    guarded = reference.explicit_export(assemble_pob)
    assert guarded({"items": []}, "manual")["policy"] == "explicit"
    assert not guarded({}, "bad", input_policy="legacy")["ok"]
    assert not guarded({}, "bad", purpose="recommendation")["ok"]
    assert calls == ["explicit"]


def test_reference_refuses_catalog_drift_before_mutation(tmp_path, reference):
    server = SimpleNamespace(_TOOL_PARAMS={"unexpected": {}})
    with pytest.raises(ValueError, match="frozen manifest"):
        reference.configure_reference(
            server,
            tmp_path,
            tmp_path,
            expected_tools=reference.BASIC_TOOLS,
            facts=tmp_path,
            pob=tmp_path,
        )
    assert set(server._TOOL_PARAMS) == {"unexpected"}


@pytest.mark.parametrize("outside", ["facts", "pob"])
def test_reference_refuses_unshared_fact_or_pob_pool(tmp_path, reference, outside):
    repo = tmp_path / "repo"
    facts = repo / "knowledge"
    pob = repo / "external/pob/5d173cb"
    facts.mkdir(parents=True)
    pob.mkdir(parents=True)
    other = tmp_path / "other"
    other.mkdir()
    server = SimpleNamespace(_TOOL_PARAMS=dict.fromkeys(reference.BASIC_TOOLS))
    with pytest.raises(ValueError, match=r"frozen common|fixed snapshot"):
        reference.configure_reference(
            server,
            tmp_path,
            repo,
            expected_tools=reference.BASIC_TOOLS,
            facts=other if outside == "facts" else facts,
            pob=other if outside == "pob" else pob,
        )


def test_reference_has_no_optimizer_graph_or_kb_api(reference):
    assert not reference.BASIC_TOOLS & {
        "optimize_tree",
        "optimize_items",
        "optimize_rare",
        "optimize_runes",
        "search_kb",
        "get_entry",
        "evaluate_delta",
        "scan_synergies",
        "create_design_record",
        "evaluate_change_bundle",
    }
    assert {"compute_pob", "assemble_pob", "prepare_pob_delivery"} <= reference.BASIC_TOOLS
