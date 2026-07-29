"""fetch-plan 생성 — 계획 주도 수집의 1단계 (KI-4, 완전성 기준 ①·③).

목록 페이지를 먼저 확정해 '전체 항목 목록'과 '표시 개수'를 기록한다.
목록 원시 HTML도 증거로 저장한다 (개수 불변량의 물증).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from pok.kb.ingest.sources import CATEGORIES, POE2DB_BASE, USER_AGENT, Category


def extract_items(listing_html: str) -> list[str]:
    """목록 HTML → 상세 페이지 이름 목록.

    시그널: 테이블 내부 + data-hover 속성을 가진 /us/ 앵커 (정찰로 확정한 패턴).
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    names: set[str] = set()
    for table in soup.find_all("table"):
        if not isinstance(table, Tag):
            continue
        for a in table.find_all("a", href=True):
            if not isinstance(a, Tag):
                continue
            href = str(a["href"])
            if href.startswith("/us/") and "#" not in href and a.get("data-hover"):
                names.add(href.removeprefix("/us/"))
    return sorted(names)


def extract_listed_count(listing_html: str, count_prefix: str) -> int | None:
    """헤더의 'Skill Gems /427' 표기에서 개수를 추출 (기준 ③ 근거)."""
    m = re.search(re.escape(count_prefix) + r"\s*/\s*(\d+)", listing_html)
    return int(m.group(1)) if m else None


def build_plan(
    patch: str,
    raw_dir: Path,
    category_keys: list[str] | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """목록 페이지를 수집해 fetch-plan.json을 만든다. 이미 있으면 그대로 반환(확정 불변)."""
    plan_path = raw_dir / "fetch-plan.json"
    if plan_path.exists():
        loaded: dict[str, Any] = json.loads(plan_path.read_text(encoding="utf-8"))
        return loaded

    cats: list[Category] = [CATEGORIES[k] for k in (category_keys or list(CATEGORIES))]
    own_client = client is None
    c = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    )
    try:
        categories: dict[str, Any] = {}
        for cat in cats:
            r = c.get(POE2DB_BASE + cat.listing_path)
            r.raise_for_status()
            # 목록 원시 저장 (증거)
            evidence = raw_dir / "poe2db" / "us" / f"_listing_{cat.key}.html"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(r.content)

            items = extract_items(r.text)
            categories[cat.key] = {
                "listing_url": POE2DB_BASE + cat.listing_path,
                "listed_count": extract_listed_count(r.text, cat.count_prefix),
                "planned_count": len(items),
                "items": items,
            }
    finally:
        if own_client:
            c.close()

    plan: dict[str, Any] = {
        "patch": patch,
        "source": "poe2db",
        "langs": ["us", "kr"],
        "categories": categories,
    }
    raw_dir.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan
