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

import re
from pathlib import Path
from typing import Any

from pok.kb.ingest.parse import parse_detail
from pok.kb.store import load as store_load
from pok.kb.store import patch_records

_CONVERT_LIFE = re.compile(r"Reserve Life instead of Spirit", re.IGNORECASE)
_COST_KEYS = (
    "cost",
    "reservation",
    "additional_reservation",
    "conditional_reservation",
    "cost_multiplier_pct",
    "cast_time_s",
    "cooldown_s",
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
    if page.conditional_reservation:
        updates["conditional_reservation"] = page.conditional_reservation
    if page.cost_multiplier_pct is not None:
        updates["cost_multiplier_pct"] = page.cost_multiplier_pct
    if page.cast_time_s is not None:
        updates["cast_time_s"] = page.cast_time_s
    if page.cooldown_s is not None:
        updates["cooldown_s"] = page.cooldown_s
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
    patches: dict[str, dict[str, Any]] = {}  # id → data 패치
    updated = no_cost_fields = 0
    missing_html: list[str] = []
    no_slug: list[str] = []
    for r in kb.records.values():
        if r.type not in ("Skill", "Support"):
            continue
        slug = _slug_of(r.raw)
        if slug is None:
            no_slug.append(r.id)
            continue
        html_path = us_dir / f"{slug}.html"
        if not html_path.exists():
            missing_html.append(f"{r.id} ({slug})")
            continue
        updates = _updates_from_page(html_path.read_text(encoding="utf-8"))
        # 쿨다운은 **없음을 명시적 0으로** 싣는다 — 필드 부재로 두면 "쿨다운 없음"과
        # "미수록"이 구분되지 않아, 쿨기를 지속 주력기로 오인한 채 회전율을 계산하게
        # 된다(실측 2026-08-07: 겨울의 눈 10초 쿨다운을 모르고 초당 1.07시전 전제).
        # 스킬 페이지를 실제로 읽었다는 것이 근거이므로, 표기가 없으면 0이 참이다.
        # 보조 젬은 자체 쿨다운 개념이 없어 대상에서 뺀다.
        if r.type == "Skill" and "cooldown_s" not in updates:
            updates["cooldown_s"] = 0.0
        # 코스트도 **같은 규약**으로 (#5, 사용자 선례 지목 2026-08-09). 필드 부재로
        # 두면 "코스트 없음"과 "미수록"이 구분되지 않는다 — 실제로 부재를 보고
        # "마나 소모 0"으로 단정했다가 철회한 오판이 있었다.
        #
        #     cost: [{...}]  읽은 값 (명시적 0 포함)
        #     cost: []       **명시적 무코스트** — 페이지를 읽었고 Cost 표기가 없다
        #     필드 부재       미수록 — 페이지가 없거나 못 읽었다
        #
        # 근거는 쿨다운과 같다: **스킬 페이지를 실제로 읽었다**는 것.
        if r.type == "Skill" and "cost" not in updates:
            updates["cost"] = []
        if not updates:
            no_cost_fields += 1
            continue
        # 재적용 멱등: 이전 코스트 필드를 지우고 새 값만 남긴다 (소스에서 빠진 값의 눌러붙음 방지)
        stale = {k: None for k in _COST_KEYS if k in r.raw.get("data", {}) and k not in updates}
        patches[r.id] = {**updates, **stale}
        updated += 1

    # 정본 쓰기는 store 단일 경로로 (B-6) — 배치 판단·재검증·원자성이 거기 있다
    patch_records(patches, root=knowledge.parent)
    return {
        "updated": updated,
        "no_cost_fields": no_cost_fields,
        "missing_html": missing_html,
        "no_slug": no_slug,
    }
