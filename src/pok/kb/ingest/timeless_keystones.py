"""타임리스 주얼이 **부여하는** 키스톤 수록 — PoB `TimelessJewelData/LegionPassives.lua`.

트리 수집(`tree.py`)은 poe2db 트리 데이터를 읽으므로 **트리에 없는 이 키스톤들을
못 본다**. 그래서 래더 프로파일에 `unmapped:<이름>`으로만 남아 있었다
(실측 2026-08-16: 7종 · 최다 `Black Scythe Training` 129벌 · `Sacrifice of Flesh` 114벌).

**왜 트리 밖인가**: 타임리스 주얼은 반경 안의 노드를 정복자별 대체물로 바꾼다.
키스톤 대체는 **시드와 무관하게 정복자 이름만으로** 정해지고(PoB `PassiveSpec.lua`),
그 부분만 PoB에서 동작한다 — 노터블·스몰의 시드→효과 매핑은 PoE2 시드 데이터가
아직 없어 주석 처리돼 있다(조사 2026-07-31, `unique_fixes.py` 참조). 즉 **이 8종은
지금 상류에서 확정적으로 읽히는 유일한 타임리스 산출물**이다.

⛔ **PoE1 잔재 20종은 수록하지 않는다.** 같은 파일에 vaal·karui·maraketh·templar·
eternal 정복자 항목이 남아 있는데, 그중 `Eternal Youth`·`Glancing Blows`·
`Dance with Death`·`Wind Dancer`는 **PoE2 트리에 같은 이름의 진짜 노드가 있다** —
그대로 실으면 트리 노드와 중복된 레코드가 생겨 조회가 갈린다. PoE2 정복자
(`kalguur`·`abyss`)만 싣는다.

**주얼 대응은 실측으로 확정**(래더 2,689벌 전수, 예외 0건):
`Heroic Tragedy` → kalguur 3종 · `Undying Hate` → abyss 5종.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SHARD = "timeless-keystones.ndjson"

# 정복자 접두 → (부여 주얼 KB id, 사람이 읽는 이름). PoE2에 실재하는 둘뿐이다.
_CONQUERORS: dict[str, tuple[str, str]] = {
    "kalguur": ("item.heroic-tragedy", "Heroic Tragedy"),
    "abyss": ("item.undying-hate", "Undying Hate"),
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _conqueror_of(pob_id: str) -> str | None:
    prefix = pob_id.split("_", 1)[0]
    return prefix if prefix in _CONQUERORS else None


def keystones(raw_pob_dir: Path) -> list[dict[str, Any]]:
    """`legionpassives.json` → 수록 대상(PoE2 정복자 키스톤)만."""
    doc = json.loads((raw_pob_dir / "legionpassives.json").read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for node in doc.get("nodes") or []:
        if not isinstance(node, dict) or not node.get("ks"):
            continue
        pob_id = str(node.get("id") or "")
        conqueror = _conqueror_of(pob_id)
        if conqueror is None:
            continue  # PoE1 잔재 — 위 머리주석 참조
        name = str(node.get("dn") or "").strip()
        if not name:
            continue
        out.append(
            {
                "name": name,
                "pob_id": pob_id,
                "conqueror": conqueror,
                "stats": [str(s) for s in (node.get("sd") or [])],
                "icon": str(node.get("icon") or ""),
            }
        )
    return sorted(out, key=lambda e: e["pob_id"])


def build_records(raw_pob_dir: Path, *, patch: str, pob_commit: str) -> list[dict[str, Any]]:
    """Passive 레코드로 만든다.

    ⚠ `node_id`를 **주지 않는다** — 트리에 없는 키스톤이라 노드 번호가 없다.
    번호가 없으면 `_tree_index`·`suggest_anchors`의 노드 변환에서 자연히 빠지므로
    트리 연산에 섞이지 않는다. 대신 `grant`로 **어떻게 얻는지**를 싣는다:
    그게 이 레코드의 존재 이유다(트리 경로 말고 다른 취득 경로).
    """
    records: list[dict[str, Any]] = []
    for entry in keystones(raw_pob_dir):
        jewel_ref, jewel_name = _CONQUERORS[entry["conqueror"]]
        records.append(
            {
                "id": f"passive.timeless-{_slug(entry['name'])}",
                "type": "Passive",
                "name": {"ko": entry["name"], "en": entry["name"]},
                "tags": ["keystone", "timeless-jewel"],
                "data": {
                    "kind": "keystone",
                    # 트리 노드가 아니라는 사실을 **레코드가 말한다**. 없으면 읽는 쪽이
                    # 「수집이 빠뜨린 트리 노드」로 읽는다(형태 ①).
                    "on_tree": False,
                    "grant": {
                        "via": "timeless-jewel",
                        "jewel": jewel_ref,
                        "jewel_name": jewel_name,
                        "conqueror": entry["conqueror"],
                    },
                    "stats": entry["stats"],
                    "pob_id": entry["pob_id"],
                },
                # 어휘는 스키마가 고정한다 — `granted-by`는 없다. 「그 주얼 없이는
                # 얻을 수 없다」가 이 관계의 내용이므로 `requires`가 맞다.
                "relations": [{"rel": "requires", "target": jewel_ref}],
                "verification": "POB_CODE",
                "sources": [
                    {
                        "src": "pob",
                        "ref": "Data/TimelessJewelData/LegionPassives.lua",
                        "patch": patch,
                        "pob": pob_commit,
                    }
                ],
            }
        )
    return records
