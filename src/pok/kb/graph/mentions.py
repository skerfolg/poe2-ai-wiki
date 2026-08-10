"""메커니즘 언급 스캐너 — 의심 엣지의 **발견**을 기계로 (사용자 지시 2026-08-06).

관계 그래프(RC2)가 자라려면 typed edge가 쌓여야 하는데, 사용자가 엣지를 하나하나
가르치는 구조는 지속 불가다. 분업을 이렇게 나눈다:

    발견(여기, 기계): 메커니즘 사전(GAME_DATA 정의문 246+개) x 효과 문구를 결정적
        대조 → 의심 엣지 + **출처 문장 인용**. 게임 지식 불요.
    판정(사용자): 승인 → typed edge 수록(store API) / 기각 → 기록(재보고 방지).
        판정 전 후보 전량 나열 원칙 그대로다.

실측 2026-08-06: 엔티티→메커니즘 언급 8,235건 · 메커니즘→메커니즘 상호 언급
(상태 전이 후보) 363건 — 사용자 예시 연쇄(동결→산산조각→얼음의 전령)의 고리가
전부 이 스캔에 잡혔다. 소비처는 둘이다: ① 빌드 발산 단계("출혈 빌드"라는 컨셉만
받아도 "이런 것도 가능해 보인다"를 근거와 함께) ② 아이템 선정의 연쇄 축 확장.

한계(정직): ① 사전 매칭이라 문구에 키워드가 없는 암묵 상호작용(PoB 내부 구현만
존재)은 못 찾는다 — 그건 측정 이상치 신호의 몫. ② 언급≠인과 — "면역" 같은 부정
문맥도 잡히므로 negated 플래그를 달고, 최종 판정은 사용자가 한다.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 부정 문맥 표식 — 언급이 "연계"가 아니라 "차단/면역"일 가능성. 걸러내지 않고
# **표시만** 한다(AD-3) — "출혈 면역" 자체가 설계 재료일 수도 있다.
_NEGATION = re.compile(r"\b(immun\w*|cannot|can't|never|no longer|unaffected|prevent\w*)\b", re.I)
# 조건 문맥 표식 — 전이/발동 관계일 가능성이 높은 문장
_CONDITION = re.compile(r"\b(while|when(?:ever)?|if|on (?:hit|kill|death)|against|causes?)\b", re.I)
_TEXT_KEYS = ("description", "stats", "explicits", "implicits", "stats_en", "keyword_stats")
_MIN_NAME = 4  # 3자 이하 이름(Web 등)은 오탐이 압도한다


@dataclass(frozen=True)
class SuspectedEdge:
    """의심 엣지 — 수록 후보이지 사실이 아니다. 판정은 사용자."""

    source_id: str
    source_type: str
    mechanic_id: str
    quote: str  # 출처 문장 — 판정은 항상 인용문을 보고 한다
    conditional: bool  # 조건 문맥(while/when/…) — 전이·발동일 가능성
    negated: bool  # 부정 문맥(immune/never/…) — 연계가 아니라 차단일 가능성


@dataclass(frozen=True)
class MentionScan:
    edges: tuple[SuspectedEdge, ...]
    total_found: int  # 필터 전 전체 — 잘렸으면 얼마나 잘렸는지 보인다
    lexicon_size: int
    notes: tuple[str, ...]


@functools.lru_cache(maxsize=4)
def _records(root: Path | None) -> dict[str, Any]:
    """읽기 전용 캐시 — engine의 `_kb_records`와 같은 이유(로드가 측정보다 비쌈)지만
    kb→engine 역방향 import를 만들 수 없어(의존 방향 §4) 여기 따로 둔다."""
    from pok.kb.store import load as store_load

    return dict(store_load(root).records)


def _mechanic_lexicon(records: Mapping[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for record_id, record in records.items():
        if record.type != "Mechanic":
            continue
        name = str((record.raw.get("name") or {}).get("en") or "")
        if len(name) >= _MIN_NAME:
            out[name.lower()] = record_id
    return out


def _texts_of(data: Mapping[str, Any]) -> list[str]:
    texts: list[str] = []
    for key in _TEXT_KEYS:
        value = data.get(key)
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            texts.extend(str(v) for v in value)
    return texts


def scan_mechanic_mentions(
    root: Path | None = None,
    *,
    concepts: Sequence[str] = (),
    types: tuple[str, ...] = ("Skill", "Support", "Item", "Passive", "Mechanic"),
    limit: int = 60,
) -> MentionScan:
    """효과 문구에서 메커니즘 언급을 결정적으로 발견한다.

    `concepts`(예: ["bleed", "cold"])를 주면 **그 축에 닿는 후보만** 낸다 — 전량
    (8,235건)을 내밀면 판정 게이트가 마비된다(가설 도구의 max_pairs 교훈).
    컨셉 매칭은 ① 메커니즘 이름 ② 인용문 본문 양쪽이다. Mechanic 타입을 포함하면
    메커니즘 정의문끼리의 상호 언급(상태 전이 후보 — "동결된 적은 처치 시
    산산조각")도 나온다.
    """
    records = _records(root)
    lexicon = _mechanic_lexicon(records)
    # ⚡ 패턴을 **한 번만** 컴파일한다. 전에는 (레코드 x 어휘)마다 `re.search`에 f-string을
    # 넘겨 매번 컴파일했는데, 어휘가 `re` 내부 캐시(512개)보다 많으면 캐시가 계속 밀려
    # 사실상 전량 재컴파일이 된다 — 실측 2026-08-09: 이 스캔 3회가 46초였다.
    patterns = {name: re.compile(rf"\b{re.escape(name)}", re.I) for name in lexicon}
    concept_terms = [c.strip().lower() for c in concepts if c.strip()]
    edges: list[SuspectedEdge] = []
    total = 0
    for record_id, record in records.items():
        if record.type not in types:
            continue
        data = record.raw.get("data") or {}
        texts = _texts_of(data)
        if not texts:
            continue
        self_name = str((record.raw.get("name") or {}).get("en") or "").lower()
        for name, mechanic_id in lexicon.items():
            if mechanic_id == record_id or name == self_name:
                continue
            pattern = patterns[name]
            quote = next((t for t in texts if pattern.search(t)), None)
            if quote is None:
                continue
            total += 1
            if concept_terms:
                hay = f"{name} {self_name} {quote}".lower()
                if not any(term in hay for term in concept_terms):
                    continue
            edges.append(
                SuspectedEdge(
                    source_id=record_id,
                    source_type=record.type,
                    mechanic_id=mechanic_id,
                    quote=quote.strip()[:200],
                    conditional=bool(_CONDITION.search(quote)),
                    negated=bool(_NEGATION.search(quote)),
                )
            )
    # 전이 후보(조건 문맥·Mechanic 출처)를 앞으로 — 연쇄의 뼈대가 되는 것부터 판정받는다
    edges.sort(
        key=lambda e: (e.source_type != "Mechanic", not e.conditional, e.source_id, e.mechanic_id)
    )
    notes = [
        f"의심 엣지 {len(edges)}건 (필터 전 전체 {total}건, 사전 {len(lexicon)}개) — "
        f"**사실이 아니라 수록 후보**다. 인용문을 보고 판정할 것: 승인 → typed edge "
        f"수록(store API), 기각 → design.md에 기록해 재보고를 막는다",
        "negated=true는 연계가 아니라 차단(면역 등)일 가능성 — 걸러내지 않고 표시만 했다",
    ]
    if len(edges) > limit:
        notes.append(f"⚠ {len(edges)}건 중 {limit}건만 반환 — concepts를 좁혀 다시 볼 것")
        edges = edges[:limit]
    return MentionScan(
        edges=tuple(edges),
        total_found=total,
        lexicon_size=len(lexicon),
        notes=tuple(notes),
    )
