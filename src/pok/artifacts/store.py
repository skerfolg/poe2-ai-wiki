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


def _record(
    kind: str,
    id_key: str,
    artifact_id: str,
    files: dict[str, str],
    manifest: dict[str, Any],
    root: Path | None,
) -> Path:
    out = artifacts_dir(root) / kind / artifact_id
    out.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    for name in sorted(files):
        hasher.update(name.encode())
        hasher.update(files[name].encode("utf-8"))
        (out / name).write_text(files[name], encoding="utf-8")
    full = {
        id_key: artifact_id,
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "content_hash": hasher.hexdigest(),
        **manifest,
    }
    (out / "manifest.json").write_text(
        json.dumps(full, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


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
    return _record("builds", "build_id", build_id, files, manifest, root)


def new_anchor_id(slug: str, *, root: Path | None = None, now: datetime | None = None) -> str:
    """앵커 id = YYYYMMDD-슬러그 (builds와 같은 규약, anchors/ 실존 기준 회피)."""
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
    base = f"{stamp}-{slugify(slug)}"
    anchors = artifacts_dir(root) / "anchors"
    anchor_id, n = base, 1
    while (anchors / anchor_id).exists():
        n += 1
        anchor_id = f"{base}-{n}"
    return anchor_id


def record_anchor(
    anchor_id: str,
    files: dict[str, str],
    manifest: dict[str, Any],
    *,
    root: Path | None = None,
) -> Path:
    """외부 앵커 빌드 보관 — artifacts/anchors/<id>/ (D30, 계보 manifest 필수).

    manifest에는 source(url·site·provenance)가 있어야 한다 — 계보 없는 앵커는
    "근거 있는 재조합"(RC5)의 근거가 될 수 없다.
    """
    if "source" not in manifest:
        raise ValueError("앵커 manifest에 source(계보)가 없음 — url·site·provenance 필수")
    return _record("anchors", "anchor_id", anchor_id, files, manifest, root)


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
