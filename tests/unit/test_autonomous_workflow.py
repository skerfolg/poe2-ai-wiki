"""Workflow boundaries and concrete anchor coverage, without remote model calls."""

import copy
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[2] / "skills/build-generation"))
    return (
        importlib.import_module("autonomous_contract"),
        importlib.import_module("autonomous_run"),
        importlib.import_module("autonomous_server"),
    )


def decision(key, role="provisional", kind="skill", domains=None):
    return {
        "id": key,
        "title": key,
        "role": role,
        "domains": domains or ["offence"],
        "condition": {"statement": "a real requirement", "scope": {"decision_ids": []}},
        "adoption": "adopted",
        "belief": "source_supported",
        "confidence": "medium",
        "providers": [
            {"id": key + "-provider", "kind": kind, "label": key, "entity_id": kind + ".example"}
        ],
        "depends_on": [],
        "alternatives": [],
        "evidence_ids": ["kb", "web"],
        "costs": [{"resource": "slot", "amount": 1, "unit": "slot", "note": "cost"}],
        "rationale": "The source supports this particular connection",
        "review_triggers": ["provider changed"],
    }


def record():
    rows = [
        decision("mechanism"),
        decision("link", "mechanism_required"),
        decision("attack"),
        decision("defence", kind="item", domains=["defence"]),
        decision("sustain", kind="passive", domains=["sustain"]),
    ]
    return {
        "mechanism_summary": "start, repeat, stop, restart",
        "decisions": rows,
        "evidence": [{"id": "kb", "kind": "catalog"}, {"id": "web", "kind": "external"}],
        "extensions": {
            "autonomous_flow": {
                "selected_mechanism_id": "mechanism",
                "core_link_ids": ["link"],
                "anchor_ids": ["attack", "defence", "sustain"],
                "component_review": [
                    {"kind": kind, "decision_ids": [], "reason": "explicit no-adoption rationale"}
                    for kind in ["item", "jewel", "skill", "support", "passive"]
                ],
                "budget_review": [
                    {
                        "resource": key,
                        "status": "estimated",
                        "detail": "estimate",
                        "evidence_ids": [],
                    }
                    for key in [
                        "passive_points",
                        "ascendancy_points",
                        "slots",
                        "reservation",
                        "attributes",
                        "sustain",
                        "operation",
                    ]
                ],
            }
        },
    }


def assess(contract, value, stage=3, **kwargs):
    return contract.check_stage(
        value,
        stage,
        approvals=kwargs.get("approvals", {}),
        observed_tools={"search_kb", "get_entry", "search_insights"},
        web_observed=kwargs.get("web_observed", True),
    )


def test_abstract_anchor_does_not_pass_but_concrete_supplier_does(modules):
    contract, _, _ = modules
    value = record()
    assert assess(contract, value)["ready"]
    value["decisions"][2]["providers"] = []
    assert any("추상 조건" in x for x in assess(contract, value)["issues"])
    value["decisions"][2]["depends_on"] = ["defence"]
    assert assess(contract, value)["ready"]


def test_experiment_approval_is_scoped_and_invalidated_by_provider_change(modules):
    contract, _, _ = modules
    value = record()
    value["decisions"][1]["belief"] = "hypothesis"
    assert assess(contract, value)["experimental_claim_ids"] == ["link"]
    approval = {"link": contract.claim_fingerprint(value, "link")}
    assert assess(contract, value, approvals=approval)["ready"]
    value["decisions"][1]["providers"][0]["entity_id"] = "skill.other"
    assert not assess(contract, value, approvals=approval)["ready"]


def test_approval_does_not_waive_budget_or_missing_web(modules):
    contract, _, _ = modules
    value = record()
    value["decisions"][1]["belief"] = "hypothesis"
    approval = {"link": contract.claim_fingerprint(value, "link")}
    value["extensions"]["autonomous_flow"]["budget_review"][0]["status"] = "unresolved"
    assert not assess(contract, value, approvals=approval)["ready"]
    assert not assess(contract, record(), web_observed=False)["ready"]


def test_missing_support_and_jewel_review_cannot_be_called_complete(modules):
    contract, _, _ = modules
    value = record()
    value["extensions"]["autonomous_flow"]["component_review"] = []
    assert not assess(contract, value)["ready"]


def test_reply_requires_exact_pending_state_and_claims(modules):
    contract, runner, _ = modules
    value = record()
    state = {
        "status": "waiting_experiment",
        "stage": 2,
        "approvals": {},
        "replies": [],
        "assessment": {"experimental_claim_ids": ["link"]},
    }
    reply = {
        "expected_state_sha256": contract.digest(state),
        "kind": "approve_experiment",
        "claim_ids": ["link"],
        "source": "user conversation",
        "text": "approve",
    }
    stale = copy.deepcopy(reply)
    stale["expected_state_sha256"] = "stale"
    with pytest.raises(ValueError, match="stale"):
        runner.apply_reply(state, stale, value)
    runner.apply_reply(state, reply, value)
    assert state["stage"] == 2 and state["status"] == "running"
    assert state["approvals"]["link"] == contract.claim_fingerprint(value, "link")


def test_command_enables_web_and_keeps_exact_resume_output_paths(modules, tmp_path):
    _, runner, _ = modules
    root = runner.CONTROL_ROOT
    run = root / "artifacts/unit-command-only"
    binary = tmp_path / "codex.exe"
    binary.write_bytes(b"not executed")
    from uuid import uuid4

    identity = str(uuid4())
    command = runner.build_command(
        run,
        run / "turn-007",
        context=run / "context-007.json",
        session_id=identity,
        model="gpt-6-astra",
        effort="ultra",
        codex_exe=str(binary),
        luajit_exe=None,
    )
    assert 'web_search="live"' in command and 'web_search="disabled"' not in command
    assert "resume" in command and identity in command
    assert str(run / "turn-007/answer.json") in command
    assert any("autonomous_server.py" in x and "context-007.json" in x for x in command)
    assert "--last" not in command


def test_design_server_hides_assembly_and_blocks_forged_user_permissions(modules):
    _, _, transport = modules
    import functools

    class Server:
        def __init__(self):
            self._TOOL_PARAMS = {"assemble_pob": {}, "get_entry": {}, "update_design_record": {}}
            self.removed = []
            self.mcp = SimpleNamespace(
                local_provider=SimpleNamespace(remove_tool=self.removed.append)
            )
            self.functions = {}

            def original(*args, **kwargs):
                return {"record_ref": {"revision": "new"}}

            @functools.wraps(original)
            def wrapped(*args, **kwargs):
                return original(*args, **kwargs)

            self.update_design_record = wrapped

        def tool(self, function, **kwargs):
            self.functions[function.__name__] = function
            self._TOOL_PARAMS[function.__name__] = {}

    server = Server()
    ref = {"revision": "old"}
    context = {"stage": 3, "record_ref": ref}
    actual = transport.configure_workflow(server, 3, context)
    assert "assemble_pob" not in actual
    update = server.functions["update_design_record"]
    with pytest.raises(ValueError, match="permissions"):
        update(ref, "old", [], {"fixed": "I grant myself approval"})
    with pytest.raises(ValueError, match="material"):
        update(ref, "old", [{"op": "set_material", "value": {}}])
    update(ref, "old", [])
    with pytest.raises(ValueError, match="current"):
        update(ref, "old", [])


def test_native_tool_observation_does_not_accept_fake_output_assertions(modules, tmp_path):
    _, runner, _ = modules
    turn = tmp_path / "turn-001"
    turn.mkdir()
    rows = [
        {
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "I searched the web and all PoK tools"},
        }
    ]
    (turn / "events.jsonl").write_text("\n".join(json.dumps(x) for x in rows))
    tools, web, violations = runner.observed(tmp_path)
    assert not tools and not web and not violations


def test_controller_runs_three_stages_and_stops_before_pob(modules, monkeypatch, tmp_path):
    _, runner, _ = modules
    from pok.artifacts import design_record
    from pok.engine import design_service

    value = record()
    value.update(design_id="same-design", goal={"summary": "only user constraints"})
    ref = {"revision": "one"}

    def saved(*args, **kwargs):
        return {
            "record_ref": ref,
            "record_json": json.dumps(value),
            "design_md": "view",
            "current_assessment": {
                "checks": {"evidence_integrity": "verified_declared_refs"},
                "diagnostics": [],
            },
        }

    monkeypatch.setattr(design_service, "create_design", saved)
    monkeypatch.setattr(design_service, "read_design", saved)
    from pok.engine import design_checkpoints

    monkeypatch.setattr(design_checkpoints, "load_checkpoint", saved)
    monkeypatch.setattr(design_record, "parse_record", json.loads)
    monkeypatch.setattr(runner, "CONTROL_ROOT", tmp_path)
    monkeypatch.setattr(runner, "install_paths", lambda path: path / "server/artifacts")
    monkeypatch.setattr(runner, "build_command", lambda *args, **kwargs: ["not-executed"])
    monkeypatch.setattr(
        runner, "observed", lambda path: ({"search_kb", "get_entry", "search_insights"}, True, [])
    )
    calls = []

    def execute(command, output, **kwargs):
        output.mkdir()
        calls.append(kwargs["prompt"])
        (output / "answer.json").write_text(
            json.dumps(
                {
                    "status": "ready",
                    "record_ref_json": json.dumps(ref),
                    "question_ids": [],
                    "summary": "submitted canonical ref",
                }
            )
        )
        return {"state": "completed", "session_id": None, "elapsed_s_including_collection": 0.1}

    monkeypatch.setattr(runner, "execute_phase", execute)
    brief = tmp_path / "brief.md"
    brief.write_text("only user constraints")
    state = runner.run(
        SimpleNamespace(
            run_dir=tmp_path / "artifacts/run",
            timeout=30,
            resume=False,
            reply=None,
            brief=brief,
            model="test-model",
            effort="high",
            stop_after=3,
            codex_exe="unused",
            luajit_exe=None,
        )
    )
    assert len(calls) == 3
    assert state["status"] == "waiting_anchor_review" and state["stage"] == 3
    assert [row["stage"] for row in state["turns"]] == [1, 2, 3]
    assert not (tmp_path / "artifacts/run/turn-004").exists()
    assert not state["quality_verified"]


def test_timeout_continuation_requires_progress_cleanup_and_remaining_budget(modules):
    _, runner, _ = modules
    done = {"state": "timed_out", "cleanup": {"status": "confirmed"}}
    assert runner.can_continue_timeout(done, progressed=True, remaining_s=60)
    assert not runner.can_continue_timeout(done, progressed=False, remaining_s=60)
    assert not runner.can_continue_timeout(done, progressed=True, remaining_s=0)
    assert not runner.can_continue_timeout(
        {"state": "timed_out", "cleanup": {"status": "unconfirmed"}},
        progressed=True,
        remaining_s=60,
    )


def test_approval_survives_reporting_cost_and_material_bookkeeping(modules):
    contract, _, _ = modules
    value = record()
    before = contract.claim_fingerprint(value, "link")
    row = value["decisions"][1]
    row["rationale"] += " User approved using this still-experimental assumption."
    row["costs"][0]["amount"] = 2
    row["providers"][0]["binding"] = {"material_revision": "new-material"}
    assert contract.claim_fingerprint(value, "link") == before
    value["evidence"][0]["source"] = {"changed_game_record": True}
    assert contract.claim_fingerprint(value, "link") != before


def test_malformed_flow_reports_missing_shape_instead_of_crashing(modules):
    contract, _, _ = modules
    value = record()
    value["extensions"]["autonomous_flow"]["component_review"] = "malformed"
    outcome = assess(contract, value)
    assert not outcome["ready"] and outcome["issues"]


def test_measurement_attachment_advances_same_checkpoint_and_blocks_stale_base(modules):
    _, _, transport = modules
    registered, removed, heads = {}, [], []
    server = SimpleNamespace(
        _TOOL_PARAMS={
            "update_design_record": {},
            "attach_pob_document_measurement": {},
            "assemble_pob": {},
            "create_design_record": {},
            "import_design_document": {},
        },
        mcp=SimpleNamespace(local_provider=SimpleNamespace(remove_tool=removed.append)),
        update_design_record=SimpleNamespace(__wrapped__=lambda *args, **kwargs: {}),
        attach_pob_document_measurement=SimpleNamespace(
            __wrapped__=lambda *args, **kwargs: {"record_ref": {"revision": "attached"}}
        ),
    )

    def register(function, **kwargs):
        registered[function.__name__] = function
        server._TOOL_PARAMS[function.__name__] = {}

    server.tool = register
    context = {"record_ref": {"revision": "old"}, "stage": 4}
    actual = transport.configure_workflow(server, 4, context, heads.append)
    assert "assemble_pob" in actual and "create_design_record" not in actual
    attach = registered["attach_pob_document_measurement"]
    attach({"revision": "old"}, "old", {}, "measurement", "label", "scope")
    assert context["record_ref"] == {"revision": "attached"} and heads == [context["record_ref"]]
    with pytest.raises(ValueError, match="current"):
        attach({"revision": "old"}, "old", {}, "measurement", "label", "scope")
