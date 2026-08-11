"""빌드 조립·검증·기록 — assemble_pob의 실행부 (BLUEPRINT §10.2 ⑧~⑨).

결정적 파이프라인만 담당한다(AD-3):
  BuildSpec → ① 합성 아이템 적법성(RC4) → ② PoB 계산(트리 적법성 포함)
  → ③ artifacts/builds/<build-id>/ 기록 (build.xml·build.pob·validation.json)

validation.json은 **실측 기록이지 합격 판정이 아니다** — 다차원 목적 프로파일
대비 floor 판정(RC1: validation은 바닥선)은 skills/+에이전트의 몫.
"무엇을 만들지"의 판단도 여기 없다: 이 모듈은 주어진 스펙을 조립·측정·보존만 한다.
"""

from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.artifacts.store import find_by_hash, new_build_id, record_build
from pok.common.paths import knowledge_dir
from pok.engine.decisions import (
    find_design_doc,
    rejected_but_present,
    rejection_record_gap,
)
from pok.engine.integrity import spec_integrity
from pok.engine.legality import ItemLegalityChecker, LegalityReport
from pok.engine.provenance import missing_procedures, stale_components
from pok.pob import codec
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.runner import PobResult, run_build
from pok.pob.versions import pinned_commit


@dataclass(frozen=True)
class AssembledBuild:
    """조립 결과 — 기록 위치·PoB 공유 코드·실측·적법성을 한 번에."""

    build_id: str
    path: Path
    build_code: str  # PoB '불러오기'에 붙여넣는 코드
    result: PobResult
    item_reports: dict[str, LegalityReport]  # slot → 판정
    duplicates: tuple[str, ...]  # 같은 content_hash의 기존 build-id들

    @property
    def is_legal(self) -> bool:
        return self.result.is_tree_legal and all(r.is_legal for r in self.item_reports.values())


class IllegalBuildError(ValueError):
    """RC4: 못 만드는 아이템이 포함된 빌드 — 사유를 담는다."""


def assemble(
    spec: BuildSpec,
    slug: str,
    *,
    checker: ItemLegalityChecker | None = None,
    strict: bool = True,
    use_cache: bool = True,
    spec_data: dict[str, Any] | None = None,
) -> AssembledBuild:
    """조립→검증→계산→기록. strict=True(기본)면 비합법 아이템에서 즉시 거부.

    strict=False는 진단 목적(비합법을 알면서 스탯을 보고 싶을 때)만 —
    기록물 validation.json에 비합법 사실이 그대로 남는다.

    `spec_data`는 **PoB에 안 가는 스펙 칸**(`derived_from`)을 읽으려는 것이다 —
    `BuildSpec`엔 없지만 산출 출처는 기록물에 남아야 다음 세션이 안다(#58 ③).
    """
    chk = checker or ItemLegalityChecker(knowledge_dir())
    item_reports: dict[str, LegalityReport] = {}
    targets = [(item.slot, item.text) for item in spec.items] + [
        (f"Jewel@{j.socket_node_id}", j.text) for j in spec.jewels
    ]
    for slot, text in targets:
        report = chk.check(text)
        item_reports[slot] = report
        if strict and not report.is_legal:
            problems = list(report.errors) + [
                f"{v.line} → {v.status}: {v.reason}"
                for v in report.verdicts
                if v.status in ("ILLEGAL", "UNKNOWN")
            ]
            raise IllegalBuildError(f"[{slot}] " + " / ".join(problems))

    result = run_build(spec, use_cache=use_cache)
    if strict and not result.is_tree_legal:
        raise IllegalBuildError(_pruned_reason(result.pruned_nodes))

    xml = to_xml(spec)
    build_code = codec.encode(xml)
    build_id = new_build_id(slug)
    validation: dict[str, Any] = {
        "stats": result.stats,  # PoB 실측 전부 — floor 판정은 소비자(스킬) 몫
        "meta": result.meta,
        "tree": {
            "requested": list(spec.tree_nodes),
            "allocated": list(result.allocated_nodes),
            "pruned": list(result.pruned_nodes),
            "legal": result.is_tree_legal,
        },
        "items": {
            slot: {
                "legal": r.is_legal,
                "errors": list(r.errors),
                "lines": [dataclasses.asdict(v) for v in r.verdicts],
            }
            for slot, r in item_reports.items()
        },
    }
    files = {
        "build.xml": xml,
        "build.pob": build_code + "\n",
        "validation.json": json.dumps(validation, ensure_ascii=False, indent=1, sort_keys=True)
        + "\n",
    }
    manifest: dict[str, Any] = {
        "pob_commit": pinned_commit(),
        "class": spec.class_name,
        "ascendancy": spec.ascendancy,
        "level": spec.level,
        "legal": bool(result.is_tree_legal and all(r.is_legal for r in item_reports.values())),
    }
    # 설계 무결성 경고는 **산출물에 각인한다** (#58 ①, 보고자 요청 2026-08-11).
    # 반환값에만 실으면 그 자리에서만 보이고 사라진다 — 다음 세션은 `build.pob`만
    # 받아 이어받으므로, 「주력기가 없는 채로 출고됐다」는 사실이 기록에 남아야 한다.
    design = spec_integrity(dataclasses.asdict(spec))
    if design:
        manifest["design_warnings"] = list(design)
    # 낡음도 각인한다 — 정본 출고물만 받은 다음 세션이 "이 트리가 어느 문맥에서
    # 나왔는지"를 알 수 있어야 한다(#58 ③). `derived_from`은 스펙에만 있고 PoB로는
    # 안 가므로 조립이 옮겨 주지 않으면 사라진다.
    if spec_data is not None:
        stamps = spec_data.get("derived_from")
        if stamps:
            manifest["derived_from"] = stamps
        stale = stale_components(spec_data)
        if stale:
            manifest["stale"] = stale
        # **출고 시점에만** 묻는다 (#58 ④) — 탐색 중에는 안 돌린 게 정상이라 매번
        # 물으면 소음이 된다(§0 ⑤). 규율은 이미 `skills/`에 있었고 **감지 수단만**
        # 없었다: 실측 2026-08-11, 한 회차가 유니크 전수를 끝까지 안 돌렸고 그래서
        # 검은화염을 포함한 유니크가 후보에 오른 적이 없었다.
        skipped = missing_procedures(spec_data)
        if skipped:
            manifest["skipped_procedures"] = skipped
        # **문서의 기각 결정과 대조한다** (#58 ②). 적법성은 「기각했었나」를 모른다 —
        # 실측: 문서가 기각한 복점관이 스펙에 남아 5슬롯 실측 전체가 그 위에서 나왔다.
        # 문서는 슬러그로 자동 탐색한다(인자를 새로 만들면 안 넘기면 그만이다).
        design_text = find_design_doc(slug)
        if design_text:
            revived = rejected_but_present(spec_data, design_text)
            if revived:
                manifest["rejected_but_present"] = revived
            gap = rejection_record_gap(design_text)
            if gap:
                manifest["design_record_gap"] = gap

    # 대체 모델링 계보(B-3): 효과를 트리 노드로 재현한 주얼은 사실을 기록에 남긴다 —
    # 소켓 소모·조달 가정은 재현되지 않으므로 실측 해석 시 이 사실이 필요하다.
    substitutes = [
        {"socket_node_id": j.socket_node_id, "allocated_nodes": list(j.allocates)}
        for j in spec.jewels
        if j.allocates
    ]
    if substitutes:
        manifest["substitute_modeling"] = {
            "reason": (
                "KB pob_computable:false 유니크 — explicits가 플레이스홀더라 텍스트 조립 불가"
            ),
            "method": "부여 노터블을 트리 노드로 직접 할당해 효과만 재현",
            "not_reproduced": ["주얼 소켓 소모", "랜덤 롤 조달 가정"],
            "jewels": substitutes,
        }
    # 대리 측정 주입(#3, 2026-08-08): PoB가 못 읽는 문구를 등가 표현으로 바꿔 넣은 것.
    # **이 기록이 없으면 추산이 실측으로 읽힌다** — 산출물을 나중에 보는 쪽은 어느 수치가
    # 주입분인지 알 방법이 없다. 사람 기억에 맡기지 않고 조립이 자동으로 붙인다(철칙 5).
    injected = [
        {"slot": item.slot, "lines": list(item.substitutes)}
        for item in spec.items
        if item.substitutes
    ]
    if injected:
        entry = manifest.setdefault("substitute_modeling", {})
        entry["injected_lines"] = injected
        # 룬 증폭 함정 — 주입 줄은 PoB가 룬으로 인식하지 못해 `socketedRuneEffectModifier`가
        # **안 곱해진다**. 실측 2026-08-09(룬 효과 +200%): 정본 표기 +300 vs 주입 +100.
        # 문서 규율로 두면 안 지켜진다(철칙 5) — 감지되는 조건이므로 조립이 붙인다.
        rune_warning = _rune_amplification_warning(spec)
        if rune_warning:
            entry["rune_amplification"] = rune_warning
        entry["estimate"] = (
            "PoB가 계산하지 못하는 효과를 등가 문구로 주입해 잰 값이다 — **실측이 아니라 "
            "추산**이다. 원문과 등가라는 보장은 없고, 주입 문구가 원래 대상 한정어를 잃으므로 "
            "적용 범위가 실제보다 넓을 수 있다"
        )
    path = record_build(build_id, files, manifest)
    manifest_hash = json.loads((path / "manifest.json").read_text(encoding="utf-8"))["content_hash"]
    dups = tuple(b for b in find_by_hash(manifest_hash) if b != build_id)
    return AssembledBuild(
        build_id=build_id,
        path=path,
        build_code=build_code,
        result=result,
        item_reports=item_reports,
        duplicates=dups,
    )


def _pruned_reason(pruned: tuple[int, ...]) -> str:
    """PoB가 잘라낸 노드 — **왜 잘렸는지**까지 말한다 (백로그 #26 요청안 3).

    "비연결"과 "PoB가 자동 배정하는 노드라 목록에 못 넣는다"는 원인이 전혀 다른데
    같은 문구로 나왔다. 어센던시 시작 노드는 PoB가 **스스로 배정하고 포인트로 세지
    않으므로**(`points.py` 주석), `tree_nodes`에 적으면 항상 잘린다 — 그건 트리가
    끊긴 게 아니라 **적을 필요가 없는 것을 적은 것**이다.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.graph import TreeGraph

    graph = TreeGraph(knowledge_dir())
    auto = [
        n
        for n in pruned
        if (node := graph.nodes.get(n)) is not None and node.kind == "ascendancy-start"
    ]
    rest = [n for n in pruned if n not in auto]
    parts: list[str] = []
    if auto:
        parts.append(
            f"어센던시 **시작 노드** {tuple(auto)}는 PoB가 자동 배정한다 — "
            f"`tree_nodes`에서 빼면 된다(트리가 끊긴 게 아니다)"
        )
    if rest:
        parts.append(f"트리 비연결 노드: {tuple(rest)}")
    return " / ".join(parts) if parts else f"트리 비연결 노드: {pruned}"


_RUNE_EFFECT_LINE = re.compile(r"(\d+(?:\.\d+)?)%\s+increased effect of Socketed Runes", re.I)


def _rune_amplification_warning(spec: BuildSpec) -> str:
    """주입 줄이 룬 증폭을 잃는 상황인가 (#3 확장, 2026-08-09).

    `substitutes`로 넣은 줄은 `augmentType == "Rune"`이 안 붙어 아이템의
    `increased effect of Socketed Runes`가 **곱해지지 않는다**. 실측(`Greater Body
    Rune` 2개 · 룬 효과 +200%): 정본 표기 **+300** vs 주입 **+100** — 3배 과소다.

    조건이 명확하니(주입 줄 + 그 아이템에 룬 효과 줄) 문서가 아니라 여기서 잡는다.
    수치를 고쳐 주지는 않는다 — 무엇을 얼마로 선반영할지는 호출자의 판단이다(AD-3).
    """
    hits: list[str] = []
    for item in spec.items:
        if not item.substitutes:
            continue
        match = _RUNE_EFFECT_LINE.search(item.text)
        if match:
            hits.append(f"{item.slot}(+{match.group(1)}%)")
    if not hits:
        return ""
    return (
        f"⚠ 주입 줄이 있는 아이템에 **룬 효과 증폭**이 걸려 있다({' · '.join(hits)}) — "
        "`substitutes` 줄은 룬으로 인식되지 않아 그 증폭이 **안 곱해진다**(실측: 정본 "
        "+300 vs 주입 +100). 룬을 대리 측정한 것이라면 수치에 (1 + 룬효과/100)을 "
        "선반영하고 그 사실을 산출물에 적을 것 — 안 적으면 다음 사람이 두 번 곱한다. "
        "가능하면 대리 측정 대신 `optimize_runes`/`render_runed`를 쓴다"
    )
