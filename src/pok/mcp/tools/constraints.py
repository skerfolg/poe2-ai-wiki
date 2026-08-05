"""설계 루프 MCP 도구 — check_constraints(D27)·evaluate_objective(D28)·
parse_design_doc(D26). 얇은 어댑터: 산수는 engine/constraints·engine/objective,
파싱은 artifacts/design이 하고 여기는 dict 입출력만 관리한다.

에이전트 워크플로(BUILD_DESIGN §4): design.md의 제약 원장(표·수식)을 읽어
아래 입력으로 전사(轉寫)하고, 리포트의 위반·여유분을 문서에 되쓴다.
"""

from __future__ import annotations

import dataclasses
from dataclasses import asdict
from typing import Any

from pok.engine.constraints import (
    AnointPlan,
    Bundle,
    KbDefaults,
    ReservationEntry,
    SideEffect,
    SkillLinks,
    SocketPlan,
    check_color_majority,
    check_exhaustion,
    check_point_budget,
    check_reservation,
    check_sustain,
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
    sustain: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """설계 제약 원장 5종의 결정적 검사(D27) — 준 것만 검사해 리포트 반환.

    입력 (모두 선택, design.md 장부의 전사):
      point_budget = {"bundles": [{"name","points","required"?}], "budget"?}
                     (budget 생략 = KB mechanic.ascendancy-points)
      color_ledger = {"skills": [{"skill", "supports": [[이름, 색], …]}], "color": "red"}
      reservation  = {"entries": [{"name","base_amount","fixed"?}], "efficiency_pct",
                      "pool"?, "axis"?, "low_life_threshold_pct"?}
                     **축 무관** — 생명력 축은 pool 생략(=100, 단위 %), 정신력 축은
                     pool=총 정신력·단위 절대량(CoC 100·신성 모독 저주당 60 등).
                     로우라이프 판정은 생명력 축에서만(임계 생략 = KB resource.life).
                     축별로 각각 호출하라 — 한 축 검증이 다른 축을 대신하지 않는다
      exhaustion   = {"skills": […color_ledger와 동일…], "anoints":
                      [{"item","existing"?,"planned"?}], "max_supports_per_skill"?,
                      "sockets": [{"item","sockets","filled"?}]}
                     **룬 소켓도 자원 축이다** — `sockets`를 주면 충전율과 미사용
                     칸을 보고한다. 총 칸은 베이스의 `data.socket_limit`(KB 수록).
                     미사용은 위반이 아니지만(비용상 의도일 수 있다) 보이지 않으면
                     판단할 수도 없다 — 실측 사고: 16칸 0% 사용에도 "5종 통과"였고,
                     나중에 채우자 DPS +37~47%가 나왔다
      sustain      = {"effects": [{"name","base_amount","mitigation_pct"?}], "pool",
                      "target_pool_ratio_pct"?} — 지속 가능성 경계(성립 질문의 산수):
                      부작용·비용 실효량 vs 가용 자원, 필요 경감 역산. 미측정이어도
                      원본·경감·가용이 수치로 있으면 경계는 여기서 계산한다.
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
                # base_pct = 생명력 축의 옛 이름 — 두 표기 모두 받는다
                base_amount=float(e.get("base_amount", e.get("base_pct", 0.0))),
                fixed=bool(e.get("fixed", False)),
            )
            for e in reservation.get("entries", [])
        )
        pool = float(reservation.get("pool") or 100.0)
        # 생명력 축(pool=100)이면 KB 임계로 로우라이프까지 판정, 정신력 등 다른 축은 생략.
        # axis를 명시하면 그 지시를 따른다 (예: axis="spirit" → 로우라이프 계산 안 함)
        axis = str(reservation.get("axis", "life" if pool == 100.0 else "other"))
        threshold: float | None = None
        if axis == "life":
            threshold = float(
                reservation.get("low_life_threshold_pct") or _get_defaults().low_life_threshold_pct
            )
        resv_report = check_reservation(
            entries,
            float(reservation.get("efficiency_pct", 0.0)),
            pool=pool,
            low_life_threshold_pct=threshold,
        )
        # remaining_pct는 property라 asdict에 안 실린다 — 축이 달라도 같은 척도로
        # 읽히는 값이라 소비자에게 필요하다
        out["reservation"] = {
            **dataclasses.asdict(resv_report),
            "remaining_pct": resv_report.remaining_pct,
        }
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
        socket_plans = tuple(
            SocketPlan(
                item=str(s["item"]),
                sockets=int(s.get("sockets", 0)),
                filled=int(s.get("filled", 0)),
            )
            for s in exhaustion.get("sockets", [])
        )
        exhaust_report = check_exhaustion(
            _skills(exhaustion.get("skills", [])),
            anoints,
            max_supports_per_skill=max_supports,
            sockets=socket_plans,
        )
        # rune_fill_pct는 property라 asdict에 안 실린다 — 0%가 조용히 지나가지 않게
        out["exhaustion"] = {
            **dataclasses.asdict(exhaust_report),
            "rune_fill_pct": exhaust_report.rune_fill_pct,
        }
    if sustain is not None:
        effects = tuple(
            SideEffect(
                name=str(e["name"]),
                base_amount=float(e["base_amount"]),
                mitigation_pct=float(e.get("mitigation_pct", 0.0)),
            )
            for e in sustain.get("effects", [])
        )
        target = sustain.get("target_pool_ratio_pct")
        out["sustain"] = dataclasses.asdict(
            check_sustain(
                effects,
                float(sustain["pool"]),
                target_pool_ratio_pct=float(target) if target is not None else None,
            )
        )
    if not out:
        return {"ok": False, "reason": "검사할 원장이 없음 — 5종 중 하나 이상을 넘길 것"}
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

    기본 반환: 헤더 4줄·경고·큐·**결정 관문**·미검증 가설(판정 조건 포함)·개수.

    미검증 가설은 `{claim, proof}` 쌍이다 — `proof`가 비면 그 가설은 큐에 쌓이기만
    하고 검증이 실행되지 않는다(v6·v7이 그 상태로 멈췄다). 파서가 경고로 알린다.
    `gates`는 컨셉을 계속 팔지 판단하는 관문 — 하나라도 실패하면 재검토 신호다.
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
        "gates": list(d.gates),
        # 가설은 판정 조건과 함께 — 조건 없는 것은 actionable=False (검증 실행 불가)
        "unverified": [dataclasses.asdict(h) for h in d.unverified],
        "unverified_actionable": sum(1 for h in d.unverified if h.actionable),
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


def compute_trigger_rate(
    gem_id: str,
    trigger: str,
    hits_per_second: float,
    socketed_cast_time_s: float,
    enemy_rarity: str = "normal",
    enemy_base_power: float | None = None,
    energy_gain_increase_pct: float = 0.0,
) -> dict[str, Any]:
    """메타 젬 발동률 (B-10) — PoB가 모델링하지 않는 축이라 여기서 잰다.

    `gem_id`는 KB 젬 레코드(`skill.cast-on-…`)이고, 에너지 계수·최대 에너지는
    그 레코드에서 읽는다(B-9 수록분). `trigger`는 에너지를 얻는 사건
    (`Freeze`·`Ignite`·`Shock`·`Critically`·`Hit`·`kill` 등 — 젬마다 다르다).

    `socketed_cast_time_s`는 **소켓된 스펠들의 기본 시전시간 합**이다. 최대 에너지가
    그것으로 정해진다(`10 maximum Energy per 0.1s of base cast time`).

    `energy_gain_increase_pct`에 품질·Impetus(+40%) 같은 "increased Energy gained"를
    합쳐 넣는다.

    ⚠ 대상 Power는 **예상치**다 — poe2db가 주는 건 등급별 범위 서술뿐이고 몬스터별
    표는 없다. 결과의 `assumptions`에 그 가정이 실려 온다.

    Power 기반이 아닌 젬(고정 25·이동거리·자원 등)은 계산하지 않고 사유를 낸다 —
    그 경우 젬 레코드의 `energy_stats` 원문을 읽을 것.
    """
    from pok.engine.trigger import Enemy, MetaGem
    from pok.engine.trigger import compute_trigger_rate as _rate
    from pok.index.search import get_entry

    record = get_entry(gem_id, fields=["data", "name"])
    data = record.get("data") or {}
    per_power = data.get("energy_per_power")
    if not per_power:
        return {
            "ok": False,
            "reason": (
                f"{gem_id}: Power 기반 에너지 계수가 없다 — 이 젬은 다른 방식으로 "
                f"에너지를 얻는다. 원문을 읽을 것: {data.get('energy_stats') or '(수록 없음)'}"
            ),
        }
    gem = MetaGem(
        name=str((record.get("name") or {}).get("en") or gem_id),
        energy_per_power=dict(per_power),
        max_energy_per_100ms=float(data.get("max_energy_per_100ms", 10.0)),
        max_energy_flat=data.get("max_energy_flat"),
        energy_gain_increase_pct=energy_gain_increase_pct,
    )
    enemy = Enemy(
        rarity=enemy_rarity,
        **({"base_power": enemy_base_power} if enemy_base_power is not None else {}),
    )
    try:
        result = _rate(
            gem,
            trigger,
            enemy=enemy,
            hits_per_second=hits_per_second,
            socketed_cast_time_s=socketed_cast_time_s,
        )
    except ValueError as e:
        return {"ok": False, "reason": str(e)}
    return {"ok": True, **asdict(result), "assumptions": list(result.assumptions)}
