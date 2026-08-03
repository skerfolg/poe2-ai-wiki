"""피드백 기록 — P5 학습 루프의 입구 (BLUEPRINT §10.4, PROJECT_STRUCTURE §6).

인게임 실험·설계 폐기 노트 등 **런타임에서 얻은 관찰**을 원문 그대로 보관한다.
여기서 KB로 직행하지 않는다 — `artifacts/feedback/raw/` 는 스테이징이고, 정본
진입은 큐레이션(사람 승인) → 승격(promote)을 거쳐야 한다.

원문 보존 이유: 관찰에도 오류가 섞인다(실증 2026-08-02 — 사용자 폐기 노트의
한 수치가 인게임 확인값과 달랐고, 큐레이션 게이트가 그것을 걸러냈다). 원문을
남겨야 나중에 판정을 뒤집을 때 근거를 다시 읽을 수 있다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir


def _slug(text: str) -> str:
    keep = [c if c.isalnum() or c in "-가-힣" else "-" for c in text.strip().lower()]
    out = "".join(keep)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-") or "feedback"


def record_feedback(
    title: str,
    content: str,
    *,
    kind: str,
    source: dict[str, Any],
    root: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """관찰 원문을 `artifacts/feedback/raw/<id>/`에 보관하고 경로를 돌려준다.

    kind: in-game-test | design-postmortem | build-feedback 등 (자유 문자열 —
    분류는 큐레이션에서 판단, 여기는 기록만).
    source: 출처 계보(제공자·원 파일·일시 등) — 근거 없는 피드백은 승격 불가.
    """
    stamp = (now or datetime.now(UTC)).strftime("%Y%m%d")
    base = f"{stamp}-{_slug(title)}"
    raw_dir = artifacts_dir(root) / "feedback" / "raw"
    out, n = raw_dir / base, 1
    while out.exists():
        n += 1
        out = raw_dir / f"{base}-{n}"
    out.mkdir(parents=True)
    (out / "content.md").write_text(content, encoding="utf-8")
    manifest = {
        "feedback_id": out.name,
        "title": title,
        "kind": kind,
        "recorded": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
        "source": source,
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "state": "raw",  # raw → candidate(큐레이션) → promoted(승격)
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return out


def list_feedback(state: str | None = None, *, root: Path | None = None) -> list[dict[str, Any]]:
    """기록된 피드백 목록 (state로 필터)."""
    raw_dir = artifacts_dir(root) / "feedback" / "raw"
    if not raw_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for mf in sorted(raw_dir.glob("*/manifest.json")):
        try:
            m = json.loads(mf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if state is None or m.get("state") == state:
            out.append(m)
    return out
