"""유니크 아이템 — poe2db 목록 수집·정형화 + PoB 대사 (KB_INGEST §6-2 ③).

수집은 **일괄 페이지 2회**(us/kr)로 끝난다 — 개별 상세 페이지 스크래핑 불필요
(목록 카드에 베이스타입·요구사항·모드가 모두 실려 있다).

KI-8 판정: A = poe2db 목록 멤버십(=존재 증거) · P = PoB Uniques 데이터 존재.
PoB에 있으면 모드 값은 PoB(계산 소스, D8)를, 이름·한국어는 poe2db를 따른다.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from pok.kb.ingest.sources import USER_AGENT
from pok.kb.ingest.uniques import UniqueItem, parse_pob_uniques
from pok.kb.ingest.verify import (
    SourceEntity,
    acquisition_coverage,
    cross_source,
    substance_floor,
    verification_block,
)

PAGE_URL = "https://poe2db.tw/{lang}/Unique_item"
LANGS = ("us", "kr")

# 카드 헤더 접두 → class_group
_GROUPS_US = (
    ("Weapon Unique", "weapon"),
    ("Armour Unique", "armour"),
    ("Other Unique", "other"),
    ("Cultivated Uniques", "cultivated"),
)
# kr 페이지는 분류만 한글화됨 ("Weapon 고유 /88")
_GROUPS_KR = (
    ("Weapon 고유", "weapon"),
    ("Armour 고유", "armour"),
    ("Other 고유", "other"),
    ("Cultivated Uniques", "cultivated"),
)


# 요구사항 조각: "Level 24" | "레벨 24" | "10 Str" | "10 지능"
_REQ_PART = re.compile(r"^(Level|레벨)\s*\d+$|^\d+\s*\S+$")


@dataclass
class PageUnique:
    name: str
    base_type: str
    class_group: str
    requires: str | None = None
    mods: list[str] = field(default_factory=list)


def fetch_pages(raw_dir: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """Unique_item 페이지(us/kr)를 원시로 저장한다 (멱등)."""
    out = raw_dir / "uniques"
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
            time.sleep(1.0)
    finally:
        if own:
            c.close()
    return saved


def parse_page(html: str, kr: bool = False) -> list[PageUnique]:
    """목록 페이지 → 유니크 항목들 (이름/베이스/요구/모드)."""
    soup = BeautifulSoup(html, "html.parser")
    groups = _GROUPS_KR if kr else _GROUPS_US
    req_marker = "요구 사항" if kr else "Requires"
    out: list[PageUnique] = []
    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None:
            continue
        htext = header.get_text(" ", strip=True)
        group = next((g for prefix, g in groups if htext.startswith(prefix)), None)
        if group is None:
            continue
        row = card.select_one("div.row")
        if row is None:
            continue
        for col in row.find_all("div", recursive=False):
            if not isinstance(col, Tag):
                continue
            lines = [
                line
                for line in col.get_text("\n", strip=True).split("\n")
                if line.strip() and line not in (",", ":")
            ]
            if len(lines) < 2:
                continue
            # 재배(cultivated) 카드는 **베이스타입 줄이 없다** — 이름 다음이 바로 모드다.
            # 예전엔 lines[1]("(100" 같은 모드 조각)을 베이스로 잡아 48건 전부 오염됐다.
            # 베이스는 동명 일반판에서 승계한다(process()).
            if group == "cultivated":
                name, base_type, rest = lines[0], "", lines[1:]
            else:
                name, base_type, rest = lines[0], lines[1], lines[2:]
            requires = None
            if rest and rest[0].startswith(req_marker):
                # "Requires:" 다음은 레벨·능력치 요구 — 개수가 가변이라 패턴으로 끊는다
                req_parts: list[str] = []
                idx = 1
                while idx < len(rest) and _REQ_PART.match(rest[idx]):
                    req_parts.append(rest[idx])
                    idx += 1
                requires = ", ".join(req_parts) or None
                rest = rest[idx:]
            out.append(
                PageUnique(
                    name=name,
                    base_type=base_type,
                    class_group=group,
                    requires=requires,
                    mods=rest,
                )
            )
    return out


def _verify(pob: dict[str, UniqueItem], items: list[dict[str, Any]]) -> dict[str, Any]:
    """완전성 기준 ⑥⑦⑧ (KB_INGEST §4) — 판정하지 않고 리포트만 한다.

    poe2db 쪽은 **정형화 후**(items)를 본다 — KB에 실제로 들어갈 값을 검증해야 하고,
    재배판 베이스 승계 같은 보정이 반영된 뒤라야 중복 key 충돌이 진짜 결함만 가리킨다.

    ⑧ 유니크의 획득 경로(드랍 출처)는 목록 페이지에 없다 → 커버리지 0이 정상 출력이며,
    그 0 자체가 "상세 페이지 수집이 필요하다"는 누락 신호다(조용히 넘어가지 않는다).
    """
    return verification_block(
        cross=[
            cross_source(
                [
                    SourceEntity(
                        key=i["name_en"],
                        name=i["name_en"],
                        facts={"base_type": str(i["base_type"]).strip()},
                    )
                    for i in items
                ],
                [
                    SourceEntity(key=u.name, name=u.name, facts={"base_type": u.base_type.strip()})
                    for u in pob.values()
                ],
                labels=("poe2db", "pob"),
            )
        ],
        substance=[
            substance_floor(
                (
                    SourceEntity(
                        key=i["name_en"],
                        name=i["name_en"],
                        substance=tuple(i["implicits"]) + tuple(i["explicits"]),
                    )
                    for i in items
                ),
                scope="unique:included",
            )
        ],
        acquisition=[
            acquisition_coverage(
                (SourceEntity(key=i["name_en"], name=i["name_en"]) for i in items),
                entity_type="unique",
            )
        ],
    )


def process(raw_dir: Path, pob_dir: Path, out_dir: Path) -> dict[str, Any]:
    """poe2db 목록과 PoB 데이터를 대사해 중간 산출물 + 리포트를 만든다."""
    src = raw_dir / "uniques"
    us = parse_page((src / "us.html").read_text(encoding="utf-8"))
    kr = parse_page((src / "kr.html").read_text(encoding="utf-8"), kr=True)
    pob = {i.name: i for i in parse_pob_uniques(pob_dir)}

    # 한국어: 같은 카드·같은 순서로 **위치 대응** (개수 일치 시에만).
    # 이름으로 짝지으면 재배판이 동명 일반판을 덮어쓴다 (0.5.4b: 48건).
    aligned = len(us) == len(kr)

    # 재배판은 베이스타입 줄이 없다 → 동명 일반판에서 승계
    base_of = {u.name: u.base_type for u in us if u.class_group != "cultivated" and u.base_type}
    base_ko_of: dict[str, str] = {}
    if aligned:
        base_ko_of = {
            u.name: k.base_type
            for u, k in zip(us, kr, strict=True)
            if u.class_group != "cultivated" and k.base_type
        }
    unresolved_base: list[str] = []

    items: list[dict[str, Any]] = []
    for idx, u in enumerate(us):
        p = pob.get(u.name)
        k = kr[idx] if aligned else None
        base_type = u.base_type or base_of.get(u.name, "")
        base_type_ko = (k.base_type if k else None) or base_ko_of.get(u.name)
        if not base_type:
            unresolved_base.append(u.name)
        items.append(
            {
                "name_en": u.name,
                "name_ko": k.name if k else u.name,
                "base_type": base_type,
                "base_type_ko": base_type_ko,
                "class_group": u.class_group,
                "category": p.category if p else None,
                "requires": u.requires,
                # 모드 값은 PoB(계산 소스, D8) 우선, 없으면 페이지 텍스트
                # 한국어 모드 텍스트는 페이지에서 조각으로 쪼개져 나와 의미 단위 복원이
                # 불가능하다 → 수집하지 않는다 (서술 트랙 ⑤에서 별도 처리)
                "implicits": p.implicits if p else [],
                "explicits": p.explicits if p else u.mods,
                "variants": p.variants if p else [],
                "mod_tags": p.mod_tags if p else [],
                "in_pob": p is not None,
            }
        )

    pob_only = sorted(set(pob) - {u.name for u in us})
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "uniques.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    report = {
        "page_items": len(us),
        "kr_items": len(kr),
        "kr_aligned": aligned,
        "cultivated_base_inherited": sum(
            1 for u in us if u.class_group == "cultivated" and base_of.get(u.name)
        ),
        "unresolved_base_type": unresolved_base,
        "pob_items": len(pob),
        "matched_pob": sum(1 for i in items if i["in_pob"]),
        "page_only": sum(1 for i in items if not i["in_pob"]),
        "pob_only": len(pob_only),
        "pob_only_sample": pob_only[:20],
        "verification": _verify(pob, items),
    }
    (raw_dir / "uniques" / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _to_record(item: dict[str, Any], patch: str) -> dict[str, Any]:
    from pok.kb.ingest.merge import POB_COMMIT, slug_to_id_part

    data: dict[str, Any] = {
        "rarity": "unique",
        "base_type": item["base_type"],
        "class_group": item["class_group"],
        "implicits": item["implicits"],
        "explicits": item["explicits"],
    }
    for key in ("base_type_ko", "category", "requires"):
        if item.get(key):
            data[key] = item[key]
    if item.get("variants"):
        data["variants"] = item["variants"]
    if item.get("mod_tags"):
        data["mod_tags"] = item["mod_tags"]
    if not item["in_pob"]:
        data["pob_computable"] = False

    sources: list[dict[str, Any]] = [
        {
            "src": "poe2db",
            "ref": f"https://poe2db.tw/us/{item['name_en'].replace(' ', '_')}",
            "patch": patch,
        }
    ]
    if item["in_pob"]:
        sources.append(
            {
                "src": "pob",
                "ref": f"Data/Uniques/{item['category']}.lua",
                "patch": patch,
                "pob": POB_COMMIT,
            }
        )
    # Cultivated(재배) 판은 같은 이름의 별개 아이템 — id로 구분한다 (0.5.4b: 48건)
    suffix = "-cultivated" if item["class_group"] == "cultivated" else ""
    return {
        "id": f"item.{slug_to_id_part(item['name_en'])}{suffix}",
        "type": "Item",
        "name": {"ko": item["name_ko"], "en": item["name_en"]},
        "tags": [],  # 유니크엔 게임 공식 태그가 없다 (모드 태그는 data.mod_tags)
        "data": data,
        "verification": "GAME_DATA" if item["in_pob"] else "SUPPORTED_INFERENCE",
        "sources": sources,
    }


def merge(out_dir: Path, knowledge: Path, patch: str) -> dict[str, Any]:
    """중간 산출물 → knowledge/game-data/uniques/uniques.ndjson."""
    from pok.kb.store import load as store_load

    items = json.loads((out_dir / "uniques.json").read_text(encoding="utf-8"))
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        rec = _to_record(item, patch)
        if rec["id"] in seen:
            continue
        seen.add(rec["id"])
        records.append(rec)

    dst = knowledge / "game-data" / "uniques"
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "uniques.ndjson").write_text(
        "".join(
            json.dumps(r, ensure_ascii=False) + "\n"
            for r in sorted(records, key=lambda r: str(r["id"]))
        ),
        encoding="utf-8",
    )
    after = store_load(knowledge.parent)
    return {"written": len(records), "kb_total": len(after.records)}


__all__ = ["PageUnique", "asdict", "fetch_pages", "merge", "parse_page", "process"]
