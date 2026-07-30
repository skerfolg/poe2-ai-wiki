"""에센스 목록 수집·교차 검증 (KB_INGEST §6-2 ④ 보강).

PoB `Essence.lua`는 "에센스 → 부여 모드 키" 매핑을 갖지만 **현재 패치에 실존하는지**는
말해주지 않는다(KI-8: 소스에 존재 ≠ 게임에 구현). poe2db `Essence` 페이지가 카탈로그
권위(D8)이므로 여기서 실존 목록을 받아 PoB와 대사한다.

이 대사가 필요한 이유(사용자 지적, 2026-07-29): 스폰 가중치가 0인 모드 상당수는
"죽은 모드"가 아니라 **에센스로 고정 부여되는 모드**일 수 있다. PoB 가중치만으로
획득 가능성을 판정하면 실존 모드를 KB에서 지운다.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from pok.kb.ingest.sources import USER_AGENT
from pok.kb.ingest.verify import SourceEntity, cross_source, verification_block

PAGE_URL = "https://poe2db.tw/{lang}/Essence"
LANGS = ("us", "kr")

# 목록 카드 헤더: "Essence /95" · kr은 "에센스 /95"
_LIST_HEADER = re.compile(r"^(?:Essence|에센스)\s*/\s*(\d+)")
# 등급 접두 — 같은 계열의 Lesser/Greater 판을 한 계열로 묶는 축
_TIER_PREFIX = (("Lesser ", "lesser"), ("Greater ", "greater"))


def fetch_pages(raw_dir: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """Essence 페이지(us/kr)를 원시로 저장한다 (멱등)."""
    out = raw_dir / "essences"
    out.mkdir(parents=True, exist_ok=True)
    own = client is None
    c = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    )
    saved: dict[str, Any] = {}
    try:
        for lang in LANGS:
            dst = out / f"{lang}.html"
            if dst.exists():
                saved[lang] = "skipped"
                continue
            r = c.get(PAGE_URL.format(lang=lang))
            r.raise_for_status()
            dst.write_bytes(r.content)
            saved[lang] = len(r.content)
            time.sleep(1.0)  # 정중함 정책
    finally:
        if own:
            c.close()
    return saved


def _tier_and_family(name: str) -> tuple[str, str]:
    """'Greater Essence of the Body' → ('greater', 'Essence of the Body')."""
    for prefix, tier in _TIER_PREFIX:
        if name.startswith(prefix):
            return tier, name[len(prefix) :]
    return "normal", name


def parse_page(html: str) -> list[dict[str, Any]]:
    """Essence 목록 카드 → [{name, tier, family, effect_lines}] (현재 패치 실존분)."""
    soup = BeautifulSoup(html, "html.parser")
    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None or not _LIST_HEADER.match(header.get_text(" ", strip=True)):
            continue
        row = card.select_one("div.row")
        if row is None:
            continue
        out: list[dict[str, Any]] = []
        for col in row.find_all("div", recursive=False):
            if not isinstance(col, Tag):
                continue
            lines = [x for x in col.get_text("\n", strip=True).split("\n") if x.strip()]
            if not lines:
                continue
            name = lines[0]
            tier, family = _tier_and_family(name)
            out.append(
                {
                    "name": name,
                    "tier": tier,
                    "family": family,
                    "effect_lines": lines[1:],
                }
            )
        return out
    return []


def process(raw_dir: Path, out_dir: Path) -> dict[str, Any]:
    """poe2db 실존 목록과 PoB Essence.lua를 대사한다 (⑥). 네트워크 없음."""
    src = raw_dir / "essences"
    us = parse_page((src / "us.html").read_text(encoding="utf-8"))
    kr = parse_page((src / "kr.html").read_text(encoding="utf-8"))
    pob_raw = json.loads((raw_dir / "pob" / "essence.json").read_text(encoding="utf-8"))

    # 한국어: 같은 카드·같은 순서로 위치 대응 (개수 일치 시에만)
    aligned = len(us) == len(kr)
    items: list[dict[str, Any]] = []
    for idx, e in enumerate(us):
        item = dict(e)
        item["name_ko"] = kr[idx]["name"] if aligned else None
        items.append(item)

    pob_entities = [
        SourceEntity(key=str(v.get("name", k)), name=str(v.get("name", k)))
        for k, v in sorted(pob_raw.items())
    ]
    page_entities = [SourceEntity(key=e["name"], name=e["name"]) for e in items]
    cross = cross_source(page_entities, pob_entities, labels=("poe2db", "pob"))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "essences.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    report: dict[str, Any] = {
        "page_items": len(us),
        "kr_items": len(kr),
        "kr_aligned": aligned,
        "pob_items": len(pob_raw),
        "by_tier": {
            t: sum(1 for e in items if e["tier"] == t) for t in ("normal", "lesser", "greater")
        },
        "verification": verification_block(cross=[cross]),
    }
    (src / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def live_essence_names(raw_dir: Path) -> set[str]:
    """현재 패치에 실존하는 에센스 이름 (PoB 매핑을 걸러내는 필터)."""
    src = raw_dir / "essences" / "us.html"
    if not src.exists():
        return set()
    return {e["name"] for e in parse_page(src.read_text(encoding="utf-8"))}
