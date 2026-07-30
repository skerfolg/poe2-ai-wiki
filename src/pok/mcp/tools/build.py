"""빌드·계산 MCP 도구 — BLUEPRINT §11 (compute_pob·evaluate_delta·
check_item_legality·assemble_pob). 얇은 어댑터: 검증·계산·기록은 engine이,
여기는 dict 입출력과 토큰 예산(D14 — stats 선별 반환)만 관리한다.

build_spec dict 형식 (spec_from_dict 계약):
  {"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90,
   "tree_nodes": [4739, ...],
   "skills": [{"gems": [{"gem_id": "Metadata/Items/Gems/SkillGemSpark",
                          "name": "Spark", "level": 20}]}],
   "items": [{"slot": "Ring 1", "text": "Rarity: RARE\\n..."}],
   "config": {"enemyIsBoss": true}}
"""

from __future__ import annotations

import dataclasses
from typing import Any

from pok.common.paths import knowledge_dir
from pok.engine.assemble import IllegalBuildError, assemble
from pok.engine.compute import compute_pob as _compute
from pok.engine.compute import evaluate_delta as _delta
from pok.engine.legality import ItemLegalityChecker
from pok.pob.buildxml import spec_from_dict
from pok.pob.runner import PobResult

# 기본 반환 스탯 — 다차원 목적 프로파일의 축(RC3). 전체는 stats=["*"]로.
DEFAULT_STATS = (
    "Life", "EnergyShield", "Mana", "TotalEHP", "PhysicalMaximumHitTaken",
    "Armour", "Evasion", "BlockChance", "SpellSuppressionChance",
    "FireResist", "ColdResist", "LightningResist", "ChaosResist",
    "TotalDPS", "TotalDot", "CombinedDPS", "CritChance", "HitChance",
    "CastSpeed", "Speed", "MovementSpeedMod", "Str", "Dex", "Int",
)  # fmt: skip

_checker: ItemLegalityChecker | None = None


def _get_checker() -> ItemLegalityChecker:
    global _checker
    if _checker is None:
        _checker = ItemLegalityChecker(knowledge_dir())
    return _checker


def _pick(result: PobResult, stats: list[str] | None) -> dict[str, Any]:
    keys = result.stats.keys() if stats == ["*"] else (stats or DEFAULT_STATS)
    return {
        "stats": {k: result.stats[k] for k in keys if k in result.stats},
        "tree_legal": result.is_tree_legal,
        "pruned_nodes": list(result.pruned_nodes),
        "meta": result.meta,
    }


def compute_pob(build_spec: dict[str, Any], stats: list[str] | None = None) -> dict[str, Any]:
    """빌드 스펙(dict)을 headless PoB로 계산. stats로 반환 스탯 선별
    (생략=핵심 24종, ["*"]=전부). pruned_nodes가 비어있지 않으면 트리에
    비연결 노드가 있다는 뜻 — 그 노드는 계산에 반영되지 않았다."""
    return _pick(_compute(spec_from_dict(build_spec)), stats)


def evaluate_delta(
    base_spec: dict[str, Any], variants: dict[str, dict[str, Any]], stats: list[str] | None = None
) -> dict[str, Any]:
    """변경안들의 스탯 델타를 PoB로 실측 (추측 금지의 실행 수단, AD-8).
    variants = {라벨: 변경된 build_spec}. 반환 delta는 변경안-기준의 차이."""
    base_result, deltas = _delta(
        spec_from_dict(base_spec),
        {label: spec_from_dict(v) for label, v in variants.items()},
        stats=tuple(stats or DEFAULT_STATS),
    )
    return {
        "base": _pick(base_result, stats),
        "deltas": [
            {
                "label": d.label,
                "delta": {k: d.diff(k) for k in (stats or DEFAULT_STATS) if d.diff(k) is not None},
                "tree_legal": d.result.is_tree_legal,
            }
            for d in deltas
        ],
    }


def check_item_legality(item_text: str) -> dict[str, Any]:
    """합성 아이템 텍스트를 KB 모드풀로 검증(RC4). LEGAL/CONDITIONAL(경로
    한정—사유 확인)/ILLEGAL/UNKNOWN 판정과 접사 수·group 배타 오류를 반환."""
    report = _get_checker().check(item_text)
    return {
        "legal": report.is_legal,
        "errors": list(report.errors),
        "lines": [dataclasses.asdict(v) for v in report.verdicts],
    }


def assemble_pob(
    build_spec: dict[str, Any], slug: str, stats: list[str] | None = None
) -> dict[str, Any]:
    """빌드 조립→검증→계산→artifacts/builds/<build-id>/ 기록. 비합법이면
    거부하고 사유 반환. 성공 시 PoB 공유 코드(build_code) 포함."""
    try:
        built = assemble(spec_from_dict(build_spec), slug, checker=_get_checker())
    except IllegalBuildError as e:
        return {"ok": False, "reason": str(e)}
    return {
        "ok": True,
        "build_id": built.build_id,
        "path": str(built.path),
        "build_code": built.build_code,
        "duplicates": list(built.duplicates),
        **_pick(built.result, stats),
    }
