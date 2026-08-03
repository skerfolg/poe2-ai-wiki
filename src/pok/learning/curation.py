"""큐레이션 게이트 — 피드백 원문에서 **주장 단위 후보**를 뽑아 사람 승인을 받는다.

P5의 핵심 안전장치: 관찰 원문을 그대로 KB에 넣지 않는다. 원문을 검증 가능한
주장(claim)으로 쪼개고, 각각에 검증 라벨 후보와 근거를 붙여 **사람이 항목별로
승인/기각**하게 한다 — 통째 승인은 오류를 함께 들여온다(실증 2026-08-02).

주장을 쪼개는 일(무엇이 하나의 주장인가)은 에이전트·사람의 판단이다. 이 모듈은
그 결과를 담아 승인 상태를 관리하는 그릇만 제공한다(AD-3).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir

_LABELS = frozenset(
    {"CONFIRMED_OFFICIAL", "GAME_DATA", "POB_CODE", "IN_GAME", "SUPPORTED_INFERENCE", "UNVERIFIED"}
)
_DECISIONS = frozenset({"pending", "approved", "rejected"})


@dataclass
class Claim:
    """피드백에서 뽑은 검증 가능한 주장 하나."""

    text: str  # 주장 본문 (한 문장으로 판정 가능해야 한다)
    label: str  # 제안 검증 라벨 (승인 시 확정)
    evidence: str  # 근거 — 어디서 왔는가(원문 위치·인게임 확인·소스 링크)
    target_id: str | None = None  # 연결할 KB 레코드 id (없으면 신규 인사이트)
    decision: str = "pending"
    note: str = ""  # 판정 사유 (기각 시 필수 — 같은 주장이 다시 오면 근거가 된다)

    def __post_init__(self) -> None:
        if self.label not in _LABELS:
            raise ValueError(f"라벨 어휘 밖: {self.label!r} (허용: {sorted(_LABELS)})")
        if self.decision not in _DECISIONS:
            raise ValueError(f"판정값 밖: {self.decision!r}")


@dataclass
class CandidateSet:
    feedback_id: str
    claims: list[Claim] = field(default_factory=list)

    @property
    def approved(self) -> list[Claim]:
        return [c for c in self.claims if c.decision == "approved"]

    @property
    def pending(self) -> list[Claim]:
        return [c for c in self.claims if c.decision == "pending"]


def _candidates_path(feedback_id: str, root: Path | None) -> Path:
    return artifacts_dir(root) / "feedback" / "candidates" / f"{feedback_id}.json"


def _save(feedback_id: str, claims: list[Claim], root: Path | None) -> Path:
    """주어진 상태 그대로 저장 (병합 없음) — 판정 반영 경로."""
    path = _candidates_path(feedback_id, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"feedback_id": feedback_id, "claims": [asdict(c) for c in claims]},
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def propose(feedback_id: str, claims: list[Claim], *, root: Path | None = None) -> Path:
    """주장 후보를 `artifacts/feedback/candidates/<feedback_id>.json`에 기록.

    전부 `pending`으로 시작한다 — 사람이 판정하기 전에는 어떤 것도 승격 대상이
    아니다. 재호출 시 **기존 판정을 보존**하고 신규 주장만 추가한다(멱등) —
    제안을 다시 돌려도 사람의 승인·기각이 지워지지 않는다.
    """
    existing: dict[str, Claim] = {}
    if _candidates_path(feedback_id, root).exists():
        existing = {c.text: c for c in load_candidates(feedback_id, root=root).claims}
    merged: list[Claim] = []
    for c in claims:
        old = existing.pop(c.text, None)
        merged.append(old if old is not None else c)
    merged.extend(existing.values())  # 이번 제안에 없는 기존 주장도 보존
    return _save(feedback_id, merged, root)


def load_candidates(feedback_id: str, *, root: Path | None = None) -> CandidateSet:
    path = artifacts_dir(root) / "feedback" / "candidates" / f"{feedback_id}.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return CandidateSet(
        feedback_id=str(data["feedback_id"]),
        claims=[Claim(**c) for c in data.get("claims", [])],
    )


def decide(
    feedback_id: str,
    decisions: dict[str, tuple[str, str]],
    *,
    root: Path | None = None,
) -> CandidateSet:
    """사람 판정 반영 — decisions = {주장 텍스트: (판정, 사유)}.

    기각은 사유 필수: 같은 주장이 다음 피드백에서 다시 올라올 때 판단 근거가 된다.
    """
    cand = load_candidates(feedback_id, root=root)
    by_text = {c.text: c for c in cand.claims}
    for text, (decision, note) in decisions.items():
        claim = by_text.get(text)
        if claim is None:
            raise KeyError(f"후보에 없는 주장: {text!r}")
        if decision not in _DECISIONS:
            raise ValueError(f"판정값 밖: {decision!r}")
        if decision == "rejected" and not note.strip():
            raise ValueError(f"기각에는 사유가 필요하다: {text!r}")
        claim.decision, claim.note = decision, note
    _save(feedback_id, cand.claims, root)  # 판정은 병합 없이 그대로 반영
    return cand
