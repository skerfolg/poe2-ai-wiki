"""보존 정책 — 무엇을 지워도 되는지가 아니라 **무엇을 지우면 안 되는지** (§9-3).

산출물은 재생성이 불가능하다. 그래서 이 모듈의 기본 태도는 삭제가 아니라 **보호**다.
용량은 문제가 아니다(실측 2026-08-04: artifacts 전체 190KB) — 진짜 위험은 둘이다:

1. **계보 절단** — 승격된 인사이트는 `feedback_id`로 원문을 가리킨다. 그 원문을
   지우면 "이 판단이 어디서 왔나"에 답할 수 없고, `promote_insight`가 계보 없는
   승격을 막아 둔 의미도 사라진다.
2. **폐기 설계의 재도출** — 왜 버렸는지가 사라지면 같은 설계를 다시 만든다.
   실제로 겪었다(P5 실증: 폐기 노트 계보를 역추적해서야 재도출임을 알아냈다).

그래서 **자동 삭제는 없다**. 이 모듈은 후보를 나열하고 보호 사유를 붙일 뿐이고,
지울지는 사람이 정한다 — "지우기 전에 후보를 전량 나열해 사람이 판단한다"(사용자
확립 원칙). 삭제 함수도 참조된 항목은 거부한다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pok.common.paths import artifacts_dir
from pok.kb.insights import load_insights


@dataclass(frozen=True)
class Item:
    """보관물 1건과 그 보호 상태."""

    kind: str  # "build" | "feedback" | "session" | "anchor"
    name: str
    path: Path
    bytes: int
    age_days: int
    referenced_by: tuple[str, ...] = ()

    @property
    def protected(self) -> bool:
        return bool(self.referenced_by)


@dataclass
class RetentionReport:
    items: list[Item] = field(default_factory=list)

    @property
    def protected(self) -> list[Item]:
        return [i for i in self.items if i.protected]

    @property
    def candidates(self) -> list[Item]:
        """참조가 없는 것들 — **삭제 대상이 아니라 판단 대상**이다."""
        return [i for i in self.items if not i.protected]

    @property
    def total_bytes(self) -> int:
        return sum(i.bytes for i in self.items)


def _dir_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _age_days(path: Path, now: datetime | None) -> int:
    stamp = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return max(0, ((now or datetime.now(UTC)) - stamp).days)


def _insight_references(root: Path | None) -> dict[str, list[str]]:
    """정본 인사이트가 가리키는 feedback_id → [인사이트 slug].

    이 참조가 계보의 뼈대다. 여기 걸린 피드백 원문은 지울 수 없다.
    """
    refs: dict[str, list[str]] = {}
    for insight in load_insights(root):
        feedback_id = insight.feedback_id
        if feedback_id:
            refs.setdefault(feedback_id, []).append(insight.slug)
    return refs


def scan(root: Path | None = None, now: datetime | None = None) -> RetentionReport:
    """보관물을 훑어 보호 상태와 함께 나열한다 (삭제하지 않는다)."""
    arts = artifacts_dir(root)
    refs = _insight_references(root)
    report = RetentionReport()

    for kind, pattern in (
        ("build", "builds/*"),
        ("anchor", "anchors/*"),
        ("feedback", "feedback/raw/*"),
        ("session", "sessions/*.md"),
    ):
        for path in sorted(arts.glob(pattern)):
            if path.name.startswith("."):
                continue
            referenced: list[str] = []
            if kind == "feedback":
                referenced += [f"insight:{s}" for s in refs.get(path.name, [])]
                manifest = path / "manifest.json"
                if manifest.exists():
                    meta = json.loads(manifest.read_text(encoding="utf-8"))
                    if meta.get("state") == "promoted":
                        referenced.append("state:promoted")
            report.items.append(
                Item(
                    kind=kind,
                    name=path.name,
                    path=path,
                    bytes=_dir_bytes(path),
                    age_days=_age_days(path, now),
                    referenced_by=tuple(referenced),
                )
            )
    return report


def delete(
    names: list[str],
    *,
    reason: str,
    root: Path | None = None,
    now: datetime | None = None,
) -> list[str]:
    """사람이 지목한 보관물만 지운다 — 참조된 것은 거부한다.

    `reason`은 필수다. 근거 없이 사라진 산출물은 나중에 "왜 없지?"에 답할 수 없다.
    """
    if not reason.strip():
        raise ValueError("삭제 사유 없음 — 산출물은 재생성 불가라 근거가 남아야 한다")

    report = scan(root, now)
    by_name = {i.name: i for i in report.items}
    unknown = sorted(set(names) - set(by_name))
    if unknown:
        raise KeyError(f"보관물 없음: {unknown}")

    blocked = [n for n in names if by_name[n].protected]
    if blocked:
        detail = "; ".join(f"{n} ← {', '.join(by_name[n].referenced_by)}" for n in blocked)
        raise ValueError(f"참조된 산출물은 지울 수 없다 (계보 절단): {detail}")

    removed: list[str] = []
    for name in names:
        path = by_name[name].path
        if path.is_file():
            path.unlink()
        else:
            for child in sorted(path.rglob("*"), reverse=True):
                child.unlink() if child.is_file() else child.rmdir()
            path.rmdir()
        removed.append(name)
    return removed
