"""요구-공급 맞물림 스캔 — 능동 탐사의 후보 생성기 (판단 없음, AD-3).

`predicates`가 뽑은 술어를 조건 subject로 맞물린다:

    A가 공급하는 subject를 B가 요구한다  ⇒  AxB는 후보다

이게 시너지의 **결정적** 정의다. "좋은 조합인가"는 여기서 답하지 않는다 — 점수도
순위도 매기지 않고, 세는 것(공급원 수·요구처 수)과 근거 문구만 낸다. 선별은
게이트(learning/hypothesis)의 몫이다.

**왜 능동 탐사인가**: 사용자가 겪은 것만 기록하면 학습이 사용자의 사고 범위에
갇힌다(문제 제기 2026-07-31). 이 스캔은 정본 16,600건 전수를 대상으로 삼으므로
아무도 떠올린 적 없는 쌍도 후보로 올라온다.

계층 계약상 여기서는 **정본만** 본다 — 어떤 쌍이 이미 탐사됐는지는 산출물을 읽어야
알 수 있고, 그 판정은 상위 계층(learning)이 한다.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from pok.kb.graph.predicates import Predicate, extract_predicates, record_texts
from pok.kb.store import Store


@dataclass(frozen=True)
class SynergyPair:
    """공급자 x 요구자 후보 1쌍. 두 근거 문구가 판정의 전부다(AD-8)."""

    subject_key: str  # "enemy.status=chilled" 등 — 맞물림의 축
    supplier_id: str
    supplier_name: str
    supplier_evidence: str
    demander_id: str
    demander_name: str
    demander_evidence: str


@dataclass(frozen=True)
class SubjectSummary:
    """subject 하나의 수급 현황 — 어디가 넓고 어디가 마른지 보여주는 지도."""

    subject_key: str
    suppliers: int
    demanders: int
    pairs: int


@dataclass(frozen=True)
class SynergyScan:
    summary: tuple[SubjectSummary, ...]
    pairs: tuple[SynergyPair, ...]
    truncated: bool = False  # 상한에 걸려 잘렸는가 (조용한 절단 금지)


def _index(store: Store) -> dict[str, dict[str, list[tuple[str, str, Predicate]]]]:
    """정본 전수를 훑어 subject_key → 방향 → [(id, 이름, 술어)] 색인을 만든다."""
    index: dict[str, dict[str, list[tuple[str, str, Predicate]]]] = defaultdict(
        lambda: {"supply": [], "demand": []}
    )
    for record in store.records.values():
        for predicate in extract_predicates(record_texts(record.raw), store.subjects):
            index[predicate.key][predicate.direction].append(
                (record.id, record.name_ko or record.name_en, predicate)
            )
    return index


def scan_synergies(
    store: Store,
    *,
    subject_key: str | None = None,
    limit: int = 200,
) -> SynergyScan:
    """요구-공급 맞물림 후보를 전수 생성한다.

    subject_key 를 주면 그 축만(예: "enemy.status=chilled"). limit 은 쌍 상한 —
    상한에 걸리면 `truncated=True`로 알린다. 요약(summary)은 잘리지 않으므로
    전체 규모는 언제나 그대로 보인다.
    """
    index = _index(store)
    summary: list[SubjectSummary] = []
    pairs: list[SynergyPair] = []
    truncated = False

    for key in sorted(index):
        if subject_key and key != subject_key:
            continue
        suppliers = index[key]["supply"]
        demanders = index[key]["demand"]
        summary.append(
            SubjectSummary(key, len(suppliers), len(demanders), len(suppliers) * len(demanders))
        )
        for sid, sname, sp in suppliers:
            for did, dname, dp in demanders:
                if sid == did:
                    continue  # 자기 자신은 시너지가 아니다
                if len(pairs) >= limit:
                    truncated = True
                    break
                pairs.append(
                    SynergyPair(
                        subject_key=key,
                        supplier_id=sid,
                        supplier_name=sname,
                        supplier_evidence=sp.evidence,
                        demander_id=did,
                        demander_name=dname,
                        demander_evidence=dp.evidence,
                    )
                )
            if truncated:
                break

    summary.sort(key=lambda s: (-s.pairs, s.subject_key))
    return SynergyScan(tuple(summary), tuple(pairs), truncated)
