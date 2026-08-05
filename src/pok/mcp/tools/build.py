"""빌드·계산 MCP 도구 — BLUEPRINT §11 (compute_pob·evaluate_delta·
check_item_legality·assemble_pob). 얇은 어댑터: 검증·계산·기록은 engine이,
여기는 dict 입출력과 토큰 예산(D14 — stats 선별 반환)만 관리한다.

build_spec dict 형식 (spec_from_dict 계약):
  {"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90,
   "tree_nodes": [4739, ...],
   "skills": [{"gems": [{"gem_id": "Metadata/Items/Gems/SkillGemSpark",
                          "name": "Spark", "level": 20}]}],
   "items": [{"slot": "Ring 1", "text": "Rarity: RARE\\n..."}],
   "jewels": [{"socket_node_id": 55555, "text": "Rarity: UNIQUE\\n...",
                "allocates": [51868]}],
   "config": {"enemyIsBoss": true}}

주얼의 `allocates`는 **대체 모델링**(B-3): KB `pob_computable: false` 유니크
(과대망상 등)는 explicits가 플레이스홀더라 PoB가 텍스트로 못 읽으므로, 부여
노터블의 node_id를 적으면 트리에 병합해 **효과만** 재현한다. 소켓 소모·조달
가정은 재현되지 않으며, 그 사실이 manifest `substitute_modeling`에 기록된다.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir
from pok.engine.assemble import IllegalBuildError, assemble
from pok.engine.compute import compute_pob as _compute
from pok.engine.compute import evaluate_delta as _delta
from pok.engine.legality import ItemLegalityChecker
from pok.pob.buildxml import spec_from_dict
from pok.pob.runner import PobResult

# 기본 반환 스탯 — 다차원 목적 프로파일의 축(RC3). 전체는 stats=["*"]로.
# 기본 반환 스탯. **곱연산 인자를 반드시 포함한다** — 이게 빠져 있으면 세션은
# 가산 항만 보고 그것만 키운다(실측 2026-08-05: PoB가 유효 빌드에서 760종을 내는데
# 우리는 24종만 봤고, 거기에 `CritEffect`도 층별 경감률도 없었다).
DEFAULT_STATS = (
    "Life", "EnergyShield", "Mana", "TotalEHP", "PhysicalMaximumHitTaken",
    "Armour", "Evasion", "BlockChance", "SpellSuppressionChance",
    "FireResist", "ColdResist", "LightningResist", "ChaosResist",
    "TotalDPS", "TotalDot", "CombinedDPS", "CritChance", "HitChance",
    "CastSpeed", "Speed", "MovementSpeedMod", "Str", "Dex", "Int",
    # 곱연산 축 (Π) — 1.0 근처면 그 축이 통째로 미개발이라는 신호
    "CritEffect", "CritMultiplier",
    "PhysicalDamageReduction", "FireDamageReduction",
    "ColdDamageReduction", "LightningDamageReduction", "ChaosDamageReduction",
    "AverageDamage", "AilmentThreshold",
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


def _unset_config(build_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """이 빌드에 **관련 있는데 미설정인** PoB config.

    기본값 0을 실측으로 오해하는 것을 구조적으로 막는다 — 실측 2026-08-05:
    `multiplierIncisionStackCount`가 0이라 절개가 무가치해 보였고 필수 젬을 뺄
    뻔했다. 관련성은 PoB `ConfigOptions.lua`의 `ifFlag`·`ifMod` 조건을 젬 효과
    문구(KB `stats`)와 대조해 판정한다 — 추측이 아니라 양쪽 다 게임 데이터다.
    """
    from pok.engine.constraints.config_relevance import find_unset_options
    from pok.index.search import get_entry

    texts: dict[str, list[str]] = {}
    for group in build_spec.get("skills", []):
        for gem in group.get("gems", []):
            name = str(gem.get("name", "")).strip()
            if not name:
                continue
            for prefix in ("support", "skill"):
                rid = f"{prefix}.{name.lower().replace(' ', '-')}"
                try:
                    lines = (get_entry(rid, fields=["data"]).get("data") or {}).get("stats")
                except KeyError:
                    continue
                if lines:
                    texts[rid] = list(lines)
                    break
    if not texts:
        return []
    unset = find_unset_options(texts, configured=dict(build_spec.get("config", {})))
    return [
        {"var": u.var, "label": u.label, "matched": u.matched_keyword, "from": u.matched_in}
        for u in unset
    ]


def compute_pob(build_spec: dict[str, Any], stats: list[str] | None = None) -> dict[str, Any]:
    """빌드 스펙(dict)을 headless PoB로 계산. stats로 반환 스탯 선별
    (생략=핵심 24종+곱연산 축, ["*"]=전부). pruned_nodes가 비어있지 않으면 트리에
    비연결 노드가 있다는 뜻 — 그 노드는 계산에 반영되지 않았다.

    `unset_config`는 **이 빌드에 관련 있는데 안 켠 PoB 설정**이다. 미설정 config의
    기본값에서 나온 델타 0은 "효과 없음"이 아니라 "안 켰다"의 증거다 — 그걸로
    무엇을 빼기 전에 이 목록을 볼 것(BUILD_DESIGN §2-3 측정 무효의 판정 의무).
    켜지 않는 게 맞는 축도 있으니 판단은 호출자 몫이다(AD-3)."""
    out = _pick(_compute(spec_from_dict(build_spec)), stats)
    unset = _unset_config(build_spec)
    if unset:
        out["unset_config"] = unset
    return out


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


def parse_pob(
    build_code: str = "",
    anchor: dict[str, Any] | None = None,
    code_path: str = "",
) -> dict[str, Any]:
    """PoB 공유 코드 → 구조 요약 (클래스·어센던시·스킬 그룹·트리·아이템·저장 스탯).

    `code_path`로 **파일에서 읽을 수 있다.** 앵커 코드는 2만 자를 넘기도 해서 인라인으로
    넘기면 도중에 잘린다 — 실측 2026-08-05: 24,244자가 13,737자로 절단돼 분석이
    실패했다. 긴 코드는 파일로 두고 경로를 준다(사용자 규율과도 맞는다).

    anchor를 주면 artifacts/anchors/<id>/에 계보 manifest와 함께 보관한다(D30):
      anchor = {"slug": "user-ember-fusillade",
                "source": {"url": ..., "site": "poe.ninja", "provenance": ...}}
    source(계보)가 없는 앵커 기록은 거부된다 — RC5 "근거 있는 재조합"의 전제.
    """
    from pok.artifacts.store import new_anchor_id, record_anchor
    from pok.pob.parse import parse_pob as _parse

    if code_path:
        source = Path(code_path).expanduser()
        if not source.exists():
            return {"ok": False, "reason": f"파일 없음: {source}"}
        build_code = source.read_text(encoding="utf-8").strip()
    if not build_code:
        return {"ok": False, "reason": "build_code 또는 code_path 중 하나는 있어야 한다"}
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
    from pok.pob.buildxml import find_probe_lines

    probes = find_probe_lines(build_spec)
    if probes:
        # **출고 게이트** (회차 종결 R1): 탐침은 천장을 재는 가정치다 — 측정
        # (`compute_pob`)은 통과하지만 출고는 실물로 재건한 뒤여야 한다. 실측:
        # `+16650 생명력` 탐침이 빠진 뒤 주 엔진을 재건하지 않은 채 출고됐다.
        return {
            "ok": False,
            "reason": (
                "탐침([탐침]/[PROBE]) 줄이 남아 있다 — 출고 전에 실물 조달로 "
                "재건하거나, 뺐다면 그 축을 대체할 것:\n  " + "\n  ".join(probes)
            ),
        }
    try:
        built = assemble(spec_from_dict(build_spec), slug, checker=_get_checker())
    except (IllegalBuildError, ValueError) as e:
        # 스펙 오류(ValueError)도 사유로 돌려준다 — 예외로 터지면 호출자는
        # "어느 젬의 어느 키"인지 못 보고 추측으로 재시도한다
        return {"ok": False, "reason": str(e)}
    return {
        "ok": True,
        "build_id": built.build_id,
        "path": str(built.path),
        "build_code": built.build_code,
        "duplicates": list(built.duplicates),
        **_pick(built.result, stats),
    }


def measure_leverage(
    build_spec: dict[str, Any],
    other_spec: dict[str, Any] | None = None,
    stat: str = "CombinedDPS",
) -> dict[str, Any]:
    """조건 ON/OFF를 두 번 재서 **사전 작업 의존도**를 낸다. 앵커를 주면 2x2 교차 (D1·D2).

    ⚠ **앵커 비교는 반드시 이걸 거칠 것.** 상대의 조건 on 수치를 우리 조건 off 수치와
    나란히 놓으면 오독한다 — 실측 2026-08-05: 21,302,501 대 302,794를 "70배 차이"로
    읽었는데 **같은 저울에서는 3.7배**였다.

    `leverage`(조건 on ÷ off)는 그 자체가 강건성 지표다. 실측: 21M 앵커 19.0배,
    갈퀴질 창 2.1/1.88배, 우리 1.36배. 높을수록 사전 작업 의존이 크고 실전에서
    무너진다 — 사용자 판정: "이론상 가능해도 추구해서는 안 된다".

    얼마가 적정인지는 판단이라 정하지 않는다(AD-3) — 목표 상태에 상한을 걸 때 쓴다.
    조건성으로 보는 것은 `condition*`·`enemyCondition*`·`multiplier*` 키다.
    """
    from pok.engine.leverage import compare_on_same_scale, measure_operating_cost
    from pok.engine.leverage import measure_leverage as _measure

    def _reading(r: Any) -> dict[str, Any]:
        return {
            "label": r.label,
            "stat": r.stat,
            "off": r.off,
            "on": r.on,
            "leverage": r.leverage,
            "conditions_toggled": list(r.conditions),
        }

    # 운용 비용도 함께 낸다 — DPS·EHP 밖의 축이라 따로 물으면 아무도 안 묻는다(D3).
    # `evaluate_objective`의 measured에 그대로 넣어 사전식 목표로 쓸 수 있다.
    cost = measure_operating_cost(build_spec).as_measured()
    if other_spec is None:
        return {"ok": True, **_reading(_measure(build_spec, stat=stat)), "operating_cost": cost}
    comparison = compare_on_same_scale(build_spec, other_spec, stat=stat)
    return {
        "ok": True,
        "ours": _reading(comparison.ours),
        "other": _reading(comparison.other),
        "ratio_same_scale": comparison.ratio_off,
        "ratio_conditions_on": comparison.ratio_on,
        "naive_ratio_do_not_use": comparison.naive_ratio,
        "operating_cost": cost,
        "other_operating_cost": measure_operating_cost(other_spec).as_measured(),
        "notes": list(comparison.notes),
    }
