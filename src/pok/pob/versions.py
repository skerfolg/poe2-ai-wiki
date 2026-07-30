"""PoB 스냅샷 해석 — 커밋 고정·경로·LuaJIT 발견 (AD-2/D4/D21).

스냅샷 = `external/pob/<short-sha>/` 독립 클론. 새 버전은 새 클론(덮어쓰기 금지).
어떤 스냅샷이 정본인지는 `knowledge/ingest/manifest.json`의 `pob_commit`이 결정한다
— KB와 계산 오라클이 같은 증거 체인에 묶인다(KB_INGEST §5).
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from pok.common.paths import project_root


@dataclass(frozen=True)
class PobSnapshot:
    """검증된 PoB 스냅샷 — src_dir을 cwd로 LuaJIT을 돌릴 수 있는 상태."""

    commit: str  # 전체 SHA (manifest 기록값)
    root: Path  # external/pob/<short>/
    src_dir: Path  # HeadlessWrapper.lua 가 있는 곳

    @property
    def short(self) -> str:
        return self.commit[:7]


def pinned_commit(root: Path | None = None) -> str:
    """manifest.json의 pob_commit — KB가 근거한 바로 그 PoB."""
    manifest = (root or project_root()) / "knowledge" / "ingest" / "manifest.json"
    commit = json.loads(manifest.read_text(encoding="utf-8")).get("pob_commit", "")
    if not commit:
        raise RuntimeError(f"manifest에 pob_commit 없음: {manifest}")
    return str(commit)


def resolve_snapshot(root: Path | None = None, commit: str | None = None) -> PobSnapshot:
    """스냅샷 디렉터리를 찾아 검증한다. 없으면 준비 방법을 담아 실패."""
    base = root or project_root()
    sha = commit or pinned_commit(base)
    snap_root = base / "external" / "pob" / sha[:7]
    src = snap_root / "src"
    if not (src / "HeadlessWrapper.lua").exists():
        raise FileNotFoundError(
            f"PoB 스냅샷 없음: {snap_root}\n"
            f"준비: git clone --no-checkout <PoB-PoE2 repo> {snap_root} && "
            f"git -C {snap_root} checkout {sha}"
        )
    return PobSnapshot(commit=sha, root=snap_root, src_dir=src)


def find_luajit() -> str:
    """LuaJIT 실행 파일 — POK_LUAJIT 환경변수 > PATH (Win/mac 공통, D21)."""
    override = os.environ.get("POK_LUAJIT")
    if override:
        if not Path(override).exists():
            raise FileNotFoundError(f"POK_LUAJIT 경로가 없음: {override}")
        return override
    found = shutil.which("luajit")
    if found is None:
        raise FileNotFoundError(
            "luajit을 찾지 못함 — PATH에 추가하거나 POK_LUAJIT로 지정 "
            "(mac: brew install luajit / Windows: MSYS2 mingw-w64-x86_64-luajit)"
        )
    return found
