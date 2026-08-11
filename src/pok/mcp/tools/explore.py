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


def find_payloads(carrier: str, limit: int = 200) -> dict[str, Any]:
    """이 담체(메타 젬·토템·보조)에 **넣을 수 있는** 활성 스킬 전량.

    `find_carriers`의 반대 방향이다. 컨셉을 정하기 전에 "이 담체로 무엇을 할 수
    있나"를 훑는 발산용 — 판정은 PoB 타입 시스템이라 전수이고 정확하다.
    아이템 부여 스킬은 담을 수 없으므로 제외된다.
    """
    from pok.engine.hosting import find_payloads as _payloads

    return _payloads(carrier, limit=limit)
