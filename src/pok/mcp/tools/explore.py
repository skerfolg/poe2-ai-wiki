"""능동 탐사 MCP 도구 — 시너지 스캔·가설 큐. 얇은 어댑터(산수·판정은 하위 계층).

수동 기록만으로는 KB가 사용자의 사고 범위에 갇힌다. 이 도구들은 정본 전수에서
**아직 아무도 시도하지 않은 조합**과 **요구에 비해 공급이 마른 축**을 꺼내온다.

결과는 전부 **후보**다 — 성립 여부는 게임 지식 판정이고 사람 게이트의 몫이다(AD-3).
"""

from __future__ import annotations

import dataclasses
from typing import Any

from pok.kb import store as kb_store
from pok.kb.graph.synergy import scan_synergies as _scan
from pok.learning.hypothesis import find_hypotheses as _find
from pok.learning.hypothesis import queue_hypotheses as _queue


def scan_synergies(subject_key: str | None = None, limit: int = 40) -> dict[str, Any]:
    """요구-공급 맞물림 스캔 — 조건 subject를 축으로 조합 후보를 낸다.

    시너지의 결정적 정의: A가 공급하는 조건을 B가 요구하면 AxB는 후보다.
    (예: "Chill 확률 증가"가 공급하는 `enemy.status=chilled`를
     "냉각된 적에게 피해 증가"가 요구한다)

    subject_key: 특정 축만 (예: "enemy.status=chilled", "self.charge.power").
                 생략하면 전 축. 축 목록은 summary로 항상 돌아온다.
    limit: 쌍 상한 (전체는 5,000쌍 규모 — 요약은 잘리지 않는다).

    반환: summary(축별 공급·요구·쌍 수) + pairs(근거 문구 포함) + truncated.
    점수·순위는 없다 — 무엇이 좋은 조합인지는 호출자가 판단한다.
    """
    scan = _scan(kb_store.load(), subject_key=subject_key, limit=limit)
    return {
        "summary": [dataclasses.asdict(s) for s in scan.summary],
        "pairs": [dataclasses.asdict(p) for p in scan.pairs],
        "truncated": scan.truncated,
    }


def find_hypotheses(
    demand_supply_ratio: float = 3.0, max_pairs: int = 12, queue: bool = False
) -> dict[str, Any]:
    """능동 탐사 가설을 만든다 — 미탐사 조합(pair)과 수급 갭(gap).

    gap: 요구/공급 비가 `demand_supply_ratio` 이상인 축. "이 조건을 원하는 효과는
         많은데 만드는 법은 몇 개뿐" — KB 수집 갭이거나 미탐사 설계 공간이다.
    pair: 어떤 산출물(설계 문서·인사이트·피드백)에도 함께 등장한 적 없는 조합.

    queue=True 면 사람 피드백과 **같은 파이프라인**에 올린다(피드백 기록 →
    큐레이션 후보). 그 뒤는 `decide`로 판정하고 승인분만 승격한다 — 기계 가설이
    정본에 바로 들어가는 경로는 없다.
    """
    store = kb_store.load()
    if queue:
        feedback_id, count = _queue(
            store, demand_supply_ratio=demand_supply_ratio, max_pairs=max_pairs
        )
        return {
            "queued": count,
            "feedback_id": feedback_id,
            "next": "curation.decide 로 항목별 판정 후 승인분만 promote_insight",
        }
    return {
        "hypotheses": [
            dataclasses.asdict(h)
            for h in _find(store, demand_supply_ratio=demand_supply_ratio, max_pairs=max_pairs)
        ]
    }


def discover_mechanics(
    concepts: list[str] | None = None,
    types: list[str] | None = None,
    limit: int = 60,
) -> dict[str, Any]:
    """메커니즘 의심 엣지 **발견** — 판정은 사용자 몫 (사용자 지시 2026-08-06).

    메커니즘 사전(GAME_DATA 정의문)을 스킬·보조·아이템·패시브·메커니즘의 효과
    문구와 결정적으로 대조해, 관계 그래프에 아직 없는 **의심 연결**을 출처 인용문과
    함께 낸다. 컨셉만 받아도 돈다 — 예: concepts=["bleed"]면 출혈 축에 닿는
    후보만(빌드 발산 단계의 "이런 것도 가능해 보인다" 재료, 근거 포함).

    **이것은 사실 목록이 아니라 수록 후보 큐다**: ① 인용문을 보고 실제 연계인지
    판정을 받는다(negated=true는 면역·차단일 가능성) ② 승인되면 typed edge로 정본
    수록(store API — B-6) ③ 기각은 design.md에 기록해 같은 후보를 다시 묻지
    않는다. Mechanic 출처 + conditional=true가 앞에 온다 — 상태 전이(동결→산산조각
    류)가 연쇄의 뼈대라서다.

    한계: 사전 매칭이라 문구에 키워드가 없는 암묵 상호작용(PoB 내부 구현만 존재)은
    못 찾는다. 언급≠인과 — 최종 판정은 게임 지식 게이트(사용자)가 한다.
    """
    from pok.kb.graph.mentions import scan_mechanic_mentions

    scan = scan_mechanic_mentions(
        concepts=tuple(concepts or ()),
        types=tuple(types) if types else ("Skill", "Support", "Item", "Passive", "Mechanic"),
        limit=limit,
    )
    return {
        "edges": [
            {
                "source": e.source_id,
                "source_type": e.source_type,
                "mechanic": e.mechanic_id,
                "quote": e.quote,
                "conditional": e.conditional,
                "negated": e.negated,
            }
            for e in scan.edges
        ],
        "total_found": scan.total_found,
        "lexicon_size": scan.lexicon_size,
        "notes": list(scan.notes),
    }


def scan_state_edges(
    axis: str | None = None,
    kind: str | None = None,
    limit: int = 150,
) -> dict[str, Any]:
    """상태 축의 생산·소비·페이오프 엣지 전수 — 「무엇이 무엇을 만들고 먹나」 (#92).

    `scan_supply_edges`(스탯→스탯)의 자매다. 두 소스를 **융합**한다:
    구조화 타입(`GeneratesInfusion`·`SkillConsumesFreeze` 등 33종 — 소비/생산
    의미론이 정확)과 텍스트 술어(상태이상 생산·페이오프). 어느 한쪽만 쓰면
    그래프의 절반만 나온다(실측: 타입만 쓰면 20축 중 2축만 연쇄 가능).

    axis: 특정 상태 축만 (예: "freeze", "infusion", "ward"). 축 목록은 `axes`에.
    kind: "produce" | "consume" | "payoff"만 거르기.

    ⚠ **consume과 payoff는 다르다** — 소비는 그 상태를 없애므로 다음 소비자가 먹지
    못한다. 사슬을 이을 때 이 구분이 없으면 불가능한 연쇄가 나온다.
    ⚠ `source`가 "text"인 엣지는 문구 패턴 매칭이라 소비/잔존을 구분하지 못한다 —
    소비 판정은 "type" 출처에만 있다.
    반환의 `unproduced_axes`는 **소비·페이오프는 있는데 생산자가 없는 축**이다:
    수집 갭이거나 어휘 갭이니 "그 축은 못 쓴다"로 읽지 말 것.
    """
    from pok.kb.graph.mechanism import scan_state_edges as _scan_state

    scan = _scan_state(kb_store.load())
    edges = [
        e
        for e in scan.edges
        if (axis is None or e.axis == axis) and (kind is None or e.kind == kind)
    ]
    return {
        "edges": [dataclasses.asdict(e) for e in edges[:limit]],
        "axes": [dataclasses.asdict(a) for a in scan.axes],
        "unproduced_axes": list(scan.unproduced_axes),
        "total_matched": len(edges),
        "truncated": len(edges) > limit,
    }


def trace_mechanism_chains(
    from_axis: str | None = None, depth: int = 4, max_chains: int = 60
) -> dict[str, Any]:
    """상태 전이를 이어 다단 연쇄를 편다 — 「A를 만들면 무엇까지 갈 수 있나」 (#92).

    전이 = 한 담체가 상태 A를 먹고(consume/payoff) 상태 B를 만드는 것.
    예: `Snap`은 동결·감전·점화를 소비해 주입과 잔류물을 생산한다 →
    `freeze → infusion → charge` 같은 사슬이 나온다.

    from_axis 생략 시 전이가 있는 모든 축에서 출발한다. 같은 축 경로를 여러 담체가
    잇는 경우는 **한 사슬의 마디별 선택지**(`hop_options`)로 묶는다 — 담체 수만큼
    사슬을 복제하지 않는다.

    `terminal_payoffs`는 사슬 끝 축의 페이오프 수다(「여기까지 오면 무엇을 먹나」).
    순위·점수는 없다 — 어느 연쇄가 좋은지는 호출자가 근거를 보고 판단한다(AD-3).
    """
    from pok.kb.graph.mechanism import trace_mechanism_chains as _trace

    trace = _trace(kb_store.load(), from_axis, depth=depth, max_chains=max_chains)
    return {
        "chains": [
            {
                "axes": list(c.axes),
                "hop_options": [list(o) for o in c.hop_options],
                "terminal_payoffs": c.terminal_payoffs,
                "warnings": list(c.warnings),
                "transitions": [dataclasses.asdict(t) for t in c.transitions],
            }
            for c in trace.chains
        ],
        "transition_count": len(trace.transitions),
        "truncated": trace.truncated,
    }


def trace_cross_chains(
    from_axis: str | None = None,
    depth: int = 4,
    max_chains: int = 60,
    cross_only: bool = False,
) -> dict[str, Any]:
    """스탯·상태·객체를 **한 사슬로** 잇는 교차 순회 (#95).

    `trace_chains`(스탯)와 `trace_mechanism_chains`(상태·객체)는 각각 자기 층만
    순회한다 — 두 축 어휘가 갈려 있어 「생명을 쌓으면 어떤 상태가 열리나」에 답할 수
    없었다. 이 도구는 두 전이 목록을 합쳐 순회하고, 마디마다 **층 꼬리표**를 단다:

      · `supply` — A가 늘면 B가 **비례해서** 는다
      · `state`  — 한 담체가 A를 **먹고** B를 만든다(A는 사라질 수 있다)

    `cross_only=True`면 **층이 바뀌는 사슬만** 낸다(이 도구의 고유 산출).

    ⚠ **실측 2026-08-21: 교차 전이는 아직 0건이다.** 어휘를 통일해 공유 축이 7종이
    됐는데도 방향이 안 겹친다 — supply는 스탯에 도착하고 state는 상태·객체에서
    출발한다. 그래서 지금 이 도구의 실익은 **페이오프 병합**이다: `power_charge`는
    스탯 그래프만 보면 2건이지만 두 층을 합치면 **60건**이다(한 층만 보면 그 축을
    과소평가한다).
    """
    from pok.kb.graph.crosswalk import trace_cross_chains as _trace

    trace = _trace(
        kb_store.load(), from_axis, depth=depth, max_chains=max_chains, cross_only=cross_only
    )
    return {
        "chains": [
            {
                "axes": list(c.axes),
                "layers": list(c.layers),
                "hop_options": [list(o) for o in c.hop_options],
                "terminal_payoffs": c.terminal_payoffs,
                "crosses_layers": c.crosses_layers,
                "hops": [dataclasses.asdict(h) for h in c.hops],
            }
            for c in trace.chains
        ],
        "edge_count": trace.edge_count,
        "shared_axes": list(trace.shared_axes),
        "truncated": trace.truncated,
    }


def find_carriers(skill: str, include_blocked: bool = False) -> dict[str, Any]:
    """이 스킬을 **담을 수 있는** 보조·메타 젬·토템·트리거 전량 (사용자 요청 2026-08-11).

    `discover_mechanics`는 사전 매칭이라 **문구에 없는 것을 못 찾는다.** 그런데
    「주문 토템에 무엇을 넣을 수 있나」는 어느 레코드 문구에도 없고 PoB의
    `requireSkillTypes`/`excludeSkillTypes`에만 있다 — 그래서 구조적으로 안 나왔다.
    실측 2026-08-11: 구형 번개를 점화 소스로 채택하고도 **주문 토템이 후보에 오른
    적이 없었다**(사용자 지적: "주문 토템쪽 기재는 한 번도 추천받지 못했다").

    `include_blocked=True`면 막힌 것도 **사유와 함께** 낸다 — 「왜 안 되는가」가
    설계 정보다. 아이템 부여 스킬(`fromItem`)은 젬 소켓 자체가 안 되므로 경고가 붙는다.

    ⚠ **부착 여부를 PoB 델타로 시험하지 말 것** — 효과가 PoB 미모델링이면 붙어도
    수치가 안 변해 거부로 오독한다(원소 집정관·잔류물 귀속에서 두 번 겪었다).
    """
    from pok.engine.hosting import find_carriers as _carriers

    return _carriers(skill, include_blocked=include_blocked)


def scan_supply_edges(
    axis: str | None = None,
    kind: str | None = None,
    include_flow: bool = False,
    limit: int = 200,
) -> dict[str, Any]:
    """스택 축의 비례 엣지 전수 — 「이 스탯은 어디로 흘러가나」 (#91, #62 계열).

    유니크 explicits·트리 노드·속성 고유 보너스(전부 KB 정본)에서
    `per N X` / `for every N X` / `equal to N% of X` / `N% of X as Y` 문구를
    결정적으로 추출한다. supply(축→축 공급)와 payoff(축→피해·효과)를 가르고,
    배타 판단 재료(슬롯·전직 잠금·대가 줄)와 근거 문구를 함께 낸다.

    axis: 이 축이 source 또는 target인 엣지만 (예: "life", "strength").
          축 어휘는 반환 `axes` 요약에 전부 나온다.
    kind: "supply" | "payoff"만 거르기.
    include_flow: 이벤트 획득(처치·적중·소모 시)도 포함 — 스택 사슬이 아니라
          기본 제외. 제외분은 조용히 사라지지 않고 `axes`/skipped에 집계된다.

    ⚠ `scope="item_static"`은 장비에 박힌 수치의 정적 판독이다 — 전역 스탯과
    섞어 사슬을 그리면 가짜 순환이 생긴다(사슬은 trace_chains가 올바르게 잇는다).
    ⚠ 접사(Modifier) 레코드는 구변형을 구분 없이 담아 **일부러 안 본다** —
    신성모독·바알 변이 경로는 이 도구 밖이다(수동 확인 필요).
    """
    from pok.kb.graph.supply import scan_supply_edges as _scan_supply

    scan = _scan_supply(kb_store.load())
    edges = [
        e
        for e in scan.edges
        if (axis is None or axis in (e.source_axis, e.target_axis))
        and (kind is None or e.kind == kind)
        and (include_flow or e.scope != "flow")
    ]
    return {
        "edges": [dataclasses.asdict(e) for e in edges[:limit]],
        "axes": [dataclasses.asdict(a) for a in scan.axes],
        "skipped": [{"reason": r, "count": c} for r, c in scan.skipped],
        # 보상은 있는데 들어오는 비례 공급이 0인 축 — 플랫 성장(속성)이거나
        # 행동 획득(충전·저주)이거나 **다리 누락**이다. 다리 갭을 침묵시키지
        # 않는 가시성 장치이므로 그냥 지나치지 말 것.
        "unsourced_axes": list(scan.unsourced_axes),
        "truncated": len(edges) > limit,
        "total_matched": len(edges),
    }


def trace_chains(from_axis: str, depth: int = 3, max_chains: int = 40) -> dict[str, Any]:
    """from_axis에서 시작하는 다단 공급 사슬과 순환 후보 (#91).

    예: trace_chains("strength") → 힘→생명(고유 보너스)→ES(Beidat's Hand)…처럼
    「이 축을 밀면 무엇이 따라 자라는가」를 그래프 순회로 편다. 각 사슬에는
    공존 진단(전직 잠금·슬롯 충돌)이 붙고, 순환 후보는 잘라내지 않고 성립/불성립
    사유와 함께 낸다. scope="global" 엣지만 잇는다 — 장비 정적 판독(item_static)과
    이벤트 플로우는 전역 스탯을 되먹이지 못한다.

    점수·순위는 없다 — 어느 사슬이 유망한가는 호출자가 payoff 수와 근거로 판단
    한다. 공존 진단은 **발견된 충돌만** 말한다(충돌 없음 ≠ 성립 보장, 철칙 4).
    """
    from pok.kb.graph.supply import trace_chains as _trace

    trace = _trace(kb_store.load(), from_axis, depth=depth, max_chains=max_chains)
    return {
        "chains": [
            {
                "axes": list(c.axes),
                "conflicts": list(c.conflicts),
                "edges": [dataclasses.asdict(e) for e in c.edges],
            }
            for c in trace.chains
        ],
        "cycles": [dataclasses.asdict(c) for c in trace.cycles],
        "payoff_counts": [{"axis": a, "payoffs": n} for a, n in trace.payoff_counts],
        "truncated": trace.truncated,
    }


def find_payloads(carrier: str, limit: int = 200) -> dict[str, Any]:
    """이 담체(메타 젬·토템·보조)에 **넣을 수 있는** 활성 스킬 전량.

    `find_carriers`의 반대 방향이다. 컨셉을 정하기 전에 "이 담체로 무엇을 할 수
    있나"를 훑는 발산용 — 판정은 PoB 타입 시스템이라 전수이고 정확하다.
    아이템 부여 스킬은 담을 수 없으므로 제외된다.
    """
    from pok.engine.hosting import find_payloads as _payloads

    return _payloads(carrier, limit=limit)


def scan_scalers(
    axis: str | None = None,
    kind: str | None = None,
    attribution: str | None = None,
    limit: int = 120,
) -> dict[str, Any]:
    """「X당 Y」 스케일러를 **크기 판정 가능한 형태로 분해**한다 (#102).

    `scan_supply_edges`가 「어디로 흘러가나」(연결)를 본다면, 이쪽은 **「얼마나 큰가」**를
    본다. 문구를 그냥 나열하면 담체 개수를 배율 크기로 착각하게 된다 — 실제로 그 오독이
    2026-08-22에 **세 번 연속** 났다(per Power 17종 · 위세 담체 93종 · 워크라이 카운트).

    각 스케일러를 네 축으로 가른다:

    - `payoff_kind` — `more`(곱연산·희석 없음) / `increased`(가산·**희석**) /
      `added` / `counter`(횟수) / `resource`(게이지) / `sustain` /
      `reach`(**반경은 페이오프가 아니다**) / `other`
    - `cap` — 상한. 있으면 그 위 투자는 **0**이다(워크라이 50 · 산의 가르침 30).
    - `attribution` — `player`(「네가 명중/처치」)면 **프록시에서 발동하지 않는다**
      (공허의 형상 분신·토템·소환수). 인게임 실측 2026-08-22 확인.
    - `obtainable` — id에 `unused`거나 `carrier_unknown`이면 **아예 제외**하고
      사유별로 세어 `excluded`에 보고한다(조용한 절단 금지).

    axis: 세는 대상만 거르기 (예: "Power", "Rage", "Combo"). 대소문자 무시.
    kind / attribution: 위 값으로 거르기.

    ⚠ `counter`·`resource`는 **딜이 아니다** — 그 게이지가 무엇에 쓰이는지
    한 단계 더 봐야 한다. 반환값의 `warnings`가 그때그때 알려 준다.
    """
    from pok.kb.graph.scalers import scan_scalers as _scan

    scan = _scan(kb_store.load(), input_axis=axis)
    rows = [
        s
        for s in scan.scalers
        if (kind is None or s.payoff_kind == kind)
        and (attribution is None or s.attribution == attribution)
    ]
    # 곱연산이 먼저 보이도록 — 크기 순서가 곧 판정 순서다.
    order = {
        k: i
        for i, k in enumerate(
            ["more", "added", "sustain", "increased", "counter", "resource", "reach", "other"]
        )
    }
    rows.sort(key=lambda s: (order.get(s.payoff_kind, 99), s.carrier_name))
    return {
        "total_matched": len(rows),
        "by_kind": [{"kind": k, "count": n} for k, n in scan.by_kind],
        "excluded": [{"reason": r, "count": n} for r, n in scan.excluded],
        "scalers": [dataclasses.asdict(s) for s in rows[:limit]],
        "truncated": len(rows) > limit,
    }
