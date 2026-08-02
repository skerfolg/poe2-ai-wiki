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


def parse_pob(build_code: str, anchor: dict[str, Any] | None = None) -> dict[str, Any]:
    """PoB 공유 코드 → 구조 요약 (클래스·어센던시·스킬 그룹·트리·아이템·저장 스탯).

    anchor를 주면 artifacts/anchors/<id>/에 계보 manifest와 함께 보관한다(D30):
      anchor = {"slug": "user-ember-fusillade",
                "source": {"url": ..., "site": "poe.ninja", "provenance": ...}}
    source(계보)가 없는 앵커 기록은 거부된다 — RC5 "근거 있는 재조합"의 전제.
    """
    from pok.artifacts.store import new_anchor_id, record_anchor
    from pok.pob.parse import parse_pob as _parse

    try:
        summary = _parse(build_code)
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    out: dict[str, Any] = {
        "ok": True,
        "class": summary.class_name,
        "ascendancy": summary.ascendancy,
        "ascendancy_internal_id": summary.ascendancy_internal_id,
        "level": summary.level,
        "main_socket_group": summary.main_socket_group,
        "main_skill_gems": list(summary.main_skill_gems),
        "skill_groups": [
            {"gems": list(g.gems), "slot": g.slot, "enabled": g.enabled, "label": g.label}
            for g in summary.skill_groups
        ],
        "tree_version": summary.tree_version,
        "tree_node_count": len(summary.tree_nodes),
        "tree_nodes": list(summary.tree_nodes),
        "items": [dataclasses.asdict(i) for i in summary.items],
        "player_stats": summary.player_stats,
    }
    if anchor is not None:
        try:
            anchor_id = new_anchor_id(str(anchor.get("slug", "anchor")))
            path = record_anchor(
                anchor_id,
                files={"pob-code.txt": build_code},
                manifest={
                    "kind": "external-anchor-build",
                    "source": anchor.get("source", {}),
                    "parse_summary": {
                        k: out[k]
                        for k in (
                            "class",
                            "ascendancy",
                            "level",
                            "main_skill_gems",
                            "tree_node_count",
                        )
                    },
                },
            )
            out["anchor_id"], out["anchor_path"] = anchor_id, str(path)
        except ValueError as e:
            out["anchor_error"] = str(e)
    return out


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
