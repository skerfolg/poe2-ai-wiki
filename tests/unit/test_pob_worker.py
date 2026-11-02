"""Worker transport binds inputs and execution, without synthesizing a build."""

import math
import queue
from pathlib import Path
from time import sleep

import pytest

from pok.common.execution import checkpoint
from pok.pob.daemon import PobDaemon
from pok.pob.document import xml_revision
from pok.pob.runner import PobResult
from pok.pob.worker import WorkerConfig, WorkerService, _json_safe, _portable_identity


def observation(root):
    return {
        "status": "observed",
        "sha256": "9" * 64,
        "adapter_code_sha256": "location-sensitive",
        "components": {
            name: {"sha256": str(index) * 64, "root": str(root / name)}
            for index, name in enumerate(
                ("adapter_lua", "pob_source", "pob_runtime", "executable"), 1
            )
        },
    }


class Calculator(PobDaemon):
    def __init__(self, root):
        self.root = root
        self.running = False
        self.waiting = False
        self.received = []

    def start(self):
        self.running = True

    def _observe_inputs(self):
        return observation(self.root)

    def inspect_execution(self, *, observe_current=False):
        return {
            "process_state": "running" if self.running else "stopped",
            "current_matches_startup": True,
            "current_disk": self._observe_inputs(),
            "last_cleanup": None if self.running else {"status": "confirmed"},
        }

    def compute(self, xml, *, requested_nodes=()):
        self.received.append(xml)
        while self.waiting:
            checkpoint()
            sleep(0.001)
        return PobResult({"Life": 123.0, "CombinedDPS": 456.0}, {}, (), (), False)

    def build_item(self, text):
        return text + "\nRendered"

    def close(self):
        self.running = False


@pytest.fixture
def config(tmp_path):
    adapter = tmp_path / "assets"
    pob = tmp_path / "pob"
    for path in (adapter / "scripts/pob_daemon.lua", pob / "src/HeadlessWrapper.lua"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    (pob / "runtime").mkdir()
    executable = tmp_path / "luajit"
    executable.write_text("fixture", encoding="utf-8")
    return WorkerConfig(adapter, pob, "f" * 40, executable, tmp_path / "cache")


@pytest.fixture
def service(config):
    replies = queue.Queue()
    calculator = Calculator(config.adapter_root)
    worker = WorkerService(config, replies.put, calculator=calculator)
    yield worker, calculator, replies
    worker.close()


def initialize(worker, replies):
    assert worker.dispatch({"id": "init", "method": "initialize"})
    response = replies.get(timeout=10)
    assert response["id"] == "init" and response["ok"], response
    return response


def test_hello_does_not_claim_initialization_or_unimplemented_capabilities(service):
    worker, _, _ = service
    hello = worker.hello()
    assert hello["state"] == "configured_not_initialized"
    assert hello["capabilities"]["compute_xml"] is True
    assert hello["capabilities"]["render_item"] is True
    assert hello["capabilities"]["catalog_export"] is True
    assert hello["capabilities"]["bundled_runtime"] is False


def test_relative_byte_identity_does_not_alias_location_dependent_observations(config):
    first = observation(Path("first"))
    second = observation(Path("second"))
    second["sha256"] = "8" * 64
    second["adapter_code_sha256"] = "a-different-compiled-filename"
    assert _portable_identity(first, config) == _portable_identity(second, config)
    assert "kb" not in _portable_identity(first, config)


def test_compute_keeps_exact_xml_and_expected_revision(service):
    worker, calculator, replies = service
    initialize(worker, replies)
    xml = '<PathOfBuilding2>\r\n<!--unknown--><Opaque keep="yes"/>\r\n</PathOfBuilding2>'
    worker.dispatch(
        {
            "id": "calc",
            "method": "compute_xml",
            "params": {
                "xml": xml,
                "expected_xml_revision": xml_revision(xml),
                "stats": ["Life", "Missing"],
            },
        }
    )
    response = replies.get(timeout=10)
    assert response["ok"], response
    assert calculator.received == [xml]
    assert response["result"]["stats"] == {"Life": 123.0}
    assert response["result"]["missing_stats"] == ["Missing"]
    assert response["result"]["xml_revision"] == xml_revision(xml)
    assert response["execution"]["state"] == "completed"


def test_mismatched_expected_revision_never_reaches_calculator(service):
    worker, calculator, replies = service
    initialize(worker, replies)
    worker.dispatch(
        {
            "id": "calc",
            "method": "compute_xml",
            "params": {"xml": "<PathOfBuilding2/>", "expected_xml_revision": "sha256:" + "0" * 64},
        }
    )
    response = replies.get(timeout=10)
    assert response["ok"] is False
    assert response["error"]["code"] == "input_mismatch"
    assert calculator.received == []


@pytest.mark.parametrize("method", [[], {}, 1, None])
def test_malformed_method_is_a_protocol_error_not_a_worker_crash(service, method):
    worker, _, replies = service
    assert worker.dispatch({"id": "bad", "method": method})
    response = replies.get(timeout=1)
    assert response["error"]["code"] == "invalid_request"


def test_duplicate_id_cannot_resolve_another_request_even_with_bad_schema(service):
    worker, _, replies = service
    initialize(worker, replies)
    assert worker.dispatch({"id": "init", "method": [], "unknown": True}) is False
    response = replies.get(timeout=1)
    assert response["id"] is None
    assert response["error"]["code"] == "duplicate_request_id"


def test_cancel_targets_only_the_active_owned_request(service):
    worker, calculator, replies = service
    initialize(worker, replies)
    calculator.waiting = True
    worker.dispatch(
        {"id": "calc", "method": "compute_xml", "params": {"xml": "<PathOfBuilding2/>"}}
    )
    worker.dispatch({"id": "cancel", "method": "cancel", "params": {"request_id": "calc"}})
    responses = {
        response["id"]: response for response in (replies.get(timeout=10), replies.get(timeout=10))
    }
    assert responses["cancel"]["ok"] is True
    assert responses["calc"]["ok"] is False
    assert responses["calc"]["execution"]["state"] == "cancelled"
    assert "result" not in responses["calc"]


def test_unknown_cancel_does_not_claim_completion(service):
    worker, _, replies = service
    worker.dispatch({"id": "cancel", "method": "cancel", "params": {"request_id": "missing"}})
    response = replies.get(timeout=1)
    assert response["ok"] is False
    assert response["error"]["code"] == "request_not_active"


def test_nonfinite_wire_values_remain_diagnostic_and_are_not_zero():
    source = {"stats": {"Life": math.inf, "Unknown": math.nan}}
    changes = []
    safe = _json_safe(source, "", changes)
    assert safe["stats"] == {"Life": None, "Unknown": None}
    assert {entry["path"] for entry in changes} == {"/stats/Life", "/stats/Unknown"}
    assert math.isinf(source["stats"]["Life"])
