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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.artifacts.store import find_by_hash, new_build_id, record_build
from pok.common.paths import knowledge_dir
from pok.engine.legality import ItemLegalityChecker, LegalityReport
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
) -> AssembledBuild:
    """조립→검증→계산→기록. strict=True(기본)면 비합법 아이템에서 즉시 거부.

    strict=False는 진단 목적(비합법을 알면서 스탯을 보고 싶을 때)만 —
    기록물 validation.json에 비합법 사실이 그대로 남는다.
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
