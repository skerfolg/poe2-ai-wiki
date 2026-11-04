"""Real stdio worker operations with KB reads disabled in a fresh process."""

import json
import os
import queue
import shutil
import subprocess
import sys
from threading import Thread
from time import monotonic, sleep

import pytest

from pok.common.owned_process import spawn_owned, terminate_owned
from pok.common.paths import project_root
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.document import xml_revision
from pok.pob.versions import find_luajit, resolve_snapshot


def ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not ready(), reason="LuaJIT or pinned PoB unavailable")


class Client:
    def __init__(self, tmp_path, *, stall=False):
        root = project_root()
        snapshot = resolve_snapshot()
        self.audit = tmp_path / "kb-audit.json"
        assets = tmp_path / "assets"
        (assets / "scripts").mkdir(parents=True)
        for script in (root / "scripts").glob("*.lua"):
            shutil.copyfile(script, assets / "scripts" / script.name)
        assert not (assets / "knowledge").exists()
        assert not (assets / "pyproject.toml").exists()
        self.driver = assets / "scripts/pob_daemon.lua"
        self.marker = tmp_path / "native-entered"
        if stall:
            self.driver.write_text(
                "io.stdout:setvbuf('no')\nprint('POK_READY')\n"
                "for line in io.lines() do\n"
                " if line == 'QUIT' then break end\n"
                " local f=assert(io.open(os.getenv('POB_WORKER_TEST_MARKER'),'w'))\n"
                " f:write('entered');f:close()\n"
                " local until_time=os.clock()+30\n"
                " while os.clock()<until_time do end\n"
                " os.exit(0)\nend\n",
                encoding="utf-8",
            )
        bootstrap = (
            "import sys,json,atexit,os;from pathlib import Path\n"
            f"blocked_root=Path({str(root / 'knowledge')!r}).resolve();attempts=[]\n"
            "def audit(event,args):\n"
            " if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):\n"
            "  path=Path(os.fsdecode(args[0])).resolve()\n"
            "  if path.is_relative_to(blocked_root):\n"
            "   attempts.append(str(path))\n"
            "   raise PermissionError('KB reads disabled in worker test')\n"
            "sys.addaudithook(audit)\n"
            f"audit_path=Path({str(self.audit)!r})\n"
            "def record_audit():\n"
            " modules=[m for m in sys.modules if m=='pok.kb' or m.startswith('pok.kb.')]\n"
            " value=json.dumps({'blocked':attempts,'modules':modules})\n"
            " audit_path.write_text(value,encoding='utf-8')\n"
            "atexit.register(record_audit)\n"
            "from pok.pob.worker import main\nraise SystemExit(main())\n"
        )
        command = [
            sys.executable,
            "-B",
            "-c",
            bootstrap,
            "--adapter-root",
            str(assets),
            "--pob-root",
            str(snapshot.root),
            "--pob-commit",
            snapshot.commit,
            "--luajit",
            find_luajit(),
            "--cache-home",
            str(tmp_path / "cache"),
        ]
        self.errors = (tmp_path / "stderr.txt").open("w", encoding="utf-8")
        self.process = spawn_owned(
            command,
            cwd=tmp_path,
            env={
                **os.environ,
                "PYTHONPATH": str(root / "src"),
                "PYTHONUTF8": "1",
                "POB_WORKER_TEST_MARKER": str(self.marker),
            },
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.errors,
            text=True,
            encoding="utf-8",
        )
        self.responses = queue.Queue()
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()
        self.hello = self.receive()
        assert self.hello["event"] == "hello", self.hello

    def _read(self):
        for line in self.process.stdout:
            self.responses.put(json.loads(line))

    def send(self, identity, method, params=None, timeout=120_000):
        self.process.stdin.write(
            json.dumps(
                {"id": identity, "method": method, "params": params or {}, "timeout_ms": timeout}
            )
            + "\n"
        )
        self.process.stdin.flush()

    def receive(self):
        try:
            return self.responses.get(timeout=150)
        except queue.Empty:
            self.errors.flush()
            raise AssertionError("worker response deadline exceeded") from None

    def initialize(self):
        self.send("init", "initialize")
        result = self.receive()
        assert result["ok"], result
        observation = result["result"]["execution_observation"]
        assert observation["current_matches_startup"] is True
        assert observation["current_disk"]["launch_config"]["driver"] == str(self.driver.resolve())
        assert result["result"]["identity"]["runtime_kind"] == "pob-worker"
        assert result["result"]["provenance"]["mode"] == "development"

    def close(self):
        if (
            self.process.poll() is None
            and self.process.stdin is not None
            and not self.process.stdin.closed
        ):
            self.send("test-cleanup", "shutdown")
            deadline = monotonic() + 15
            while monotonic() < deadline:
                try:
                    response = self.responses.get(timeout=max(0.01, deadline - monotonic()))
                except queue.Empty:
                    break
                if response.get("id") == "test-cleanup":
                    break
        cleanup = terminate_owned(self.process)
        self.errors.close()
        self.reader.join(timeout=2)
        assert cleanup["status"] == "confirmed", cleanup


def source_xml():
    return to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(
                SkillGroupSpec(
                    gems=(
                        GemSpec(
                            gem_id="Metadata/Items/Gems/SkillGemSpark",
                            name="Spark",
                            stat_set_index=1,
                        ),
                    )
                ),
            ),
        )
    )


def test_worker_initializes_computes_and_shuts_down_without_kb(tmp_path):
    client = Client(tmp_path)
    try:
        client.initialize()
        xml = source_xml()
        client.send(
            "calc",
            "compute_xml",
            {
                "xml": xml,
                "expected_xml_revision": xml_revision(xml),
                "stats": ["Life", "CombinedDPS"],
            },
        )
        result = client.receive()
        assert result["ok"], result
        assert result["result"]["xml_revision"] == xml_revision(xml)
        assert result["result"]["stats"]["Life"] > 0
        assert result["execution"]["owner"] == client.hello["worker_instance"]
        client.send(
            "item",
            "build_native_item",
            {"spec_text": "Rarity: Rare\nWorker Fixture\nIron Ring\nItem Level: 80"},
        )
        item = client.receive()
        assert item["ok"], item
        assert "Iron Ring" in item["result"]["text"]
        client.send("bye", "shutdown")
        closed = client.receive()
        assert closed["id"] == "bye" and closed["cleanup"]["confirmed"], closed
        assert client.process.wait(timeout=15) == 0
        audit = json.loads(client.audit.read_text(encoding="utf-8"))
        assert audit == {"blocked": [], "modules": []}
    finally:
        client.close()


def test_worker_owner_eof_closes_its_native_process(tmp_path):
    client = Client(tmp_path)
    try:
        client.initialize()
        client.process.stdin.close()
        assert client.process.wait(timeout=15) == 0
        assert json.loads(client.audit.read_text(encoding="utf-8")) == {
            "blocked": [],
            "modules": [],
        }
    finally:
        client.close()


def test_worker_cancel_interrupts_owned_native_loop(tmp_path):
    # A real LuaJIT process speaks the ready protocol and stalls; no fake game DPS.
    client = Client(tmp_path, stall=True)
    try:
        client.initialize()
        client.send("calc", "compute_xml", {"xml": source_xml(), "stats": ["Life"]})
        deadline = monotonic() + 30
        while not client.marker.exists() and monotonic() < deadline:
            sleep(0.01)
        assert client.marker.exists(), "native request never started"
        client.send("cancel", "cancel", {"request_id": "calc"})
        responses = {response["id"]: response for response in (client.receive(), client.receive())}
        assert responses["cancel"]["ok"] is True
        assert responses["calc"]["ok"] is False
        assert responses["calc"]["execution"]["state"] == "cancelled"
        assert "result" not in responses["calc"]
        client.send("bye", "shutdown")
        closed = client.receive()
        assert closed["id"] == "bye" and closed["cleanup"]["confirmed"], closed
        assert client.process.wait(timeout=15) == 0
    finally:
        client.close()


def test_worker_exports_native_catalog_and_renders_catalog_ids_without_kb(tmp_path):
    client = Client(tmp_path)
    try:
        client.initialize()
        client.send("catalog", "export_catalog")
        exported = client.receive()
        assert exported["ok"], exported
        catalog = exported["result"]["catalog"]
        assert catalog["schemaVersion"] == 2
        assert catalog["source"]["identity"]["format"] == "pok.pob-worker-identity.v1"
        assert "kbManifestSha256" not in catalog["source"]
        assert len(catalog["entries"]) > 10000
        assert not [row for row in catalog["diagnostics"] if row.get("severity") == "error"]
        requests = [
            {"kind": "base", "id": "Iron Ring"},
            {"kind": "rare", "id": "Iron Ring", "mods": ["Strength1"], "rolls": {"Strength1": 0.5}},
            {"kind": "unique", "id": "unique:Dream Fragments:Sapphire Ring", "variants": ["1"]},
        ]
        rendered = []
        for index, request in enumerate(requests):
            client.send(f"render{index}", "render_item", request)
            response = client.receive()
            assert response["ok"], response
            assert response["result"]["ok"], response
            rendered.append(response["result"]["text"])
        assert "Iron Ring" in rendered[0]
        assert "+7 to Strength" in rendered[1]
        assert "Selected Variant: 1" in rendered[2]
        client.send("bye", "shutdown")
        closed = client.receive()
        assert closed["cleanup"]["confirmed"], closed
        assert client.process.wait(timeout=15) == 0
        assert json.loads(client.audit.read_text(encoding="utf-8")) == {
            "blocked": [],
            "modules": [],
        }
    finally:
        client.close()


def test_worker_mode_error_does_not_import_kb_and_next_input_recovers(tmp_path):
    client = Client(tmp_path)
    try:
        client.initialize()
        invalid = to_xml(
            BuildSpec(
                class_name="Mercenary",
                ascendancy="Mercenary2",
                level=100,
                skills=(
                    SkillGroupSpec(
                        gems=(
                            GemSpec(
                                gem_id="Metadata/Items/Gems/SkillGemFragmentationRounds",
                                name="Fragmentation Rounds",
                                level=20,
                                stat_set_index=2,
                            ),
                        )
                    ),
                ),
            )
        )
        client.send("invalid-mode", "compute_xml", {"xml": invalid})
        failed = client.receive()
        assert failed["ok"] is False, failed
        assert "statSet" in json.dumps(failed), failed
        assert "ModuleNotFoundError" not in json.dumps(failed), failed
        valid = source_xml()
        client.send("valid-after-mode-error", "compute_xml", {"xml": valid, "stats": ["Life"]})
        recovered = client.receive()
        assert recovered["ok"], recovered
        assert recovered["result"]["stats"]["Life"] > 0
        client.send("bye", "shutdown")
        closed = client.receive()
        assert closed["id"] == "bye" and closed["cleanup"]["confirmed"], closed
        assert client.process.wait(timeout=15) == 0
        assert json.loads(client.audit.read_text(encoding="utf-8")) == {
            "blocked": [],
            "modules": [],
        }
    finally:
        client.close()
