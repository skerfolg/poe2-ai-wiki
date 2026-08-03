"""화폐 아이템 수집·정형화 (§6-2 ⑥ 중 제작 화폐 — ④로 앞당김, 사용자 승인 2026-07-30).

배경: 모드 획득 경로가 `essence:Essence of Woe` 같은 문자열로 화폐를 가리키는데
정작 화폐 레코드가 KB에 없었다(사용자 지적). 제작 화폐는 제작규칙(RC4)과 한 몸이라
카탈로그 권위(poe2db)의 Stackable_Currency 페이지에서 수록한다.

us/kr 조인 축 = 카드 앵커의 href(영문 슬러그, 언어 공통) — 베이스 아이템 ko 부착과
동일한 방식(data-hover는 kr에서 CDN 해시라 불가).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from pok.kb.ingest.merge import slug_to_id_part
from pok.kb.ingest.verify import (
    SourceEntity,
    cross_source,
    substance_floor,
    verification_block,
)

# (us 헤더 접두, kr 헤더 접두, 분류)
_CARDS = (
    ("Stackable Currency Item /", "중첩 가능 화폐 아이템 /", "stackable"),
    ("Essence /", "에센스 /", "essence"),
    ("Splinter Item /", "Splinter 아이템 /", "splinter"),
    ("Catalyst Item /", "Catalyst 아이템 /", "catalyst"),
)

_STACK = re.compile(r"^\d+\s*/\s*\d+$")
_WS = re.compile(r"\s+")


def parse_page(html: str, kr: bool = False) -> dict[str, dict[str, Any]]:
    """Stackable_Currency 페이지 → {href 슬러그: {name, category, stack_size, effect}}."""
    soup = BeautifulSoup(html, "html.parser")
    marker = "중첩 개수:" if kr else "Stack Size:"
    out: dict[str, dict[str, Any]] = {}
    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None:
            continue
        htext = header.get_text(" ", strip=True)
        category = next(
            (c for us_p, kr_p, c in _CARDS if htext.startswith(kr_p if kr else us_p)), None
        )
        if category is None:
            continue
        for col in card.select(".row > .col"):
            a = col.select_one("a.item_currency[href]")
            if a is None:
                a = col.select_one("a[href]")
            if not isinstance(a, Tag):
                continue
            href = str(a["href"])
            lines = [x for x in col.get_text("\n", strip=True).split("\n") if x.strip()]
            if not lines:
                continue
            name = lines[0]
            stack = None
            effect_parts: list[str] = []
            i = 1
            while i < len(lines):
                if lines[i] == marker and i + 1 < len(lines) and _STACK.match(lines[i + 1]):
                    stack = int(lines[i + 1].split("/")[1].strip())
                    i += 2
                    continue
                effect_parts.append(lines[i])
                i += 1
            # poe2db가 텍스트를 키워드 링크 단위로 쪼개 놓는다 → 공백으로 복원
            effect = _WS.sub(" ", " ".join(effect_parts)).strip()
            out.setdefault(
                href,
                {
                    "name": name,
                    "category": category,
                    "stack_size": stack,
                    "effect": effect,
                },
            )
    return out


def to_record(
    href: str, us: dict[str, Any], ko: dict[str, Any] | None, patch: str
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "rarity": "currency",
        "currency_category": us["category"],
    }
    if us.get("stack_size"):
        data["stack_size"] = us["stack_size"]
    if us.get("effect"):
        data["effect"] = us["effect"]
    if ko and ko.get("effect"):
        data["effect_ko"] = ko["effect"]
    return {
        "id": f"item.{slug_to_id_part(href)}",
        "type": "Item",
        "name": {"ko": (ko or {}).get("name") or us["name"], "en": us["name"]},
        "tags": [],
        "data": data,
        "verification": "SUPPORTED_INFERENCE",  # poe2db 단독 소스 (유니크 관행과 동일)
        "sources": [
            {
                "src": "poe2db",
                "ref": f"https://poe2db.tw/us/{href}",
                "patch": patch,
            }
        ],
    }


def process_and_merge(raw_dir: Path, knowledge: Path, patch: str) -> dict[str, Any]:
    """파싱 → ⑥⑦ 검증 → knowledge/game-data/currency/ 기록 → 전량 재검증."""
    from pok.kb.store import load as store_load
    from pok.kb.store import write_shard

    src = raw_dir / "currency"
    us = parse_page((src / "stackable.us.html").read_text(encoding="utf-8"))
    kr = parse_page((src / "stackable.kr.html").read_text(encoding="utf-8"), kr=True)

    # ⑥: us↔kr href 교차 (양방향) — 언어판 사이 목록 어긋남 감지
    cross = cross_source(
        [SourceEntity(key=h, name=v["name"]) for h, v in sorted(us.items())],
        [SourceEntity(key=h, name=v["name"]) for h, v in sorted(kr.items())],
        labels=("us", "kr"),
    )
    records = [to_record(h, v, kr.get(h), patch) for h, v in sorted(us.items())]
    floor = substance_floor(
        (
            SourceEntity(
                key=r["id"], name=r["name"]["en"], substance=(r["data"].get("effect", ""),)
            )
            for r in records
        ),
        scope="currency:all",
    )

    out = knowledge / "game-data" / "currency"
    # 쓰기는 store 단일 경로로 (B-6): 원자적 + 근거 없는 레코드 감소 거부
    write_shard(out / "currency-01.ndjson", records, root=knowledge.parent, validate=False)
    after = store_load(knowledge.parent)  # 스키마·중복(기존 item.*와 충돌 포함) 전량 재검증

    by_cat: dict[str, int] = {}
    for r in records:
        c = r["data"]["currency_category"]
        by_cat[c] = by_cat.get(c, 0) + 1
    report: dict[str, Any] = {
        "written": len(records),
        "note": "Stackable∩Essence 중복 게재(Alloy)는 href dedup — 첫 카드 분류 유지",
        "by_category": dict(sorted(by_cat.items())),
        "ko_names": sum(1 for r in records if r["name"]["ko"] != r["name"]["en"]),
        "kb_total": len(after.records),
        "verification": verification_block(cross=[cross], substance=[floor]),
    }
    (src / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
