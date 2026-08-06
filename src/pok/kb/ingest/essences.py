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

# 아이템 클래스 → poe2db 페이지 슬러그: 조인 축 단일 정본은 kb.item_classes.
# 여기(수집)는 미등재 클래스를 **감지**해 보고해야 하므로 dict를 직접 조회한다.
from pok.kb.item_classes import PAGE_OF_CLASS as _PAGE_OF_CLASS

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


def unmapped_slugs(raw_dir: Path) -> list[str]:
    """PoB에 부여 매핑이 없는 실존 에센스의 페이지 슬러그 (개별 페이지 수집 대상).

    perfect essence(합금) 계열은 poe2db 목록엔 실존하지만 PoB `Essence.lua`에 없어
    "에센스 → 부위 → 모드" 매핑을 **개별 페이지에서만** 얻을 수 있다
    (실측 0.5.4b: 95 - 82 = 13건 전부 Alloy 계열). 이름 패턴이 아니라
    "PoB 매핑 부재"로 고르므로 패치가 계열명을 바꿔도 흔들리지 않는다.
    """
    pob_path = raw_dir / "pob" / "essence.json"
    pob_names: set[str] = set()
    if pob_path.exists():
        pob_raw = json.loads(pob_path.read_text(encoding="utf-8"))
        pob_names = {str(v.get("name", k)) for k, v in pob_raw.items()}
    src = raw_dir / "essences" / "us.html"
    items = parse_page(src.read_text(encoding="utf-8"))
    return sorted(e["slug"] for e in items if e["slug"] and e["name"] not in pob_names)


def fetch_detail_pages(raw_dir: Path, client: httpx.Client | None = None) -> dict[str, Any]:
    """PoB 매핑이 없는 에센스의 개별 페이지(us/kr)를 원시로 저장한다 (멱등)."""
    slugs = unmapped_slugs(raw_dir)
    out = raw_dir / "essences" / "pages"
    own = client is None
    c = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
    )
    saved: dict[str, Any] = {}
    try:
        for lang in LANGS:
            (out / lang).mkdir(parents=True, exist_ok=True)
            for slug in slugs:
                dst = out / lang / f"{slug}.html"
                key = f"{lang}/{slug}"
                if dst.exists():
                    saved[key] = "skipped"
                    continue
                r = c.get(f"https://poe2db.tw/{lang}/{slug}")
                r.raise_for_status()
                dst.write_bytes(r.content)
                saved[key] = len(r.content)
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
            anchor = col.find("a", href=True)
            out.append(
                {
                    "name": name,
                    "tier": tier,
                    "family": family,
                    "effect_lines": lines[1:],
                    "slug": str(anchor["href"]) if isinstance(anchor, Tag) else None,
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


_GRANT_TABLE_HEADERS = ("Class", "Modifier")


def parse_detail_page(html: str) -> list[dict[str, Any]]:
    """개별 에센스 페이지 → [{page, item_class, text, affix_type, req_level}].

    매핑 테이블(Class | Modifier | Pre/Suf | Required Level)이 정본이다 — 목록
    페이지의 effect_lines는 같은 정보의 평문 조각이라 구조를 복원할 수 없다.
    `page`는 Class 셀 앵커의 href(영문 페이지 슬러그, 언어 무관 조인 축 — 베이스
    ko 부착 때와 같은 원칙)이다.
    """
    from pok.kb.ingest.mod_catalog import _strip_html

    soup = BeautifulSoup(html, "html.parser")
    out: list[dict[str, Any]] = []
    for card in soup.select("div.card"):
        table = card.select_one("table")
        if table is None:
            continue
        rows = table.select("tr")
        if not rows:
            continue
        heads = [c.get_text(strip=True) for c in rows[0].select("th,td")]
        if tuple(heads[:2]) != _GRANT_TABLE_HEADERS:
            continue
        for tr in rows[1:]:
            tds = tr.select("td")
            if len(tds) < 4:
                continue
            anchor = tds[0].find("a", href=True)
            level = tds[3].get_text(strip=True)
            out.append(
                {
                    "page": str(anchor["href"])
                    if isinstance(anchor, Tag)
                    else tds[0].get_text(strip=True).replace(" ", "_"),
                    "item_class": tds[0].get_text(" ", strip=True),
                    "text": _strip_html(tds[1].decode_contents()),
                    "affix_type": tds[2].get_text(strip=True).lower(),
                    "req_level": int(level) if level.isdigit() else 0,
                }
            )
    return out


def _grant_norm(s: str) -> str:
    """행↔KB 텍스트 대조 정규화 — 카탈로그 정규화 + `+ (4-5)` 류 공백 흡수.

    poe2db 에센스 페이지는 `+`와 괄호 사이에 공백을 두기도 하고(실측: The
    Runebinder's Alloy 셉터 행), 키워드 배지 제거 흔적으로 쉼표 앞에 공백이
    남는다(실측: "Armour , Evasion"). 의미가 같은 표기 차이만 지운다.
    """
    from pok.kb.ingest.mod_catalog import _norm_text

    return _norm_text(s).replace("+ (", "+(").replace(" ,", ",")


def process_grants(raw_dir: Path, out_dir: Path, root: Path | None = None) -> dict[str, Any]:
    """개별 페이지 → (에센스, 부위, 부여 모드) 매핑 + KB 대사 리포트 (네트워크 없음).

    행의 모드 텍스트를 KB Modifier 전체와 정규화 대조해 modifier id를 해소한다.
    하이브리드는 KB texts 두 줄 ↔ 페이지 한 셀이므로 결합 텍스트로 대조한다
    (카탈로그 대사와 같은 흡수). 동문이의 해소는 반증 가능한 순서로:
      ① affix_type 일치 → ② 획득 경로에 poe2db:perfect_essence 보유 →
      ③ pob_key가 완벽 에센스 모드 계열 접두(Alloy)
    ②만으로 끝나지 않는 이유(실측): 카탈로그 계단식 대조가 일부 Alloy 모드의
    풀을 오귀속했다(예: AlloyCastSpeedGloves1 → poe2db:normal). 남는 0건·다건은
    조용히 넘기지 않고 리포트에 전량 남긴다 (KI-8).

    KB에 아예 없는 부여 모드(PoB 미수록 ∧ 카탈로그 미대조)는 poe2db-단독 신규
    레코드 스펙을 산출한다 — 훼손(desecrated) 모드 249건과 같은 수록 경로다.
    """
    from pok.kb.ingest.merge import slug_to_id_part
    from pok.kb.store import load as store_load

    store = store_load(root)

    # KB 후보 색인: 결합 텍스트 정규화 → [modifier id]
    by_text: dict[str, list[str]] = {}
    pool_ids: set[str] = set()
    for rec in store.records.values():
        if rec.type != "Modifier":
            continue
        data = rec.raw.get("data") or {}
        if "poe2db:perfect_essence" in (data.get("acquisition") or []):
            pool_ids.add(rec.id)
        texts = [str(t) for t in data.get("texts") or []]
        if texts:
            by_text.setdefault(_grant_norm(" ".join(texts)), []).append(rec.id)

    def _mod_data(rid: str) -> dict[str, Any]:
        return store.records[rid].raw.get("data") or {}

    def _resolve(row: dict[str, Any]) -> tuple[str | None, list[str]]:
        cands = [
            rid
            for rid in by_text.get(_grant_norm(row["text"]), [])
            if str(_mod_data(rid).get("affix_type", "")) == row["affix_type"]
        ]
        if len(cands) > 1:
            narrowed = [r for r in cands if r in pool_ids]
            cands = narrowed or cands
        if len(cands) > 1:
            narrowed = [
                r for r in cands if str(_mod_data(r).get("pob_key", "")).startswith("Alloy")
            ]
            cands = narrowed or cands
        return (cands[0], cands) if len(cands) == 1 else (None, cands)

    # 교차 축(⑥): 클래스 페이지 perfect_essence 풀 — 항목 Name이 곧 에센스 이름이라
    # (에센스, 효과 텍스트) 쌍을 독립 표면에서 재확인할 수 있다.
    catalog_path = out_dir / "mod_catalog.json"
    catalog_pairs: set[tuple[str, str]] = set()
    catalog_meta: dict[tuple[str, str], dict[str, Any]] = {}
    if catalog_path.exists():
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        for entry in catalog.values():
            if "perfect_essence" not in entry.get("pools", {}):
                continue
            for tx in entry.get("texts") or []:
                pair = (str(entry.get("affix_name", "")).lower(), _grant_norm(tx))
                catalog_pairs.add(pair)
                catalog_meta[pair] = entry

    pob_path = raw_dir / "pob" / "essence.json"
    pob_raw: dict[str, Any] = (
        json.loads(pob_path.read_text(encoding="utf-8")) if pob_path.exists() else {}
    )
    pob_names = {str(v.get("name", k)) for k, v in pob_raw.items()}
    listed = parse_page((raw_dir / "essences" / "us.html").read_text(encoding="utf-8"))

    entries: list[dict[str, Any]] = []
    new_mods: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    tie_broken: list[dict[str, Any]] = []
    cross_missing: list[dict[str, Any]] = []
    missing_pages: list[str] = []
    missing_currency: list[str] = []
    matched_mod_ids: set[str] = set()
    covered_pairs: set[tuple[str, str]] = set()
    for e in listed:
        if e["name"] in pob_names or not e["slug"]:
            continue  # PoB에 매핑이 있는 고전 에센스는 그쪽이 정본
        page_path = raw_dir / "essences" / "pages" / "us" / f"{e['slug']}.html"
        if not page_path.exists():
            missing_pages.append(e["slug"])
            continue
        item_id = f"item.{slug_to_id_part(e['slug'])}"
        if item_id not in store.records:
            missing_currency.append(item_id)
        grants: list[dict[str, Any]] = []
        for row in parse_detail_page(page_path.read_text(encoding="utf-8")):
            rid, cands = _resolve(row)
            grant = dict(row)
            pair = (e["name"].lower(), _grant_norm(row["text"]))
            covered_pairs.add(pair)
            if pair not in catalog_pairs:
                cross_missing.append({"essence": e["name"], "page": row["page"]})
            if rid is not None:
                grant["modifier"] = rid
                matched_mod_ids.add(rid)
                if len(cands) > 1:
                    tie_broken.append({"essence": e["name"], **row, "chosen": rid})
            elif not cands:
                # KB 부재 — poe2db-단독 신규 레코드 스펙 (훼손 모드와 같은 경로).
                # 카탈로그 항목이 있으면 group·ilvl을 보강한다.
                meta = catalog_meta.get(pair) or {}
                new_id = (
                    "modifier."
                    + slug_to_id_part(f"essence {e['name']} {row['page']} {row['text']}")[:90]
                )
                grant["modifier"] = new_id
                matched_mod_ids.add(new_id)
                spec_data: dict[str, Any] = {
                    "affix_type": row["affix_type"],
                    "origins": ["item"],
                    "texts": [row["text"]],
                    "spawn_weights": {"default": 0},
                    "acquisition": ["poe2db:perfect_essence"],
                }
                if meta.get("families"):
                    spec_data["group"] = "+".join(meta["families"])
                if meta.get("ilvl"):
                    spec_data["ilvl"] = meta["ilvl"]
                new_mods.append(
                    {
                        "id": new_id,
                        "type": "Modifier",
                        "name": {"ko": row["text"][:60], "en": row["text"][:60]},
                        "tags": [],
                        "data": spec_data,
                        "verification": "SUPPORTED_INFERENCE",  # poe2db 단독 소스
                        "sources": [
                            {
                                "src": "poe2db",
                                "ref": f"https://poe2db.tw/us/{e['slug']}",
                                "patch": _patch_of(raw_dir),
                            }
                        ],
                    }
                )
                unmatched.append({"essence": e["name"], **row, "new_record": new_id})
            else:
                grant["modifier"] = None
                ambiguous.append({"essence": e["name"], **row, "candidates": cands})
            grants.append(grant)
        entries.append({"essence": item_id, "name": e["name"], "slug": e["slug"], "grants": grants})

    # ── 고전 에센스: PoB Essence.lua가 (에센스 → 클래스 → 모드 키) 정본 ──
    # poe2db 실존 목록으로 거른다 (KI-8: 소스에 존재 ≠ 게임에 구현). 화폐 레코드는
    # 영문명으로 조인한다 (currency 수록도 같은 poe2db 표면에서 왔으므로 이름이 축).
    currency_by_name = {
        str(r.raw.get("name", {}).get("en", "")): r.id
        for r in store.records.values()
        if r.type == "Item" and (r.raw.get("data") or {}).get("rarity") == "currency"
    }
    live_names = {e["name"] for e in listed}
    from pok.kb.ingest.mods import mod_slug

    pob_missing_mods: list[dict[str, Any]] = []
    pob_unknown_class: list[str] = []
    pob_not_live: list[str] = []
    pob_no_currency: list[str] = []
    for _, spec in sorted(pob_raw.items()):
        name = str(spec.get("name", ""))
        mods_map = spec.get("mods") or {}
        if name not in live_names:
            pob_not_live.append(name)
            continue
        essence_item = currency_by_name.get(name)
        if essence_item is None:
            pob_no_currency.append(name)
            continue
        grants = []
        for cls, key in sorted(mods_map.items()):
            page = _PAGE_OF_CLASS.get(cls)
            if page is None:
                pob_unknown_class.append(f"{name}: {cls}")
                continue
            rid = f"modifier.{mod_slug(str(key))}"
            if rid not in store.records:
                pob_missing_mods.append({"essence": name, "class": cls, "pob_key": key})
                continue
            data = _mod_data(rid)
            text = " ".join(str(t) for t in data.get("texts") or [])
            covered_pairs.add((name.lower(), _grant_norm(text)))
            grants.append(
                {
                    "page": page,
                    "item_class": cls,
                    "text": text,
                    "affix_type": str(data.get("affix_type", "")),
                    "modifier": rid,
                }
            )
            matched_mod_ids.add(rid)
        entries.append({"essence": essence_item, "name": name, "slug": None, "grants": grants})

    # id 충돌(같은 에센스·페이지·텍스트 중복)은 산출 자체가 잘못 — 결정적 id라 재실행엔 안전
    dup_new = len(new_mods) - len({m["id"] for m in new_mods})

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "essence_grants.json").write_text(
        json.dumps(entries, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "essence_new_mods.json").write_text(
        json.dumps(new_mods, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    # 완전성의 반대 방향: perfect_essence 획득이라던 KB 모드 중 어느 에센스도
    # 부여하지 않는 것 — 카탈로그 계단식 대조의 오귀속 후보이므로 전량 보고한다.
    report: dict[str, Any] = {
        "essences": len(entries),
        "rows": sum(len(x["grants"]) for x in entries),
        "rows_matched": sum(1 for x in entries for g in x["grants"] if g["modifier"]),
        "new_mod_records": [m["id"] for m in new_mods],
        "new_mod_id_collisions": dup_new,
        "tie_broken_rows": tie_broken,
        "unmatched_rows": unmatched,
        "ambiguous_rows": ambiguous,
        "kb_pool_total": len(pool_ids),
        "kb_pool_covered": len(pool_ids & matched_mod_ids),
        "kb_pool_uncovered": sorted(pool_ids - matched_mod_ids),
        "cross_catalog": {
            "catalog_pairs": len(catalog_pairs),
            "covered_by_rows": len(catalog_pairs & covered_pairs),
            "rows_not_in_catalog": cross_missing,
            "catalog_only": sorted(
                f"{name} :: {text[:50]}" for name, text in catalog_pairs - covered_pairs
            ),
        },
        "missing_detail_pages": missing_pages,
        "missing_currency_records": missing_currency,
        "pob": {
            "missing_mod_records": pob_missing_mods,
            "unknown_classes": pob_unknown_class,
            "not_live_skipped": pob_not_live,
            "no_currency_record": pob_no_currency,
        },
    }
    (raw_dir / "essences" / "grants-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _patch_of(raw_dir: Path) -> str:
    """원시 스냅샷 디렉터리 이름 = 패치 버전 (fetch-plan과 같은 관례)."""
    return raw_dir.name


def apply_grants(out_dir: Path, root: Path | None = None) -> dict[str, Any]:
    """essence_grants.json → KB 부착 (store 단일 경로, B-6).

    · Item(에센스): `data.grants` = [{page, item_class, text, affix_type, req_level?,
      modifier}] — "이 에센스는 어느 부위에 무엇을 부여하나"의 정본.
    · Modifier: `data.granted_by`(부여 에센스 item id)는 부여받는 모드 전부에,
      `data.applicable_pages`(poe2db 페이지 — desecrated와 같은 축)는 **자연 스폰이
      전무한 모드(spawn_weights 전부 0)에만** 부착한다 — 자연 스폰 모드에 붙이면
      에센스 부위 목록(부분집합)이 전체 적용 범위로 오독된다. legality의 신호 ②가
      되어 "어느 베이스에 붙나"가 결정적으로 판정된다.
    · 신규 모드(essence_new_mods.json — poe2db 단독)는 전용 샤드에 먼저 쓴다.
    재실행은 같은 값을 다시 쓰므로 멱등이다 (리스트는 통째 교체).
    """
    from pok.common.paths import knowledge_dir
    from pok.kb.store import load as store_load
    from pok.kb.store import patch_records, write_shard

    new_mods_path = out_dir / "essence_new_mods.json"
    new_mods: list[dict[str, Any]] = (
        json.loads(new_mods_path.read_text(encoding="utf-8")) if new_mods_path.exists() else []
    )
    if new_mods:
        write_shard(
            knowledge_dir(root) / "game-data" / "modifiers" / "essence-poe2db-01.ndjson",
            new_mods,
            root=root,
        )

    entries = json.loads((out_dir / "essence_grants.json").read_text(encoding="utf-8"))
    store = store_load(root)

    def _can_spawn(rid: str) -> bool:
        weights = (store.records[rid].raw.get("data") or {}).get("spawn_weights") or {}
        return any(int(w or 0) > 0 for w in weights.values())

    updates: dict[str, dict[str, Any]] = {}
    mod_pages: dict[str, set[str]] = {}
    mod_sources: dict[str, set[str]] = {}
    for entry in entries:
        updates[entry["essence"]] = {"grants": entry["grants"]}
        for g in entry["grants"]:
            if not g["modifier"]:
                continue
            mod_pages.setdefault(g["modifier"], set()).add(g["page"])
            mod_sources.setdefault(g["modifier"], set()).add(entry["essence"])
    pages_attached = 0
    for rid, pages in mod_pages.items():
        patch: dict[str, Any] = {"granted_by": sorted(mod_sources[rid])}
        if not _can_spawn(rid):
            patch["applicable_pages"] = sorted(pages)
            pages_attached += 1
        updates[rid] = patch
    reports = patch_records(updates, root=root)
    return {
        "items_patched": len(entries),
        "modifiers_patched": len(mod_pages),
        "applicable_pages_attached": pages_attached,
        "new_mod_records": len(new_mods),
        "files_touched": len(reports),
    }


def live_essence_names(raw_dir: Path) -> set[str]:
    """현재 패치에 실존하는 에센스 이름 (PoB 매핑을 걸러내는 필터)."""
    src = raw_dir / "essences" / "us.html"
    if not src.exists():
        return set()
    return {e["name"] for e in parse_page(src.read_text(encoding="utf-8"))}
