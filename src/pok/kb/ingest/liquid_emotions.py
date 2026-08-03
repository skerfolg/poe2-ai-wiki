"""성유(액체 감정) 부여 정보 수집·반영 (KB_INGEST §6-2 ② 보강).

패시브 노드의 **획득 방법**은 트리 데이터에 없다 — poe2db의 Liquid_Emotions 페이지가
유일한 출처다(PoB의 LiquidEmotions.lua는 주얼용 감정 화폐 목록이라 다름).

부여 조건이 없으면 생성기가 "이 노드를 쓰자"고 결정해도 실현 가능성·비용을 판단할 수
없다 — 조건 1급 필드 원칙(RC1: 불가능한 조건의 발동 가정 금지)의 적용 지점.

카드 2종:
  Liquid Emotions Passives      — 성유로 부여 가능한 일반 노드 (0.5.4b: 875)
  Liquid Emotions Only Passives — 성유로만 얻는 전용 노드 (0.5.4b: 17)
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from pok.kb.ingest.sources import USER_AGENT
from pok.kb.store import write_shard

PAGE_URL = "https://poe2db.tw/{lang}/Liquid_Emotions"
LANGS = ("us", "kr")

# (카드 헤더 접두, 획득 분류)
_CARDS = (
    ("Liquid Emotions Only Passives", "liquid-emotion-only"),
    ("Liquid Emotions Passives", "liquid-emotion"),
)
_KR_CARDS = (
    ("액체 감정 Only Passives", "liquid-emotion-only"),
    ("액체 감정 Passives", "liquid-emotion"),
)


def fetch_pages(raw_dir: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """Liquid_Emotions 페이지(us/kr)를 원시로 저장한다 (멱등)."""
    out = raw_dir / "liquid-emotions"
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


def _cards(soup: BeautifulSoup, specs: tuple[tuple[str, str], ...]) -> list[tuple[Tag, str]]:
    found: list[tuple[Tag, str]] = []
    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None:
            continue
        text = header.get_text(" ", strip=True)
        for prefix, kind in specs:
            if text.startswith(prefix):
                found.append((card, kind))
                break
    return found


def parse_page(html: str, kr: bool = False) -> dict[str, dict[str, Any]]:
    """페이지 → {노드 영문명: {emotions, acquisition}}.

    각 항목 텍스트: 이름 / "Liquid Emotions" / 감정 3개 / 효과…
    """
    soup = BeautifulSoup(html, "html.parser")
    marker = "액체 감정" if kr else "Liquid Emotions"
    out: dict[str, dict[str, Any]] = {}
    for card, kind in _cards(soup, _KR_CARDS if kr else _CARDS):
        row = card.select_one("div.row")
        if row is None:
            continue
        for col in row.find_all("div", recursive=False):
            if not isinstance(col, Tag):
                continue
            lines = [
                line
                for line in col.get_text("\n", strip=True).split("\n")
                if line not in (",", ":")
            ]
            if len(lines) < 5 or marker not in lines:
                continue
            idx = lines.index(marker)
            emotions = lines[idx + 1 : idx + 4]
            if len(emotions) != 3:
                continue
            out[lines[0]] = {"emotions": emotions, "acquisition": kind}
    return out


def apply_to_kb(raw_dir: Path, knowledge: Path) -> dict[str, Any]:
    """트리 NDJSON 샤드의 해당 레코드에 부여 정보를 반영한다 (이름 기준, 멱등)."""
    src = raw_dir / "liquid-emotions"
    us = parse_page((src / "us.html").read_text(encoding="utf-8"))
    kr = parse_page((src / "kr.html").read_text(encoding="utf-8"), kr=True)

    shards = sorted((knowledge / "game-data" / "tree").glob("*.ndjson"))
    records = [
        json.loads(line)
        for shard in shards
        for line in shard.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # 감정명 en→ko 매핑: KB의 노드 ko/en 이름 쌍으로 두 페이지를 이어 붙인다
    # (페이지 항목 수가 언어별로 다를 수 있어 순서 대응은 쓰지 않는다)
    ko_to_en_node = {str(r["name"]["ko"]).strip(): str(r["name"]["en"]).strip() for r in records}
    emotion_ko: dict[str, str] = {}
    for ko_name, ko_info in kr.items():
        en_name = ko_to_en_node.get(ko_name.strip())
        us_info = us.get(en_name) if en_name else None
        if us_info and len(us_info["emotions"]) == len(ko_info["emotions"]):
            for en_e, ko_e in zip(us_info["emotions"], ko_info["emotions"], strict=True):
                emotion_ko.setdefault(en_e, ko_e)

    updated = 0
    matched_names: set[str] = set()
    idx = 0
    for shard in shards:
        lines_out: list[dict[str, Any]] = []
        for _ in range(
            sum(1 for line in shard.read_text(encoding="utf-8").splitlines() if line.strip())
        ):
            rec = records[idx]
            idx += 1
            name_en = str(rec["name"]["en"]).strip()
            info = us.get(name_en)
            if info is not None:
                rec["data"]["acquisition"] = info["acquisition"]
                rec["data"]["liquid_emotions"] = info["emotions"]
                ko_emotions = [emotion_ko.get(e, e) for e in info["emotions"]]
                if any(k != e for k, e in zip(ko_emotions, info["emotions"], strict=True)):
                    rec["data"]["liquid_emotions_ko"] = ko_emotions
                updated += 1
                matched_names.add(name_en)
            lines_out.append(rec)
        # 쓰기는 store 단일 경로로 (B-6)
        write_shard(shard, lines_out, root=knowledge.parent, validate=False)

    return {
        "page_entries": len(us),
        "kb_records_updated": updated,
        "distinct_names_matched": len(matched_names),
        "emotion_names_mapped": len(emotion_ko),
        "unmatched_names": sorted(set(us) - matched_names)[:20],
        "unmatched_count": len(set(us) - matched_names),
    }
