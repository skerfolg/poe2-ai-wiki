"""poe2db 모드 카탈로그 파서 — 클래스별 ModsView JSON + Desecrated 테이블.

왜 필요한가 (사용자 판정 2026-07-29): PoB의 스폰 가중치는 PoE2에서 성기게 채워져
있어(가중치 0인 실존 모드 다수) **PoB만으로는 모드의 획득 가능성을 판정할 수 없다**.
poe2db가 카탈로그 권위(D8)이며, 클래스 페이지(`/us/<class>#ModifiersCalc`)에 획득
경로별 모드 풀이 임베디드 JSON(`new ModsView({...})`)으로 통째로 실려 있다:

  normal(일반 제작) · corrupted(바알) · desecrated(훼손) · essence · perfect_essence ·
  corruption_upgrade · breach_* · chronomancy/marksman/decay/soul/destruction/berserking …

PoB와의 매칭 키 = (접사명, 패밀리, ilvl): PoB Strength1 {affix "of the Brute",
group "Strength", level 1} ↔ poe2db {Name, ModFamilyList, Level}.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup, Tag

from pok.kb.ingest.verify import (
    SourceEntity,
    cross_source,
    verification_block,
)

# ModsView 페이로드 — 클래스 페이지의 마지막 스크립트에 임베드
_MODSVIEW = re.compile(r"new ModsView\((\{.*?\})\);", re.S)

# ModGenerationTypeID → 접사 종류 (poe2db/게임 데이터 관례)
_GEN_TYPE = {"1": "prefix", "2": "suffix"}

_WS = re.compile(r"\s+")


def _strip_html(fragment: str) -> str:
    """효과 HTML → 평문 (모드 텍스트 대조용)."""
    text = BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True)
    text = text.replace("—", "-")
    text = _WS.sub(" ", text)
    return re.sub(r"\(\s*([\d.]+)\s*-\s*([\d.]+)\s*\)", r"(\1-\2)", text).strip()


def parse_modsview(html: str) -> dict[str, list[dict[str, Any]]]:
    """클래스 페이지 → {풀 이름: [모드…]} (빈 풀은 생략).

    모드 필드: affix_name·ilvl·affix_type·families·drop_chance·text·spawn_tags·mod_tags
    """
    m = _MODSVIEW.search(html)
    if m is None:
        return {}
    data = json.loads(m.group(1))
    pools: dict[str, list[dict[str, Any]]] = {}
    for pool, entries in data.items():
        if not isinstance(entries, list) or not entries:
            continue
        mods: list[dict[str, Any]] = []
        for e in entries:
            if not isinstance(e, dict) or "str" not in e:
                continue
            tags = []
            for badge in e.get("mod_no") or []:
                bt = BeautifulSoup(str(badge), "html.parser").find(attrs={"data-tag": True})
                if isinstance(bt, Tag):
                    tags.append(str(bt["data-tag"]))
            mods.append(
                {
                    "affix_name": _strip_html(str(e.get("Name", ""))),
                    "ilvl": int(e["Level"]) if str(e.get("Level", "")).isdigit() else 0,
                    "affix_type": _GEN_TYPE.get(str(e.get("ModGenerationTypeID")), "other"),
                    "families": [str(f) for f in (e.get("ModFamilyList") or [])],
                    "drop_chance": int(e["DropChance"])
                    if str(e.get("DropChance", "")).isdigit()
                    else None,
                    "text": _strip_html(str(e["str"])),
                    "spawn_tags": [str(t) for t in (e.get("spawn_no") or [])],
                    "mod_tags": tags,
                }
            )
        if mods:
            pools[pool] = mods
    return pools


# Desecrated 페이지 테이블: Name | Level | Pre/Suf | Description(+badge 태그)
_DESECRATED_HEADERS = (
    ("Desecrated Mods /", "equipment"),
    ("Jewels Desecrated Mods /", "jewel"),
    ("Desecrated Waystone Mods /", "waystone"),
)


def parse_desecrated(html: str) -> dict[str, list[dict[str, Any]]]:
    """Desecrated_Modifiers 페이지 → {대상군: [모드…]}."""
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, list[dict[str, Any]]] = {}
    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None:
            continue
        htext = header.get_text(" ", strip=True)
        scope = next((s for p, s in _DESECRATED_HEADERS if htext.startswith(p)), None)
        if scope is None:
            continue
        table = card.select_one("table")
        if table is None:
            continue
        first_row = table.select("tr")[0]
        header_cells = [th.get_text(" ", strip=True) for th in first_row.select("th,td")]
        has_level = "Level" in header_cells  # Waystone 테이블은 Level 열이 없다 (3열)
        rows: list[dict[str, Any]] = []
        for tr in table.select("tr")[1:]:  # 첫 행 = 헤더
            tds = tr.select("td")
            if len(tds) < (4 if has_level else 3):
                continue
            desc = tds[3 if has_level else 2]
            tags = [
                str(b["data-tag"])
                for b in desc.select("span.badge[data-tag]")
                if isinstance(b, Tag)
            ]
            for b in desc.select("span.badge"):
                b.decompose()  # 태그 배지를 빼고 남은 것이 효과 텍스트
            rows.append(
                {
                    "affix_name": tds[0].get_text(" ", strip=True),
                    "ilvl": int(tds[1].get_text(strip=True) or 0) if has_level else 0,
                    "affix_type": tds[2 if has_level else 1].get_text(strip=True).lower(),
                    "text": _strip_html(desc.decode_contents()),
                    "mod_tags": tags,
                }
            )
        out[scope] = rows
    return out


def _norm_text(s: str) -> str:
    """대조용 텍스트 정규화 — 수치 범위 표기·공백·대소문자 차이를 지운다."""
    s = s.replace("\u2014", "-").replace("\u2013", "-")  # em/en dash
    s = _WS.sub(" ", s).strip().lower()
    s = re.sub(r"\(\s*([\d.]+)\s*-\s*([\d.]+)\s*\)", r"(\1-\2)", s)
    return s.replace(" %", "%")  # poe2db는 '% ' 앞에 공백을 두기도 한다


def match_key(affix_name: str, families: list[str], ilvl: int) -> str:
    """poe2db↔PoB 대조 키. 패밀리는 정렬해 순서 차이를 흡수한다."""
    return f"{affix_name.strip().lower()}|{'+'.join(sorted(f.lower() for f in families))}|{ilvl}"


def process_catalog(raw_dir: Path, out_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """클래스 페이지 전체 + Desecrated 페이지 → 통합 카탈로그 + PoB 교차(⑥).

    산출물(중간): var/ingest/<patch>/mod_catalog.json
    리포트: <raw>/modifiers/catalog-report.json (데이터 repo 증거)
    """
    pages = plan["categories"]["modifier-pages"]["items"]
    catalog: dict[str, dict[str, Any]] = {}  # match_key → 항목(+등장 페이지·풀)
    parsed_pages = 0
    missing_pages: list[str] = []
    for slug in pages:
        path = raw_dir / "poe2db" / "us" / f"{slug}.html"
        if not path.exists():
            missing_pages.append(slug)
            continue
        pools = parse_modsview(path.read_text(encoding="utf-8"))
        if pools:
            parsed_pages += 1
        for pool, mods in pools.items():
            for m in mods:
                key = match_key(m["affix_name"], m["families"], m["ilvl"])
                slot = catalog.setdefault(
                    key,
                    {
                        "affix_name": m["affix_name"],
                        "ilvl": m["ilvl"],
                        "affix_type": m["affix_type"],
                        "families": sorted(f.lower() for f in m["families"]),
                        "texts": [],
                        "pools": {},
                        "mod_tags": sorted(set(m["mod_tags"])),
                        "drop_chance": m["drop_chance"],
                    },
                )
                norm = _norm_text(m["text"])
                if norm not in (_norm_text(t) for t in slot["texts"]):
                    slot["texts"].append(m["text"])
                slot["pools"].setdefault(pool, []).append(slug)

    desecrated = parse_desecrated(
        (raw_dir / "modifiers" / "desecrated.us.html").read_text(encoding="utf-8")
    )

    # ── ⑥ 교차: poe2db 카탈로그 ↔ PoB 수록·보류 모드 ─────────────
    from pok.kb.ingest.mods import is_included

    pob_mods = json.loads((out_dir / "mods.json").read_text(encoding="utf-8"))
    pob_entities = []
    for m in pob_mods:
        if m["affix_type"] not in ("prefix", "suffix"):
            continue  # 룬·부패는 카탈로그 축이 다르다 (desecrated/corrupted 별도)
        key = match_key(m.get("affix_name", ""), [m.get("group", "")], m.get("ilvl", 0))
        pob_entities.append(
            SourceEntity(key=key, name=m["pob_key"], facts={"held": str(not is_included(m))})
        )
    db_entities = [
        SourceEntity(key=k, name=v["affix_name"] or (v["texts"] or [""])[0][:40])
        for k, v in catalog.items()
    ]
    cross = cross_source(db_entities, pob_entities, labels=("poe2db", "pob"))

    # 전 모드의 poe2db 실존 판정 — 계단식: 이름키 → (패밀리+ilvl) → 텍스트(결합 포함).
    # Alloy 계열은 poe2db Name이 접사명이 아니라 부여 화폐 링크라 이름 매칭이 원천 불가
    # (실측: AlloyArchonDuration1은 perfect_essence 풀의 (archonduration, 45)와 대응).
    # 하이브리드는 PoB 두 줄 ↔ poe2db 한 줄 → 결합 텍스트로 흡수.
    db_keys = set(catalog)
    db_fam_lvl: dict[str, set[str]] = {}
    for v in catalog.values():
        for fam in v["families"]:
            db_fam_lvl.setdefault(f"{fam}|{v['ilvl']}", set()).update(v["pools"])
    db_texts: dict[str, set[str]] = {}
    for v in catalog.values():
        for tx in v["texts"]:
            db_texts.setdefault(_norm_text(tx), set()).update(v["pools"])

    def _pools_for(m: dict[str, Any]) -> tuple[str, set[str]]:
        key = match_key(m.get("affix_name", ""), [m.get("group", "")], m.get("ilvl", 0))
        if key in db_keys:
            return "key", set(catalog[key]["pools"])
        fam_key = f"{str(m.get('group', '')).lower()}|{m.get('ilvl', 0)}"
        if fam_key in db_fam_lvl:
            return "key", db_fam_lvl[fam_key]
        texts = [str(t) for t in (m.get("texts") or [])]
        candidates = [_norm_text(t) for t in texts]
        if len(texts) > 1:
            candidates.append(_norm_text(" ".join(texts)))
        hit = next((db_texts[c] for c in candidates if c in db_texts), None)
        if hit is not None:
            return "text", set(hit)
        return "none", set()

    match_result: dict[str, list[str]] = {}  # pob_key → poe2db 풀들 (merge가 획득 경로로 부착)
    held = [m for m in pob_mods if not is_included(m)]
    held_keys = {m["pob_key"] for m in held}
    confirmed: list[str] = []
    confirmed_pools: dict[str, int] = {}
    text_only: list[str] = []
    unmatched: list[str] = []
    for m in pob_mods:
        if m["affix_type"] not in ("prefix", "suffix"):
            continue
        how, pools_hit = _pools_for(m)
        if pools_hit:
            match_result[m["pob_key"]] = sorted(pools_hit)
        if m["pob_key"] not in held_keys:
            continue
        if how == "key":
            confirmed.append(m["pob_key"])
        elif how == "text":
            text_only.append(m["pob_key"])
        else:
            unmatched.append(m["pob_key"])
        for pool in pools_hit:
            confirmed_pools[pool] = confirmed_pools.get(pool, 0) + 1

    # 부활 감지 (KI-8): 원장에 제외된 키가 카탈로그에 다시 나타나면 리포트
    from pok.common.paths import knowledge_dir

    revival: list[str] = []
    ledger_path = knowledge_dir() / "ingest" / "exclusions.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        for entry in ledger.get("unobtainable_mods", []):
            revival += [k for k in entry.get("pob_keys", []) if k in match_result]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mod_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "catalog_match.json").write_text(
        json.dumps(match_result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "desecrated.json").write_text(
        json.dumps(desecrated, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    pool_counts: dict[str, int] = {}
    for v in catalog.values():
        for pool in v["pools"]:
            pool_counts[pool] = pool_counts.get(pool, 0) + 1
    report: dict[str, Any] = {
        "pages_planned": len(pages),
        "pages_parsed": parsed_pages,
        "pages_missing": missing_pages,
        "catalog_entries": len(catalog),
        "entries_by_pool": dict(sorted(pool_counts.items())),
        "desecrated_tables": {k: len(v) for k, v in desecrated.items()},
        "held_membership": {
            "held_total": len(held),
            "confirmed_by_key": len(confirmed),
            "confirmed_by_text": len(text_only),
            "confirmed_pools": dict(sorted(confirmed_pools.items())),
            "unmatched": len(unmatched),
            "unmatched_sample": sorted(unmatched)[:30],
        },
        "matched_total": len(match_result),
        "revival_candidates": sorted(revival)[:30],
        "verification": verification_block(cross=[cross]),
    }
    (raw_dir / "modifiers" / "catalog-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
