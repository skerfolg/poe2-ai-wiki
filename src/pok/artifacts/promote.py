"""승격 — 큐레이션 승인분만 정본(`knowledge/insights/`)에 기록 (PROJECT_STRUCTURE §6).

"학습이 KB를 직접 수정하지 않는다"(BLUEPRINT §7)를 물리적으로 보장하는 지점:
- 입력은 **승인된 주장만** — pending·rejected는 통과 못 한다.
- 산출물엔 검증 라벨과 `verified_by`(승인 주체·근거)가 반드시 박힌다.
- 계보(피드백 id·원문 해시)를 front-matter에 남겨 원문으로 되짚을 수 있게 한다.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir, knowledge_dir


def _front_matter(fields: dict[str, Any]) -> str:
    lines = [f"{k}: {v}" for k, v in fields.items() if v not in (None, "")]
    return "---\n" + "\n".join(lines) + "\n---\n"


def promote_insight(
    feedback_id: str,
    slug: str,
    title: str,
    body: str,
    *,
    label: str,
    verified_by: str,
    target_id: str | None = None,
    patch: str,
    root: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """승인분을 `knowledge/insights/<slug>.md`로 기록한다.

    body는 호출자가 승인된 주장들로 구성한 본문 — 이 함수는 계보·라벨을 박고
    파일로 떨어뜨리는 일만 한다(내용 판단 없음, AD-3).
    """
    if not verified_by.strip():
        raise ValueError("verified_by 없음 — 승격에는 검증 주체 기록이 필수다")
    raw_manifest = artifacts_dir(root) / "feedback" / "raw" / feedback_id / "manifest.json"
    if not raw_manifest.exists():
        raise FileNotFoundError(f"피드백 원문 없음: {feedback_id} — 계보 없는 승격 금지")
    meta = json.loads(raw_manifest.read_text(encoding="utf-8"))
    stamp = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
    front = _front_matter(
        {
            "id": target_id or f"insight.{slug}",
            "label": label,
            "verified_by": verified_by,
            "lang": "ko",
            "source": "feedback",
            "source_title": meta.get("title", ""),
            "source_revid": str(meta.get("content_sha256", ""))[:8],
            "source_timestamp": stamp,
            "feedback_id": feedback_id,
            "patch": patch,
        }
    )
    out = knowledge_dir(root) / "insights" / f"{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{front}\n# {title}\n\n{body.strip()}\n", encoding="utf-8")
    meta["state"] = "promoted"
    meta.setdefault("promoted", []).append({"slug": slug, "at": stamp})
    raw_manifest.write_text(
        json.dumps(meta, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    return out
