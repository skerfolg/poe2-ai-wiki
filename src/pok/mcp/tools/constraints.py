"""설계 루프 MCP 도구 — check_constraints(D27)·evaluate_objective(D28)·
parse_design_doc(D26). 얇은 어댑터: 산수는 engine/constraints·engine/objective,
파싱은 artifacts/design이 하고 여기는 dict 입출력만 관리한다.

에이전트 워크플로(BUILD_DESIGN §4): design.md의 제약 원장(표·수식)을 읽어
아래 입력으로 전사(轉寫)하고, 리포트의 위반·여유분을 문서에 되쓴다.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from pok.engine.constraints import (
    AnointPlan,
    Bundle,
    KbDefaults,
    ReservationEntry,
    SkillLinks,
    check_color_majority,
    check_exhaustion,
    check_point_budget,
    check_reservation,
    kb_defaults,
)
from pok.engine.objective import Target, evaluate_targets

_defaults: KbDefaults | None = None


def _get_defaults() -> KbDefaults:
    global _defaults
    if _defaults is None:
        _defaults = kb_defaults()
    return _defaults


def _skills(raw: list[dict[str, Any]]) -> tuple[SkillLinks, ...]:
    return tuple(
        SkillLinks(
            skill=str(s.get("skill", "")),
            supports=tuple((str(n), str(c)) for n, c in s.get("supports", [])),
        )
        for s in raw
    )


def check_constraints(
    point_budget: dict[str, Any] | None = None,
    color_ledger: dict[str, Any] | None = None,
    reservation: dict[str, Any] | None = None,
    exhaustion: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """설계 제약 원장 4종의 결정적 검사(D27) — 준 것만 검사해 리포트 반환.

    입력 (모두 선택, design.md 장부의 전사):
      point_budget = {"bundles": [{"name","points","required"?}], "budget"?}
                     (budget 생략 = KB mechanic.ascendancy-points)
      color_ledger = {"skills": [{"skill", "supports": [[이름, 색], …]}], "color": "red"}
      reservation  = {"entries": [{"name","base_pct","fixed"?}], "efficiency_pct",
                      "low_life_threshold_pct"?}  (임계 생략 = KB resource.life)
      exhaustion   = {"skills": […color_ledger와 동일…], "anoints":
                      [{"item","existing"?,"planned"?}], "max_supports_per_skill"?}
    판단 없음(AD-3): 위반 사유·여유분만 — 무엇을 고를지는 호출자 몫.
    """
    out: dict[str, Any] = {}
    if point_budget is not None:
        bundles = tuple(
            Bundle(
                name=str(b["name"]),
                points=int(b["points"]),
                required=bool(b.get("required", False)),
            )
            for b in point_budget.get("bundles", [])
        )
        budget = int(point_budget.get("budget") or _get_defaults().ascendancy_budget)
        out["point_budget"] = dataclasses.asdict(check_point_budget(bundles, budget))
    if color_ledger is not None:
        report = check_color_majority(
            _skills(color_ledger.get("skills", [])), str(color_ledger.get("color", "red"))
        )
        out["color_ledger"] = dataclasses.asdict(report)
    if reservation is not None:
        entries = tuple(
            ReservationEntry(
                name=str(e["name"]),
                base_pct=float(e["base_pct"]),
                fixed=bool(e.get("fixed", False)),
            )
            for e in reservation.get("entries", [])
        )
        threshold = float(
            reservation.get("low_life_threshold_pct") or _get_defaults().low_life_threshold_pct
        )
        out["reservation"] = dataclasses.asdict(
            check_reservation(
                entries,
                float(reservation.get("efficiency_pct", 0.0)),
                low_life_threshold_pct=threshold,
            )
        )
    if exhaustion is not None:
        anoints = tuple(
            AnointPlan(
                item=str(a["item"]),
                existing=a.get("existing"),
                planned=a.get("planned"),
            )
            for a in exhaustion.get("anoints", [])
        )
        max_supports = int(
            exhaustion.get("max_supports_per_skill") or _get_defaults().max_supports_per_skill
        )
        out["exhaustion"] = dataclasses.asdict(
            check_exhaustion(
                _skills(exhaustion.get("skills", [])),
                anoints,
                max_supports_per_skill=max_supports,
            )
        )
    if not out:
        return {"ok": False, "reason": "검사할 원장이 없음 — 4종 중 하나 이상을 넘길 것"}
    return out


def evaluate_objective(targets: list[dict[str, Any]], measured: dict[str, float]) -> dict[str, Any]:
    """목표 상태 판정(D28) — targets 나열 순서 = 우선순위(사전식).

    targets = [{"metric","op" (">="|"<="),"value","label"?}, …]
    measured = {metric: 실측값} — 출처는 PoB stats·인게임 정보창·제약 검사기
    리포트만(추측값 금지, AD-8). 첫 미충족(미측정 포함)이 next_bottleneck.
    """
    report = evaluate_targets(
        tuple(
            Target(
                metric=str(t["metric"]),
                op=str(t["op"]),
                value=float(t["value"]),
                label=str(t.get("label", "")),
            )
            for t in targets
        ),
        measured,
    )
    return dataclasses.asdict(report)


def parse_design_doc(build_id: str, full: bool = False) -> dict[str, Any]:
    """artifacts/builds/<build_id>/design.md 를 BUILD_DESIGN §4 계약으로 파싱.

    기본 반환: 헤더 4줄·경고·큐·미검증 목록(P5 가설 입력)·섹션/표/수식 개수.
    full=True 면 확정/잠정 목록과 수식·표 원문까지 (토큰 예산 주의).
    """
    from pok.artifacts.design import parse_design
    from pok.common.paths import artifacts_dir

    path = artifacts_dir() / "builds" / build_id / "design.md"
    if not path.exists():
        return {"ok": False, "reason": f"설계 문서 없음: {path}"}
    d = parse_design(path.read_text(encoding="utf-8"))
    out: dict[str, Any] = {
        "ok": True,
        "version": d.version,
        "updated": d.updated,
        "status": d.status,
        "goal": d.goal,
        "warnings": list(d.warnings),
        "has_constraints": d.has_constraints,
        "queue": list(d.queue),
        "unverified": list(d.unverified),
        "counts": {
            "headings": len(d.headings),
            "confirmed": len(d.confirmed),
            "tentative": len(d.tentative),
            "unverified": len(d.unverified),
            "formulas": len(d.formulas),
            "tables": len(d.tables),
        },
    }
    if full:
        out["confirmed"] = list(d.confirmed)
        out["tentative"] = list(d.tentative)
        out["formulas"] = [dataclasses.asdict(f) for f in d.formulas]
        out["tables"] = [dataclasses.asdict(t) for t in d.tables]
    return out
