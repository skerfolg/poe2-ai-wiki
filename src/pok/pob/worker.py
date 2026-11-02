"""Standalone PoB stdio worker; no KB, MCP, or build-generation dependency.

Development paths and verified bundle manifests are separate launch profiles.
Native calculation, catalog export and item rendering do not depend on the KB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import queue
import re
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, RLock, Thread
from typing import Any
from uuid import uuid4

from pok.common.execution import ExecutionScope, ExecutionStopped, bind_execution
from pok.common.stdio import force_utf8_stdio
from pok.pob.daemon import PobDaemon
from pok.pob.document import inspect_xml, xml_revision
from pok.pob.versions import PobSnapshot
from pok.pob.worker_bundle import WorkerBundle, load_bundle

PROTOCOL = "pok.pob-worker.v1"
MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_XML_BYTES = 8 * 1024 * 1024
MAX_TIMEOUT_MS = 180_000
MAX_REQUESTS = 8192


class WorkerError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class WorkerConfig:
    adapter_root: Path
    pob_root: Path
    pob_commit: str
    luajit: Path
    cache_home: Path
    bundle: WorkerBundle | None = None

    def validate(self) -> None:
        if self.bundle is not None:
            self.bundle.validate()
        if not re.fullmatch(r"[0-9a-f]{40}", self.pob_commit):
            raise WorkerError("invalid_runtime", "A full lowercase PoB commit is required")
        for path in (self.adapter_root, self.pob_root, self.luajit, self.cache_home):
            if not path.is_absolute():
                raise WorkerError("invalid_runtime", "Runtime paths must be absolute")
        for path in (
            self.adapter_root / "scripts/pob_daemon.lua",
            self.pob_root / "src/HeadlessWrapper.lua",
            self.luajit,
        ):
            if not path.is_file():
                raise WorkerError("runtime_missing", f"Runtime file unavailable: {path.name}")
        if not (self.pob_root / "runtime").is_dir():
            raise WorkerError("runtime_missing", "PoB runtime directory unavailable")

    def snapshot(self) -> PobSnapshot:
        return PobSnapshot(self.pob_commit, self.pob_root, self.pob_root / "src")


def _adapter_source_digest() -> str:
    """Relative file names/bytes, not location-dependent compiled-code hashes."""
    base = Path(__file__).resolve().parents[1]
    files = {base / "__init__.py"}
    for directory in (base / "common", base / "pob"):
        files.update(p for p in directory.rglob("*") if p.suffix in {".py", ".lua"})
    digest = hashlib.sha256()
    for path in sorted(files):
        if not path.is_file():
            continue
        if not path.resolve().is_relative_to(base):
            raise WorkerError("runtime_changed", "Adapter source resolves outside its package")
        name = path.relative_to(base).as_posix().encode("utf-8")
        raw = path.read_bytes()
        digest.update(len(name).to_bytes(8, "big"))
        digest.update(name)
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


def _portable_identity(observed: dict[str, Any], config: WorkerConfig) -> dict[str, Any]:
    if observed.get("status") != "observed":
        raise WorkerError("runtime_unobserved", "Calculator inputs could not be observed")
    components = observed["components"]
    identity: dict[str, Any] = {
        "format": "pok.pob-worker-identity.v1",
        "runtime_kind": "pob-worker",
        "protocol": PROTOCOL,
        "algorithm": "relative-file-bytes-and-runtime-components.v1",
        "pob_commit": config.pob_commit,
        "adapter_sources_sha256": _adapter_source_digest(),
        "adapter_lua_sha256": components["adapter_lua"]["sha256"],
        "pob_source_sha256": components["pob_source"]["sha256"],
        "pob_runtime_sha256": components["pob_runtime"]["sha256"],
        "lua_executable_sha256": components["executable"]["sha256"],
        "python_executable_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
        "python_version": sys.version,
        "platform": sys.platform,
        "claim": "content_fingerprints_not_deployment_or_game_certification",
        "loaded_native_modules": "not_verified",
        "external_system_libraries": "not_verified",
    }
    identity["sha256"] = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return identity


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WorkerError("invalid_request", "Duplicate JSON object key")
        result[key] = value
    return result


def _json_safe(value: Any, path: str, changes: list[dict[str, str]]) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        changes.append({"path": path, "value": repr(value), "serialized_as": "null"})
        return None
    if isinstance(value, dict):
        return {
            key: _json_safe(
                child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"), changes
            )
            for key, child in value.items()
        }
    if isinstance(value, list | tuple):
        return [_json_safe(child, f"{path}/{i}", changes) for i, child in enumerate(value)]
    return value


class WorkerService:
    def __init__(
        self,
        config: WorkerConfig,
        emit: Callable[[dict[str, Any]], None],
        *,
        calculator: PobDaemon | None = None,
    ) -> None:
        config.validate()
        self.config = config
        self.instance = uuid4().hex
        self.emit = emit
        self.calculator = calculator or PobDaemon(
            config.snapshot(), adapter_root=config.adapter_root
        )
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pob-worker")
        self.lock = RLock()
        self.active: ExecutionScope | None = None
        self.identity: dict[str, Any] | None = None
        self._catalog: dict[str, Any] | None = None
        self.closing = False
        self._seen_ids: set[str] = set()

    def hello(self) -> dict[str, Any]:
        return {
            "event": "hello",
            "protocol": PROTOCOL,
            "worker_instance": self.instance,
            "state": "configured_not_initialized",
            "capabilities": {
                "compute_xml": True,
                "build_native_item": True,
                "render_item": True,
                "catalog_export": True,
                "bundled_runtime": self.config.bundle is not None,
                "cancel": True,
            },
            "limits": {
                "max_xml_bytes": MAX_XML_BYTES,
                "max_timeout_ms": MAX_TIMEOUT_MS,
                "max_requests": MAX_REQUESTS,
            },
        }

    def _error(self, identity: str | None, code: str, message: str) -> None:
        self.emit({"id": identity, "ok": False, "error": {"code": code, "message": message}})

    def dispatch(self, value: Any) -> bool:
        identity = value.get("id") if isinstance(value, dict) else None
        if isinstance(identity, str):
            with self.lock:
                if identity in self._seen_ids:
                    self._error(
                        None,
                        "duplicate_request_id",
                        "Request IDs must be unique within a worker session",
                    )
                    return False
        try:
            if not isinstance(value, dict) or set(value) - {"id", "method", "params", "timeout_ms"}:
                raise WorkerError("invalid_request", "Expected a worker request object")
            if not isinstance(identity, str) or not re.fullmatch(
                r"[A-Za-z0-9._:-]{1,128}", identity
            ):
                raise WorkerError("invalid_request", "Expected a bounded string request ID")
            method = value.get("method")
            if not isinstance(method, str):
                raise WorkerError("invalid_request", "method must be a string")
            with self.lock:
                if identity in self._seen_ids:
                    self._error(
                        None,
                        "duplicate_request_id",
                        "Request IDs must be unique within a worker session",
                    )
                    return False
                if len(self._seen_ids) >= MAX_REQUESTS and method not in {"cancel", "shutdown"}:
                    raise WorkerError(
                        "session_capacity", "Restart the worker after its request budget"
                    )
                self._seen_ids.add(identity)
            params = value.get("params", {})
            if not isinstance(params, dict):
                raise WorkerError("invalid_request", "params must be an object")
            if method == "cancel":
                if set(params) != {"request_id"} or not isinstance(params["request_id"], str):
                    raise WorkerError("invalid_request", "cancel requires request_id")
                with self.lock:
                    active = self.active
                    if active is None or active.request_id != params["request_id"]:
                        raise WorkerError(
                            "request_not_active", "No active owned request has that ID"
                        )
                    active.request_cancel()
                self.emit({"id": identity, "ok": True, "cancel_requested": params["request_id"]})
                return True
            if method == "shutdown":
                if params:
                    raise WorkerError("invalid_request", "shutdown takes no parameters")
                cleanup = self.close()
                self.emit({"id": identity, "ok": cleanup["confirmed"], "cleanup": cleanup})
                return not cleanup["confirmed"]
            if method == "runtime_info":
                if params or self.identity is None:
                    raise WorkerError(
                        "not_initialized", "Initialize the worker before reading runtime info"
                    )
                self.emit({"id": identity, "ok": True, "identity": self.identity})
                return True
            if method not in {
                "initialize",
                "compute_xml",
                "build_native_item",
                "export_catalog",
                "render_item",
            }:
                raise WorkerError("unsupported_method", "Worker method is not supported")
            timeout = value.get("timeout_ms", 30_000 if method == "initialize" else MAX_TIMEOUT_MS)
            if type(timeout) is not int or not 0 < timeout <= MAX_TIMEOUT_MS:
                raise WorkerError("invalid_request", "timeout_ms is outside the supported bound")
            with self.lock:
                if self.closing:
                    raise WorkerError("worker_closing", "The worker is closing")
                if self.active is not None:
                    raise WorkerError("busy", "An owned request is already active")
                scope = ExecutionScope(self.instance, timeout / 1000, request_id=identity)
                self.active = scope
                self.pool.submit(self._execute, method, params, scope)
            return True
        except WorkerError as exc:
            self._error(identity if isinstance(identity, str) else None, exc.code, str(exc))
            return True

    def _execute(self, method: str, params: dict[str, Any], scope: ExecutionScope) -> None:
        result: dict[str, Any] | None = None
        error: dict[str, str] | None = None
        try:
            with bind_execution(scope):
                if self.config.bundle is not None:
                    self.config.bundle.validate()
                if method == "initialize":
                    if params:
                        raise WorkerError("invalid_request", "initialize takes no parameters")
                    self.calculator.start()
                    execution = self.calculator.inspect_execution(observe_current=True)
                    if execution.get("current_matches_startup") is not True:
                        raise WorkerError(
                            "runtime_changed", "Startup calculator inputs are not stable"
                        )
                    self.identity = _portable_identity(execution["current_disk"], self.config)
                    if (
                        self.config.bundle is not None
                        and self.identity != self.config.bundle.data["identity"]
                    ):
                        raise WorkerError(
                            "runtime_identity_mismatch",
                            "Actual worker identity differs from its bundle",
                        )
                    self._catalog = None
                    result = {
                        "identity": self.identity,
                        "execution_observation": execution,
                        "provenance": {
                            "mode": "bundled" if self.config.bundle is not None else "development",
                            "bundle_manifest_verified": self.config.bundle is not None,
                            "bundle_manifest_sha256": self.config.bundle.manifest_sha256
                            if self.config.bundle is not None
                            else None,
                            "pob_commit_origin": "manifest_declared_with_verified_bytes"
                            if self.config.bundle is not None
                            else "caller_declared_not_upstream_attested",
                        },
                    }
                else:
                    if self.identity is None:
                        raise WorkerError("not_initialized", "Initialize the worker first")
                    current = self.calculator._observe_inputs()
                    if _portable_identity(current, self.config) != self.identity:
                        raise WorkerError(
                            "runtime_changed", "Worker input bytes changed after initialization"
                        )
                    if method == "export_catalog":
                        if params:
                            raise WorkerError(
                                "invalid_request", "export_catalog takes no parameters"
                            )
                        catalog = self._get_catalog()
                        result = {
                            "catalog": catalog,
                            "identity": self.identity,
                            "claim": "raw_pob_catalog_not_game_recommendation",
                        }
                    elif method == "render_item":
                        from pok.pob.ui_render import render_item

                        try:
                            rendered = render_item(params, self._get_catalog(), self.calculator)
                        except ValueError as exc:
                            raise WorkerError("invalid_item", str(exc)) from exc
                        result = {**rendered, "identity": self.identity}
                    elif method == "compute_xml":
                        if set(params) - {"xml", "stats", "expected_xml_revision"}:
                            raise WorkerError("invalid_request", "Unsupported compute parameter")
                        xml = params.get("xml")
                        if (
                            not isinstance(xml, str)
                            or not 0 < len(xml.encode("utf-8")) <= MAX_XML_BYTES
                        ):
                            raise WorkerError(
                                "invalid_input", "XML is missing or exceeds the byte bound"
                            )
                        nodes = inspect_xml(xml)
                        if not nodes or nodes[0].tag not in {"PathOfBuilding", "PathOfBuilding2"}:
                            raise WorkerError("invalid_input", "Expected PoB XML")
                        revision = xml_revision(xml)
                        expected = params.get("expected_xml_revision")
                        if expected is not None and expected != revision:
                            raise WorkerError(
                                "input_mismatch", "XML differs from expected revision"
                            )
                        stats = params.get("stats")
                        if stats is not None and (
                            not isinstance(stats, list)
                            or len(stats) > 1024
                            or any(not isinstance(name, str) or len(name) > 256 for name in stats)
                        ):
                            raise WorkerError("invalid_request", "stats must be bounded names")
                        native = self.calculator.compute(xml)
                        result = {
                            "xml_revision": revision,
                            "stats": native.stats
                            if stats is None
                            else {
                                name: native.stats[name] for name in stats if name in native.stats
                            },
                            "missing_stats": []
                            if stats is None
                            else [name for name in stats if name not in native.stats],
                            "meta": native.meta,
                            "allocated_nodes": list(native.allocated_nodes),
                            "identity": self.identity,
                            "claim": "native_calculation_not_game_validation",
                        }
                    else:
                        text = params.get("spec_text")
                        if (
                            set(params) != {"spec_text"}
                            or not isinstance(text, str)
                            or not 0 < len(text.encode()) <= 1024 * 1024
                        ):
                            raise WorkerError(
                                "invalid_request", "Expected a bounded native item specification"
                            )
                        result = {
                            "text": self.calculator.build_item(text),
                            "identity": self.identity,
                            "claim": "native_item_render_not_acquisition_validation",
                        }
                    if (
                        _portable_identity(self.calculator._observe_inputs(), self.config)
                        != self.identity
                    ):
                        raise WorkerError(
                            "runtime_changed", "Worker input bytes changed during the operation"
                        )
                if self.config.bundle is not None:
                    self.config.bundle.validate()
                scope.checkpoint()
        except ExecutionStopped as exc:
            error = {"code": exc.reason, "message": str(exc)}
            if method == "initialize":
                self.identity = None
                with suppress(Exception):
                    self.calculator.close()
        except Exception as exc:
            error = {
                "code": exc.code if isinstance(exc, WorkerError) else "operation_failed",
                "message": str(exc),
            }
            if method == "initialize" or (
                isinstance(exc, WorkerError) and exc.code == "runtime_changed"
            ):
                self.identity = None
                with suppress(Exception):
                    self.calculator.close()  # Shutdown reports the actual disposition.
        finally:
            receipt = scope.finish(failed=error is not None)
            with self.lock:
                if self.active is scope:
                    self.active = None
                if receipt["state"] == "termination_unconfirmed":
                    self.closing = True
                    self.identity = None
            ok = error is None and receipt["state"] == "completed"
            self.emit(
                {
                    "id": scope.request_id,
                    "ok": ok,
                    "execution": receipt,
                    **(
                        {"result": result}
                        if ok
                        else {
                            "error": error
                            or {"code": receipt["state"], "message": "Execution did not complete"}
                        }
                    ),
                }
            )

    def _get_catalog(self) -> dict[str, Any]:
        if self.identity is None:
            raise WorkerError("not_initialized", "Initialize the worker first")
        if self._catalog is None:
            from pok.pob.ui_export import catalog_data

            catalog = catalog_data(self.config.snapshot(), self.identity)
            errors = [row for row in catalog["diagnostics"] if row.get("severity") == "error"]
            if errors:
                raise WorkerError(
                    "catalog_incomplete", f"Unresolved catalog diagnostics: {len(errors)}"
                )
            self._catalog = catalog
        return self._catalog

    def close(self) -> dict[str, Any]:
        with self.lock:
            self.closing = True
            if self.active is not None:
                self.active.request_cancel()
        try:
            self.calculator.close()
            native = self.calculator.inspect_execution()
            confirmed = native["process_state"] == "stopped" and (
                native["last_cleanup"] is None
                or native["last_cleanup"].get("status") == "confirmed"
            )
            return {"confirmed": confirmed, "scope": "worker_owned_native_daemon", "native": native}
        except Exception as exc:
            return {"confirmed": False, "scope": "worker_owned_native_daemon", "error": str(exc)}
        finally:
            self.pool.shutdown(wait=False, cancel_futures=False)


def serve(config: WorkerConfig) -> int:
    outgoing = Lock()
    stopped = Event()
    incoming: queue.Queue[bytes | Exception | None] = queue.Queue(maxsize=8)

    def emit(value: dict[str, Any]) -> None:
        changes: list[dict[str, str]] = []
        safe = _json_safe(value, "", changes)
        if changes:
            safe["wire_normalizations"] = changes
        wire = json.dumps(safe, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
        try:
            with outgoing:
                sys.stdout.write(wire + "\n")
                sys.stdout.flush()
        except (OSError, UnicodeError):
            stopped.set()

    def read() -> None:
        pending = bytearray()
        try:
            while not stopped.is_set():
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    if pending.strip():
                        raise WorkerError("truncated_frame", "Worker input ended within a frame")
                    incoming.put(None)
                    return
                pending.extend(chunk)
                while b"\n" in pending:
                    line, _, rest = pending.partition(b"\n")
                    if len(line) > MAX_FRAME_BYTES:
                        raise WorkerError(
                            "frame_too_large", "Worker request exceeds the wire bound"
                        )
                    pending = bytearray(rest)
                    incoming.put(bytes(line))
                if len(pending) > MAX_FRAME_BYTES:
                    raise WorkerError("frame_too_large", "Worker request exceeds the wire bound")
        except Exception as exc:
            incoming.put(exc)

    service = WorkerService(config, emit)
    Thread(target=read, name="pob-worker-input", daemon=True).start()
    emit(service.hello())
    exit_code = 0
    try:
        while not stopped.is_set():
            try:
                line = incoming.get(timeout=0.1)
            except queue.Empty:
                continue
            if line is None:
                break
            if isinstance(line, Exception):
                service._error(None, "protocol_error", str(line))
                exit_code = 2
                break
            if not line.strip():
                continue
            try:
                value = json.loads(line.decode("utf-8"), object_pairs_hook=_strict_object)
            except (ValueError, UnicodeError) as exc:
                service._error(None, "invalid_json", str(exc))
                continue
            if not service.dispatch(value):
                break
    finally:
        stopped.set()
        cleanup = service.close()
        emit({"event": "closed", "worker_instance": service.instance, "cleanup": cleanup})
        if not cleanup["confirmed"]:
            exit_code = 3
    return exit_code


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-manifest")
    parser.add_argument("--cache-home", required=True)
    for name in ("adapter-root", "pob-root", "pob-commit", "luajit"):
        parser.add_argument("--" + name)
    args = parser.parse_args()
    if args.bundle_manifest:
        if any((args.adapter_root, args.pob_root, args.pob_commit, args.luajit)):
            parser.error("Bundle and explicit runtime paths cannot be mixed")
        bundle = load_bundle(Path(args.bundle_manifest))
        config = WorkerConfig(
            bundle.path("adapter"),
            bundle.path("pob"),
            bundle.data["pob_commit"],
            bundle.path("luajit"),
            Path(args.cache_home).resolve(),
            bundle=bundle,
        )
    else:
        if not all((args.adapter_root, args.pob_root, args.pob_commit, args.luajit)):
            parser.error("Explicit runtime paths or a worker bundle are required")
        config = WorkerConfig(
            Path(args.adapter_root).resolve(),
            Path(args.pob_root).resolve(),
            args.pob_commit,
            Path(args.luajit).resolve(),
            Path(args.cache_home).resolve(),
        )
    config.validate()
    os.environ["POK_LUAJIT"] = str(config.luajit)
    os.environ["POK_CACHE_HOME"] = str(config.cache_home)
    for name in ("LUA_INIT", "LUA_INIT_5_1"):
        os.environ.pop(name, None)
    return serve(config)


if __name__ == "__main__":
    raise SystemExit(main())
