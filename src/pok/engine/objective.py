"""목표 상태 목적 — D28 (BLUEPRINT §10.0 ③, RC3 다차원 프로파일의 판정기).

목적함수는 평평한 가중 합산이 아니라 **임계값(floor)·캡(cap) 충족**으로 표현한다.
v6 실증: 설계 판단 대부분이 "더 많이"가 아니라 "경계 지키기"(로우라이프 35%,
색상 과반, 포인트 8 예산)였고, 가중 합산은 이런 경계·배타 구조를 표현하지 못한다.

판정은 **사전식(lexicographic)**: 목표 나열 순서 = 우선순위이며, 첫 미충족
목표가 "다음 병목"이다 — 그것을 해소하기 전 하위 목표의 개선은 무의미하다.

판단 없음(AD-3): 이 모듈은 실측값 대 목표의 충족·여유분만 보고한다.
목표를 무엇으로 잡을지, 병목을 어떻게 풀지는 에이전트·사용자 몫.
실측값의 출처는 PoB(compute_pob stats)·인게임 정보창·제약 검사기 리포트 —
추측값 입력 금지(반프록시 AD-8).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

_OPS = (">=", "<=")


@dataclass(frozen=True)
class Target:
    """목표 하나 — metric이 op 방향으로 value를 충족해야 한다.

    op ">=" = 하한(floor, 예: 치명타 확률 ≥ 60), "<=" = 상한(cap, 예: 잔여
    생명력 ≤ 35 = 로우라이프 유지). label은 사람용 설명(예: "로우라이프 경계").
    """

    metric: str
    op: str
    value: float
    label: str = ""


@dataclass(frozen=True)
class TargetResult:
    metric: str
    op: str
    value: float
    measured: float | None  # None = 실측값 없음 (판정 불가)
    satisfied: bool  # 실측 없으면 False (충족 확인 전까지 충족 아님 — 반프록시)
    margin: float | None  # 충족 방향 여유분 (floor: 실측-목표, cap: 목표-실측)
    label: str = ""


@dataclass(frozen=True)
class ObjectiveReport:
    results: tuple[TargetResult, ...]
    satisfied: bool  # 전 목표 충족 (미측정 포함 시 False)
    next_bottleneck: TargetResult | None  # 사전식 첫 미충족 (미측정이면 그것)
    unmeasured: tuple[str, ...]  # 실측값이 없는 metric들 = 측정 큐

    @property
    def ok(self) -> bool:
        return self.satisfied


def evaluate_targets(targets: tuple[Target, ...], measured: Mapping[str, float]) -> ObjectiveReport:
    """목표 나열(우선순위 순)과 실측값 → 충족·여유분·다음 병목 보고."""
    results: list[TargetResult] = []
    unmeasured: list[str] = []
    for t in targets:
        if t.op not in _OPS:
            raise ValueError(f"{t.metric}: op {t.op!r} 불허 (허용: {_OPS})")
        got = measured.get(t.metric)
        if got is None:
            unmeasured.append(t.metric)
            results.append(TargetResult(t.metric, t.op, t.value, None, False, None, t.label))
            continue
        margin = (got - t.value) if t.op == ">=" else (t.value - got)
        results.append(
            TargetResult(t.metric, t.op, t.value, got, margin >= 0, round(margin, 4), t.label)
        )
    bottleneck = next((r for r in results if not r.satisfied), None)
    return ObjectiveReport(
        results=tuple(results),
        satisfied=bottleneck is None,
        next_bottleneck=bottleneck,
        unmeasured=tuple(unmeasured),
    )
