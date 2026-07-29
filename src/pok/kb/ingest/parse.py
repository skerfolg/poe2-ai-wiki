"""② parse — poe2db 상세 HTML → 중간 레코드 (가공 최소, KB_INGEST §2).

파서는 소스 취약성의 격리벽: poe2db HTML이 바뀌면 이 파일만 고친다.
`From`(획득) 카드는 구현 판정 게이트(KI-8)의 신호 A라 필수 추출 대상이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag


@dataclass
class DetailPage:
    """poe2db 상세 페이지 1장의 파싱 결과 (us 기준; kr은 name만 씀)."""

    name: str
    description: str | None = None
    type_line: str | None = None
    tags: list[str] = field(default_factory=list)
    tier: int | None = None
    acquisition: list[str] = field(default_factory=list)  # From 카드 항목들 (신호 A)
    acquisition_count: int | None = None  # "From /N" 헤더의 N
    has_level_effect: bool = False


def _title_name(soup: BeautifulSoup) -> str:
    t = soup.title.get_text() if soup.title else ""
    return t.split(" - PoE2DB")[0].strip()


def parse_detail(html: str) -> DetailPage:
    soup = BeautifulSoup(html, "html.parser")
    page = DetailPage(name=_title_name(soup))

    og = soup.find("meta", property="og:description")
    if isinstance(og, Tag) and og.get("content"):
        page.description = str(og["content"]).strip()

    tl = soup.select_one(".typeLine")
    if tl is not None:
        page.type_line = tl.get_text(strip=True)

    stats = soup.select_one(".Stats")
    if stats is not None:
        text = stats.get_text(" ", strip=True)
        m = re.search(r"Tier:\s*(\d+)", text)
        if m:
            page.tier = int(m.group(1))
        tags_part = text.split("Tier:")[0]
        page.tags = [t.strip() for t in tags_part.split(",") if t.strip()]

    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None:
            continue
        htext = header.get_text(strip=True)
        if htext.startswith("From"):
            m = re.search(r"From\s*/\s*(\d+)", htext)
            page.acquisition_count = int(m.group(1)) if m else 0
            page.acquisition = [
                a.get_text(strip=True) for a in card.find_all("a") if a.get_text(strip=True)
            ]
        elif htext.startswith("Level Effect"):
            page.has_level_effect = True
    return page


def parse_name_only(html: str) -> str:
    """kr 페이지에서 한국어 이름만 추출."""
    return _title_name(BeautifulSoup(html, "html.parser"))


def pob_gems_by_name(gems: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """PoB gems.json → 소문자 이름 → 젬 데이터 (신호 P 조회용)."""
    out: dict[str, dict[str, Any]] = {}
    for meta_id, gem in gems.items():
        name = str(gem.get("name", "")).strip()
        if name:
            out.setdefault(name.lower(), {**gem, "_meta_id": meta_id})
    return out
