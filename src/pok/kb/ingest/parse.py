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
    # 코스트·점유 전수 (사용자 지시 2026-08-02 — 정신력 지출 장부의 원천)
    costs: list[dict[str, Any]] = field(default_factory=list)  # Cost: {resource,min,max[,pct]}
    reservation: list[dict[str, Any]] = field(default_factory=list)  # Reservation:
    additional_reservation: list[dict[str, Any]] = field(default_factory=list)  # 보조 젬
    cost_multiplier_pct: float | None = None  # 보조 젬 Cost Multiplier: 115%
    cast_time_s: float | None = None


def _title_name(soup: BeautifulSoup) -> str:
    t = soup.title.get_text() if soup.title else ""
    return t.split(" - PoE2DB")[0].strip()


# 태그 토큰: 짧은 단어(구) — 숫자·콜론·긴 서술문 배제
_TAG_TOKEN = re.compile(r"^[A-Za-z][A-Za-z' ]{0,24}$")


def _extract_tags(stats_text: str) -> list[str]:
    """`.Stats` 선두의 태그 나열만 추출.

    페이지 유형별 종결자: 스킬 젬 = 'Tier:' / 서포트 젬 = 'Category :'.
    종결자 이전 구간을 쉼표로 나눠 **태그 형태 토큰만** 접두 스캔으로 취한다
    (첫 비태그 토큰에서 중단 — 설명문 유입 차단, 0.5.4b 763건 오염 실증 후 강화).
    """
    head = re.split(r"Tier:|Category\s*:", stats_text)[0]
    tags: list[str] = []
    for token in head.split(","):
        token = token.strip()
        if not token or not _TAG_TOKEN.match(token) or len(token.split()) > 3:
            break
        tags.append(token)
    return tags


# ── 코스트·점유 파싱 (Stats 텍스트) ──────────────────────────────────
# 값 형태: "30" | "(3 — 37)" (+선택 "%"), 자원: Mana·Life·Spirit·Energy Shield·Rage
_COST_VALUE = re.compile(
    r"\(?\s*(\d+(?:\.\d+)?)(?:\s*—\s*(\d+(?:\.\d+)?)\s*\))?\s*(%)?\s*"
    r"(Mana|Life|Spirit|Energy Shield|Rage)"
)
# 세그먼트 종결자: 다음 라벨/속성 시작 (Stats 텍스트는 라벨 나열이라 접두 구간만 취한다)
_SEG_END = (
    r"(?=Additional Reservation:|Reservation:|Cost Multiplier:|Cost:|Cast Time:|"
    r"Attack Time:|Critical|Projectile|Cooldown|Radius|Requires:|Support Requirements|"
    r"Tier:|Level:|$)"
)


def _cost_values(segment: str) -> list[dict[str, Any]]:
    out = []
    for m in _COST_VALUE.finditer(segment):
        lo = float(m.group(1))
        hi = float(m.group(2)) if m.group(2) else lo
        value: dict[str, Any] = {"resource": m.group(4), "min": lo, "max": hi}
        if m.group(3):
            value["pct"] = True
        out.append(value)
    return out


def _segment(text: str, label: str) -> str:
    m = re.search(re.escape(label) + r"\s*(.*?)" + _SEG_END, text, re.S)
    return m.group(1) if m else ""


def parse_stats_costs(stats_text: str) -> dict[str, Any]:
    """Stats 텍스트 → 코스트·점유·시전시간 (없는 항목은 빈 값).

    "Additional Reservation:"(보조 젬의 추가 점유)이 "Reservation:"을 포함하므로
    일반 점유는 'Additional ' 접두가 없는 위치만 매칭한다.
    """
    plain_reservation = ""
    m = re.search(r"(?<!Additional )Reservation:\s*(.*?)" + _SEG_END, stats_text, re.S)
    if m:
        plain_reservation = m.group(1)
    mult = re.search(r"Cost Multiplier:\s*(\d+(?:\.\d+)?)\s*%", stats_text)
    cast = re.search(r"Cast Time:\s*(\d+(?:\.\d+)?)\s*sec", stats_text)
    return {
        "costs": _cost_values(_segment(stats_text, "Cost:")),
        "reservation": _cost_values(plain_reservation),
        "additional_reservation": _cost_values(_segment(stats_text, "Additional Reservation:")),
        "cost_multiplier_pct": float(mult.group(1)) if mult else None,
        "cast_time_s": float(cast.group(1)) if cast else None,
    }


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
        page.tags = _extract_tags(text)
        for key, value in parse_stats_costs(text).items():
            setattr(page, key, value)

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
