"""Build a portable POK desktop runtime without adding freezer dependencies."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import uuid
from collections.abc import Iterable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from pok import __version__  # noqa: E402
from pok.common.paths import knowledge_dir, project_root  # noqa: E402
from pok.pob.runtime_identity import (  # noqa: E402
    json_sha256,
    runtime_identity,
    sha256_file,
    sha256_tree,
)
from pok.pob.versions import find_luajit, pinned_commit, resolve_snapshot  # noqa: E402

SKIP_DIRS = {".git", ".mypy_cache", ".pytest_cache", "__pycache__", "var"}
MARKER = ".pok-runtime-output"
PACKAGED_SKILL = "trade-search"


def _copy_tree(src: Path, dst: Path) -> None:
    def ignore(_root: str, names: list[str]) -> set[str]:
        return {name for name in names if name in SKIP_DIRS or name.endswith((".pyc", ".pyo"))}

    shutil.copytree(src, dst, ignore=ignore)


def _is_inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _is_ancestor(path: Path, child: Path) -> bool:
    try:
        child.resolve().relative_to(path.resolve())
        return path.resolve() != child.resolve()
    except ValueError:
        return False


def _git(root: Path, *args: str) -> str:
    result = subprocess_run(["git", "-C", str(root), *args])
    return result.strip()


def subprocess_run(args: list[str]) -> str:
    import subprocess

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"command failed: {args}"
        raise RuntimeError(message)
    return result.stdout


def _assert_pob_matches_pin(root: Path) -> None:
    snapshot = resolve_snapshot(root)
    actual = _git(snapshot.root, "rev-parse", "HEAD")
    if actual != pinned_commit(root):
        raise RuntimeError(f"PoB snapshot HEAD {actual} != pinned {pinned_commit(root)}")
    dirty = _git(snapshot.root, "status", "--porcelain")
    if dirty:
        raise RuntimeError("Pinned PoB snapshot is dirty; refusing to package it")


def _copy_python(dst: Path) -> Path:
    """Copy the current interpreter, stdlib and site-packages into dst/python."""
    base = Path(sys.base_prefix).resolve()
    venv = Path(sys.prefix).resolve()
    target = dst / "python"
    target.mkdir(parents=True)
    exe_name = "python.exe" if os.name == "nt" else "python"
    source_exe = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    shutil.copy2(source_exe, target / exe_name)
    for pattern in ("python*.dll", "vcruntime*.dll"):
        for src in source_exe.parent.glob(pattern):
            if src.is_file():
                shutil.copy2(src, target / src.name)
    if (base / "DLLs").exists():
        _copy_tree(base / "DLLs", target / "DLLs")
    _copy_tree(base / "Lib", target / "Lib")
    for name in ("LICENSE.txt", "LICENSE"):
        license_file = base / name
        if license_file.exists():
            resources = dst / "resources"
            resources.mkdir(exist_ok=True)
            shutil.copy2(license_file, resources / "PYTHON-LICENSE.txt")
            break
    site = venv / "Lib" / "site-packages"
    if site.exists():
        dst_site = target / "Lib" / "site-packages"
        if dst_site.exists():
            shutil.rmtree(dst_site)
        _copy_tree(site, dst_site)
        _strip_dev_site_files(dst_site, dst)
        _strip_local_direct_url(dst_site)
    return Path("python") / exe_name


def _strip_dev_site_files(site: Path, runtime_root: Path) -> None:
    """Remove editable-install loaders and .pth files carrying local absolute paths."""
    for path in site.glob("__editable__*"):
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    for path in site.glob("*.pth"):
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = [
            line
            for line in text.splitlines()
            if line.strip()
            and not line.lstrip().startswith("#")
            and not _line_points_outside_runtime(line, runtime_root)
        ]
        if lines:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            path.unlink()


def _line_points_outside_runtime(line: str, runtime_root: Path) -> bool:
    stripped = line.strip()
    if stripped.startswith(("import ", "import\t")):
        return "__editable__" in stripped or "site-packages" in stripped
    candidate = Path(stripped)
    if not candidate.is_absolute():
        return False
    return not _is_inside(candidate, runtime_root)


def _strip_local_direct_url(site: Path) -> None:
    for path in site.glob("*.dist-info/direct_url.json"):
        path.unlink()


def _copy_luajit(dst: Path) -> None:
    source = Path(find_luajit()).resolve()
    target = dst / "resources" / "luajit"
    target.mkdir(parents=True, exist_ok=True)
    exe_name = "luajit.exe" if os.name == "nt" else "luajit"
    shutil.copy2(source, target / exe_name)
    for dll in source.parent.glob("*.dll"):
        shutil.copy2(dll, target / dll.name)
    for license_file in source.parent.glob("LICEN*"):
        if license_file.is_file():
            shutil.copy2(license_file, target / license_file.name)


def _file_hashes(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root).as_posix()
        if rel == "resources/runtime-manifest.json":
            continue
        out[rel] = sha256_file(path)
    return out


def _text_files(root: Path) -> Iterable[Path]:
    suffixes = {
        ".cfg",
        ".ini",
        ".json",
        ".md",
        ".pth",
        ".py",
        ".rst",
        ".toml",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
    metadata_names = {"METADATA", "RECORD", "WHEEL", "entry_points.txt", "top_level.txt"}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in suffixes or path.name in metadata_names:
            yield path


def _sensitive_needles(root: Path) -> list[str]:
    raw = {
        str(root.resolve()),
        str(Path.home().resolve()),
        str(Path(sys.prefix).resolve()),
        str(Path(sys.executable).resolve().parent),
    }
    needles: set[str] = set()
    for value in raw:
        if not value:
            continue
        needles.add(value)
        needles.add(value.replace("\\", "/"))
    return sorted(needles, key=len, reverse=True)


def _assert_no_sensitive_paths(runtime_root: Path, source_root: Path) -> None:
    needles = _sensitive_needles(source_root)
    offenders: list[str] = []
    for path in _text_files(runtime_root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="ignore")
        if any(needle and needle in text for needle in needles):
            offenders.append(path.relative_to(runtime_root).as_posix())
            if len(offenders) >= 20:
                break
    if offenders:
        raise RuntimeError(f"Runtime artifact contains local absolute paths: {offenders}")


def _copy_runtime_inputs(root: Path, out: Path) -> None:
    _copy_tree(root / "src", out / "src")
    _copy_tree(root / "knowledge", out / "knowledge")
    _copy_skill_inputs(root, out)
    scripts = out / "scripts"
    scripts.mkdir()
    for path in sorted((root / "scripts").glob("pob*.lua")):
        shutil.copy2(path, scripts / path.name)
    snapshot = resolve_snapshot(root)
    target_pob = out / "external" / "pob" / snapshot.short
    target_pob.parent.mkdir(parents=True)
    _copy_tree(snapshot.root, target_pob)
    license_file = snapshot.root / "LICENSE.md"
    if license_file.exists():
        resources = out / "resources"
        resources.mkdir(exist_ok=True)
        shutil.copy2(license_file, resources / "POB-LICENSE.md")
    _copy_luajit(out)


def _copy_skill_inputs(root: Path, out: Path) -> None:
    """Stage the single runtime-approved skill without source orchestration config."""
    skills = out / "skills"
    skills.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "skills" / "AGENTS.md", skills / "AGENTS.md")
    _copy_tree(root / "skills" / PACKAGED_SKILL, skills / PACKAGED_SKILL)

    skill_entry = out / ".agents" / "skills" / PACKAGED_SKILL
    skill_entry.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        root / ".agents" / "skills" / PACKAGED_SKILL / "SKILL.md",
        skill_entry / "SKILL.md",
    )
    _write_runtime_agents(out)


def _write_runtime_agents(out: Path) -> None:
    out.joinpath("AGENTS.md").write_text(
        "\n".join(
            [
                "# POK desktop runtime",
                "",
                "This deployed runtime contains the `trade-search` skill only.",
                "Start from `.agents/skills/trade-search/SKILL.md`, then follow",
                "`skills/AGENTS.md` and `skills/trade-search/AGENTS.md`.",
                "",
                "Path schema:",
                "- `POK_RESOURCE_ROOT`: this read-only runtime resource root.",
                "- `python/python.exe` on Windows, or `python/python` on POSIX: bundled Python.",
                "- `POK_DATA_HOME/live/trade-search/`: writable query/input JSON and results.",
                "- `POK_CACHE_HOME/trade-search/`: disposable trade catalog and rate-limit cache.",
                "",
                "Keep the agent permission posture at the default read-only setting with",
                "on-request approvals. Do not weaken permissions for packaged runtime use.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _copy_content_digests(root: Path) -> dict[str, str]:
    snapshot = resolve_snapshot(root)
    return {
        "source": sha256_tree(
            root,
            include=(
                "src/pok/**/*.py",
                "src/pok/**/*.lua",
                "scripts/pob*.lua",
                "skills/AGENTS.md",
                f"skills/{PACKAGED_SKILL}/**/*",
                f".agents/skills/{PACKAGED_SKILL}/SKILL.md",
            ),
        ),
        "pob": sha256_tree(snapshot.src_dir),
        "kb": sha256_tree(knowledge_dir(root)),
    }


def _write_launcher(out: Path) -> Path:
    launcher = out / "pok_launcher.py"
    launcher.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import pathlib",
                "import os",
                "import sys",
                "root = pathlib.Path(__file__).resolve().parent",
                "local_app_data = os.environ.get('LOCALAPPDATA')",
                "if local_app_data:",
                "    state_root = pathlib.Path(local_app_data) / 'POK'",
                "else:",
                "    state_root = pathlib.Path.home() / '.pok'",
                "os.environ.pop('POK_POB_ROOT', None)",
                "os.environ.pop('POK_LUAJIT', None)",
                "os.environ.setdefault('POK_RESOURCE_ROOT', str(root))",
                "os.environ.setdefault('POK_DATA_HOME', str(state_root / 'data'))",
                "os.environ.setdefault('POK_CACHE_HOME', str(state_root / 'cache'))",
                "sys.dont_write_bytecode = True",
                "sys.path.insert(0, str(root / 'src'))",
                "from pok.desktop import main",
                "raise SystemExit(main(sys.argv[1:]))",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return Path("pok_launcher.py")


def _safe_replace(temp: Path, output: Path, *, force: bool) -> None:
    if output.exists() and not force:
        raise RuntimeError(f"Output already exists: {output}")
    if output.exists() and not (output / MARKER).is_file():
        raise RuntimeError(f"Refusing to replace unmarked runtime output: {output}")
    backup = output.with_name(f"{output.name}.old-{uuid.uuid4().hex}")
    if output.exists():
        output.rename(backup)
    try:
        temp.rename(output)
    except Exception:
        if backup.exists():
            backup.rename(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def build(output: Path, *, force: bool = False) -> Path:
    root = project_root()
    output = output.resolve()
    if output == root.resolve() or _is_ancestor(output, root):
        raise RuntimeError("Runtime output must not be the source root or any ancestor of it")
    if _is_inside(output, root) and not _is_inside(output, root / "var"):
        raise RuntimeError("Runtime output must be outside the source tree or under var/")
    if output.exists() and not force:
        raise RuntimeError(f"Output already exists: {output}")
    if output.exists() and not (output / MARKER).is_file():
        raise RuntimeError(f"Refusing to replace unmarked runtime output: {output}")
    parent = output.parent.resolve()
    parent.mkdir(parents=True, exist_ok=True)
    temp = parent / f".{output.name}.tmp-{uuid.uuid4().hex}"
    if temp.exists():
        raise RuntimeError(f"Temporary runtime path unexpectedly exists: {temp}")
    _assert_pob_matches_pin(root)
    before_copy = _copy_content_digests(root)
    temp.mkdir(parents=True)
    _copy_runtime_inputs(root, temp)
    after_copy = _copy_content_digests(root)
    staged_copy = _copy_content_digests(temp)
    if before_copy != after_copy:
        raise RuntimeError("Source, PoB, or KB changed while building runtime; rerun the build")
    if staged_copy != after_copy:
        raise RuntimeError("Staged runtime content does not match current source/PoB/KB digests")
    python_rel = _copy_python(temp)
    launcher_rel = _write_launcher(temp)
    final_source = _copy_content_digests(root)
    if final_source != staged_copy:
        raise RuntimeError("Source, PoB, or KB changed before manifest sealing; rerun the build")
    identity = runtime_identity(root, force_compute=True)
    if _copy_content_digests(root) != staged_copy:
        raise RuntimeError(
            "Source, PoB, or KB changed while computing runtime identity; rerun the build"
        )
    entrypoint = [python_rel.as_posix(), "-B", launcher_rel.as_posix(), "serve"]
    manifest = {
        "format_version": 1,
        "version": __version__,
        "pob_commit": identity["pob"]["commit"],
        "platform": f"{sys.platform}-{platform.machine().lower()}",
        "entrypoint": entrypoint,
        "identity": identity,
        "sha256": {},
    }
    manifest["manifest_digest"] = json_sha256({k: v for k, v in manifest.items() if k != "sha256"})
    resources = temp / "resources"
    resources.mkdir(exist_ok=True)
    manifest_path = resources / "runtime-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    manifest["sha256"] = _file_hashes(temp)
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _assert_no_sensitive_paths(temp, root)
    (temp / MARKER).write_text("POK desktop runtime output\n", encoding="utf-8")
    _safe_replace(temp, output, force=force)
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("var/desktop-runtime"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    out = build(args.output, force=args.force)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
