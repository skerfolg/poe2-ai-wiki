"""Phase commands keep product identity, output separation and exact resume ownership."""

import importlib
import json
import tomllib
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture
def module(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "skills/build-generation")
    )
    return importlib.import_module("product_run")


@pytest.fixture
def inputs(tmp_path):
    product = tmp_path / "artifacts/product"
    (product / "src/pok").mkdir(parents=True)
    (product / "knowledge").mkdir()
    (product / "pyproject.toml").write_text("", encoding="utf-8")
    binary = tmp_path / "codex.exe"
    binary.write_bytes(b"command construction only")
    return {
        "trial_root": tmp_path / "artifacts/trial",
        "product_root": product,
        "control_root": tmp_path,
        "model": "gpt-6-astra",
        "reasoning_effort": "ultra",
        "codex_exe": str(binary),
    }


def pok_config(command):
    values = [value for value in command if value.startswith("mcp_servers.pok=")]
    assert len(values) == 1
    return tomllib.loads(values[0])["mcp_servers"]["pok"]


def test_resume_uses_same_namespace_exact_id_and_separate_outputs(module, inputs):
    identity = str(uuid4())
    first = module.build_product_command(**inputs, phase=1)
    resumed = module.build_product_command(**inputs, phase=2, session_id=identity)
    for command in (first, resumed):
        assert "--ephemeral" not in command and "--last" not in command
        assert "gpt-6-astra" in command
        assert 'model_reasoning_effort="ultra"' in command
        config = pok_config(command)
        assert "product_server.py" in config["args"][0]
        assert "--arm" not in config["args"]
        assert config["env"]["PYTHONPATH"] == str(inputs["product_root"] / "src")
    assert pok_config(first) == pok_config(resumed)
    assert resumed[resumed.index("exec") + 1] == "resume"
    assert resumed[-2:] == [identity, "-"]
    assert "--sandbox" not in resumed and 'sandbox_mode="read-only"' in resumed
    assert "-C" not in resumed and "--color" not in resumed
    assert (
        first[first.index("--output-last-message") + 1]
        != resumed[resumed.index("--output-last-message") + 1]
    )
    assert not inputs["trial_root"].exists(), "Constructing commands must not launch or write"


@pytest.mark.parametrize(
    "phase,identity", [(1, str(uuid4())), (2, None), (2, "--last"), (True, None), (3, None)]
)
def test_resume_does_not_guess_missing_or_invalid_context(module, inputs, phase, identity):
    with pytest.raises(ValueError):
        module.build_product_command(**inputs, phase=phase, session_id=identity)


def test_complete_start_record_survives_interrupted_tail_without_rewriting_log(module, tmp_path):
    identity = str(uuid4())
    raw = json.dumps({"type": "thread.started", "thread_id": identity}) + '\n{"type":"item.'
    path = tmp_path / "events.jsonl"
    path.write_text(raw, encoding="utf-8")
    assert module.session_from_events(path) == identity
    assert path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "turn.completed"}],
        [{"type": "thread.started", "thread_id": "not-a-session"}],
        [
            {"type": "thread.started", "thread_id": str(uuid4())},
            {"type": "thread.started", "thread_id": str(uuid4())},
        ],
    ],
)
def test_session_log_missing_or_ambiguous_ownership_is_rejected(module, tmp_path, events):
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
    with pytest.raises(ValueError):
        module.session_from_events(path)


def test_interior_log_corruption_is_not_a_truncated_tail(module, tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{broken\n{"type":"turn.completed"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="interior"):
        module.session_from_events(path)


@pytest.mark.parametrize("tail", [b'{"text":"\xed\x95', b'{"text":"\xf0\x9f'])
def test_interrupted_utf8_tail_preserves_prior_session_and_original_bytes(module, tmp_path, tail):
    identity = str(uuid4())
    raw = json.dumps({"type": "thread.started", "thread_id": identity}).encode() + b"\n" + tail
    path = tmp_path / "events.jsonl"
    path.write_bytes(raw)
    diagnostics = []
    assert len(list(module.complete_events(path, diagnostics))) == 1
    assert diagnostics == [{"code": "TRUNCATED_FINAL_EVENT", "line": 2}]
    assert module.session_from_events(path) == identity
    assert path.read_bytes() == raw


def test_invalid_utf8_inside_log_is_not_silently_removed(module, tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_bytes(b'{"text":"\xed\x95\n{"type":"turn.completed"}\n')
    with pytest.raises(ValueError, match="interior"):
        list(module.complete_events(path))


def test_reference_command_pins_the_policy_and_cannot_reuse_changed_catalog(module, inputs):
    import hashlib

    from product_reference import BASIC_TOOLS

    path = inputs["control_root"] / "artifacts/reference-policy.json"
    path.write_text(
        json.dumps({"format": "pok.reference-policy.v1", "source_tools": sorted(BASIC_TOOLS)}),
        encoding="utf-8",
    )
    pin = {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    command = module.build_product_command(**inputs, phase=1, reference_policy=pin)
    config = pok_config(command)
    assert config["args"][-4:] == [
        "--reference-policy",
        str(path),
        "--reference-policy-sha256",
        pin["sha256"],
    ]
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="checksum"):
        module.build_product_command(**inputs, phase=1, reference_policy=pin)
