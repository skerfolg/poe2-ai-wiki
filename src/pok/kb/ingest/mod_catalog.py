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
from collections.abc import Mapping
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
        # Waystone 테이블은 Level 열이 없다(3열) · kr은 '레벨' 표기
        has_level = any(h in ("Level", "레벨") for h in header_cells)
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


_ITEM_CARD = re.compile(r"(?:Item|아이템)\s*/\s*\d+")


def parse_base_item_names(html: str) -> dict[str, str]:
    """클래스 페이지의 '<Class> Item /N' 카드 → {href 슬러그: 표시 이름}.

    href(영문 페이지 슬러그)가 언어와 무관한 공통 키다 — data-hover는 kr에서
    CDN 해시 URL로 바뀌어 조인 축이 못 된다(실측).
    """
    soup = BeautifulSoup(html, "html.parser")
    out: dict[str, str] = {}
    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None or not _ITEM_CARD.search(header.get_text(" ", strip=True)):
            continue
        for a in card.select("a.whiteitem[href]"):
            name = a.get_text(strip=True)
            if name:
                out.setdefault(str(a["href"]), name)
    return out


def _norm_text(s: str) -> str:
    """대조용 텍스트 정규화 — 수치 범위 표기·공백·대소문자 차이를 지운다."""
    s = s.replace("\u2014", "-").replace("\u2013", "-")  # em/en dash
    s = _WS.sub(" ", s).strip().lower()
    s = re.sub(r"\(\s*([\d.]+)\s*-\s*([\d.]+)\s*\)", r"(\1-\2)", s)
    return s.replace(" %", "%")  # poe2db는 '% ' 앞에 공백을 두기도 한다


def match_key(affix_name: str, families: list[str], ilvl: int) -> str:
    """poe2db↔PoB 대조 키. 패밀리는 정렬해 순서 차이를 흡수한다.

    ⚠️ **이 키는 poe2db에서 유일하지 않다** — 한 슬롯에 서로 다른 모드가 쌓인다.
    반경 주얼판과 일반판이 접사명·패밀리·레벨을 공유하기 때문이다(실측 0.5.4b:
    `blasting|areaofeffect|1` = 일반 '효과 범위 (4-6)% 증가' + 반경 '주요 패시브가
    효과 범위 (2-3)% 증가도 부여'). 그래서 슬롯의 텍스트 목록은 **여러 모드의 줄이
    섞인 풀**이지 한 모드의 문구가 아니다. 줄을 꺼낼 땐 반드시 `aligned_ko_texts`처럼
    **영문 줄을 축으로** 짝지어야 한다.
    """
    return f"{affix_name.strip().lower()}|{'+'.join(sorted(f.lower() for f in families))}|{ilvl}"


def align_key(text: str) -> str:
    """영문 줄의 동일성 키 — 공백을 완전히 지운다.

    두 소스의 공백 차이는 의미가 아니라 HTML 추출의 부산물이다(poe2db는
    `get_text(" ")`로 뽑아 `armour , evasion`·`+ (4-5)`처럼 띄운다). 남겨 두면
    같은 줄이 다른 줄로 보여 한글이 통째로 떨어져 나간다(실측 2026-08-07: 5건).
    """
    return _WS.sub("", _norm_text(text))


def build_ko_line_index(catalog: dict[str, dict[str, Any]]) -> tuple[dict[str, str], list[str]]:
    """전 슬롯의 (영문 줄 → 한글 줄) 짝을 합쳐 **전역 색인**으로 만든다.

    왜 슬롯이 아니라 전역인가: 한 줄의 한글 번역은 그 줄이 **어느 슬롯에서 왔는지와
    무관**하다. 반면 슬롯 키(`match_key`)는 유일하지 않아 옆 모드의 줄을 함께 담고
    있고, PoB↔poe2db 대조는 계단식(이름 → 패밀리+ilvl → 텍스트)이라 **다른 모드의
    슬롯을 가리키기도 한다**. 슬롯을 경유하면 그 두 오차가 곱해진다 — 실측
    2026-08-07: 그래서 en/ko 줄 수가 어긋난 Modifier가 1,536건이었고, 오염된 한글에
    `pob_gaps` 반경 스캐너가 매칭해 `radius-grant` 오탐 519건이 붙었으며, 한 세션이
    그걸 "주얼 소켓은 PoB에서 구조적으로 저평가된다"로 읽어 측정 방법론을 바꿨다.
    수치도 어긋났다(`JewelRadiusCriticalDamage`: 영문 (5-10)% ↔ 한글 (10-20)%).

    영문 줄을 축으로 삼으면 슬롯이 섞여 있어도 자기 줄만 온다. 전역화가 안전한지는
    **재보지 말고 여기서 측정한다**: 한 영문 줄에 서로 다른 한글이 붙으면 그 줄은
    색인에서 **빼고** 충돌로 보고한다(임의로 하나 고르지 않는다). 실측 0.5.4b:
    3,427줄 중 충돌 0건.
    """
    seen: dict[str, set[str]] = {}
    for entry in catalog.values():
        for en, ko in (entry.get("ko_by_text") or {}).items():
            seen.setdefault(align_key(en), set()).add(ko)
    index = {k: next(iter(v)) for k, v in seen.items() if len(v) == 1}
    return index, sorted(k for k, v in seen.items() if len(v) > 1)


def aligned_ko_texts(texts: list[str], ko_lines: Mapping[str, str]) -> list[str]:
    """영문 줄 각각에 **그 줄의** 한글을 짝지어 돌려준다 — 하나라도 없으면 빈 목록.

    반환 길이가 입력 길이와 **구조적으로** 같아진다 — 규율을 문서가 아니라 자료구조가
    강제한다(철칙 5). 짝을 못 찾은 줄이 하나라도 있으면 부분 부착 대신 통째로
    포기한다: 틀린 한글보다 없는 한글이 낫다. 하이브리드(PoB 두 줄 ↔ poe2db 한 줄)가
    여기 걸리는데, 젬 쪽에서 이미 같은 판정을 했다 — KB_INGEST §3b "en/ko 항목 수가
    일치할 때만 분할하고 아니면 접는다".
    """
    if not texts:
        return []
    matched = [ko_lines.get(align_key(t)) for t in texts]
    return [k for k in matched if k] if all(matched) else []


def process_catalog(raw_dir: Path, out_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """클래스 페이지 전체 + Desecrated 페이지 → 통합 카탈로그 + PoB 교차(⑥).

    산출물(중간): var/ingest/<patch>/mod_catalog.json
    리포트: <raw>/modifiers/catalog-report.json (데이터 repo 증거)
    """
    pages = plan["categories"]["modifier-pages"]["items"]
    catalog: dict[str, dict[str, Any]] = {}  # match_key → 항목(+등장 페이지·풀)
    parsed_pages = 0
    missing_pages: list[str] = []
    base_hover_en: dict[str, str] = {}
    base_hover_ko: dict[str, str] = {}
    ko_zip_mismatch = 0  # us/kr 항목 정렬키가 어긋난 것 (ko 부착 스킵)
    for slug in pages:
        path = raw_dir / "poe2db" / "us" / f"{slug}.html"
        if not path.exists():
            missing_pages.append(slug)
            continue
        html_us = path.read_text(encoding="utf-8")
        pools = parse_modsview(html_us)
        kr_path = raw_dir / "poe2db" / "kr" / f"{slug}.html"
        html_kr = kr_path.read_text(encoding="utf-8") if kr_path.exists() else ""
        pools_kr = parse_modsview(html_kr) if html_kr else {}
        base_hover_en.update(parse_base_item_names(html_us))
        if html_kr:
            base_hover_ko.update(parse_base_item_names(html_kr))
        if pools:
            parsed_pages += 1
        for pool, mods in pools.items():
            kr_mods = pools_kr.get(pool) or []
            for idx, m in enumerate(mods):
                key = match_key(m["affix_name"], m["families"], m["ilvl"])
                slot = catalog.setdefault(
                    key,
                    {
                        "affix_name": m["affix_name"],
                        "ilvl": m["ilvl"],
                        "affix_type": m["affix_type"],
                        "families": sorted(f.lower() for f in m["families"]),
                        "texts": [],
                        # 영문 줄(정규화) → 그 줄의 한글. **목록이 아니라 짝**이다 —
                        # 슬롯 키가 유일하지 않아 목록으로 두면 옆 모드의 줄이 섞인다
                        # (match_key·aligned_ko_texts 참고).
                        "ko_by_text": {},
                        "pools": {},
                        "mod_tags": sorted(set(m["mod_tags"])),
                        "drop_chance": m["drop_chance"],
                    },
                )
                norm = _norm_text(m["text"])
                if norm not in (_norm_text(t) for t in slot["texts"]):
                    slot["texts"].append(m["text"])
                slot["pools"].setdefault(pool, []).append(slug)
                # ko: 같은 (페이지,풀)의 같은 위치 — 정렬키(ilvl, families)가 같을 때만
                # (kr ModsView의 families/Level은 영문 그대로라 검증 축으로 쓸 수 있다)
                if idx < len(kr_mods):
                    k = kr_mods[idx]
                    if (k["ilvl"], k["families"]) == (m["ilvl"], m["families"]):
                        slot.setdefault("affix_name_ko", k["affix_name"])
                        slot["ko_by_text"].setdefault(norm, k["text"])
                    else:
                        ko_zip_mismatch += 1

    # 베이스 아이템 ko: data-hover(언어 무관 메타데이터 키)로 조인
    base_names_ko = {
        base_hover_en[h]: base_hover_ko[h]
        for h in base_hover_en.keys() & base_hover_ko.keys()
        if base_hover_en[h] != base_hover_ko[h]
    }

    desecrated = parse_desecrated(
        (raw_dir / "modifiers" / "desecrated.us.html").read_text(encoding="utf-8")
    )
    kr_desecrated_path = raw_dir / "modifiers" / "desecrated.kr.html"
    if kr_desecrated_path.exists():
        desecrated_kr = parse_desecrated(kr_desecrated_path.read_text(encoding="utf-8"))
        for scope, rows in desecrated.items():
            kr_rows = desecrated_kr.get(scope) or []
            for idx, row in enumerate(rows):
                if idx < len(kr_rows) and kr_rows[idx]["ilvl"] == row["ilvl"]:
                    row["affix_name_ko"] = kr_rows[idx]["affix_name"]
                    row["text_ko"] = kr_rows[idx]["text"]

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

    db_fam_lvl_key: dict[str, str] = {}  # (family|ilvl) → 대표 catalog_key
    for ck, v in catalog.items():
        for fam in v["families"]:
            db_fam_lvl_key.setdefault(f"{fam}|{v['ilvl']}", ck)
    db_text_key: dict[str, str] = {}
    for ck, v in catalog.items():
        for tx in v["texts"]:
            db_text_key.setdefault(_norm_text(tx), ck)

    def _pools_for(m: dict[str, Any]) -> tuple[str, set[str], str | None]:
        key = match_key(m.get("affix_name", ""), [m.get("group", "")], m.get("ilvl", 0))
        if key in db_keys:
            return "key", set(catalog[key]["pools"]), key
        fam_key = f"{str(m.get('group', '')).lower()}|{m.get('ilvl', 0)}"
        if fam_key in db_fam_lvl:
            return "key", db_fam_lvl[fam_key], db_fam_lvl_key.get(fam_key)
        texts = [str(t) for t in (m.get("texts") or [])]
        candidates = [_norm_text(t) for t in texts]
        if len(texts) > 1:
            candidates.append(_norm_text(" ".join(texts)))
        hit_key = next((db_text_key[c] for c in candidates if c in db_text_key), None)
        if hit_key is not None:
            return "text", set(catalog[hit_key]["pools"]), hit_key
        return "none", set(), None

    # pob_key → {pools, catalog_key} (merge가 획득 경로·ko·GAME_DATA 승격에 쓴다)
    match_result: dict[str, dict[str, Any]] = {}
    held = [m for m in pob_mods if not is_included(m)]
    held_keys = {m["pob_key"] for m in held}
    confirmed: list[str] = []
    confirmed_pools: dict[str, int] = {}
    text_only: list[str] = []
    unmatched: list[str] = []
    for m in pob_mods:
        if m["affix_type"] not in ("prefix", "suffix"):
            continue
        how, pools_hit, catalog_key = _pools_for(m)
        if pools_hit:
            match_result[m["pob_key"]] = {"pools": sorted(pools_hit), "key": catalog_key}
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

    # 한글 줄은 슬롯이 아니라 **줄**에 딸린다 — merge가 쓰는 정본 색인 (build_ko_line_index)
    ko_lines, ko_conflicts = build_ko_line_index(catalog)

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mod_texts_ko.json").write_text(
        json.dumps(dict(sorted(ko_lines.items())), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    (out_dir / "mod_catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "catalog_match.json").write_text(
        json.dumps(match_result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "desecrated.json").write_text(
        json.dumps(desecrated, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "base_names_ko.json").write_text(
        json.dumps(dict(sorted(base_names_ko.items())), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
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
        "ko": {
            "catalog_with_ko": sum(1 for v in catalog.values() if v.get("affix_name_ko")),
            # 전역 (영문 줄 → 한글 줄) 색인 — merge가 줄 단위로 짝지을 때 쓰는 정본.
            # conflicts는 한 영문 줄에 한글이 둘 이상이라 **뺀** 줄이다(임의 선택 금지).
            "ko_lines": len(ko_lines),
            "ko_line_conflicts": len(ko_conflicts),
            # 슬롯 키가 유일하지 않아 한 슬롯에 여러 모드의 줄이 쌓인 건수 — 슬롯을
            # 경유해 ko를 붙이면 오염되는 자리다(그래서 전역 색인을 쓴다).
            "slots_with_multiple_texts": sum(1 for v in catalog.values() if len(v["texts"]) > 1),
            "zip_mismatch_skipped": ko_zip_mismatch,
            "base_names_ko": len(base_names_ko),
        },
        "verification": verification_block(cross=[cross]),
    }
    (raw_dir / "modifiers" / "catalog-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
