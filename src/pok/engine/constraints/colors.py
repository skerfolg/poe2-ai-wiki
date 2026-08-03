"""보조 젬 색상 장부 검사 — D27 ② (근거: passive.crystallised-immunities-5332 서술).

전 빌드 스코프 집계 조건: 결정화된 면역의 "과반"은 세 색 중 최다가 아니라
전체의 절반 초과다 — `지정색 수 > 전체 장착 보조 수 ÷ 2` (문구=GAME_DATA,
판정식=SUPPORTED_INFERENCE). 무색·복합색의 분모 포함 방식은 UNVERIFIED이므로
장부에 넣은 보조는 전부 분모에 포함해 보수적으로 계산한다(v6 색상 안전 규칙).

v6 실증(design.md §7.3): 빨강 6/전체 10 = 60% 통과 → 비빨강 +1 = 6/11 통과
→ 비빨강 +2 = 6/12 = 50% 실패. 여유분 = 조건 유지한 채 추가 가능한 비지정색 수.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SkillLinks:
    """스킬 하나의 장착 보조 장부 — (보조 이름, 색상) 나열.

    색상은 소문자 문자열("red"|"blue"|"green" 등). 비활성 스킬·교체 무기 세트의
    보조는 집계 방식이 UNVERIFIED — 장부에 넣지 않는 것이 안전 규칙(v6).
    """

    skill: str
    supports: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ColorLedgerReport:
    color: str  # 과반 조건의 지정색
    counts: tuple[tuple[str, int], ...]  # 색상별 집계 (지정색 우선, 이후 사전순)
    total: int
    satisfied: bool  # 지정색 수 > 전체 ÷ 2
    headroom_additions: int  # 조건 유지한 채 추가 가능한 비지정색 보조 수 (위반 시 0)
    deficit: int  # 조건 충족까지 부족한 지정색 보조 수 (충족 시 0)
    violations: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.violations


def check_color_majority(skills: tuple[SkillLinks, ...], color: str) -> ColorLedgerReport:
    """장착 보조 전수 집계 후 `지정색 > 전체 ÷ 2` 판정 + 여유분 계산."""
    tally: dict[str, int] = {}
    for grp in skills:
        for _name, c in grp.supports:
            tally[c] = tally.get(c, 0) + 1
    total = sum(tally.values())
    matched = tally.get(color, 0)
    satisfied = matched * 2 > total
    # matched > (total + k) / 2  ⇔  k < 2·matched - total  ⇒  최대 k = 2·matched - total - 1
    headroom = max(0, 2 * matched - total - 1) if satisfied else 0
    # 미충족 시: matched + d > (total + d) / 2  ⇔  d > total - 2·matched
    deficit = 0 if satisfied else total - 2 * matched + 1
    violations: tuple[str, ...] = ()
    if not satisfied:
        violations = (
            f"{color} {matched}/{total} — 과반({color} > 전체÷2) 미충족, "
            f"{color} 보조 {deficit}개 보강 필요",
        )
    ordered = sorted(tally.items(), key=lambda kv: (kv[0] != color, kv[0]))
    return ColorLedgerReport(
        color=color,
        counts=tuple(ordered),
        total=total,
        satisfied=satisfied,
        headroom_additions=headroom,
        deficit=deficit,
        violations=violations,
    )
