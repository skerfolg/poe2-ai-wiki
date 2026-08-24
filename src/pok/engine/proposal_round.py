"""M5 라운드 러너 — 제안·측정을 **무인 배치**로 (확정 설계 2026-08-20).

## 왜 배치인가

사람이 루프의 동력이면 셋이 무너진다(사용자 지적 2026-08-20): ①노가다 ②탐색 공간이
**사람 머릿속 상한**에 갇힌다(LLM을 넣은 이유 자체가 그건데 트리거를 사람에게 걸면
도로 사람 상한이다) ③사용량에 기대면 축적이 빈약하다. M3 캠페인을 수십 시간 무인으로
돌린 것과 같은 이유로 M5도 라운드 단위 배치다.

사람은 **판정자**로만 남는다 — 정본 진입은 M6 큐레이션 게이트뿐이라, 라운드가 아무리
돌아도 정본은 안 움직인다.

## 세 단계 — 가운데만 LLM

    plan     결정적  라운드 브리프(유형 할당량·중복 제외·재료)를 낸다
    (제안)   LLM     세션이 브리프를 읽고 제안을 낸다 — 이 레포에 LLM 클라이언트는
                    없다. LLM은 **세션**이고, 무인화는 예약 세션이 담당한다
    measure  결정적  전개 → PoB 전수 측정 → 다이제스트

## 유형 할당량이 가로등을 막는다

할당량이 없으면 제안이 **잴 수 있는 조각**(스태킹)으로 쏠린다 — 창의의 중심 축
(트리거 연쇄·DoT·플레이 패턴)은 공급 그래프 밖이라 전개기도 없고 그래서 쓰기도
어렵다. 브리프가 유형별 최소 건수를 요구하고, 미달은 다이제스트에 남는다.

⛔ 여기서 제안의 좋고 나쁨을 판단하지 않는다(철칙 3). 할당·중복 제외·측정·집계만.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from pok.engine import dps_axis
from pok.engine.proposal import UNVERIFIABLE, VERIFICATION_ROUTES
from pok.engine.proposal_flow import proposals_dir, record_measurement

BRIEF = "round-brief.json"
DIGEST = "round-digest.json"

# 라운드당 메커니즘 유형별 **최소** 제안 수. 스태킹 쏠림을 막는 유일한 강제 지점이다.
# 값은 「고르게」이지 「옳게」가 아니다 — 유형의 값어치는 측정이 정한다.
TYPE_QUOTA: dict[str, int] = {
    "스태킹": 3,
    "트리거 연쇄": 3,
    "상태이상·DoT": 3,
    "자원 순환": 2,
    "방어 구성": 2,
    "기타": 2,
}


def _existing(season: str, base: Path | None) -> list[dict[str, Any]]:
    folder = proposals_dir(season, base=base)
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json")):
        if path.name in {BRIEF, DIGEST}:
            continue
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def build_brief(season: str, *, base: Path | None = None) -> dict[str, Any]:
    """라운드 브리프 — LLM 세션이 읽는 **유일한 입력 규격**.

    ⚠ 중복 제외 목록을 반드시 낸다. 없으면 라운드마다 같은 제안이 다시 나오고
    (LLM은 이전 라운드를 모른다) 측정 예산이 재탕에 소모된다.
    """
    prior = _existing(season, base)
    seen_types: dict[str, int] = {}
    for doc in prior:
        mech = str((doc.get("proposal") or {}).get("mechanism") or "기타")
        seen_types[mech] = seen_types.get(mech, 0) + 1
    return {
        "season": season,
        "quota": TYPE_QUOTA,
        "already_proposed": sorted(
            str((d.get("proposal") or {}).get("title") or "") for d in prior
        ),
        "prior_counts": seen_types,
        "routes": {k: v["limits"] for k, v in VERIFICATION_ROUTES.items()},
        "contract": (
            "제안마다 title·mechanism·premise·route·bundle이 필수다. 검증 경로를 "
            f'모르겠으면 route="{UNVERIFIABLE}" + route_gap(사유) — 버리지 말고 '
            "갭으로 남겨라. 그 라벨의 누적이 다음 측정기의 우선순위 데이터다"
        ),
        "materials": [
            "search_kb·get_entry — 메커니즘·담체 조회 (게임 지식은 KB가 정본이다)",
            "suggest_anchors — 채택률 + 제거 실측(NodeValue)이 함께 붙어 나온다",
            "scan_supply_edges·trace_chains — 비례 공급 그래프(스태킹 축)",
            "search_insights·get_insight — 이미 반증된 것을 다시 제안하지 말 것",
        ],
        "why_quota": (
            "유형 할당량은 **가로등 밑 열쇠 찾기**를 막는다 — 잴 수 있는 조각으로 "
            "제안이 쏠리면 창의의 중심 축(트리거·DoT·플레이 패턴)이 통째로 빠진다"
        ),
    }


def measure_round(
    season: str,
    spec_doc: dict[str, Any],
    *,
    base: Path | None = None,
    limit: int | None = None,
    daemon: Any = None,
) -> dict[str, Any]:
    """저장된 제안들을 전개·측정한다. **이미 측정된 제안은 건너뛴다**(재개 가능).

    측정 대상은 `spec_doc`(기준 빌드) 위의 변경이다 — 제안은 「무엇을 바꾸나」이지
    빌드 전체가 아니다. 기준이 없으면 델타가 없다.
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.deltas import evaluate_change_bundle
    from pok.engine.tree.graph import TreeGraph
    from pok.pob.buildxml import spec_from_dict
    from pok.pob.daemon import PobDaemon

    graph = TreeGraph(knowledge_dir())
    spec = spec_from_dict(spec_doc, validate_catalog=False)
    folder = proposals_dir(season, base=base)
    done = skipped = failed = 0
    gaps: list[dict[str, str]] = []
    own = daemon is None
    d = daemon or PobDaemon()
    try:
        pob_commit = getattr(d, "commit", "") or "unknown"
        for path in sorted(folder.glob("*.json")):
            if path.name in {BRIEF, DIGEST} or (limit is not None and done >= limit):
                continue
            doc = json.loads(path.read_text(encoding="utf-8"))
            proposal = doc.get("proposal") or {}
            if doc.get("measurements"):
                skipped += 1
                continue
            if proposal.get("route") == UNVERIFIABLE:
                # ⛔ 갭은 실패가 아니다 — 잴 수 없을 뿐이고 그 사실이 산출물이다
                gaps.append(
                    {
                        "title": str(proposal.get("title")),
                        "gap": str(proposal.get("route_gap") or ""),
                    }
                )
                continue
            for index, bundle in enumerate(doc.get("expansion", {}).get("bundles") or []):
                changes = _changes_for(bundle, graph)
                if not changes:
                    failed += 1
                    record_measurement(
                        path,
                        {
                            "bundle": index,
                            "pob_commit": pob_commit,
                            "failed": "담체를 측정 변경안으로 못 옮겼다 — "
                            "아이템 텍스트도 노드 번호도 못 찾음(전개기 갭)",
                        },
                    )
                    continue
                got = evaluate_change_bundle(spec, graph, changes, daemon=d)
                record_measurement(
                    path,
                    {
                        "bundle": index,
                        "pob_commit": pob_commit,
                        "deltas": dict(got.deltas),
                        # 시너지 = 묶음 - 개별 합. 양수면 **함께여야 열리는 조합**이다
                        # (실측 2026-08-05: 눈알 왕관+래스피스는 각각 0인데 함께 1.44배).
                        # M5가 LLM을 쓰는 이유가 이 항이라 반드시 싣는다.
                        "synergy": {k: got.synergy(k) for k in got.deltas},
                        "parts": list(got.parts),
                    },
                )
                done += 1
    finally:
        if own:
            d.close()
    return {"measured": done, "skipped": skipped, "failed": failed, "gaps": gaps}


def _changes_for(bundle: dict[str, Any], graph: Any) -> list[dict[str, Any]]:
    """전개 묶음 → `evaluate_change_bundle` 변경안.

    ⛔ 옮기지 못한 담체는 **조용히 빼지 않는다** — 부분 묶음을 재면 그 측정이 무엇을
    잰 것인지 알 수 없다. 하나라도 못 옮기면 빈 리스트를 내고 호출자가 실패로 남긴다.
    """
    from pok.engine.items import render_unique
    from pok.kb.store import load

    records = load().records
    changes: list[dict[str, Any]] = []
    for carrier in bundle.get("carriers") or []:
        record = records.get(str(carrier.get("id")))
        if record is None:
            return []
        data = record.raw.get("data") or {}
        if record.type == "Item":
            slot = carrier.get("slot") or data.get("slot")
            if not slot:
                return []
            changes.append({"item": {"slot": str(slot), "text": render_unique(record.raw)}})
        elif record.type == "Passive" and data.get("node_id") is not None:
            changes.append({"nodes": [int(data["node_id"])]})
        else:
            return []
    return changes


def digest(season: str, *, base: Path | None = None) -> dict[str, Any]:
    """사람이 **판정할 것만** 추린다 — 라운드 산출물의 사람 대면 면이다."""
    prior = _existing(season, base)
    rows: list[dict[str, Any]] = []
    gaps: list[dict[str, str]] = []
    by_type: dict[str, int] = {}
    for doc in prior:
        p = doc.get("proposal") or {}
        mech = str(p.get("mechanism") or "기타")
        by_type[mech] = by_type.get(mech, 0) + 1
        if p.get("route") == UNVERIFIABLE:
            gaps.append({"title": str(p.get("title")), "gap": str(p.get("route_gap") or "")})
            continue
        best = None
        for m in doc.get("measurements") or []:
            # ⛔ 축을 **고른다**(#113) — `showAverage` 스킬에서 `CombinedDPS`는 밑값이
            #    1회 평균 피해라 속도가 안 곱해진다. 기준선(`baseline`)이 있으면 거기서
            #    갈리고, 없으면 기본 축을 그대로 둔다(판정 불가를 확신으로 바꾸지 않는다).
            axis = dps_axis.axis_for(m.get("baseline") or {}, m.get("meta"))
            dps = (m.get("deltas") or {}).get(axis)
            if dps is None:
                continue
            if best is None or dps > best[0]:
                best = (dps, m)
        if best is not None:
            rows.append(
                {
                    "title": p.get("title"),
                    "mechanism": mech,
                    "premise": p.get("premise"),
                    "best_dps_delta": best[0],
                    "best_dps_axis": dps_axis.axis_for(
                        best[1].get("baseline") or {}, best[1].get("meta")
                    ),
                    "synergy": (best[1].get("synergy") or {}).get(
                        dps_axis.axis_for(best[1].get("baseline") or {}, best[1].get("meta"))
                    ),
                    "proposed_by": p.get("proposed_by"),
                }
            )
    rows.sort(key=lambda r: -(r["best_dps_delta"] or 0))
    short = {k: v - by_type.get(k, 0) for k, v in TYPE_QUOTA.items() if by_type.get(k, 0) < v}
    return {
        "season": season,
        "proposals": len(prior),
        "by_type": by_type,
        # ⚠ 할당 미달을 밝힌다 — 안 밝히면 「고르게 봤다」로 읽힌다
        "quota_shortfall": short,
        "ranked": rows[:30],
        # 갭은 실패가 아니라 **다음 측정기의 우선순위 데이터**다
        "tool_gaps": gaps,
        "note": (
            "⛔ 이 순위는 **측정값**이지 채택 권고가 아니다(철칙 3·4). 인게임 성립·"
            "조작 난이도·플레이 감각은 PoB가 못 잰다 — 정본 진입은 큐레이션 판정뿐이다"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="M5 제안 라운드 — 브리프·측정·다이제스트")
    ap.add_argument("command", choices=["brief", "measure", "digest"])
    ap.add_argument("--season", required=True)
    ap.add_argument("--spec", type=Path, help="measure: 기준 빌드 스펙 JSON")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    if args.command == "brief":
        doc = build_brief(args.season)
        folder = proposals_dir(args.season)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / BRIEF).write_text(
            json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
        )
        print(json.dumps({"brief": str(folder / BRIEF), "quota": doc["quota"]}, ensure_ascii=False))
        return 0
    if args.command == "measure":
        if not args.spec:
            print(
                json.dumps(
                    {"error": "--spec(기준 빌드)이 없다 — 기준이 없으면 델타가 없다"},
                    ensure_ascii=False,
                )
            )
            return 2
        got = measure_round(
            args.season, json.loads(args.spec.read_text(encoding="utf-8")), limit=args.limit
        )
        print(json.dumps(got, ensure_ascii=False, indent=1))
        return 0
    doc = digest(args.season)
    folder = proposals_dir(args.season)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / DIGEST).write_text(
        json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps({k: v for k, v in doc.items() if k != "ranked"}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
