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
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pok.common.paths import artifacts_dir, knowledge_dir
from pok.kb.graph.predicates import SUPPLIABLE_SUBJECTS
from pok.kb.graph.synergy import scan_synergies
from pok.kb.store import Record, Store
from pok.learning.curation import Claim, propose
from pok.learning.feedback import record_feedback

# 이름이 문장형이면(모드 텍스트가 그대로 이름인 레코드가 있다) 코퍼스 대조가
# 무의미하다 — 탐사 여부를 판정하지 않고 미판정으로 둔다.
_NAME_MAX = 30

# 공급자 한 명이 큐를 독점하지 못하게 하는 상한. 첫 큐가 12칸을 전부 같은
# 공급자(아즈메리 늑대)로 채웠다 — 5,000쌍에서 12개를 뽑는데 다양성이 없으면
# 탐사가 아니다(2026-08-04).
_MAX_PER_SUPPLIER = 2

# 축 다양성도 같은 이유로 필요하다 — 첫 큐는 12건이 전부 출혈 축이었다.
# 스캔은 축별로 뭉쳐 나오므로 상한이 없으면 앞 축이 큐를 다 먹는다.
_MAX_PER_SUBJECT = 2

# 게임에서 쓰지 않는 데이터가 정본에 남아 있다(poe2db 덤프의 잔재). 후보로 내밀면
# 게이트가 실체 없는 항목을 판정하게 된다.
_NOISE = re.compile(r"\bDNT[-_]|\bUNUSED\b|\bDoNotTranslate\b", re.I)

# 가설 큐 본문의 첫 줄 — 코퍼스에서 자기 자신을 알아보는 표지.
_QUEUE_MARKER = "# 능동 탐사 가설 큐"


def _acquisition_note(record: Record) -> str:
    """획득 경로 미수록이면 그 사실을 후보에 덧붙인다 (배제하지 않는다).

    한때 `acquisition_unknown`인 레코드를 후보에서 빼려 했으나 **잘못이었다**:
    이 플래그는 *poe2db에 획득 경로가 안 실렸다*는 수집 한계일 뿐, 게임에 없다는
    뜻이 아니다. 실제로 원통한 망자 같은 룬 수호(Ward) 코스트 스킬들은 0.5.0
    시즌 컨텐츠에서 얻을 수 있다(사용자 판정 2026-08-04).

    수집 한계를 성립 판정으로 바꿔 읽으면 멀쩡한 설계 공간이 통째로 사라진다.
    그래서 사실만 전하고 판단은 게이트에 맡긴다(AD-3).
    """
    if (record.raw.get("data") or {}).get("acquisition_unknown", False):
        name = record.name_ko or record.name_en
        return f"\n※ {name}: 획득 경로 미수록 (수집 갭 — 게임 부재 아님)"
    return ""


def _demand_shape(text: str) -> str:
    """요구 문구에서 수치를 지운 뼈대 — 티어 변종을 하나로 묶는 키.

    "30% increased Attack Damage against Bleeding Enemies"와 "40% …"는 같은 요구다.
    첫 큐는 이 다섯 변종을 서로 다른 후보로 세어 자리를 낭비했다(2026-08-04).
    """
    return re.sub(r"[\d.]+|\(\s*-\s*\)", "", text).strip().lower()


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
            text = path.read_text(encoding="utf-8", errors="ignore")
            # 능동 탐사 큐 자신은 탐사 흔적이 아니다. 이걸 포함하면 지난번에 낸
            # 후보가 "이미 다룬 것"이 되어 매 실행마다 후보가 뒤바뀐다(2026-08-04).
            if text.lstrip().startswith(_QUEUE_MARKER):
                continue
            parts.append(text)
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

    pairs_out = 0
    seen: set[tuple[str, str]] = set()
    shapes: set[tuple[str, str]] = set()  # (공급자, 요구 뼈대) — 티어 변종 접기
    per_supplier: Counter[str] = Counter()
    per_subject: Counter[str] = Counter()
    for pair in scan.pairs:
        if pairs_out >= max_pairs:
            break
        if _NOISE.search(pair.demander_name) or _NOISE.search(pair.supplier_name):
            continue  # 게임에 없는 데이터는 판정 대상이 아니다
        acq_notes = "".join(
            _acquisition_note(store.records[rid])
            for rid in (pair.supplier_id, pair.demander_id)
            if rid in store.records
        )
        if per_supplier[pair.supplier_id] >= _MAX_PER_SUPPLIER:
            continue  # 한 공급자가 큐를 독점하지 못하게
        if per_subject[pair.subject_key] >= _MAX_PER_SUBJECT:
            continue  # 한 축이 큐를 독점하지 못하게
        sup_seen = _mentioned(pair.supplier_name, corpus)
        dem_seen = _mentioned(pair.demander_name, corpus)
        if sup_seen is not False and dem_seen is not False:
            continue  # 이미 다뤘거나 판정 불가 — 미탐사라 부를 근거가 없다
        key = (pair.supplier_id, pair.demander_id)
        shape = (pair.supplier_id, _demand_shape(pair.demander_evidence))
        if key in seen or shape in shapes:
            continue
        seen.add(key)
        shapes.add(shape)
        per_supplier[pair.supplier_id] += 1
        per_subject[pair.subject_key] += 1
        pairs_out += 1
        out.append(
            Hypothesis(
                kind="pair",
                subject_key=pair.subject_key,
                text=(
                    f"「{pair.supplier_name}」가 공급하는 {pair.subject_key}를 "
                    f"「{pair.demander_name}」가 요구한다 — 산출물에 함께 등장한 적 없는 조합."
                ),
                evidence=(
                    f"공급: {pair.supplier_evidence}\n요구: {pair.demander_evidence}{acq_notes}"
                ),
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
