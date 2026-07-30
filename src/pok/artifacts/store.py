"""빌드 산출물 기록 — artifacts/builds/<build-id>/ (PROJECT_STRUCTURE §6).

build-id = 타임스탬프+슬러그 (예: 20260730-spark-stormweaver, §9-2 확정).
사람이 읽고 대화에서 지칭하는 용도 — 내용 추적·중복 탐지는 manifest의
content_hash가 담당한다. 같은 날 같은 슬러그는 -2, -3… 접미로 회피.

이 모듈은 **파일 기록만** 한다 — 무엇을 기록할지(XML·빌드코드·검증 결과)의
조합은 상위 계층(engine)의 몫 (의존 계약상 artifacts는 pob를 import할 수 없다).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir

_SLUG = re.compile(r"[^a-z0-9가-힣-]+")


def slugify(text: str) -> str:
    s = _SLUG.sub("-", text.strip().lower()).strip("-")
    return s or "build"


def new_build_id(slug: str, *, root: Path | None = None, now: datetime | None = None) -> str:
    """YYYYMMDD-슬러그 (이미 있으면 -2, -3… — 디렉터리 실존 기준)."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
    base = f"{stamp}-{slugify(slug)}"
    builds = artifacts_dir(root) / "builds"
    build_id, n = base, 1
    while (builds / build_id).exists():
        n += 1
        build_id = f"{base}-{n}"
    return build_id


def record_build(
    build_id: str,
    files: dict[str, str],
    manifest: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    """산출물 기록. files = {파일명: 내용}, manifest에 계보·content_hash를 얹는다.

    content_hash는 files 전체(이름 포함)의 sha256 — 같은 빌드의 재기록을 탐지한다.
    """
    out = artifacts_dir(root) / "builds" / build_id
    out.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    for name in sorted(files):
        hasher.update(name.encode())
        hasher.update(files[name].encode("utf-8"))
        (out / name).write_text(files[name], encoding="utf-8")
    full = {
        "build_id": build_id,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "content_hash": hasher.hexdigest(),
        **manifest,
    }
    (out / "manifest.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def find_by_hash(content_hash: str, *, root: Path | None = None) -> list[str]:
    """같은 content_hash를 가진 기존 build-id들 (중복 탐지)."""
    builds = artifacts_dir(root) / "builds"
    if not builds.exists():
        return []
    hits = []
    for mf in sorted(builds.glob("*/manifest.json")):
        try:
            if json.loads(mf.read_text(encoding="utf-8")).get("content_hash") == content_hash:
                hits.append(mf.parent.name)
        except (OSError, json.JSONDecodeError):
            continue
    return hits
