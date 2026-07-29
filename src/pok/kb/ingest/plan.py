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


def extract_items(listing_html: str, extractor: str = "tables") -> list[str]:
    """목록 HTML → 상세 페이지 이름 목록.

    시그널: (tables=테이블 | cards=카드) 내부 + data-hover 속성의 /us/ 앵커.
    """
    soup = BeautifulSoup(listing_html, "html.parser")
    containers = soup.find_all("table") if extractor == "tables" else soup.select("div.card")
    names: set[str] = set()
    for box in containers:
        if not isinstance(box, Tag):
            continue
        for a in box.find_all("a", href=True):
            if not isinstance(a, Tag):
                continue
            href = str(a["href"])
            if (
                href.startswith("/us/")
                and "#" not in href
                and "?" not in href
                and a.get("data-hover")
            ):
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

            items = extract_items(r.text, cat.extractor)
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


def extend_plan(
    raw_dir: Path,
    category_keys: list[str],
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """확정된 plan에 **새 카테고리를 append**한다 (기존 카테고리는 불변).

    계획 확장은 append-only — 완전성 기준 ①의 분모가 커지는 방향만 허용된다.
    """
    plan_path = raw_dir / "fetch-plan.json"
    plan: dict[str, Any] = json.loads(plan_path.read_text(encoding="utf-8"))
    new_keys = [k for k in category_keys if k not in plan["categories"]]
    if not new_keys:
        return plan

    own_client = client is None
    c = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    )
    try:
        for key in new_keys:
            cat = CATEGORIES[key]
            r = c.get(POE2DB_BASE + cat.listing_path)
            r.raise_for_status()
            evidence = raw_dir / "poe2db" / "us" / f"_listing_{cat.key}.html"
            evidence.parent.mkdir(parents=True, exist_ok=True)
            evidence.write_bytes(r.content)
            items = extract_items(r.text, cat.extractor)
            plan["categories"][key] = {
                "listing_url": POE2DB_BASE + cat.listing_path,
                "listed_count": extract_listed_count(r.text, cat.count_prefix),
                "planned_count": len(items),
                "items": items,
            }
    finally:
        if own_client:
            c.close()
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return plan
