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
from pok.kb.ingest.verify import (
    SourceEntity,
    acquisition_coverage,
    cross_source,
    substance_floor,
    verification_block,
)

# KI-8 판정값 (v2 — 2026-07-29 사람 판정 반영)
IMPLEMENTED = "implemented"  # A ∧ P → KB 수록
GHOST = "ghost"  # ¬A ∧ ¬P, 규칙 미해당 → 사람 판단 대기 (다음 패치 신규 유령이 여기 옴)
NO_POB = "implemented-no-pob"  # A ∧ ¬P → 수록 + PoB 계산 불가 플래그 (사람 판정: 보존)
POB_ONLY = "pob-only-or-parse-gap"  # ¬A ∧ P, 규칙 미해당 → 보류
# ¬A ∧ P ∧ 레벨효과표 → 수록 + 획득 경로 미표기 플래그 (사용자 판정 2026-08-02).
# 신호 A를 "From 카드 유무"로만 보면 실재 젬이 걸러진다 — 칼구르의 잔류물 등은
# poe2db에 From 카드가 없지만 게임에 존재함이 사용자 확인으로 밝혀졌다.
# 레벨별 효과표(Level Effect)는 게임 데이터가 실존한다는 증거라 신호 A의 보조로 쓴다.
NO_ACQ = "implemented-no-acquisition"
LINEAGE = "include-lineage"  # 혈통 서포트 — 실존 아이템 (사람 판정)
BASIC = "include-basic-attack"  # 무기 기본 공격 — 기본 제공 (사람 판정)
SUPERSEDED = "excluded-superseded"  # 다른 젬으로 통합됨 (원장 근거)
# 현재 패치에 획득 경로 없음 (원장 근거, 사용자 인게임 판정 2026-08-03).
# NO_ACQ 규칙은 레벨효과표만 보므로 실제로 못 얻는 젬도 수록한다 — 사람 판정이 그 위에 선다.
# PoE1 잔재와 다르다: 상세 페이지·설명은 존재하되 현 패치에 경로가 없다. 매 패치 재검증 대상.
UNOBTAINABLE = "excluded-unobtainable"
NOT_A_GEM = "not-a-gem-page"  # 젬 페이지 아님 (보스/장소 등 — lineage 목록 혼입분)

# KB 수록 대상 판정
INCLUDE_VERDICTS = frozenset({IMPLEMENTED, NO_POB, NO_ACQ, LINEAGE, BASIC})
# 원장에 근거가 적힌 제외 판정 — merge가 이미 수록된 레코드를 **지워도 되는** 유일한 근거.
# (근거 없는 미포함분은 지우지 않고 삭제 후보로 리포트한다.)
RULED_OUT_VERDICTS = frozenset({SUPERSEDED, UNOBTAINABLE})

# ⑥ 태그 대조 정규화 — 두 소스가 같은 개념을 다르게 표기한다
_TAG_ALIAS = {"aoe": "area"}
# PoB 태그 중 게임 표시 태그가 아닌 구조 표식 — poe2db에 없는 게 정상이라 대조에서 뺀다
# (_norm_tag를 통과한 형태로 적는다 — 밑줄은 하이픈이 된다)
_POB_STRUCTURAL_TAGS = frozenset({"support", "active-skill", "grants-active-skill"})


def _norm_tag(tag: str) -> str:
    t = tag.strip().lower().replace(" ", "-").replace("_", "-")
    return _TAG_ALIAS.get(t, t)


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


def _poe2db_entity(item: ProcessedItem) -> SourceEntity:
    """수집 항목 → 검증기 정규형. 젬의 실질 정보 = 태그·설명·레벨효과표."""
    substance = list(item.tags)
    if item.description:
        substance.append(item.description)
    if item.has_level_effect:
        substance.append("level-effect-table")
    return SourceEntity(
        key=item.name_en.lower(),
        name=item.name_en,
        substance=tuple(substance),
        acquisition=tuple(item.acquisition),
        facts={"tier": str(item.tier)} if item.tier is not None else {},
        sets={"tags": frozenset(_norm_tag(t) for t in item.tags)},
    )


def _pob_entity(key: str, gem: dict[str, Any]) -> SourceEntity:
    tags = {_norm_tag(t) for t, on in (gem.get("tags") or {}).items() if on}
    return SourceEntity(
        key=key,
        name=str(gem.get("name", key)),
        facts={"tier": str(gem["Tier"])} if gem.get("Tier") is not None else {},
        sets={"tags": frozenset(tags - _POB_STRUCTURAL_TAGS)},
    )


def _classify(
    has_acquisition: bool,
    in_pob: bool,
    *,
    is_gem: bool = True,
    is_lineage: bool = False,
    is_basic: bool = False,
    superseded: bool = False,
    unobtainable: bool = False,
    has_level_effect: bool = False,
) -> str:
    """KI-8 매트릭스 + 사람 판정 규칙(혈통·기본공격·통합·미획득). 규칙이 매트릭스에 우선."""
    if not is_gem:
        return NOT_A_GEM
    if superseded:
        return SUPERSEDED
    if unobtainable:
        return UNOBTAINABLE
    if is_basic:
        return BASIC
    if has_acquisition and in_pob:
        return IMPLEMENTED
    if is_lineage:
        return LINEAGE
    if has_acquisition:
        return NO_POB
    if in_pob:
        # 레벨효과표 = 게임 데이터 실존 증거 → 수록(획득 경로 미표기 플래그와 함께).
        # 표도 없으면 파싱 갭 가능성이 남으므로 기존대로 보류한다.
        return NO_ACQ if has_level_effect else POB_ONLY
    return GHOST


def _load_rulings(knowledge: Path) -> tuple[dict[str, str], set[str], set[str], set[str]]:
    """정본 원장 로드 → (superseded slug→대상, poe1 잔재 PoB 이름, 기본공격·미획득 slug)."""
    superseded: dict[str, str] = {}
    remnants: set[str] = set()
    basics: set[str] = set()
    unobtainable: set[str] = set()
    exc_path = knowledge / "ingest" / "exclusions.json"
    if exc_path.exists():
        exc = json.loads(exc_path.read_text(encoding="utf-8"))
        superseded = {e["slug"]: e["merged_into"] for e in exc.get("superseded", [])}
        remnants = {e["pob_name"].lower() for e in exc.get("poe1_remnant_pob", [])}
        unobtainable = {s for e in exc.get("unobtainable_gems", []) for s in e.get("slugs", [])}
    basic_path = knowledge / "ingest" / "basic-attacks.json"
    if basic_path.exists():
        basics = set(json.loads(basic_path.read_text(encoding="utf-8"))["slugs"])
    return superseded, remnants, basics, unobtainable


def process_patch(raw_dir: Path, out_dir: Path, knowledge: Path | None = None) -> dict[str, Any]:
    """plan의 전 항목을 파싱·매칭·판정하고 리포트 데이터를 반환한다."""
    from pok.common.paths import knowledge_dir

    plan = json.loads((raw_dir / "fetch-plan.json").read_text(encoding="utf-8"))
    pob_by_name = pob_gems_by_name(
        json.loads((raw_dir / "pob" / "gems.json").read_text(encoding="utf-8"))
    )
    superseded_map, remnant_names, basic_slugs, unobtainable_slugs = _load_rulings(
        knowledge or knowledge_dir()
    )
    lineage_slugs = set(plan["categories"].get("lineage-supports", {}).get("items", []))

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
        # 젬 판별: Level Effect 표 또는 Tier — 몬스터/맵 페이지도 .Stats(tags)는 가지므로
        # tags만으로는 불충분 (lineage 목록 혼입 보스 페이지로 실증, 2026-07-29)
        is_gem = page.has_level_effect or page.tier is not None
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
            verdict=_classify(
                bool(page.acquisition),
                pob is not None,
                is_gem=is_gem,
                is_lineage=slug in lineage_slugs,
                is_basic=slug in basic_slugs,
                superseded=slug in superseded_map,
                unobtainable=slug in unobtainable_slugs,
                has_level_effect=page.has_level_effect,
            ),
        )
        items.append(item)

    # PoB에만 있는 젬 (poe2db 계획에 아예 없음) — 역방향 누락 감지 (기준 ②)
    # 원장의 PoE1 잔재 판정(승인됨)은 제외하고, 새로 나타난 것만 리포트
    plan_names = {i.name_en.lower() for i in items}
    pob_unmatched = sorted(
        str(g.get("name"))
        for name, g in pob_by_name.items()
        if name not in plan_names and name not in remnant_names and g.get("gemType") != "Meta"
    )

    by_verdict: dict[str, list[ProcessedItem]] = {}
    for i in items:
        by_verdict.setdefault(i.verdict, []).append(i)

    # 완전성 기준 ⑥⑦⑧ (KB_INGEST §4) — 판정하지 않고 리포트만 한다
    included = [i for i in items if i.verdict in INCLUDE_VERDICTS]
    pob_entities = [
        _pob_entity(name, g) for name, g in pob_by_name.items() if g.get("gemType") != "Meta"
    ]
    verification = verification_block(
        cross=[
            cross_source(
                [_poe2db_entity(i) for i in items],
                pob_entities,
                labels=("poe2db", "pob"),
                known_only_in_secondary=remnant_names,
            )
        ],
        substance=[substance_floor((_poe2db_entity(i) for i in included), scope="gem:included")],
        acquisition=[
            acquisition_coverage((_poe2db_entity(i) for i in included), entity_type="gem")
        ],
    )

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
        "include_total": sum(1 for i in items if i.verdict in INCLUDE_VERDICTS),
        "ghosts": sorted(i.slug for i in by_verdict.get(GHOST, [])),
        "hold_pob_only": sorted(i.slug for i in by_verdict.get(POB_ONLY, [])),
        "excluded_superseded": sorted(i.slug for i in by_verdict.get(SUPERSEDED, [])),
        "excluded_unobtainable": sorted(i.slug for i in by_verdict.get(UNOBTAINABLE, [])),
        "not_a_gem": sorted(i.slug for i in by_verdict.get(NOT_A_GEM, [])),
        "pob_unmatched_new": pob_unmatched,
        "parse_failures": parse_failures,
        "verification": verification,
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
