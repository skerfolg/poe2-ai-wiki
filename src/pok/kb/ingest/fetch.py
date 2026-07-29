"""정중한 fetcher — 멱등·체크포인트·레이트리밋 (KI-4, KI-7).

- 체크포인트(fetch-status.poe2db.json)는 원시와 같은 디렉터리 = 데이터 repo의 일부
  → 어느 PC든 pull 후 pending/failed만 이어서 수집.
- 같은 명령 재실행은 무해(멱등). 실패는 기록하고 계속 — 중단시키지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from pok.kb.ingest.sources import DEFAULT_RATE_SECONDS, POE2DB_BASE, USER_AGENT

_STATUS_SAVE_EVERY = 10


@dataclass
class FetchSummary:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    remaining: int = 0


def _status_path(raw_dir: Path) -> Path:
    return raw_dir / "fetch-status.poe2db.json"


def load_status(raw_dir: Path) -> dict[str, Any]:
    p = _status_path(raw_dir)
    if p.exists():
        data: dict[str, Any] = json.loads(p.read_text(encoding="utf-8"))
        return data
    return {}


def save_status(raw_dir: Path, status: dict[str, Any]) -> None:
    p = _status_path(raw_dir)
    p.write_text(json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def iter_plan_items(plan: dict[str, Any]) -> list[tuple[str, str]]:
    """plan → (lang, name) 전체 목록 (결정적 순서)."""
    out: list[tuple[str, str]] = []
    for lang in plan["langs"]:
        for cat in plan["categories"].values():
            out.extend((lang, name) for name in cat["items"])
    # 카테고리 간 중복 이름 제거 (같은 페이지)
    seen: set[tuple[str, str]] = set()
    uniq = [x for x in out if not (x in seen or seen.add(x))]  # type: ignore[func-returns-value]
    return uniq


def run_fetch(
    plan: dict[str, Any],
    raw_dir: Path,
    rate_seconds: float = DEFAULT_RATE_SECONDS,
    limit: int | None = None,
    langs: list[str] | None = None,
    client: httpx.Client | None = None,
) -> FetchSummary:
    """plan의 항목을 수집한다. fetched 항목은 스킵(멱등), 실패는 기록 후 계속."""
    status = load_status(raw_dir)
    summary = FetchSummary()
    own_client = client is None
    c = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    )
    dirty = 0
    try:
        items = [
            (lang, name) for lang, name in iter_plan_items(plan) if langs is None or lang in langs
        ]
        for lang, name in items:
            key = f"{lang}/{name}"
            out_path = raw_dir / "poe2db" / lang / f"{name}.html"
            st = status.get(key, {})
            if st.get("state") == "fetched" and out_path.exists():
                summary.skipped += 1
                continue
            if limit is not None and summary.fetched + summary.failed >= limit:
                summary.remaining += 1
                continue

            try:
                r = c.get(f"{POE2DB_BASE}/{lang}/{name}")
                r.raise_for_status()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_bytes(r.content)
                status[key] = {
                    "state": "fetched",
                    "sha256": hashlib.sha256(r.content).hexdigest(),
                    "bytes": len(r.content),
                }
                summary.fetched += 1
            except httpx.HTTPError as e:
                status[key] = {"state": "failed", "error": f"{type(e).__name__}: {e}"}
                summary.failed += 1

            dirty += 1
            if dirty >= _STATUS_SAVE_EVERY:
                save_status(raw_dir, status)
                dirty = 0
            if rate_seconds > 0:
                time.sleep(rate_seconds)
    finally:
        save_status(raw_dir, status)
        if own_client:
            c.close()
    return summary


def status_report(plan: dict[str, Any], raw_dir: Path) -> dict[str, int]:
    """계획 대비 진행 요약 (완전성 기준 ①의 실시간 뷰)."""
    status = load_status(raw_dir)
    counts = {"planned": 0, "fetched": 0, "failed": 0, "pending": 0}
    for lang, name in iter_plan_items(plan):
        counts["planned"] += 1
        st = status.get(f"{lang}/{name}", {}).get("state")
        if st == "fetched":
            counts["fetched"] += 1
        elif st == "failed":
            counts["failed"] += 1
        else:
            counts["pending"] += 1
    return counts
