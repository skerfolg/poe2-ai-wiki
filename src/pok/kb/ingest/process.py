"""③ match + KI-8 구현 판정 게이트 + ⑥ 리포트 생성.

원시(데이터 repo)에서 결정적으로 재실행 가능 — 네트워크 없음.
중간 산출물은 var/(파생), 리포트는 원시 디렉터리(데이터 repo = 증거)에 쓴다.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pok.kb.ingest.parse import DetailPage, parse_detail, parse_name_only, pob_gems_by_name

# KI-8 판정값
IMPLEMENTED = "implemented"  # A ∧ P → KB 수록
GHOST = "ghost"  # ¬A ∧ ¬P → 자동 제외 (리포트 명시)
NO_POB = "implemented-no-pob"  # A ∧ ¬P → 개별 판단 (PoB 계산 불가 플래그 후보)
POB_ONLY = "pob-only-or-parse-gap"  # ¬A ∧ P → 개별 판단 (PoB 잔재 or 파싱 실패)


@dataclass
class ProcessedItem:
    slug: str
    categories: list[str]
    name_en: str
    name_ko: str | None
    tags: list[str] = field(default_factory=list)
    tier: int | None = None
    description: str | None = None
    acquisition: list[str] = field(default_factory=list)
    has_level_effect: bool = False
    in_pob: bool = False
    pob_meta_id: str | None = None
    verdict: str = GHOST


def _classify(has_acquisition: bool, in_pob: bool) -> str:
    if has_acquisition and in_pob:
        return IMPLEMENTED
    if has_acquisition:
        return NO_POB
    if in_pob:
        return POB_ONLY
    return GHOST


def process_patch(raw_dir: Path, out_dir: Path) -> dict[str, Any]:
    """plan의 전 항목을 파싱·매칭·판정하고 리포트 데이터를 반환한다."""
    plan = json.loads((raw_dir / "fetch-plan.json").read_text(encoding="utf-8"))
    pob_by_name = pob_gems_by_name(
        json.loads((raw_dir / "pob" / "gems.json").read_text(encoding="utf-8"))
    )

    # 같은 페이지가 여러 카테고리 목록에 실릴 수 있음(예: spirit ⊂ support) → slug 단위 dedup
    slug_categories: dict[str, list[str]] = {}
    for cat_key, cat in plan["categories"].items():
        for slug in cat["items"]:
            slug_categories.setdefault(slug, []).append(cat_key)

    items: list[ProcessedItem] = []
    parse_failures: list[str] = []
    for slug, cat_keys in sorted(slug_categories.items()):
        us_path = raw_dir / "poe2db" / "us" / f"{slug}.html"
        kr_path = raw_dir / "poe2db" / "kr" / f"{slug}.html"
        if not us_path.exists():
            parse_failures.append(f"{slug}: us 원시 없음")
            continue
        try:
            page: DetailPage = parse_detail(us_path.read_text(encoding="utf-8"))
        except Exception as e:  # 파서 실패는 항목 단위로 기록 (전체 중단 금지)
            parse_failures.append(f"{slug}: {type(e).__name__}: {e}")
            continue
        name_ko = parse_name_only(kr_path.read_text(encoding="utf-8")) if kr_path.exists() else None
        pob = pob_by_name.get(page.name.lower())
        item = ProcessedItem(
            slug=slug,
            categories=cat_keys,
            name_en=page.name,
            name_ko=name_ko,
            tags=page.tags,
            tier=page.tier,
            description=page.description,
            acquisition=page.acquisition,
            has_level_effect=page.has_level_effect,
            in_pob=pob is not None,
            pob_meta_id=str(pob["_meta_id"]) if pob else None,
            verdict=_classify(bool(page.acquisition), pob is not None),
        )
        items.append(item)

    # PoB에만 있는 젬 (poe2db 계획에 아예 없음) — 역방향 누락 감지 (기준 ②)
    plan_names = {i.name_en.lower() for i in items}
    pob_unmatched = sorted(
        str(g.get("name"))
        for name, g in pob_by_name.items()
        if name not in plan_names and g.get("gemType") != "Meta"
    )

    by_verdict: dict[str, list[ProcessedItem]] = {}
    for i in items:
        by_verdict.setdefault(i.verdict, []).append(i)

    report: dict[str, Any] = {
        "patch": plan["patch"],
        "totals": {
            "processed": len(items),
            "parse_failures": len(parse_failures),
            **{v: len(lst) for v, lst in sorted(by_verdict.items())},
            "pob_unmatched": len(pob_unmatched),
        },
        "listed_vs_planned": {
            k: {"listed": c["listed_count"], "planned": c["planned_count"]}
            for k, c in plan["categories"].items()
        },
        "ghosts": sorted(i.slug for i in by_verdict.get(GHOST, [])),
        "needs_review_no_pob": sorted(i.slug for i in by_verdict.get(NO_POB, [])),
        "needs_review_pob_only": sorted(i.slug for i in by_verdict.get(POB_ONLY, [])),
        "pob_unmatched": pob_unmatched,
        "parse_failures": parse_failures,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "intermediate.json").write_text(
        json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    (raw_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report
