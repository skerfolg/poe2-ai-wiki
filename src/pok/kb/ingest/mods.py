"""베이스 아이템 + 모드 풀 수집·정형화 (KB_INGEST §6-2 ④, RC4 근거).

소스는 PoB 덤프 단독이다 — 제작규칙(접사 종류·ilvl·그룹 배타·스폰 가중치)이
`ModItem.lua` 계열에 전부 들어 있다. poe2db는 후속 단계에서 ko 이름·교차 대사 축으로
추가한다(리포트의 cross_pending 참고).

획득 경로(⑧)의 원천:
  · item      → 일반 제작 화폐 스폰 풀 (spawn_weights에 양수 가중치 존재)
  · corrupted → 바알 오브
  · rune      → 룬 소켓
  · essence   → Essence.lua가 "모드 키 → 어느 에센스가 부여하는가"의 매핑이다
                (에센스 자체가 모드가 아니라 ⑧ 데이터)
  · item-exclusive 중 spawn_weights 없는 것 → 획득 경로 불명 — ⑧이 드러낸다
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pok.kb.ingest.merge import slug_to_id_part
from pok.kb.ingest.verify import (
    SourceEntity,
    acquisition_coverage,
    cross_source,
    substance_floor,
    verification_block,
)

# PoB type → affix_type
_AFFIX_TYPE = {"Prefix": "prefix", "Suffix": "suffix", "Corrupted": "corrupted", "Rune": "rune"}

# 모드 파일 → origin (파일 계보)
MOD_FILES = (
    ("moditem.json", "item"),
    ("moditemexclusive.json", "item-exclusive"),
    ("modcorrupted.json", "corrupted"),
    ("modflask.json", "flask"),
    ("modcharm.json", "charm"),
    ("modjewel.json", "jewel"),
)


def _texts(raw: dict[str, Any]) -> list[str]:
    """숫자 키("1","2"…)로 들어온 효과 줄들을 순서대로."""
    keys = sorted((k for k in raw if k.isdigit()), key=int)
    return [str(raw[k]) for k in keys]


def _spawn_weights(raw: dict[str, Any]) -> dict[str, int]:
    keys = raw.get("weightKey") or []
    vals = raw.get("weightVal") or []
    return {str(k): int(v) for k, v in zip(keys, vals, strict=False)}


def essence_acquisition(essence: dict[str, Any]) -> tuple[dict[str, list[str]], list[str]]:
    """Essence.lua → (모드 키 → ["essence:<이름>"…], 깨진 참조 목록)."""
    routes_of: dict[str, set[str]] = {}
    for v in essence.values():
        mods = v.get("mods")
        name = str(v.get("name", ""))
        if not isinstance(mods, dict):
            continue
        for mod_key in mods.values():  # 같은 에센스가 여러 슬롯에 같은 모드를 부여 → dedup
            routes_of.setdefault(str(mod_key), set()).add(f"essence:{name}")
    by_mod = {k: sorted(v) for k, v in routes_of.items()}
    return by_mod, sorted(by_mod)


def parse_mod(
    key: str, raw: dict[str, Any], origin: str, essence_routes: dict[str, list[str]]
) -> dict[str, Any]:
    """모드 원시 1건 → 중간 레코드."""
    weights = _spawn_weights(raw)
    acquisition: list[str] = []
    spawnable = any(w > 0 for w in weights.values())
    if origin in ("item", "item-exclusive", "flask", "charm", "jewel") and spawnable:
        acquisition.append("crafting-currency")
    elif origin == "corrupted":
        acquisition.append("vaal-orb")
    acquisition += essence_routes.get(key, [])

    return {
        "pob_key": key,
        "affix_type": _AFFIX_TYPE.get(str(raw.get("type", "")), "prefix"),
        "affix_name": str(raw.get("affix", "")),
        "texts": _texts(raw),
        "group": str(raw.get("group", "")),
        "ilvl": int(raw.get("level", 0)),
        "mod_tags": [str(t) for t in (raw.get("modTags") or [])],
        "spawn_weights": weights,
        "origin": origin,
        "acquisition": acquisition,
    }


def parse_rune(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """룬 1건 → 중간 레코드 (슬롯군별 효과 보존)."""
    per_slot: dict[str, list[str]] = {}
    rank = 0
    for slot, spec in raw.items():
        if not isinstance(spec, dict):
            continue
        per_slot[slot] = _texts(spec)
        ranks = spec.get("rank") or []
        if ranks:
            rank = int(ranks[0])
    return {
        "pob_key": name,
        "affix_type": "rune",
        "affix_name": name,
        "per_slot": per_slot,
        "rank": rank,
        "origin": "rune",
        "acquisition": ["rune-socket"],
    }


def _base_category(raw: dict[str, Any]) -> str:
    """베이스의 계열 — 파일명이 기본이되, PoB가 파일명과 다른 계열을 쓰면 그것을 쓴다.

    `staff.lua`의 육척봉이 그 경우다: 파일명은 `staff`인데 실제 계열은 `Warstaff`이고
    (poe2db에서도 무도 무기다) `tags`에도 `warstaff`만 있다. 파일명을 그대로 쓰면
    **시전용 지팡이와 뭉뚱그려져** 설계가 오판한다 — 실측 2026-08-05: 한 세션이
    `category="staff"`를 보고 육척봉에 caster 룬을 얹으려 했다.

    `subType`은 파일마다 의미가 다르므로(방어구는 Armour/Evasion 같은 방어 타입)
    **무기이면서 파일명이 `tags`에 없을 때만** 쓴다. 실측 검증: 이 조건에 걸리는
    무기는 `staff` 29건뿐이고 나머지 306건은 파일명이 그대로 맞다.
    """
    file_cat = str(raw.get("_base_file", ""))
    tags = {str(k) for k, v in (raw.get("tags") or {}).items() if v}
    if "weapon" not in tags or file_cat in tags:
        return file_cat
    sub = str(raw.get("subType", "")).lower()
    return sub if sub in tags else file_cat


def parse_base(name: str, raw: dict[str, Any]) -> dict[str, Any]:
    """베이스 아이템 1건 → 중간 레코드."""
    out: dict[str, Any] = {
        "name": name,
        "item_class": str(raw.get("type", "")),
        "category": _base_category(raw),
        "spawn_tags": {str(k): bool(v) for k, v in (raw.get("tags") or {}).items()},
        "req": {str(k): v for k, v in (raw.get("req") or {}).items()}
        if isinstance(raw.get("req"), dict)
        else {},
    }
    # flask 수치는 ⑦(정보량 하한)이 잡아낸 누락분 — Flask엔 weapon/armour 대신
    # flask={chargesMax, duration, life|mana}가 실린다 (0.5.4b 실측 18종)
    for field in ("implicit", "socketLimit", "quality", "weapon", "armour", "flask", "subType"):
        if raw.get(field) is not None:
            out[{"socketLimit": "socket_limit", "subType": "sub_type"}.get(field, field)] = raw[
                field
            ]
    if raw.get("implicitModTypes"):
        out["implicit_mod_types"] = raw["implicitModTypes"]
    return out


# ⑦: 실질 수치 없이도 성립할 수 있는 클래스 (플라스크·주얼·부적 등은 별도 체계) —
# 자동 제외하지 않는다. 리포트에 그대로 드러내 사람 판정을 받는다.
def _base_substance(item: dict[str, Any]) -> tuple[str, ...]:
    parts: list[str] = []
    if item.get("implicit"):
        parts.append(str(item["implicit"]))
    for k in ("weapon", "armour", "flask"):
        if item.get(k):
            parts.append(json.dumps(item[k], sort_keys=True))
    return tuple(parts)


def mod_slug(pob_key: str) -> str:
    """모드 id 슬러그 — 트레일링 `_` 변형을 보존한다.

    GGG 데이터는 같은 이름의 신구 변형을 `Key`/`Key__`로 구분하는데(내용이 실제로
    다르다 — 0.5.4b 실측: GrantCursePillarSkillUnique 쌍은 효과 줄 수·그룹이 다름),
    slug_to_id_part는 언더스코어를 지워 충돌한다. 접미로 결정적으로 구분한다.
    """
    stripped = pob_key.rstrip("_")
    n = len(pob_key) - len(stripped)
    return slug_to_id_part(stripped) + (f"-alt{n}" if n else "")


def _dedup_across_pools(
    parsed: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """여러 풀에 **내용까지 동일**하게 실린 모드를 1건으로 병합한다.

    실측(0.5.4b): 플라스크 충전 모드 24종이 ModFlask와 ModCharm에 완전 동일하게
    존재. 계보는 origins 배열로 보존한다(조용한 폐기 금지). 내용이 다르면 병합하지
    않는다 — 그 경우 id 충돌은 merge의 중복 검증이 잡아 사람에게 올라온다.
    """
    by_key: dict[str, dict[str, Any]] = {}
    merged = 0
    out: list[dict[str, Any]] = []
    for src in parsed:
        m = dict(src)  # 입력 무변이
        m["origins"] = [m.pop("origin")]
        prev = by_key.get(m["pob_key"])
        if prev is not None:
            same = {k: v for k, v in prev.items() if k != "origins"} == {
                k: v for k, v in m.items() if k != "origins"
            }
            if same:
                prev["origins"] = sorted(set(prev["origins"]) | set(m["origins"]))
                merged += 1
                continue
        by_key.setdefault(m["pob_key"], m)
        out.append(m)
    return out, merged


def process_mods(raw_dir: Path, out_dir: Path) -> dict[str, Any]:
    """PoB 덤프 → 중간 레코드 + 완전성 ⑥⑦⑧ 리포트 (네트워크 없음, 멱등)."""
    pob = raw_dir / "pob"
    essence = json.loads((pob / "essence.json").read_text(encoding="utf-8"))
    essence_routes, essence_refs = essence_acquisition(essence)

    parsed: list[dict[str, Any]] = []
    for fname, origin in MOD_FILES:
        data = json.loads((pob / fname).read_text(encoding="utf-8"))
        parsed += [parse_mod(k, v, origin, essence_routes) for k, v in sorted(data.items())]
    runes = json.loads((pob / "modrunes.json").read_text(encoding="utf-8"))
    parsed += [parse_rune(k, v) for k, v in sorted(runes.items())]
    mods, pool_merged = _dedup_across_pools(parsed)

    bases_raw = json.loads((pob / "bases.json").read_text(encoding="utf-8"))
    bases = [parse_base(k, v) for k, v in sorted(bases_raw.items())]

    # ── 완전성 기준 ⑥⑦⑧ ──────────────────────────────────────
    mod_keys = {m["pob_key"] for m in mods}
    # ⑥-1 에센스 참조 무결성: 에센스가 가리키는 모드 키가 실존하는가
    essence_cross = cross_source(
        [SourceEntity(key=k, name=k) for k in essence_refs],
        [SourceEntity(key=k, name=k) for k in sorted(mod_keys)],
        labels=("essence-refs", "mods"),
    )
    # ⑥-2 태그 어휘 정합: 모드 spawn_weights의 태그가 실존 베이스 태그인가
    #     (베이스에 없는 태그로만 스폰되는 모드 = 죽은 모드 or PoE1 잔재, KI-8)
    base_tags = {t for b in bases for t in b["spawn_tags"]} | {"default"}
    mod_tag_refs = sorted({t for m in mods for t in m.get("spawn_weights", {})})
    tag_cross = cross_source(
        [SourceEntity(key=t, name=t) for t in mod_tag_refs],
        [SourceEntity(key=t, name=t) for t in sorted(base_tags)],
        labels=("mod-weight-tags", "base-tags"),
    )

    mod_entities = [
        SourceEntity(
            key=m["pob_key"],
            name=m.get("affix_name") or (m.get("texts") or [""])[0],
            substance=tuple(
                m.get("texts") or [x for v in m.get("per_slot", {}).values() for x in v]
            ),
            acquisition=tuple(m.get("acquisition") or []),
        )
        for m in mods
    ]
    base_entities = [
        SourceEntity(
            key=b["name"],
            name=b["name"],
            substance=_base_substance(b),
            # 베이스는 일반 드랍/상점 — 상세 경로는 KB 대상 아님 (유니크 판정과 동일)
            acquisition=("drop",),
        )
        for b in bases
    ]

    verification = verification_block(
        cross=[essence_cross, tag_cross],
        substance=[
            substance_floor(mod_entities, scope="modifier:all"),
            substance_floor(base_entities, scope="base-item:all"),
        ],
        acquisition=[
            acquisition_coverage(
                [e for e, m in zip(mod_entities, mods, strict=True) if origin in m["origins"]],
                entity_type=f"modifier:{origin}",
            )
            for origin in ("item", "item-exclusive", "corrupted", "rune", "flask", "charm", "jewel")
        ],
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "mods.json").write_text(
        json.dumps(mods, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    (out_dir / "base_items.json").write_text(
        json.dumps(bases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )

    by_origin: dict[str, int] = {}
    for m in mods:
        for o in m["origins"]:
            by_origin[o] = by_origin.get(o, 0) + 1
    report: dict[str, Any] = {
        "mods_total": len(mods),
        "pool_merged_duplicates": pool_merged,
        "mods_by_origin": dict(sorted(by_origin.items())),
        "bases_total": len(bases),
        "bases_by_class": dict(
            sorted(
                {
                    c: sum(1 for b in bases if b["item_class"] == c)
                    for c in {b["item_class"] for b in bases}
                }.items()
            )
        ),
        "cross_pending": "poe2db (ko 이름·카탈로그 대사) — 후속 fetch에서 ⑥ 완성",
        "verification": verification,
    }
    (pob / "mods-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


# 수록 판정 (사람 승인 2026-07-29, KI-3):
#   A = 일반 풀 — corrupted·rune·flask·charm·jewel 전량 + item 중 획득 경로 보유분
#   B = item-exclusive 전량 (특정 아이템 고정 모드 — 스폰 가중치가 없는 게 정상)
#   C = item 풀인데 스폰 불가 ∧ 에센스 아님 → **보류**(미수록). KI-8상 획득 양성 증거 없음.
_ALWAYS_INCLUDE = frozenset({"item-exclusive", "corrupted", "rune", "flask", "charm", "jewel"})


def is_included(mod: dict[str, Any]) -> bool:
    """A·B 수록 판정. item 전용 풀만 획득 경로를 요구한다 (KI-8의 신호 A)."""
    if set(mod["origins"]) & _ALWAYS_INCLUDE:
        return True
    return bool(mod.get("acquisition"))


def _write_shards(
    out_dir: Path, prefix: str, records: list[dict[str, Any]], max_bytes: int = 1_500_000
) -> list[str]:
    """id 순으로 NDJSON 샤드에 쓰고 파일명을 돌려준다 (샤드당 크기 상한 준수).

    pre-commit의 대용량 파일 차단(2MB)에 걸리지 않도록 나눈다 — 벌크 카탈로그는
    NDJSON 샤드라는 KD-1 배치를 그대로 따르며, 분할 단위는 크기뿐이다.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    part: list[str] = []
    size, idx = 0, 1
    for rec in sorted(records, key=lambda r: str(r["id"])):
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        encoded = len(line.encode("utf-8"))
        if part and size + encoded > max_bytes:
            name = f"{prefix}-{idx:02d}.ndjson"
            (out_dir / name).write_text("".join(part), encoding="utf-8")
            written.append(name)
            part, size, idx = [], 0, idx + 1
        part.append(line)
        size += encoded
    if part:
        name = f"{prefix}-{idx:02d}.ndjson"
        (out_dir / name).write_text("".join(part), encoding="utf-8")
        written.append(name)
    return written


def _record_exclusions(knowledge: Path, patch: str, pob_keys: list[str], evidence: str) -> int:
    """미획득 모드를 제외 원장에 기록한다 (KI-8 — 매 패치 재검증·부활 감지 대상).

    같은 패치의 기존 기재는 교체한다(재실행 멱등). 다른 패치 기재는 보존.
    """
    path = knowledge / "ingest" / "exclusions.json"
    ledger: dict[str, Any] = (
        json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1}
    )
    prior: list[dict[str, Any]] = ledger.get("unobtainable_mods") or []
    entries = [e for e in prior if e.get("patch") != patch]
    entries.append(
        {
            "patch": patch,
            "approved": "2026-07-30 user",
            "evidence": evidence,
            "pob_keys": sorted(pob_keys),
        }
    )
    ledger["unobtainable_mods"] = entries
    path.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return len(pob_keys)


def desecrated_to_records(
    tables: dict[str, list[dict[str, Any]]],
    catalog: dict[str, dict[str, Any]],
    patch: str,
) -> list[dict[str, Any]]:
    """Desecrated 테이블 → Modifier 레코드 (poe2db 단독 소스 — PoB에 없는 신규 모드군).

    id는 (대상군, 접사명, 효과 텍스트)에서 결정적으로 만든다 — 같은 접사명이 다른
    효과로 수십 번 나오기 때문(Amanamu's 등). 카탈로그 desecrated 풀과 텍스트로
    맞으면 적용 클래스·패밀리를 보강한다.
    """
    from pok.kb.ingest.mod_catalog import _norm_text as norm_text

    cat_by_text: dict[str, dict[str, Any]] = {}
    for v in catalog.values():
        if "desecrated" in v.get("pools", {}):
            for tx in v["texts"]:
                cat_by_text.setdefault(norm_text(tx), v)

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for scope, rows in sorted(tables.items()):
        for row in rows:
            base = slug_to_id_part(f"desecrated {scope} {row['affix_name']} {row['text']}")[:90]
            rid = f"modifier.{base}"
            n = 2
            while rid in seen:  # 같은 (군·접사·텍스트)가 겹치면 결정적 접미
                rid = f"modifier.{base}-{n}"
                n += 1
            seen.add(rid)
            data: dict[str, Any] = {
                "affix_type": row["affix_type"]
                if row["affix_type"] in ("prefix", "suffix")
                else "prefix",
                "origins": ["desecrated"],
                "affix_name": row["affix_name"],
                "texts": [row["text"]],
                "scope": scope,  # equipment | jewel | waystone
                "acquisition": ["desecration"],
            }
            if row.get("text_ko"):
                data["texts_ko"] = [row["text_ko"]]
            if row.get("ilvl"):
                data["ilvl"] = row["ilvl"]
            if row.get("mod_tags"):
                data["mod_tags"] = row["mod_tags"]
            hit = cat_by_text.get(norm_text(row["text"]))
            if hit:
                if hit.get("families"):
                    data["group"] = "+".join(hit["families"])
                pages = sorted({p for p in hit["pools"].get("desecrated", [])})
                if pages:
                    data["applicable_pages"] = pages
            records.append(
                {
                    "id": rid,
                    "type": "Modifier",
                    "name": {
                        "ko": row.get("affix_name_ko") or row["affix_name"],
                        "en": row["affix_name"],
                    },
                    "tags": [],
                    "data": data,
                    "verification": "SUPPORTED_INFERENCE",  # poe2db 단독 소스
                    "sources": [
                        {
                            "src": "poe2db",
                            "ref": "https://poe2db.tw/us/Desecrated_Modifiers",
                            "patch": patch,
                        }
                    ],
                }
            )
    return records


def merge_mods(out_dir: Path, knowledge: Path, patch: str) -> dict[str, Any]:
    """승인 범위를 knowledge/에 기록하고 전체 재검증한다 (KI-3 게이트 뒤에서만).

    2026-07-30 승인 확장:
      · poe2db 카탈로그(catalog_match.json)에 잡힌 보류 모드 → 수록 승격
      · 잡히지 않은 보류 모드 → 제외 + 원장 기록 (양 소스 모두 획득 경로 없음)
      · 수록 모드 전체에 poe2db 풀 획득 경로(poe2db:<pool>) 부착
      · Desecrated 테이블(249) → 신규 Modifier 레코드 (poe2db 단독)
    """
    from pok.kb.ingest.merge import POB_COMMIT
    from pok.kb.store import load as store_load

    mods = json.loads((out_dir / "mods.json").read_text(encoding="utf-8"))
    bases = json.loads((out_dir / "base_items.json").read_text(encoding="utf-8"))

    match_path = out_dir / "catalog_match.json"
    match: dict[str, dict[str, Any]] = (
        json.loads(match_path.read_text(encoding="utf-8")) if match_path.exists() else {}
    )
    catalog_path = out_dir / "mod_catalog.json"
    catalog: dict[str, dict[str, Any]] = (
        json.loads(catalog_path.read_text(encoding="utf-8")) if catalog_path.exists() else {}
    )
    for m in mods:  # poe2db 풀 = 획득 경로 (E-2 실존 풀 연결 포함)
        info = match.get(m["pob_key"]) or {}
        routes = [f"poe2db:{p}" for p in info.get("pools", [])]
        if routes:
            m["acquisition"] = sorted(set(m.get("acquisition") or []) | set(routes))

    included = [m for m in mods if is_included(m)]
    held = [m for m in mods if not is_included(m)]
    excluded_count = _record_exclusions(
        knowledge,
        patch,
        [m["pob_key"] for m in held],
        "PoB 스폰 가중치 전부 0 ∧ 에센스 매핑 없음 ∧ poe2db 카탈로그(클래스별 전 풀) 미등재",
    )

    from pok.kb.ingest.heart_mods import SHARD as HEART_SHARD

    mod_dir = knowledge / "game-data" / "modifiers"
    base_dir = knowledge / "game-data" / "base-items"
    for stale in list(mod_dir.glob("*.ndjson")) + list(base_dir.glob("*.ndjson")):
        if stale.name == HEART_SHARD:
            continue  # 다른 단계(heart_mods)가 소유하는 샤드 — 여기서 지우면 재실행이 KB를 깎는다
        stale.unlink()  # 샤드 경계가 바뀌어도 잔재가 남지 않게 (멱등)

    by_pool: dict[str, list[dict[str, Any]]] = {}
    ko_attached = 0
    upgraded = 0
    for m in included:
        rec = mod_to_record(m, patch, POB_COMMIT)
        info = match.get(m["pob_key"]) or {}
        entry = catalog.get(info.get("key") or "")
        if entry is not None:
            # 양 소스(poe2db∧PoB) 확인 → GAME_DATA 승격 (유니크 때의 라벨 규칙과 동일)
            rec["verification"] = "GAME_DATA"
            upgraded += 1
            rec["sources"].append(
                {"src": "poe2db", "ref": "us/<class>#ModifiersCalc", "patch": patch}
            )
            # 이름 ko는 poe2db 접사명이 PoB 접사명과 일치할 때만 — Alloy 계열은
            # poe2db Name이 부여 화폐명이라 그대로 쓰면 접사명이 화폐명으로 오염된다
            # (실측: 'of the Stars'에 '회오리바람 합금'이 붙음)
            same_affix = (
                str(entry.get("affix_name", "")).strip().lower()
                == str(m.get("affix_name", "")).strip().lower()
            )
            if entry.get("affix_name_ko") and same_affix:
                rec["name"]["ko"] = entry["affix_name_ko"]
                ko_attached += 1
            if entry.get("texts_ko"):
                rec["data"]["texts_ko"] = entry["texts_ko"]
        by_pool.setdefault(m["origins"][0], []).append(rec)

    base_ko_path = out_dir / "base_names_ko.json"
    base_names_ko: dict[str, str] = (
        json.loads(base_ko_path.read_text(encoding="utf-8")) if base_ko_path.exists() else {}
    )

    desecrated_path = out_dir / "desecrated.json"
    if desecrated_path.exists():
        tables = json.loads(desecrated_path.read_text(encoding="utf-8"))
        by_pool["desecrated"] = desecrated_to_records(tables, catalog, patch)
    mod_files: list[str] = []
    for pool, recs in sorted(by_pool.items()):
        mod_files += _write_shards(mod_dir, pool, recs)

    base_records = []
    base_ko_attached = 0
    for b in bases:
        rec = base_to_record(b, patch, POB_COMMIT)
        ko = base_names_ko.get(b["name"])
        if ko:
            rec["name"]["ko"] = ko
            base_ko_attached += 1
        base_records.append(rec)
    base_files = _write_shards(base_dir, "bases", base_records)

    after = store_load(knowledge.parent)  # 스키마·중복·참조 무결성 전량 재검증
    return {
        "mods_included": len(included),
        "mods_excluded_to_ledger": excluded_count,  # 원장 기록 (KI-8 부활 감지 대상)
        "mods_with_poe2db_routes": sum(
            1 for m in included if any(str(r).startswith("poe2db:") for r in m["acquisition"])
        ),
        "mods_by_pool": {k: len(v) for k, v in sorted(by_pool.items())},
        "verification_upgraded": upgraded,  # POB_CODE → GAME_DATA (양 소스 확인)
        "ko_names": {"mods": ko_attached, "bases": base_ko_attached},
        "bases_written": len(bases),
        "shards": {"modifiers": len(mod_files), "base-items": len(base_files)},
        "kb_total": len(after.records),
    }


def mod_to_record(item: dict[str, Any], patch: str, pob_commit: str) -> dict[str, Any]:
    """중간 레코드 → Modifier envelope 레코드 (merge 단계, 승인 후 사용)."""
    data: dict[str, Any] = {
        "affix_type": item["affix_type"],
        "origins": item["origins"],
        "pob_key": item["pob_key"],
    }
    for k in (
        "affix_name",
        "texts",
        "per_slot",
        "group",
        "ilvl",
        "rank",
        "mod_tags",
        "spawn_weights",
        "acquisition",
    ):
        if item.get(k) or item.get(k) == 0:
            data[k] = item[k]
    name_en = item.get("affix_name") or (item.get("texts") or ["(unnamed)"])[0]
    return {
        "id": f"modifier.{mod_slug(item['pob_key'])}",
        "type": "Modifier",
        "name": {"ko": name_en, "en": name_en},  # ko는 poe2db 대사 후 갱신
        "tags": [],
        "data": data,
        "verification": "POB_CODE",  # PoB 단독 소스 — poe2db 대사 후 GAME_DATA 승격
        "sources": [
            {
                "src": "pob",
                "ref": "Data/" + "+".join(item["origins"]),
                "patch": patch,
                "pob": pob_commit,
            }
        ],
    }


def base_to_record(item: dict[str, Any], patch: str, pob_commit: str) -> dict[str, Any]:
    """중간 레코드 → Item(베이스) envelope 레코드 (merge 단계, 승인 후 사용)."""
    data: dict[str, Any] = {"rarity": "normal"}
    for k in (
        "item_class",
        "category",
        "implicit",
        "implicit_mod_types",
        "spawn_tags",
        "weapon",
        "armour",
        "flask",
        "sub_type",
        "socket_limit",
        "quality",
        "req",
    ):
        if item.get(k):
            data[k] = item[k]
    return {
        "id": f"item.{slug_to_id_part(item['name'])}",
        "type": "Item",
        "name": {"ko": item["name"], "en": item["name"]},  # ko는 poe2db 대사 후 갱신
        "tags": [],
        "data": data,
        "verification": "POB_CODE",
        "sources": [{"src": "pob", "ref": "Data/Bases", "patch": patch, "pob": pob_commit}],
    }
