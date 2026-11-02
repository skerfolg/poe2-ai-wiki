"""Build a new standalone Windows PoB runtime; never overwrite an existing one."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shutil
import sys
import tempfile
from pathlib import Path
from subprocess import PIPE
from threading import Thread
from typing import Any

from pok.common.owned_process import spawn_owned, terminate_owned
from pok.common.stdio import force_utf8_stdio
from pok.pob.runner import run_native_capture
from pok.pob.worker_bundle import FORMAT, file_sha256, load_bundle


def _copy(source: Path, target: Path, *, visuals: bool = False) -> None:
    def ignore(_path: str, names: list[str]) -> set[str]:
        return {
            name
            for name in names
            if name in {".git", "__pycache__", "site-packages"}
            or name.endswith((".pyc", ".pyo"))
            or (
                visuals
                and (
                    Path(name).suffix.lower() in {".png", ".jpg", ".jpeg", ".tga", ".tgf"}
                    or name.lower().endswith(".dds.zst")
                )
            )
        }

    shutil.copytree(source, target, ignore=ignore)


def _git(root: Path, *args: str) -> str:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git executable is required to verify build inputs")
    result = run_native_capture(
        [executable, "-c", f"safe.directory={root.as_posix()}", "-C", str(root), *args],
        cwd=root,
        env=dict(os.environ),
        timeout=30,
    )
    if result.returncode:
        raise ValueError("Unable to verify runtime source repository")
    return result.stdout.strip()


class _Probe:
    def __init__(self, root: Path, python: Path, cache: Path, commit: str, *, sealed: bool):
        command = [str(python), "-I", "-B", "-m", "pok.pob.worker", "--cache-home", str(cache)]
        if sealed:
            command += ["--bundle-manifest", str(root / "worker-manifest.json")]
        else:
            command += [
                "--adapter-root",
                str(root / "adapter"),
                "--pob-root",
                str(root / "pob"),
                "--pob-commit",
                commit,
                "--luajit",
                str(root / "luajit/luajit.exe"),
            ]
        env = dict(os.environ)
        for name in (
            "PYTHONPATH",
            "PYTHONHOME",
            "VIRTUAL_ENV",
            "POK_LUAJIT",
            "POK_DATA_HOME",
            "LUA_INIT",
            "LUA_INIT_5_1",
        ):
            env.pop(name, None)
        env["PATH"] = os.pathsep.join(
            [
                str(root / "python"),
                str(root / "luajit"),
                str(Path(os.environ.get("SYSTEMROOT", "C:/Windows")) / "System32"),
            ]
        )
        self.errors = (cache.parent / (cache.name + "-stderr.txt")).open(
            "w", encoding="utf-8", newline="\n"
        )
        self.proc = spawn_owned(
            command,
            cwd=root,
            env=env,
            stdin=PIPE,
            stdout=PIPE,
            stderr=self.errors,
            text=True,
            encoding="utf-8",
        )
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.reader = Thread(target=self._read, daemon=True)
        self.reader.start()
        self.counter = 0
        try:
            hello = self.receive()
            if hello.get("event") != "hello":
                raise ValueError("Worker bundle emitted no protocol hello")
            self.hello = hello
        except BaseException:
            terminate_owned(self.proc)
            self.errors.close()
            self.reader.join(timeout=2)
            raise

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.messages.put(json.loads(line))
        self.messages.put({"event": "eof"})

    def receive(self) -> dict[str, Any]:
        try:
            return self.messages.get(timeout=150)
        except queue.Empty:
            raise ValueError("Standalone worker probe exceeded its response deadline") from None

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.counter += 1
        identity = f"probe{self.counter}"
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps(
                {"id": identity, "method": method, "params": params or {}, "timeout_ms": 120_000}
            )
            + "\n"
        )
        self.proc.stdin.flush()
        result = self.receive()
        if result.get("id") != identity or result.get("ok") is not True:
            raise ValueError(f"Standalone worker probe failed: {result.get('error')}")
        return result

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                result = self.call("shutdown")
                if not result["cleanup"]["confirmed"]:
                    raise ValueError("Standalone worker probe did not confirm native cleanup")
                self.proc.wait(timeout=15)
        finally:
            cleanup = terminate_owned(self.proc)
            self.errors.close()
            self.reader.join(timeout=2)
            if cleanup["status"] != "confirmed":
                raise ValueError("Standalone probe containment cleanup is unconfirmed")


def build_bundle(
    output: Path,
    *,
    adapter_root: Path,
    pob_root: Path,
    pob_commit: str,
    luajit: Path,
    python_home: Path | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    if os.name != "nt":
        raise ValueError("This builder currently requires a prepared Windows Python runtime")
    output, adapter_root, pob_root, luajit = (
        path.resolve() for path in (output, adapter_root, pob_root, luajit)
    )
    python_home = (python_home or Path(sys.base_prefix)).resolve()
    sources = [
        adapter_root / "src/pok",
        adapter_root / "scripts",
        pob_root,
        python_home,
        luajit.parent,
    ]
    if output.exists() or any(
        output.is_relative_to(source) or source.is_relative_to(output) for source in sources
    ):
        raise ValueError("Output must be a new directory outside copied source trees")
    if (
        not re.fullmatch(r"[0-9a-f]{40}", pob_commit)
        or _git(pob_root, "rev-parse", "HEAD") != pob_commit
    ):
        raise ValueError("PoB source does not match the declared pin")
    if _git(pob_root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("PoB source has tracked modifications")
    dirty = bool(_git(adapter_root, "status", "--porcelain", "--", "src/pok", "scripts"))
    if dirty and not allow_dirty:
        raise ValueError("Commit adapter sources or explicitly allow a development bundle")
    output.mkdir(parents=True)
    target = output / "adapter"
    (target / "src/pok").mkdir(parents=True)
    for name in ("common", "pob"):
        _copy(adapter_root / "src/pok" / name, target / "src/pok" / name)
    shutil.copyfile(adapter_root / "src/pok/__init__.py", target / "src/pok/__init__.py")
    (target / "scripts").mkdir()
    for path in (adapter_root / "scripts").glob("*.lua"):
        shutil.copyfile(path, target / "scripts" / path.name)
    for name in ("src", "runtime"):
        _copy(pob_root / name, output / "pob" / name, visuals=True)
    python = output / "python"
    python.mkdir()
    source_python = python_home / "python.exe"
    shutil.copyfile(source_python, python / "python.exe")
    for pattern in ("python*.dll", "vcruntime*.dll"):
        for path in python_home.glob(pattern):
            shutil.copyfile(path, python / path.name)
    for name in ("DLLs", "Lib"):
        _copy(python_home / name, python / name)
    tags = [
        path.stem
        for path in python.glob("python3*.dll")
        if re.fullmatch(r"python3\d{2,}", path.stem)
    ]
    if len(tags) != 1:
        raise ValueError("Unable to identify the standalone interpreter library")
    (python / (tags[0] + "._pth")).write_text(
        "Lib\nDLLs\n.\n../adapter/src\n", encoding="utf-8", newline="\n"
    )
    lua = output / "luajit"
    lua.mkdir()
    shutil.copyfile(luajit, lua / "luajit.exe")
    for path in luajit.parent.glob("*.dll"):
        shutil.copyfile(path, lua / path.name)
    licenses = output / "licenses"
    licenses.mkdir()
    for source, name in (
        (python_home / "LICENSE.txt", "PYTHON-LICENSE.txt"),
        (pob_root / "LICENSE.md", "POB-LICENSE.md"),
    ):
        if source.is_file():
            shutil.copyfile(source, licenses / name)
    for path in luajit.parent.glob("LICEN*"):
        if path.is_file():
            shutil.copyfile(path, licenses / ("LUAJIT-" + path.name))
    if (output / "knowledge").exists() or (target / "src/pok/kb").exists():
        raise ValueError("KB must not be included in the manual runtime")
    with tempfile.TemporaryDirectory(prefix="pob-worker-build-", dir=output.parent) as temporary:
        probe_root = Path(temporary).resolve()
        if not probe_root.is_relative_to(output.parent.resolve()):
            raise ValueError("Probe directory escapes its declared build parent")
        probe = _Probe(
            output, python / "python.exe", probe_root / "unsealed", pob_commit, sealed=False
        )
        try:
            initialized = probe.call("initialize")
            identity = initialized["result"]["identity"]
        finally:
            probe.close()
        files = {
            path.relative_to(output).as_posix(): {
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(output.rglob("*"))
            if path.is_file()
        }
        manifest = {
            "format": FORMAT,
            "protocol": "pok.pob-worker.v1",
            "platform": sys.platform,
            "pob_commit": pob_commit,
            "paths": {
                "python": "python/python.exe",
                "adapter": "adapter",
                "pob": "pob",
                "luajit": "luajit/luajit.exe",
            },
            "files": files,
            "identity": identity,
            "origin": {
                "adapter_commit": _git(adapter_root, "rev-parse", "HEAD"),
                "adapter_dirty": dirty,
                "pob_tracked_source_verified": True,
            },
        }
        path = output / "worker-manifest.json"
        path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
            newline="\n",
        )
        bundle = load_bundle(path, check_interpreter=False)
        probe = _Probe(
            output, python / "python.exe", probe_root / "sealed", pob_commit, sealed=True
        )
        try:
            initialized = probe.call("initialize")
            if (
                initialized["result"]["identity"] != identity
                or not probe.hello["capabilities"]["bundled_runtime"]
            ):
                raise ValueError("Sealed worker did not verify its own bundle")
        finally:
            probe.close()
    return {
        "root": str(output),
        "manifest_sha256": bundle.manifest_sha256,
        "identity": identity,
        "files": len(files),
        "adapter_dirty": dirty,
    }


def main() -> int:
    force_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "adapter-root", "pob-root", "pob-commit", "luajit"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--python-home")
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args()
    result = build_bundle(
        Path(args.output),
        adapter_root=Path(args.adapter_root),
        pob_root=Path(args.pob_root),
        pob_commit=args.pob_commit,
        luajit=Path(args.luajit),
        python_home=Path(args.python_home) if args.python_home else None,
        allow_dirty=args.allow_dirty,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
