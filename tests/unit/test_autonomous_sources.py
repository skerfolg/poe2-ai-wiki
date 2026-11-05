"""Source isolation must reject answer material, not merely ask the model to ignore it."""

import functools
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "skills/build-generation"))
    return tuple(
        importlib.import_module(n) for n in ["source_policy", "autonomous_server", "autonomous_run"]
    )


HTML = """<div class="page-content"><nav>Site builds</nav><div class="tab-content">
<div class="tab-pane active"><h3>ExampleSkill</h3><p>Deals 10 Fire Damage</p>
<div class="card"><h5 class="card-header">Recommended Support Gems /5</h5>
<p>Unselected recommended support</p></div></div>
<div class="tab-pane"><h3>Community wiki</h3>Other player's complete recipe</div>
</div></div>"""


def test_data_page_removes_recommendations_and_other_tabs(modules):
    policy, _, _ = modules
    record = {"type": "Skill", "name": {"en": "ExampleSkill"}}
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "text/html"}, text=HTML)
        )
    )
    with client:
        result = policy.fetch_data(record, client=client)
    assert "Deals 10 Fire Damage" in result["text"]
    assert "recommended" not in result["text"].lower()
    assert "complete recipe" not in result["text"] and "Site builds" not in result["text"]
    assert result["purpose"] == "verify_preselected_mechanism_only"


def test_no_arbitrary_url_redirect_or_unrecognised_layout_fallback(modules):
    policy, _, _ = modules
    record = {"type": "Skill", "name": {"en": "ExampleSkill"}}
    calls = []

    def redirect(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.org/build"})

    with (
        httpx.Client(transport=httpx.MockTransport(redirect)) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        policy.fetch_data(record, client=client)
    assert calls == ["https://poe2db.tw/us/ExampleSkill"]
    with pytest.raises(ValueError):
        policy.check_url("https://poe2db.tw.evil/us/ExampleSkill", calls[0])
    with pytest.raises(ValueError):
        policy.data_url({"type": "Build", "name": {"en": "ExampleSkill"}})
    with pytest.raises(ValueError):
        policy.data_url({"type": "Mechanic", "name": {"en": "Build Guide"}})
    with pytest.raises(ValueError):
        policy.extract_data("<body>A complete build recipe without recognised data layout</body>")


def test_fact_filter_preserves_unknowns_but_drops_corpus_and_dangling_edges(modules):
    policy, _, _ = modules
    rows = [
        {"id": "build.example", "type": "Build", "items": ["answer"]},
        {"id": "skill.example", "type": "Skill", "unknown": None},
        {"target": "build.example", "relation": "uses"},
    ]
    assert policy.scrub_records(rows, {"build.example"}) == [
        {"id": "skill.example", "type": "Skill", "unknown": None}
    ]


def test_checkpoint_receipt_does_not_republish_large_record_or_hide_issue_count(modules):
    _, transport, _ = modules
    result = transport.checkpoint_summary(
        {
            "record_ref": {"revision": "real"},
            "record_json": "x" * 100_000,
            "current_assessment": {
                "checks": {"material_integrity": "verified_blobs"},
                "evidence_assessments": ["x" * 1000] * 100,
                "diagnostics": [{"code": str(i)} for i in range(12)],
            },
        }
    )
    assert len(json.dumps(result)) < 2000
    assert result["current_assessment"]["diagnostic_count"] == 12
    assert len(result["current_assessment"]["diagnostics"]) == 8
    assert result["current_assessment"]["checks"]["material_integrity"] == "verified_blobs"


class Server:
    def __init__(self):
        self._TOOL_PARAMS = {
            name: {} for name in ["get_entry", "search_kb", "update_design_record"]
        }
        self.functions = {}
        self.mcp = SimpleNamespace(local_provider=SimpleNamespace(remove_tool=lambda name: None))

        def get_entry(id, fields=None, include_narrative=False):
            return {"id": id, "type": "Skill", "narrative": include_narrative}

        def search_kb(query=None, type=None, limit=20):
            return [
                {"id": "build.example", "type": "Build"},
                {"id": "skill.example", "type": "Skill"},
            ]

        def update_design_record(*args, **kwargs):
            return {
                "record_ref": {"revision": "new"},
                "record_json": "large sealed record",
                "design_md": "large view",
            }

        for fn in [get_entry, search_kb, update_design_record]:

            @functools.wraps(fn)
            def wrapped(*a, __fn=fn, **kw):
                return __fn(*a, **kw)

            setattr(self, fn.__name__, wrapped)

    def tool(self, function, **kwargs):
        self.functions[function.__name__] = function
        self._TOOL_PARAMS[function.__name__] = {}


def test_verification_requires_prior_pok_selection_and_real_receipt(modules, monkeypatch, tmp_path):
    policy, transport, _ = modules
    from pok.engine import design_checkpoints
    from pok.index import search

    monkeypatch.setattr(search, "search", lambda **kw: [SimpleNamespace(id="build.example")])
    monkeypatch.setattr(
        search, "get_entry", lambda id: {"id": id, "type": "Skill", "name": {"en": "ExampleSkill"}}
    )
    record = {
        "decisions": [
            {"id": "claim", "providers": [{"entity_id": "skill.example"}], "evidence_ids": ["kb"]}
        ],
        "evidence": [{"id": "kb", "kind": "catalog"}],
    }
    monkeypatch.setattr(
        design_checkpoints, "load_checkpoint", lambda ref: {"record_json": json.dumps(record)}
    )
    fetched = []

    def fetch(record, **kwargs):
        fetched.append(record["id"])
        return {
            "url": "https://poe2db.tw/us/ExampleSkill",
            "text": "actual game data",
            "http_status": 200,
            "purpose": "verify_preselected_mechanism_only",
        }

    monkeypatch.setattr(transport, "fetch_data", fetch)
    context = {
        "source_policy": policy.POK_PRIMARY,
        "record_ref": {"revision": "old"},
        "_source_root": str(tmp_path),
        "_source_receipts": {},
    }
    server = Server()
    transport.configure_workflow(server, 2, context)
    with pytest.raises(ValueError, match="excluded"):
        server.functions["get_entry"]("build.example")
    assert (
        server.functions["get_entry"]("skill.example", include_narrative=True)["narrative"] is False
    )
    assert server.functions["search_kb"]() == [{"id": "skill.example", "type": "Skill"}]
    with pytest.raises(ValueError, match="before web"):
        server.functions["workflow_primary_source"]("claim", "skill.not-selected")
    assert not fetched
    update = server.functions["update_design_record"]
    with pytest.raises(ValueError, match="receipt"):
        update(
            context["record_ref"],
            "old",
            [
                {
                    "op": "upsert_evidence",
                    "value": {"kind": "external", "source": {"url": "https://example.org/build"}},
                }
            ],
        )
    with pytest.raises(ValueError, match="merge_extensions"):
        update(context["record_ref"], "old", [{"op": "set_extension", "value": {}}])
    source = server.functions["workflow_primary_source"]("claim", "skill.example")
    assert source["receipt"]["preselected_record_ref"] == {"revision": "old"}
    assert (
        server.functions["workflow_source_text"](source["receipt"]["id"])["text"]
        == "actual game data"
    )
    reply = update(context["record_ref"], "old", [{"op": "merge_extensions", "value": {}}])
    assert reply["record_ref"] == {"revision": "new"} and "record_json" not in reply
    assert (
        server.functions["workflow_contract"]()["value"]["merge_extensions"]["op"]
        == "merge_extensions"
    )


def test_native_web_disabled_and_source_mode_cannot_be_laundered(modules, tmp_path):
    policy, _, runner = modules
    binary = tmp_path / "codex.exe"
    binary.write_bytes(b"not executed")
    case = runner.CONTROL_ROOT / "artifacts/unit-source-command"
    command = runner.build_command(
        case,
        case / "turn-001",
        context=case / "context-001.json",
        session_id=None,
        model="gpt-6-astra",
        effort="ultra",
        codex_exe=str(binary),
        luajit_exe=None,
        source_policy=policy.POK_PRIMARY,
    )
    assert 'web_search="disabled"' in command and 'web_search="live"' not in command
    (tmp_path / "workflow.json").write_text(json.dumps({"source_policy": policy.POK_PRIMARY}))
    folder = tmp_path / "turn-001"
    folder.mkdir()
    rows = [
        {"type": "item.completed", "item": {"type": "web_search", "action": {"query": "build"}}}
    ]
    (folder / "events.jsonl").write_text(json.dumps(rows[0]))
    assert any("일반 웹검색" in issue for issue in runner.observed(tmp_path)[2])
