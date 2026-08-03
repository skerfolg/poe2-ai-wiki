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
