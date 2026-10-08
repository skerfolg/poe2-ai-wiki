"""프로젝트 경로 해석 — 크로스플랫폼(D21).

정본/파생 경계(PROJECT_STRUCTURE §3)의 물리 경로를 한 곳에서 정의한다.
"""

from __future__ import annotations

import os
from pathlib import Path

_ROOT_MARKERS = ("pyproject.toml", "knowledge")


def project_root(start: Path | None = None) -> Path:
    """`start`(기본: 이 파일 위치)에서 위로 올라가며 레포 루트를 찾는다."""
    cur = (start or Path(__file__)).resolve()
    for candidate in (cur, *cur.parents):
        if all((candidate / m).exists() for m in _ROOT_MARKERS):
            return candidate
    raise FileNotFoundError(f"프로젝트 루트를 찾지 못함 (markers={_ROOT_MARKERS}, start={cur})")


def resource_root(start: Path | None = None) -> Path:
    """읽기 전용 런타임 리소스 루트.

    개발 checkout에서는 프로젝트 루트이고, desktop runtime에서는 `POK_RESOURCE_ROOT`
    또는 이 모듈 위치에서 찾은 묶음 루트다. 쓰기 경로는 아래 data/cache 함수로만
    분리한다.
    """
    override = os.environ.get("POK_RESOURCE_ROOT")
    if override:
        return Path(override).resolve()
    return project_root(start)


def data_home(root: Path | None = None) -> Path:
    """사용자 데이터/산출물 쓰기 루트. 없으면 생성."""
    override = os.environ.get("POK_DATA_HOME")
    if root is not None:
        p = root / "var"
    elif override:
        p = Path(override).resolve()
    else:
        p = resource_root() / "var"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_home(root: Path | None = None) -> Path:
    """삭제 가능한 캐시 쓰기 루트. 없으면 생성."""
    override = os.environ.get("POK_CACHE_HOME")
    if root is not None:
        p = data_home(root) / "cache"
    elif override:
        p = Path(override).resolve()
    else:
        p = data_home() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def knowledge_dir(root: Path | None = None) -> Path:
    """① 정본 KB (git 추적)."""
    return (root or resource_root()) / "knowledge"


def schema_dir(root: Path | None = None) -> Path:
    """정본 스키마 (KD-3)."""
    return knowledge_dir(root) / "schema"


def var_dir(root: Path | None = None) -> Path:
    """③ 파생/캐시 (gitignore, 삭제 무해). 없으면 생성."""
    return data_home(root)


def index_db_path(root: Path | None = None) -> Path:
    """파생 검색 인덱스 (self-healing 대상)."""
    if root is not None:
        return var_dir(root) / "index.sqlite"
    return cache_home(root) / "index.sqlite"


def artifacts_dir(root: Path | None = None) -> Path:
    """② 산출물 (gitignore, 재생성 불가 — 계보 manifest와 함께 보존). 없으면 생성."""
    p = root / "artifacts" if root is not None else data_home() / "artifacts"
    p.mkdir(parents=True, exist_ok=True)
    return p
