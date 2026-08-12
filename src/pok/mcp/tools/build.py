"""빌드·계산 MCP 도구 — BLUEPRINT §11 (compute_pob·evaluate_delta·
check_item_legality·assemble_pob). 얇은 어댑터: 검증·계산·기록은 engine이,
여기는 dict 입출력과 토큰 예산(D14 — stats 선별 반환)만 관리한다.

build_spec dict 형식 (spec_from_dict 계약):
  {"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90,
   "tree_nodes": [4739, ...],
   "skills": [{"gems": [{"gem_id": "Metadata/Items/Gems/SkillGemSpark",
                          "name": "Spark", "level": 20, "stat_set_index": 1}]}],
   "items": [{"slot": "Ring 1", "text": "Rarity: RARE\\n...",
               "substitutes": ["25% more Elemental Damage with Spells"]}],
   "jewels": [{"socket_node_id": 55555, "text": "Rarity: UNIQUE\\n...",
                "allocates": [51868]}],
   "config": {"enemyIsBoss": true}}

젬의 `stat_set_index`는 **어느 모드로 계산할지**다(1부터). 한 스킬이 모드를 여럿
가지면(구형 번개 3개·스파크 2개 등 111종) 안 줄 때 PoB가 조용히 1번을 쓴다 —
실측 2026-08-10: 구형 번개 `TotalDPS` 151.2 / 381.5 / **497.6**. 미지정은 조립이
거부하고 어떤 모드가 있는지 알려 준다.

대체 모델링 두 갈래 — 둘 다 manifest `substitute_modeling`에 기록된다:

**① 주얼 `allocates`** (B-3): KB `pob_computable: false` 유니크(과대망상 등)는
explicits가 플레이스홀더라 PoB가 텍스트로 못 읽는다. 부여 노터블의 node_id를
적으면 트리에 병합해 **효과만** 재현한다. 소켓 소모·조달 가정은 재현되지 않는다.

**② 아이템 `substitutes`** (#3): PoB가 **문구를 못 읽는** 것(레코드의
`pob_modeling.kind`가 `tree-line-unparsed`·`rune-slot-unmatched`)의 값어치를
등가 문구로 바꿔 잰다. ⛔ `text`에 직접 섞지 말 것 — 섞으면 진짜 아이템 모드와
구분되지 않아 **추산이 실측으로 둔갑한다**. 이 칸에 적으면 산출물에 추산 사실이
자동으로 남는다. ⚠ 원문 그대로는 파서가 또 떨어뜨린다(대상 한정어가 원인) —
한정어를 뺀 형태로 근사하고, 그래서 **적용 범위가 실제보다 넓을 수 있다**.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir
from pok.engine.assemble import IllegalBuildError, assemble
from pok.engine.compute import compute_pob as _compute
from pok.engine.compute import evaluate_delta as _delta
from pok.engine.integrity import spec_integrity
from pok.engine.items import req_shortfall
from pok.engine.legality import ItemLegalityChecker
from pok.engine.provenance import missing_procedures, stale_components
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


def _items_legal(build_spec: dict[str, Any]) -> dict[str, Any]:
    """스펙의 장비를 KB 모드풀로 검사한 요약 — **매 반환에 싣는다** (백로그 #27).

    검사기는 `assemble()`에만 걸려 있었는데 **설계 반복은 `compute_pob`으로 한다.**
    즉 검사가 걸린 도구를 정작 설계 중에는 안 썼다. 실측 2026-08-09: 그렇게 20여 회
    측정한 빌드가 `assemble()`을 통과시키자 **10슬롯 중 4개가 실격**이었다
    (존재하지 않는 베이스 `Silk Gloves` · 실재하지 않는 문구 · 붙을 수 없는 접사).
    그 위에서 나온 수치가 설계 판단의 근거로 쓰였다.

    PoB를 돌리지 않으므로 비용은 KB 인덱스 조회뿐이다.
    """
    checker = _get_checker()
    illegal: list[dict[str, Any]] = []
    for item in build_spec.get("items") or []:
        report = checker.check(str(item.get("text", "")))
        if report.is_legal:
            continue
        illegal.append(
            {
                "slot": item.get("slot"),
                "reasons": [
                    *report.errors,
                    *(
                        f"{v.line} → {v.status}: {v.reason}"
                        for v in report.verdicts
                        if v.status in ("ILLEGAL", "UNKNOWN")
                    ),
                ],
            }
        )
    return {"items_legal": not illegal, "illegal_items": illegal}


def _pick(
    result: PobResult, stats: list[str] | None, build_spec: dict[str, Any] | None = None
) -> dict[str, Any]:
    keys = result.stats.keys() if stats == ["*"] else (stats or DEFAULT_STATS)
    out: dict[str, Any] = {
        "stats": {k: result.stats[k] for k in keys if k in result.stats},
        # `tree_legal`에서 개명했다(#27 요청안 3) — 이름이 "이 빌드가 합법"으로
        # 읽히는데 **장비는 안 본 값**이다. 옆의 `items_legal`과 축이 다르다.
        "tree_connected": result.is_tree_legal,
        "pruned_nodes": list(result.pruned_nodes),
        "meta": result.meta,
    }
    # 요구 속성 미달은 **매번** 싣는다 — 1회성 경고는 문서와 동급이다(#29).
    shortfall = req_shortfall(result.stats)
    if shortfall:
        out["req_shortfall"] = shortfall
    if build_spec is not None:
        out.update(_items_legal(build_spec))
        # 설계 무결성은 **적법성과 별개 축**이다 (#58 ①). 적법한데 애초에 빌드가
        # 아닌 경우를 잡는다 — 주력기 부재·트리거 미연결. 거부하지 않고 **매번**
        # 싣는다(1회성 경고는 문서와 동급이다 — #29).
        design = spec_integrity(build_spec)
        if design:
            out["design_warnings"] = list(design)
        # 낡음도 **매번** 싣는다 (#58 ③). 거부하지 않는다 — 낡은 트리로 A/B를 재는
        # 것이 정상 작업이다. 다만 「무효」를 읽고도 계승한 전례가 있으므로
        # **무엇이 달라서 낡았는지**를 문장으로 낸다.
        stale = stale_components(build_spec)
        if stale:
            out["stale"] = stale
    return out


@functools.lru_cache(maxsize=1)
def _tree_graph():  # type: ignore[no-untyped-def]
    """트리 그래프 1회 로드 — 조건 수집이 호출마다 KB를 다시 읽지 않게."""
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.graph import TreeGraph

    return TreeGraph(knowledge_dir())


def _unset_config(build_spec: dict[str, Any]) -> list[dict[str, Any]]:
    """이 빌드에 **관련 있는데 미설정인** PoB config.

    기본값 0을 실측으로 오해하는 것을 구조적으로 막는다 — 실측 2026-08-05:
    `multiplierIncisionStackCount`가 0이라 절개가 무가치해 보였고 필수 젬을 뺄
    뻔했다. 관련성은 PoB `ConfigOptions.lua`의 `ifFlag`·`ifMod` 조건을 젬 효과
    문구(KB `stats`)와 대조해 판정한다 — 추측이 아니라 양쪽 다 게임 데이터다.

    ⚠ **젬만 보면 안 된다** (백로그 #36). 조건은 **할당 노드와 장착 아이템**도
    요구한다. 실측 2026-08-09(점화 빌드): `conditionEnemyIgnited`가 미설정인데
    언급조차 없었고, 그래서 두 노드가 **조용한 0**으로 찍혀 하나는 트리에서
    걷어내졌다:

        24630 노호(1포인트)        Δ0  →  config 켜면 **+4,282**
        51868 녹아내린 갑각(2포인트) Δ0  →  config 켜면 **+4,608** · EHP +1,417

    `from` 칸에 **누가 그 조건을 요구하는지**가 남는다(`passive.…`·슬롯명) —
    젬만 나오면 노드가 원인일 때 추적이 끊긴다.
    """
    from pok.engine.constraints.config_relevance import find_unset_options
    from pok.engine.legality import _parse_item
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
    # 할당된 트리 노드 — 조건부 노드가 요구하는 config가 여기서 나온다
    for node_id in build_spec.get("tree_nodes") or ():
        node = _tree_graph().nodes.get(int(node_id))
        if node is not None and node.stats_en:
            texts[f"passive.{node_id}"] = list(node.stats_en)
    # 장착 아이템의 모드 줄 — 스펙 줄(`Prefix:`·`Sockets:` 등)은 모드가 아니다
    for item in build_spec.get("items") or ():
        text = str(item.get("text") or "")
        if not text.strip():
            continue
        with contextlib.suppress(ValueError):
            lines = _parse_item(text)[3]
            if lines:
                texts[f"item:{item.get('slot', '?')}"] = lines
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

    ⚠ **`items_legal`을 매번 볼 것** — 이 도구는 빠른 개략치를 내지만 장비가 실재하는지는
    이제 함께 검사한다(#27). 실측 2026-08-09: 그 검사가 없던 동안 **10슬롯 중 4개가
    실재하지 않는 장비**인 채 20여 회 측정됐고 그 수치가 설계 근거로 쓰였다.
    `tree_connected`는 **트리 연결만**의 판정이다(옛 이름 `tree_legal`이 "빌드가 합법"으로
    읽혀 장비 실격을 가렸다). `req_shortfall`도 매 반환에 실린다 — 1회성 경고는
    문서와 동급이라(#29) 사라진 전례가 있다.

    `stale`은 **이 스펙의 어느 산출물이 낡았나**이다(#58 ③). `optimize_*`가 결과에
    `derived_from` 도장을 자동으로 박고, 그것을 스펙에 옮겨 두면 이후 config·주력
    스킬·장비가 바뀔 때 **무엇이 달라서 낡았는지 문장으로** 나온다 —
    `config.conditionLowLife: False → True` 꼴. 거부하지 않는다(낡은 것으로 A/B를
    재는 것도 정상 작업이다). 실측 사고: 선행 문서가 「트리 전부 무효」라고 적었는데
    다음 세션이 그 트리 위에 25포인트를 더 얹었다 — **무엇이 달라서 무효인지**를
    몰랐기 때문이다.

    `skipped_procedures`는 **출고 반환에만** 실린다(#58 ④) — 돌렸어야 하는데 흔적이
    없는 절차다. 지금은 `optimize_items`(유니크 전수) 하나이며 판정 근거는
    `derived_from`에 그 도장이 있느냐다. 규율은 이미 스킬 문서에 있었고 **감지 수단만**
    없었다 — 실측: 한 회차가 끝까지 안 돌려 유니크가 후보에 오른 적이 없었다.

    `design_warnings`는 **적법한데 애초에 빌드가 아닌 것**이다(#58 ①) — 주력 그룹에
    딜 스킬이 없거나 트리거 젬에 발동될 스킬이 없는 경우. 실측: 그 상태로 3회차가
    돌았고 `CombinedDPS` 2,562 vs 주력기 투입 시 24,436.

    `unset_config`는 **이 빌드에 관련 있는데 안 켠 PoB 설정**이다. 미설정 config의
    기본값에서 나온 델타 0은 "효과 없음"이 아니라 "안 켰다"의 증거다 — 그걸로
    무엇을 빼기 전에 이 목록을 볼 것(BUILD_DESIGN §2-3 측정 무효의 판정 의무).
    켜지 않는 게 맞는 축도 있으니 판단은 호출자 몫이다(AD-3)."""
    out = _pick(_compute(spec_from_dict(build_spec)), stats, build_spec)
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
        "base": _pick(base_result, stats, base_spec),
        "deltas": [
            {
                "label": d.label,
                "delta": {k: d.diff(k) for k in (stats or DEFAULT_STATS) if d.diff(k) is not None},
                "tree_connected": d.result.is_tree_legal,
                # 변경안이 **장비를 바꿨다면** 그 장비가 실재하는지도 봐야 한다 —
                # 기준만 검사하면 "바꾼 쪽이 가짜"인 델타를 그대로 믿게 된다(#27).
                **_items_legal(variants[d.label]),
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
    # **실현 불가능한 빌드는 출고하지 않는다** (사용자 인게임 대조 2026-08-06).
    # PoB 계산기는 노드 해금 조건도 어센던시 진입도 검사하지 않고 스탯을 더해 준다 —
    # 그래서 오라클 전용 노드 7개가 섞인 블러드 메이지 트리가 "정상 산출물"로 나갔고
    # (출혈 지속시간 1.50→1.90), 공급원 없는 config가 출혈 강도를 x2.76 부풀렸다.
    # 측정이 빌드를 왜곡하면 그 수치는 산출물이 아니라 거짓이다 — 탐침 게이트와 같은
    # 이유로 여기서 막는다. 빌드 품질 판정이 아니라(AD-3) 거짓 측정치의 출고 거부다.
    from pok.engine.constraints.assumptions import check_assumptions

    assumptions = check_assumptions(build_spec)
    if assumptions.blocking:
        return {
            "ok": False,
            "reason": "실현 불가능한 구성 — 인게임에서 성립하지 않는다",
            "blocking": list(assumptions.blocking),
            "locked_nodes": [
                {
                    "node_id": n.node_id,
                    "name": n.name,
                    "locked_to": n.locked_to,
                    "missing_nodes": list(n.missing_nodes),
                    "why": n.why,
                }
                for n in assumptions.locked_nodes
            ],
        }
    try:
        built = assemble(
            spec_from_dict(build_spec), slug, checker=_get_checker(), spec_data=build_spec
        )
    except (IllegalBuildError, ValueError) as e:
        # 스펙 오류(ValueError)도 사유로 돌려준다 — 예외로 터지면 호출자는
        # "어느 젬의 어느 키"인지 못 보고 추측으로 재시도한다
        return {"ok": False, "reason": str(e)}
    # **축 완전성을 자동으로 얹는다** — 호출해야 작동하는 검사는 호출을 건너뛰면
    # 무력하다. 실측 2026-08-06: axes·유니크 열거가 스킬 문서와 서버에 있었는데
    # 새 세션이 부르지 않아 유니크·주얼 미고려가 그대로 재발했다. 룬 소켓이 안
    # 빠졌던 이유는 어차피 부르는 exhaustion에 얹혀 나왔기 때문이다 — 같은 원리로
    # 모든 빌드가 통과하는 이 지점(출고)에 붙인다. 위반이 아니라 보고다(AD-3).
    from pok.engine.constraints.axes import check_axes

    axes_report = check_axes(build_spec)
    # 같은 원리로 **트리 대조**도 여기 얹는다 (#67 6차). 설계 시점(connect_anchors)에
    # 이미 붙지만, 그 도구를 안 거치고 노드 목록을 손으로 써서 바로 조립하는 경로가
    # 있다. 트리가 산출물에 들어가는 지점은 여기뿐이라 여기가 마지막 관문이다.
    # 차단하지 않는다 — 표본과 다르다는 것이 곧 결함은 아니다(AD-3, 보고).
    from pok.engine.tree.corpus import compare_build_spec

    return {
        "ok": True,
        "build_id": built.build_id,
        "path": str(built.path),
        "build_code": built.build_code,
        "duplicates": list(built.duplicates),
        "axes": {
            "empty": list(axes_report.empty_axes),
            "unmeasured": list(axes_report.unmeasured_axes),
            "notes": list(axes_report.notes),
        },
        "corpus": compare_build_spec(build_spec),
        # 차단은 안 되지만 **상시 참으로 가정한 config** — 공급원은 있으나 항상 켜져
        # 있지는 않다. 유지율을 적지 않으면 평시에 안 나오는 수치를 출고하는 것이다.
        # 필수 절차 미이행 — **출고 반환에만** 싣는다 (#58 ④). manifest에도 각인된다.
        **(
            {"skipped_procedures": missing_procedures(build_spec)}
            if missing_procedures(build_spec)
            else {}
        ),
        "assumptions": {
            "always_on_config": [
                {"var": v.var, "value": v.value, "source": v.matched_in}
                for v in assumptions.grounded
            ],
            "notes": list(assumptions.notes),
        },
        **_pick(built.result, stats, build_spec),
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


def restore_pob_spec(build_code: str, assume_first_stat_set: bool = True) -> dict[str, Any]:
    """PoB 공유 코드 → **우리 `build_spec`** (#67 6차). 남의 빌드를 우리 도구에 태운다.

    `parse_pob`은 요약(무엇이 들어 있나)이고 이건 복원(다시 계산할 수 있게)이다.
    래더 코퍼스의 PoB 코드를 `compute_pob`·`optimize_tree`·`evaluate_bundles`에
    그대로 넣을 수 있게 된다.

    ⚠ **`notes`·`needs_decision`을 반드시 읽을 것.** 코드에 없어서 못 되돌린 것과
    우리가 가정한 것이 거기 있다. 특히:
    - `stat_set_index` — PoB 코드는 **어느 모드로 계산했는지 안 남긴다**. 기본은 1번
      가정이고, 모드가 둘 이상인 젬이면 수치가 크게 달라진다(실측 20배).
    - 단계형 스킬의 `stages`도 코드에 없다(코퍼스 300벌 전부). 필요하면 직접 채울 것.
    - 교체 무기 슬롯·무기 세트 전용 할당은 우리 스펙에 자리가 없어 빠진다.

    실측 2026-08-12(래더 300벌): 복원 53벌 · 그중 EHP 오차 5% 이내 43% · 20% 이내 86%.
    거부 247벌은 대부분 우리 게이트(아이템 부여 스킬·단계형)가 막은 것이다.
    """
    from pok.pob.restore import spec_from_pob

    out = spec_from_pob(build_code, assume_first_stat_set=assume_first_stat_set)
    return {
        "build_spec": out.spec,
        "notes": list(out.notes),
        "needs_decision": list(out.needs_decision),
        "faithful": out.faithful,
        # 딜을 원본과 견주려면 이게 비어 있어야 한다 — 부여 그룹을 빼면 그 안의
        # 보조 젬(주얼러 오브로 늘린 소켓)이 함께 빠져 낮게 나온다.
        "dropped_item_granted": [
            {"skill": name, "lost_supports": n} for name, n in out.dropped_item_granted
        ],
        "damage_comparable": out.damage_comparable,
    }
