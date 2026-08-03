"""우물의 심장(Heart of the Well) 훼손 선택 풀 수록 — ModVeiled.lua UniqueHeart*.

우물의 심장은 훼손(Desecrated) 접두 2개·접미 2개를 **선택**해 붙이는 고유 주얼이다.
KB 레코드(item.heart-of-the-well)의 explicits는 "[Custom Desecrated prefix/suffix]"
플레이스홀더 4줄뿐이라 실물 아이템 줄과의 적법성 대조가 불가능했다 — 이 모듈이
선택 풀 전체(0.5.4b: 접두 35·접미 38)를 Modifier 레코드로 수록한다.

원천: PoB `Data/ModVeiled.lua`의 `UniqueHeartPrefix*`/`UniqueHeartSuffix*`
(pob_dump.lua가 `artifacts/ingest-raw/<patch>/pob/modveiled.json`으로 덤프).
PoB Generated.lua의 Heart 블록도 같은 풀에서 변형을 생성한다(대조 근거).
origins는 "heart-of-the-well" — 일반 크래프팅 풀(item·jewel)과 분리되어
legality의 일반 대조에 섞이지 않고, Heart 전용 대조(_check_unique)만 쓴다.

주의: ModVeiled의 mod 키 이름은 스탯과 어긋난 것이 있다(Generated.lua 주석
"Hacky replacement" — GainedAsCold 키가 Chaos 텍스트를 담는 식). **텍스트가
정본**이므로 키는 pob_key(역추적)로만 보존하고 판정엔 텍스트를 쓴다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pok.kb.ingest.mods import mod_slug

_PREFIX_KEY = "UniqueHeartPrefix"
_SUFFIX_KEY = "UniqueHeartSuffix"
SHARD = "heart-01.ndjson"
ORIGIN = "heart-of-the-well"


def _texts(raw: dict[str, Any]) -> list[str]:
    keys = sorted((k for k in raw if k.isdigit()), key=int)
    return [str(raw[k]) for k in keys]


def heart_pool(raw_pob_dir: Path) -> list[dict[str, Any]]:
    """modveiled.json → 중간 산출물 (pob_key·affix_type·texts·group·weights)."""
    veiled = json.loads((raw_pob_dir / "modveiled.json").read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for key in sorted(veiled):
        if key.startswith(_PREFIX_KEY):
            affix = "prefix"
        elif key.startswith(_SUFFIX_KEY):
            affix = "suffix"
        else:
            continue
        raw = veiled[key]
        weights = {
            str(k): int(v)
            for k, v in zip(raw.get("weightKey", []), raw.get("weightVal", []), strict=False)
        }
        out.append(
            {
                "pob_key": key,
                "affix_type": affix,
                "texts": _texts(raw),
                "group": raw.get("group"),
                "ilvl": int(raw.get("level", 1)),
                "mod_tags": raw.get("modTags", []),
                "spawn_weights": weights,
            }
        )
    return out


def to_record(item: dict[str, Any], patch: str, pob_commit: str) -> dict[str, Any]:
    data: dict[str, Any] = {
        "affix_type": item["affix_type"],
        "origins": [ORIGIN],
        "pob_key": item["pob_key"],
        "texts": item["texts"],
        "ilvl": item["ilvl"],
        # 부여 방법: 아이템 자체가 선택지를 제공 — 크래프팅 화폐 경로가 아니다
        "acquisition": ["unique:heart-of-the-well"],
    }
    for k in ("group", "mod_tags", "spawn_weights"):
        if item.get(k):
            data[k] = item[k]
    name = item["texts"][0] if item["texts"] else item["pob_key"]
    return {
        "id": f"modifier.{mod_slug(item['pob_key'])}",
        "type": "Modifier",
        "name": {"ko": name, "en": name},  # ko는 poe2db 대사 소스가 없어 원문 유지
        "tags": [],
        "data": data,
        "verification": "POB_CODE",  # PoB 단독 소스 (poe2db 훼손 페이지에 미수록)
        "sources": [
            {
                "src": "pob",
                "ref": "Data/ModVeiled.lua UniqueHeart*",
                "patch": patch,
                "pob": pob_commit,
            }
        ],
    }


def merge(raw_pob_dir: Path, knowledge: Path, patch: str) -> dict[str, Any]:
    """풀 전체를 knowledge/game-data/modifiers/heart-01.ndjson 으로 기록·검증."""
    from pok.kb.ingest.merge import POB_COMMIT
    from pok.kb.store import load as store_load
    from pok.kb.store import write_shard

    records = [to_record(i, patch, POB_COMMIT) for i in heart_pool(raw_pob_dir)]
    dst = knowledge / "game-data" / "modifiers" / SHARD
    # 쓰기는 store 단일 경로로 (B-6): 원자적 + 근거 없는 레코드 감소 거부
    write_shard(dst, records, root=knowledge.parent, validate=False)
    after = store_load(knowledge.parent)  # 스키마·참조 검증 (실패 시 예외)
    prefixes = sum(1 for r in records if r["data"]["affix_type"] == "prefix")
    return {
        "written": len(records),
        "prefixes": prefixes,
        "suffixes": len(records) - prefixes,
        "kb_total": len(after.records),
    }


if __name__ == "__main__":
    from pok.common.paths import knowledge_dir, project_root

    raw = project_root() / "artifacts" / "ingest-raw" / "0.5.4b" / "pob"
    print(json.dumps(merge(raw, knowledge_dir(), "0.5.4b"), ensure_ascii=False))


__all__ = ["ORIGIN", "SHARD", "heart_pool", "merge", "to_record"]
