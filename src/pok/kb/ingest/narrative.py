"""⑤ 서술 트랙 — poe2wiki 원문 수집 (KB_INGEST §2 ⑧, KI-2).

수집만 코드가 한다(KI-7). 재작성은 사람+에이전트 공동 작업이라 벌크 자동화하지
않으며, 산출물은 `knowledge/wiki/<type>/<slug>.md` (front-matter로 KB id 연결,
기본 라벨 UNVERIFIED — 신뢰는 라벨 체계가 관리, 스팟체크로 승격).

소스 도메인 정정: 문서에 poewiki.net으로 적혀 있었으나 그것은 PoE1 위키다 —
PoE2 서술은 **poe2wiki.net** (실측 2026-07-30: 큐레이션 35종 전부 존재,
poewiki.net의 동명 페이지는 PoE1 스킬). MediaWiki API + revid 기록 = 증거 체인.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx

from pok.kb.ingest.merge import slug_to_id_part
from pok.kb.ingest.sources import USER_AGENT

API = "https://www.poe2wiki.net/w/api.php"

# 대상 = 큐레이션 엔티티 (개별 JSON 파일)만. 벌크(NDJSON)는 서술 없음 (KI-7 §6-1).
_TYPE_DIR = {
    "Skill": "skills",
    "Support": "supports",
    "Passive": "passives",
    "Defence": "defences",
    "Resource": "resources",
    "Item": "items",
}


def curated_targets(knowledge: Path) -> list[dict[str, str]]:
    """큐레이션 엔티티 목록 → [{id, name_en, type}] (개별 JSON = 큐레이션의 정의)."""
    from pok.kb.store import load as store_load

    kb = store_load(knowledge.parent)
    out = [
        {"id": r.id, "name_en": r.name_en, "type": r.type}
        for r in kb.records.values()
        if r.path.suffix == ".json"
    ]
    return sorted(out, key=lambda x: x["id"])


def fetch_narratives(
    raw_dir: Path,
    targets: list[dict[str, str]],
    client: httpx.Client | None = None,
    rate_seconds: float = 1.0,
) -> dict[str, Any]:
    """poe2wiki 원문(wikitext)을 데이터 repo에 저장한다 (멱등·revid 기록).

    한 요청에 50제목까지 배치 — 정중함 정책과 양립.
    """
    out = raw_dir / "narrative" / "poe2wiki"
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = raw_dir / "narrative" / "manifest.json"
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )

    todo = [t for t in targets if t["id"] not in manifest]
    own = client is None
    c = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    )
    fetched, missing = 0, []
    try:
        for i in range(0, len(todo), 50):
            batch = todo[i : i + 50]
            r = c.get(
                API,
                params={
                    "action": "query",
                    "titles": "|".join(t["name_en"] for t in batch),
                    "prop": "revisions",
                    "rvprop": "content|timestamp|ids",
                    "rvslots": "main",
                    "format": "json",
                },
            )
            r.raise_for_status()
            data = r.json()["query"]
            norm = {x["from"]: x["to"] for x in data.get("normalized", [])}
            by_title = {p.get("title"): p for p in data["pages"].values()}
            for t in batch:
                page = by_title.get(norm.get(t["name_en"], t["name_en"]))
                if page is None or "missing" in page or not page.get("revisions"):
                    missing.append(t["id"])
                    continue
                rev = page["revisions"][0]
                slug = slug_to_id_part(t["name_en"])
                (out / f"{slug}.wikitext").write_text(
                    str(rev["slots"]["main"]["*"]), encoding="utf-8"
                )
                manifest[t["id"]] = {
                    "title": page["title"],
                    "file": f"poe2wiki/{slug}.wikitext",
                    "revid": rev.get("revid"),
                    "timestamp": rev.get("timestamp"),
                }
                fetched += 1
            if rate_seconds > 0 and i + 50 < len(todo):
                time.sleep(rate_seconds)
    finally:
        if own:
            c.close()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {
        "targets": len(targets),
        "fetched_now": fetched,
        "cached": len(targets) - fetched - len(missing),
        "missing": missing,  # ⑧식: 서술 원료가 없는 큐레이션 엔티티
    }


# ── 재작성 산출물 검증 (코드 게이트 — KI-7 장치 ②·④) ─────────────

_FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)
_REQUIRED_KEYS = (
    "id",
    "label",
    "lang",
    "source_revid",
)  # lang: 다국어 대비 (사용자 승인 2026-07-30)


def check_wiki_docs(knowledge: Path) -> dict[str, Any]:
    """knowledge/wiki/ 산출물 검증: front-matter 필수 키 + KB id 실존 + 라벨 어휘.

    재작성 품질(환각·모순)은 스팟체크(사람/상위 모델)의 몫 — 여기는 기계 게이트만.
    """
    from pok.kb.store import load as store_load

    kb = store_load(knowledge.parent)
    labels = {"UNVERIFIED", "SUPPORTED_INFERENCE", "IN_GAME", "GAME_DATA", "CONFIRMED_OFFICIAL"}
    errors: list[str] = []
    checked = 0
    for md in sorted((knowledge / "wiki").rglob("*.md")):
        checked += 1
        rel = md.relative_to(knowledge)
        m = _FRONT.match(md.read_text(encoding="utf-8"))
        if m is None:
            errors.append(f"{rel}: front-matter 없음")
            continue
        meta: dict[str, str] = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip().strip('"')
        for key in _REQUIRED_KEYS:
            if not meta.get(key):
                errors.append(f"{rel}: front-matter '{key}' 누락")
        rid = meta.get("id", "")
        if rid and rid not in kb.records:
            errors.append(f"{rel}: id '{rid}' 가 KB에 없음")
        if meta.get("label") and meta["label"] not in labels:
            errors.append(f"{rel}: label '{meta['label']}' 어휘 밖")
        # 승격 근거 강제: UNVERIFIED 초과 라벨은 검증 주체 기록이 있어야 한다
        # (스팟체크=모델/사람, 인게임 확인=사용자 — 근거 없는 승격은 게이트가 거부)
        if meta.get("label") and meta["label"] != "UNVERIFIED" and not meta.get("verified_by"):
            errors.append(f"{rel}: label {meta['label']} 인데 verified_by 없음")
    return {"checked": checked, "errors": errors}
