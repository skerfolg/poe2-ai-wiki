"""능동 탐사 — 스캔이 만든 후보를 **가설 큐**로 바꿔 기존 게이트에 넣는다.

P5의 학습은 사용자가 겪은 것에서만 들어왔다. 그러면 KB가 사용자의 사고 범위를
넘지 못한다(문제 제기 2026-07-31). 능동 탐사는 그 반대 방향이다 — 정본 전수를
훑어 **아무도 시도한 적 없는 조합·마른 공급 경로**를 스스로 꺼낸다.

핵심은 새 게이트를 만들지 않는 것이다. 능동 탐사는 **피드백의 새로운 출처**일
뿐이고, 그 뒤는 P5에서 이미 실증된 경로를 그대로 탄다:

    스캔(기계) → 가설 큐 → `curation.decide`(사람 판정) → `promote_insight`(정본)

기계가 만든 가설은 전부 UNVERIFIED다. 스캔은 문구 패턴에서 유도한 것이라 원리상
불완전하고, 무엇보다 **"조합이 성립하는가"는 게임 지식 판정**이라 사람 몫이다
(AD-3). 그래서 큐는 후보를 내밀 뿐 정본을 건드리지 않는다.

두 종류를 낸다:

  · **gap** — 요구는 많은데 공급 경로가 마른 축. 실측(2026-08-04)에서 `self.life.low`가
    요구 67 대 공급 4로 나왔다. "로우라이프를 원하는 효과는 67개인데 로우라이프를
    만드는 법은 4개만 안다"는 뜻이고, 이건 KB 갭이거나 미탐사 설계 공간이다.
  · **pair** — 공급자 x 요구자 조합 중 **어떤 산출물에도 함께 등장한 적 없는** 쌍.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pok.common.paths import artifacts_dir, knowledge_dir
from pok.kb.graph.predicates import SUPPLIABLE_SUBJECTS
from pok.kb.graph.synergy import scan_synergies
from pok.kb.store import Store
from pok.learning.curation import Claim, propose
from pok.learning.feedback import record_feedback

# 이름이 문장형이면(모드 텍스트가 그대로 이름인 레코드가 있다) 코퍼스 대조가
# 무의미하다 — 탐사 여부를 판정하지 않고 미판정으로 둔다.
_NAME_MAX = 30


@dataclass(frozen=True)
class Hypothesis:
    """게이트에 낼 가설 하나. text는 한 문장으로 판정 가능해야 한다."""

    kind: str  # "gap" | "pair"
    subject_key: str
    text: str
    evidence: str


def exploration_corpus(root: Path | None = None) -> str:
    """지금까지 탐사한 흔적을 한 덩이 텍스트로 모은다.

    설계 문서·인사이트·피드백 원문이 곧 "우리가 생각해 본 것"의 기록이다.
    여기 없는 조합이 곧 미탐사다 — 완벽한 정의는 아니지만(문서에 안 적고 지나친
    것도 있다) 결정적이고, 과다 검출 쪽으로 틀리므로 게이트가 걸러낼 수 있다.
    """
    parts: list[str] = []
    arts = artifacts_dir(root)
    for pattern in ("builds/*/design.md", "feedback/raw/*/content.md", "sessions/*.md"):
        for path in sorted(arts.glob(pattern)):
            parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    for path in sorted((knowledge_dir(root) / "insights").glob("*.md")):
        parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(parts)


def _mentioned(name: str, corpus: str) -> bool | None:
    """이름이 탐사 흔적에 등장하는가. 판정 불가면 None."""
    clean = name.strip()
    if not clean or len(clean) > _NAME_MAX or re.search(r"\d", clean):
        return None
    return clean in corpus


def find_hypotheses(
    store: Store,
    *,
    demand_supply_ratio: float = 3.0,
    max_pairs: int = 12,
    root: Path | None = None,
) -> tuple[Hypothesis, ...]:
    """정본을 훑어 가설 후보를 만든다 (결정적 — 임계는 파라미터, 판단 아님).

    demand_supply_ratio: 요구/공급 비가 이 값 이상이면 gap 가설을 낸다.
    max_pairs: pair 가설 상한 — 5,000쌍을 다 내밀면 게이트가 마비된다.
    """
    scan = scan_synergies(store, limit=100_000)
    corpus = exploration_corpus(root)
    out: list[Hypothesis] = []

    for summary in scan.summary:
        if summary.demanders == 0:
            continue
        # 공급 개념이 성립하는 축에서만 갭을 주장한다 — 그 밖에서 "공급 0"은
        # 스캐너의 사정거리 밖이라는 뜻이지 KB의 갭이 아니다.
        if summary.subject_key.split("=")[0] not in SUPPLIABLE_SUBJECTS:
            continue
        if summary.suppliers == 0:
            out.append(
                Hypothesis(
                    kind="gap",
                    subject_key=summary.subject_key,
                    text=(
                        f"「{summary.subject_key}」를 요구하는 효과가 {summary.demanders}건 있는데 "
                        f"공급 경로가 정본에 없다 — 수집 갭인지 게임에 없는지 판정 필요."
                    ),
                    evidence=f"스캔 집계: 공급 0 · 요구 {summary.demanders}",
                )
            )
        elif summary.demanders / summary.suppliers >= demand_supply_ratio:
            out.append(
                Hypothesis(
                    kind="gap",
                    subject_key=summary.subject_key,
                    text=(
                        f"「{summary.subject_key}」는 요구 {summary.demanders}건 대 공급 "
                        f"{summary.suppliers}건으로 공급이 마르다 — 알려진 공급 경로가 정말 "
                        f"이게 전부인지, 아니면 수집·탐사 갭인지 판정 필요."
                    ),
                    evidence=f"스캔 집계: 공급 {summary.suppliers} · 요구 {summary.demanders}",
                )
            )

    seen: set[tuple[str, str]] = set()
    for pair in scan.pairs:
        if len(out) >= max_pairs + sum(1 for h in out if h.kind == "gap"):
            break
        sup_seen = _mentioned(pair.supplier_name, corpus)
        dem_seen = _mentioned(pair.demander_name, corpus)
        if sup_seen is not False and dem_seen is not False:
            continue  # 이미 다뤘거나 판정 불가 — 미탐사라 부를 근거가 없다
        key = (pair.supplier_id, pair.demander_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            Hypothesis(
                kind="pair",
                subject_key=pair.subject_key,
                text=(
                    f"「{pair.supplier_name}」가 공급하는 {pair.subject_key}를 "
                    f"「{pair.demander_name}」가 요구한다 — 산출물에 함께 등장한 적 없는 조합."
                ),
                evidence=(f"공급: {pair.supplier_evidence}\n요구: {pair.demander_evidence}"),
            )
        )
    return tuple(out)


def queue_hypotheses(
    store: Store,
    *,
    demand_supply_ratio: float = 3.0,
    max_pairs: int = 12,
    root: Path | None = None,
) -> tuple[str, int]:
    """가설을 피드백으로 기록하고 큐레이션 후보까지 만든다 → (feedback_id, 건수).

    사람 피드백과 **같은 파이프라인**에 올린다. 출처(source.kind)만 기계로 남겨
    나중에 "이 인사이트가 능동 탐사에서 왔는지"를 계보로 추적할 수 있게 한다.
    """
    hypotheses = find_hypotheses(
        store, demand_supply_ratio=demand_supply_ratio, max_pairs=max_pairs, root=root
    )
    if not hypotheses:
        return ("", 0)

    body = [
        "# 능동 탐사 가설 큐",
        "",
        "기계 생성 — 전부 미검증. 사람 판정 전에는 정본에 들어가지 않는다.",
        "",
    ]
    for i, h in enumerate(hypotheses, 1):
        body += [
            f"## {i}. [{h.kind}] {h.subject_key}",
            "",
            h.text,
            "",
            "```",
            h.evidence,
            "```",
            "",
        ]

    path = record_feedback(
        "능동 탐사 가설 큐",
        "\n".join(body),
        kind="active-exploration",
        source={
            "provider": "scan",
            "method": "kb.graph.synergy 요구-공급 맞물림",
            "note": "기계 생성 가설 — 게임 지식 판정은 사람 게이트에서",
        },
        root=root,
    )
    feedback_id = path.name
    propose(
        feedback_id,
        [
            Claim(
                text=h.text,
                label="UNVERIFIED",
                evidence=h.evidence,
                note=f"능동 탐사 {h.kind} · {h.subject_key}",
            )
            for h in hypotheses
        ],
        root=root,
    )
    return (feedback_id, len(hypotheses))
