"""④ merge — 판정 통과분(intermediate)을 KB 정본 레코드로 변환 (KB_INGEST §2 ⑦ 직전).

- KD-1 혼합 배치: 기존 큐레이션 레코드(시드)와 id가 겹치면 **그 개별 JSON을 갱신**
  (수작업 관계·조건·facets·notes 보존), 나머지는 NDJSON 벌크 샤드로.
- 검증 라벨: 양 소스(poe2db∧PoB) 확인 = GAME_DATA, 단일 소스 = SUPPORTED_INFERENCE.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.parse
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pok.kb.ingest.process import INCLUDE_VERDICTS, NO_ACQ, NO_POB, RULED_OUT_VERDICTS
from pok.kb.pob_pin import POB_COMMIT as _PIN_COMMIT
from pok.kb.store import load as store_load
from pok.kb.store import write_record, write_shard

# 핀의 authoring point는 `pok.kb.pob_pin` 하나다(#16). 여기서는 재수출만 한다 —
# 임포터가 많아 이름을 옮기면 호출부가 흩어진다.
POB_COMMIT = _PIN_COMMIT

# 기계(ingest)가 소유하는 최상위 필드 — 재실행 시 새 값으로 덮어쓴다.
# 그 밖의 필드는 후속 단계·사람이 붙인 보강으로 보고 샤드 재생성 때 보존한다.
MACHINE_TOP_KEYS = frozenset(
    {"id", "type", "name", "tags", "data", "verification", "sources", "notes"}
)
# _to_record가 채우는 data 키 (기계 소유). 이 목록 밖의 data 키 = 보강분 → 보존
# (gem_costs의 cost·reservation·cost_multiplier_pct, gem_colors의 색 정보 등).
_MACHINE_DATA_KEYS = frozenset(
    {
        "description",
        "tier",
        "category",
        "pob_computable",
        "acquisition_unknown",
        # 새 data 키는 여기에도 등록해야 재수집이 갱신한다 (실측 사고: 미등록 키는
        # 기계 산출인데도 사람 판정으로 취급돼 재수집이 덮지 못했다)
        "stats",
        "implicit_stats",
        "quality_stats",
        "minion_stats",
        "engine_stats",
        # 부여 스킬 판정 (#4) — 기계 산출이므로 재수집이 갱신해야 한다
        "source",
        "granted_by",
        "granted_by_ids",
    }
)
# ingest가 붙일 수 있는 검증 라벨 전부. 그 밖의 라벨(IN_GAME·CONTRADICTED…)은
# 사람 판정의 결과이므로 재실행이 기계 라벨로 되돌리면 안 된다 (사용자 = 게임 지식 게이트).
MACHINE_VERIFICATION = frozenset({"GAME_DATA", "SUPPORTED_INFERENCE"})

# 카테고리 → KB 타입 (스피릿 젬 = 지속 스킬, 혈통 = 서포트)
_TYPE_OF_CATEGORY = [
    ("skill-gems", "Skill"),
    ("spirit-gems", "Skill"),
    ("support-gems", "Support"),
    ("lineage-supports", "Support"),
]
_ID_PREFIX = {"Skill": "skill", "Support": "support"}


def slug_to_id_part(slug: str) -> str:
    """poe2db slug → id 슬러그 (URL 디코드, 악센트 제거, 소문자, 하이픈)."""
    s = urllib.parse.unquote(slug)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("'", "").replace("\u2019", "")  # 곧은/굽은 아포스트로피 제거
    out = []
    for ch in s.lower():
        out.append(ch if ch.isalnum() else "-")
    joined = "".join(out)
    while "--" in joined:
        joined = joined.replace("--", "-")
    return joined.strip("-")


def _kb_type(categories: list[str]) -> str:
    for cat, t in _TYPE_OF_CATEGORY:
        if cat in categories:
            return t
    return "Skill"


def _infer_category(tags: list[str]) -> str | None:
    low = {t.lower() for t in tags}
    if "minion" in low:
        return "minion"
    if "attack" in low:
        return "attack"
    if "spell" in low:
        return "spell"
    return None


# 젬으로 획득하는 스킬의 From 카드 표기. 이것 말고는 **아이템 이름**이 온다.
_GEM_ROUTES = ("uncut skill gem", "uncut spirit gem", "uncut support gem")


def skill_source(
    acquisition: list[str], item_ids: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """From 카드 → `source`(+`granted_by`) (백로그 #4, 사용자 판정 2026-08-09).

    젬 스킬과 아이템 부여 스킬이 구분되지 않아 `skill.purity-of-fire`·`skill.malice`를
    **젬 오라로 오인**해 정신력 배분표에 넣었다. 실제로는 셉터 부여라 젬으로 못 켜고
    **셉터당 하나만** 고를 수 있어 서로 배타다.

    사용자 지적대로 판정 근거는 **poe2db의 획득 출처**에 이미 있었다 — 실측:

        skill.fireball          ['Uncut Skill Gem']   → gem
        skill.purity-of-fire    ['Shrine Sceptre']    → item-granted
        skill.malice            ['Omen Sceptre']      → item-granted

    ⚠ 빈 출처는 **모른다**로 둔다 — `gem`으로 넘겨짚으면 같은 오인이 재발한다.

    ⚠ From 카드에 오는 것이 **아이템만은 아니다**: 실측 427종 중 150종이 KB Item으로
    해석되지 않고 그중 상당수가 전직 노드·다른 스킬이다(`Archon of Chayula` ·
    `Called Shots`). 그래서 `item_ids`로 실제 해석되는 것만 `item-granted`라 부르고,
    나머지는 `other-granted`로 남긴다 — **이름을 지어내지 않는다.**
    """
    if not acquisition:
        return {}
    if any(route.lower() in _GEM_ROUTES for route in acquisition):
        return {"source": "gem"}
    names = sorted(acquisition)
    out: dict[str, Any] = {"granted_by": names}
    known = item_ids or {}
    resolved = sorted({known[n.lower()] for n in names if n.lower() in known})
    if resolved:
        out["source"] = "item-granted"
        out["granted_by_ids"] = resolved
    else:
        out["source"] = "other-granted"
    return out


def _record_id(item: dict[str, Any]) -> str:
    """intermediate 항목 → KB id. 제외 판정분도 id를 알아야 기존 레코드와 대조할 수 있다."""
    return f"{_ID_PREFIX[_kb_type(item['categories'])]}.{slug_to_id_part(item['slug'])}"


def _to_record(
    item: dict[str, Any], patch: str, item_ids: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """intermediate 항목 → envelope 레코드 (신규 벌크용)."""
    rtype = _kb_type(item["categories"])
    rid = _record_id(item)
    tags = sorted({t.lower().replace(" ", "-") for t in item["tags"] if t.strip()})
    data: dict[str, Any] = {}
    if item.get("description"):
        data["description"] = item["description"]
    # 효과 문구 — 배율·확률이 여기 있다. `description`(산문)만으로는 젬을 고를 수 없다
    for key in ("stats", "implicit_stats", "quality_stats", "minion_stats", "engine_stats"):
        if item.get(key):
            data[key] = item[key]
    if item.get("tier") is not None:
        data["tier"] = item["tier"]
    if rtype == "Skill":
        cat = _infer_category(item["tags"])
        if cat:
            data["category"] = cat
        data.update(skill_source(item.get("acquisition") or [], item_ids))
    if item["verdict"] == NO_POB:
        data["pob_computable"] = False  # PoB 미지원 — compute 단계에서 거부 근거
    if item["verdict"] == NO_ACQ:
        # 실존 증거는 레벨효과표뿐 — poe2db가 획득 경로(From 카드)를 표기하지 않았다.
        # 조건 1급 원칙(RC1)상 "경로를 모른다"는 사실을 지우지 않고 데이터로 남긴다.
        data["acquisition_unknown"] = True
    sources: list[dict[str, Any]] = [
        {
            "src": "poe2db",
            "ref": f"https://poe2db.tw/us/{item['slug']}",
            "patch": patch,
        }
    ]
    if item["in_pob"]:
        sources.append(
            {"src": "pob", "ref": str(item["pob_meta_id"]), "patch": patch, "pob": POB_COMMIT}
        )
    record: dict[str, Any] = {
        "id": rid,
        "type": rtype,
        "name": {"ko": item["name_ko"] or item["name_en"], "en": item["name_en"]},
        "tags": tags,
        "data": data,
        "verification": "GAME_DATA" if item["in_pob"] else "SUPPORTED_INFERENCE",
        "sources": sources,
    }
    if item["verdict"] in {"include-basic-attack"}:
        record["notes"] = "무기 기본 공격 — 획득 경로 없이 기본 제공 (사람 승인 2026-07-29)"
    elif item["verdict"] in {"include-lineage"}:
        record["notes"] = "혈통 서포트 — 특수 획득 (Lineage_Supports 목록 근거)"
    return record


def _update_seed(seed_raw: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """시드(큐레이션) 레코드에 ingest 결과를 병합 — 수작업 필드 보존."""
    merged = dict(seed_raw)
    merged["name"] = new["name"]
    merged["tags"] = new["tags"]  # D11: 게임 공식 태그가 시드 추정 태그를 대체
    merged["verification"] = new["verification"]
    merged["sources"] = new["sources"]
    merged["data"] = {**seed_raw.get("data", {}), **new["data"]}
    # conditions/relations/facets/notes = 시드 수작업 그대로 유지
    return merged


def keep_human_verdict(prev_raw: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """사람 판정 라벨이 붙은 레코드면 라벨·근거(notes·in-game 소스)를 그대로 남긴다.

    기계는 GAME_DATA/SUPPORTED_INFERENCE만 낸다 — 그 밖의 라벨은 사람이 인게임으로
    확인·반박한 결과라, 재실행이 덮으면 판정 이력이 조용히 사라진다.
    """
    if prev_raw.get("verification") in MACHINE_VERIFICATION:
        return new
    merged = dict(new)
    merged["verification"] = prev_raw["verification"]
    if prev_raw.get("notes"):
        merged["notes"] = prev_raw["notes"]
    human_sources = [s for s in prev_raw.get("sources", []) if s.get("src") == "in-game"]
    if human_sources:
        merged["sources"] = [*new["sources"], *human_sources]
    return merged


def merge_shard_record(
    prev_raw: dict[str, Any], new: dict[str, Any], machine_data_keys: frozenset[str]
) -> dict[str, Any]:
    """샤드(벌크) 레코드 갱신 — 기계 소유 필드는 새 값, 후속 보강 필드는 보존.

    샤드는 통째로 다시 쓰므로, 병합 이후 다른 단계가 붙인 필드(예: 트리 노드의
    성유 부여 정보)는 여기서 되살리지 않으면 재실행마다 사라진다.
    반대로 기계 소유 키는 남기지 않는다 — 소스에서 빠진 값이 눌러붙으면 안 된다.
    """
    kept = {k: v for k, v in prev_raw.items() if k not in MACHINE_TOP_KEYS}
    kept_data = {k: v for k, v in prev_raw.get("data", {}).items() if k not in machine_data_keys}
    merged = {**keep_human_verdict(prev_raw, new), **kept}
    merged["data"] = {**new["data"], **kept_data}
    return merged


def merge_patch(
    raw_dir: Path, intermediate_path: Path, knowledge: Path, patch: str
) -> dict[str, Any]:
    """수록 판정분을 knowledge/에 기록한다. 반환: 요약."""
    items = json.loads(intermediate_path.read_text(encoding="utf-8"))
    included = [i for i in items if i["verdict"] in INCLUDE_VERDICTS]

    existing = store_load(knowledge.parent)  # 검증 겸 현재 정본 로드
    # From 카드의 이름을 실제 아이템으로 해석하는 색인 — 없는 것을 `item-granted`라
    # 부르지 않기 위해서다(#4: 전직 노드·다른 스킬도 From 카드에 온다).
    item_ids = {
        rec.name_en.lower(): rid for rid, rec in existing.records.items() if rec.type == "Item"
    }
    updated_seeds = 0
    bulk: dict[str, list[dict[str, Any]]] = {"Skill": [], "Support": []}
    for item in included:
        rec = _to_record(item, patch, item_ids)
        prev = existing.records.get(rec["id"])
        if prev is not None and not prev.in_shard:
            # 개별 큐레이션 JSON 시드 → 그 파일만 갱신 (수작업 관계·조건·facets·notes 보존).
            # 쓰기는 store 단일 경로로 (B-6) — 샤드 경로가 오면 거기서 거부된다.
            write_record(
                prev.path, _update_seed(prev.raw, rec), root=knowledge.parent, validate=False
            )
            updated_seeds += 1
        else:
            # 신규 또는 이미 샤드에 있는 레코드 → 벌크 재생성 경로.
            # 샤드 소속을 시드로 착각해 prev.path(=샤드 파일 전체)에 쓰면 샤드가 파괴된다
            # (실측 2026-08-02: 884→54줄 · 2026-08-03: skills 363→0·supports 521→0).
            # 후처리 보강분(cost·color 등)은 merge_shard_record가 함께 보존한다.
            bulk[rec["type"]].append(
                rec if prev is None else merge_shard_record(prev.raw, rec, _MACHINE_DATA_KEYS)
            )

    # 이번 수록분에 없는 기존 벌크 레코드의 처리 — 삭제는 **판정 근거가 있을 때만**.
    #  · 원장 근거가 적힌 제외 판정(통합·현 패치 미획득)분: 삭제한다.
    #  · 그 밖의 미포함분(부분 merge·파싱 갭 등): 보존하고 삭제 후보로 리포트한다.
    # 근거 없이 지우면 부분 merge가 KB를 깎고(2026-08-02 830건 손실), 무조건 보존하면
    # 사용자 제외 판정이 무효가 된다 — 나열 후 사람이 판단한다(사용자 확립 원칙).
    ruled_out = {_record_id(i) for i in items if i["verdict"] in RULED_OUT_VERDICTS}
    written = {r["id"] for records in bulk.values() for r in records}
    removed: list[str] = []
    candidates: list[str] = []
    for prev in existing.records.values():
        if not prev.in_shard or prev.type not in bulk or prev.id in written:
            continue
        if prev.id in ruled_out:
            removed.append(prev.id)
            continue
        candidates.append(prev.id)
        bulk[prev.type].append(prev.raw)

    out_dir = knowledge / "game-data" / "gems"
    shard_of = {"Skill": "skills.ndjson", "Support": "supports.ndjson"}
    for rtype, records in bulk.items():
        # 쓰기는 store 단일 경로로 (B-6): 원자적 쓰기 + 근거 없는 레코드 감소 거부.
        # 삭제는 원장 근거가 있는 ruled_out만 허용한다.
        write_shard(
            out_dir / shard_of[rtype],
            records,
            allow_delete=removed,
            root=knowledge.parent,
            validate=False,
        )

    # 병합 후 전체 재검증 (스키마·참조 무결성) — 실패 시 예외로 중단
    after = store_load(knowledge.parent)
    return {
        "included": len(included),
        "updated_seeds": updated_seeds,
        "bulk_skills": len(bulk["Skill"]),
        "bulk_supports": len(bulk["Support"]),
        "removed_by_ruling": sorted(removed),  # 원장 근거로 삭제한 레코드
        "deletion_candidates": sorted(candidates),  # 미포함이나 근거 없음 — 보존, 사람 판정 대기
        "total_records": len(after.records),
    }
