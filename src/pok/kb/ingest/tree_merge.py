"""패시브 트리 청크 → KB 정본 레코드 (분할 merge).

청크(keystone/ascendancy-start/notable/mastery/jewel/small) 단위로 독립 실행 가능 —
대량 데이터를 한 번에 밀어넣지 않고 검증하며 나눠 반영한다.

엣지(connections)는 P4 Steiner 연결의 기반이라 `data.connections`에 노드 id로 보존한다.
(관계 그래프 `relations`는 KB 엔티티 간 의미 관계용이므로 트리 인접은 data에 둔다.)

⚠️ **트리 엣지는 단방향 저장·무방향 의미**: 소스가 각 엣지를 한쪽에만 기록하므로
어떤 노드의 `connections`가 비어 있어도 고립이 아니다(예: Chaos Inoculation).
소비 측(P4 트리 최적화)은 반드시 **양방향으로 펼쳐** 인접을 구성해야 한다.
0.5.4b 실측: 6,070 무방향 엣지가 5,130 노드를 단일 연결 요소로 연결.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pok.kb.ingest.merge import slug_to_id_part
from pok.kb.store import load as store_load

_KIND_TO_DATA = {
    "keystone": "keystone",
    "notable": "notable",
    "small": "small",
    "ascendancy-start": "ascendancy-start",
    "mastery": "mastery",
    "jewel": "jewel-socket",
}
_SHARD = {
    "keystone": "keystones.ndjson",
    "ascendancy-start": "ascendancy-starts.ndjson",
    "notable": "notables.ndjson",
    "mastery": "masteries.ndjson",
    "jewel": "jewel-sockets.ndjson",
    "small": "small.ndjson",
}


def _to_record(item: dict[str, Any], patch: str) -> dict[str, Any]:
    """트리 노드 → Passive 레코드. id는 노드 id를 포함해 동명이인을 구분한다."""
    slug = slug_to_id_part(item["name_en"]) or "unnamed"
    rid = f"passive.{slug}-{item['node_id']}"
    data: dict[str, Any] = {
        "kind": _KIND_TO_DATA[item["kind"]],
        "node_id": item["node_id"],
        "stats": item["stats_ko"] or item["stats_en"],
        "stats_en": item["stats_en"],
        "connections": item["connections"],  # P4 Steiner 기반 (엣지 보존)
    }
    if item.get("ascendancy"):
        data["ascendancy"] = item["ascendancy"]
    if item.get("attribute_choice"):
        # 셋 중 택1 — 평평한 stats로 두면 "셋 다 부여"로 읽힌다 (tree.extract_attribute_choice).
        # 요구치 충족·스탯 스태킹 판단에 쓰이므로 기계가 읽을 수 있는 형태로 둔다.
        data["attribute_choice"] = item["attribute_choice"]
    if not item["in_pob"]:
        data["pob_computable"] = False
    sources: list[dict[str, Any]] = [
        {
            "src": "poe2db",
            "ref": f"https://poe2db.tw/us/passive-skill-tree/#{item['node_id']}",
            "patch": patch,
        }
    ]
    if item["in_pob"]:
        sources.append(
            {"src": "pob", "ref": f"TreeData/0_5 node {item['node_id']}", "patch": patch}
        )
    return {
        "id": rid,
        "type": "Passive",
        "name": {"ko": item["name_ko"], "en": item["name_en"]},
        "tags": [],  # 트리 노드엔 게임 공식 태그가 없다 (D11: 없으면 비운다)
        "data": data,
        "verification": "GAME_DATA" if item["in_pob"] else "SUPPORTED_INFERENCE",
        "sources": sources,
    }


def merge_tree(chunk_dir: Path, knowledge: Path, patch: str, kind: str) -> dict[str, Any]:
    """청크 하나를 NDJSON 샤드로 기록하고 전체 재검증한다."""
    items = json.loads((chunk_dir / f"tree_{kind}.json").read_text(encoding="utf-8"))
    existing = store_load(knowledge.parent)

    records: list[dict[str, Any]] = []
    updated_seeds = 0
    seed_by_name = {
        r.name_en.lower(): r
        for r in existing.records.values()
        if r.type == "Passive" and not r.id.split("-")[-1].isdigit()
    }
    for item in items:
        rec = _to_record(item, patch)
        seed = seed_by_name.get(item["name_en"].lower())
        if seed is not None:
            merged = dict(seed.raw)
            merged["name"] = rec["name"]
            merged["verification"] = rec["verification"]
            merged["sources"] = rec["sources"]
            merged["data"] = {**seed.raw.get("data", {}), **rec["data"]}
            seed.path.write_text(
                json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            updated_seeds += 1
            continue
        records.append(rec)

    out = knowledge / "game-data" / "tree"
    out.mkdir(parents=True, exist_ok=True)
    (out / _SHARD[kind]).write_text(
        "".join(
            json.dumps(r, ensure_ascii=False) + "\n"
            for r in sorted(records, key=lambda r: str(r["id"]))
        ),
        encoding="utf-8",
    )
    after = store_load(knowledge.parent)  # 스키마·참조 무결성 재검증
    return {
        "chunk": len(items),
        "written": len(records),
        "updated_seeds": updated_seeds,
        "kb_total": len(after.records),
    }
