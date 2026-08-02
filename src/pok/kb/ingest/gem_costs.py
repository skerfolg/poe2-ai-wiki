"""젬 코스트·점유 전수 수록 (사용자 지시 2026-08-02 — 정신력 지출 장부의 원천).

v6 사후 분석에서 확인된 공백: KB 젬 레코드에 코스트·점유 수치가 없어 점유
검사기(D27)가 정신력 축 장부를 구성할 수 없었다. 원천은 이미 수집된 poe2db
상세 페이지(ingest-raw)의 Stats 블록 — 재수집 없이 오프라인 적용한다.

수록 필드 (data, 없는 항목은 미기록):
  cost                  [{resource,min,max[,pct]}]  스킬 시전 비용
  reservation           [{…}]                       지속 스킬 점유 (예: Spirit 30)
  additional_reservation[{…}]                       보조 젬의 추가 점유 (냉철함 15 등)
  cost_multiplier_pct   115.0                       보조 젬 비용 배율
  cast_time_s           0.4
  converts_reservation_to "life"                    앗지리의 성찬식류 전환 효과
                        ("Reserve Life instead of Spirit" 공식 문구 감지 시)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pok.kb.ingest.parse import parse_detail
from pok.kb.store import load as store_load

_CONVERT_LIFE = re.compile(r"Reserve Life instead of Spirit", re.IGNORECASE)
_COST_KEYS = (
    "cost",
    "reservation",
    "additional_reservation",
    "cost_multiplier_pct",
    "cast_time_s",
    "converts_reservation_to",
)


def _slug_of(raw: dict[str, Any]) -> str | None:
    """레코드의 poe2db 소스 ref → us 페이지 슬러그 (그 페이지로 만들어진 레코드다)."""
    for src in raw.get("sources", []):
        ref = str(src.get("ref", ""))
        if src.get("src") == "poe2db" and "/us/" in ref:
            return ref.rsplit("/us/", 1)[1].split("#")[0].split("?")[0]
    return None


def _updates_from_page(html: str) -> dict[str, Any]:
    page = parse_detail(html)
    updates: dict[str, Any] = {}
    if page.costs:
        updates["cost"] = page.costs
    if page.reservation:
        updates["reservation"] = page.reservation
    if page.additional_reservation:
        updates["additional_reservation"] = page.additional_reservation
    if page.cost_multiplier_pct is not None:
        updates["cost_multiplier_pct"] = page.cost_multiplier_pct
    if page.cast_time_s is not None:
        updates["cast_time_s"] = page.cast_time_s
    if page.description and _CONVERT_LIFE.search(page.description):
        updates["converts_reservation_to"] = "life"
    return updates


def apply_gem_costs(raw_dir: Path, knowledge: Path) -> dict[str, Any]:
    """KB의 전체 Skill·Support 레코드에 코스트·점유 필드를 채운다 (멱등).

    수치는 GAME_DATA (poe2db Stats — 레코드가 이미 그 페이지를 소스로 인용).
    기존 값은 재파싱 결과로 덮어쓴다(원천 재적용 = 멱등). 페이지가 없는
    레코드는 건드리지 않고 보고만 한다.
    """
    kb = store_load(knowledge.parent)
    us_dir = raw_dir / "poe2db" / "us"
    per_path: dict[Path, dict[str, dict[str, Any]]] = {}  # 파일 → {id: 갱신 data}
    stats = {"updated": 0, "no_cost_fields": 0, "missing_html": [], "no_slug": []}
    for r in kb.records.values():
        if r.type not in ("Skill", "Support"):
            continue
        slug = _slug_of(r.raw)
        if slug is None:
            stats["no_slug"].append(r.id)
            continue
        html_path = us_dir / f"{slug}.html"
        if not html_path.exists():
            stats["missing_html"].append(f"{r.id} ({slug})")
            continue
        updates = _updates_from_page(html_path.read_text(encoding="utf-8"))
        if not updates:
            stats["no_cost_fields"] += 1
            continue
        per_path.setdefault(r.path, {})[r.id] = updates
        stats["updated"] += 1

    for path, by_id in per_path.items():
        if path.suffix == ".ndjson":
            lines = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec["id"] in by_id:
                    rec["data"] = {
                        **{k: v for k, v in rec["data"].items() if k not in _COST_KEYS},
                        **by_id[rec["id"]],
                    }
                lines.append(json.dumps(rec, ensure_ascii=False))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:  # 큐레이션 개별 JSON
            rec = json.loads(path.read_text(encoding="utf-8"))
            updates = by_id[rec["id"]]
            rec["data"] = {
                **{k: v for k, v in rec["data"].items() if k not in _COST_KEYS},
                **updates,
            }
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store_load(knowledge.parent)  # 병합 후 재검증 — 실패 시 예외
    return stats
