"""④ merge — 판정 통과분(intermediate)을 KB 정본 레코드로 변환 (KB_INGEST §2 ⑦ 직전).

- KD-1 혼합 배치: 기존 큐레이션 레코드(시드)와 id가 겹치면 **그 개별 JSON을 갱신**
  (수작업 관계·조건·facets·notes 보존), 나머지는 NDJSON 벌크 샤드로.
- 검증 라벨: 양 소스(poe2db∧PoB) 확인 = GAME_DATA, 단일 소스 = SUPPORTED_INFERENCE.
"""

from __future__ import annotations

import json
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from pok.kb.ingest.process import INCLUDE_VERDICTS, NO_ACQ, NO_POB
from pok.kb.store import load as store_load

POB_COMMIT = "5d173cbf8c9cf394a975cbb813f19d0b6dc67ea6"

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


def _to_record(item: dict[str, Any], patch: str) -> dict[str, Any]:
    """intermediate 항목 → envelope 레코드 (신규 벌크용)."""
    rtype = _kb_type(item["categories"])
    rid = f"{_ID_PREFIX[rtype]}.{slug_to_id_part(item['slug'])}"
    tags = sorted({t.lower().replace(" ", "-") for t in item["tags"] if t.strip()})
    data: dict[str, Any] = {}
    if item.get("description"):
        data["description"] = item["description"]
    if item.get("tier") is not None:
        data["tier"] = item["tier"]
    if rtype == "Skill":
        cat = _infer_category(item["tags"])
        if cat:
            data["category"] = cat
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


def merge_patch(
    raw_dir: Path, intermediate_path: Path, knowledge: Path, patch: str
) -> dict[str, Any]:
    """수록 판정분을 knowledge/에 기록한다. 반환: 요약."""
    items = json.loads(intermediate_path.read_text(encoding="utf-8"))
    included = [i for i in items if i["verdict"] in INCLUDE_VERDICTS]

    existing = store_load(knowledge.parent)  # 검증 겸 현재 정본 로드
    updated_seeds = 0
    bulk: dict[str, list[dict[str, Any]]] = {"Skill": [], "Support": []}
    for item in included:
        rec = _to_record(item, patch)
        prev = existing.records.get(rec["id"])
        if prev is not None and prev.path.suffix == ".ndjson":
            # 기존 벌크 레코드 — **개별 파일처럼 쓰면 샤드 전체가 한 줄로 잘린다**
            # (실측 2026-08-02: 884줄 → 54줄, 830건 손실). 병합해서 벌크로 되돌린다.
            # data 병합이 후처리 보강분(cost·color 등)도 함께 보존한다.
            bulk[rec["type"]].append(_update_seed(prev.raw, rec))
        elif prev is not None:
            merged = _update_seed(prev.raw, rec)
            prev.path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            updated_seeds += 1
        else:
            bulk[rec["type"]].append(rec)

    # 이번 ingest에 없는 기존 벌크 레코드도 샤드에 남긴다 — 샤드를 포함분만으로
    # 다시 쓰면 부분 merge에서 나머지가 삭제된다 (회귀 방지, 2026-08-02).
    written = {r["id"] for records in bulk.values() for r in records}
    for prev in existing.records.values():
        if prev.path.suffix == ".ndjson" and prev.type in bulk and prev.id not in written:
            bulk[prev.type].append(prev.raw)

    out_dir = knowledge / "game-data" / "gems"
    out_dir.mkdir(parents=True, exist_ok=True)
    shard_of = {"Skill": "skills.ndjson", "Support": "supports.ndjson"}
    for rtype, records in bulk.items():
        shard = out_dir / shard_of[rtype]
        shard.write_text(
            "".join(
                json.dumps(r, ensure_ascii=False) + "\n"
                for r in sorted(records, key=lambda r: str(r["id"]))
            ),
            encoding="utf-8",
        )

    # 병합 후 전체 재검증 (스키마·참조 무결성) — 실패 시 예외로 중단
    after = store_load(knowledge.parent)
    return {
        "included": len(included),
        "updated_seeds": updated_seeds,
        "bulk_skills": len(bulk["Skill"]),
        "bulk_supports": len(bulk["Support"]),
        "total_records": len(after.records),
    }
