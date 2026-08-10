"""보조 젬 색상 장부 검사 — D27 ② (근거: passive.crystallised-immunities-5332 서술).

전 빌드 스코프 집계 조건: 결정화된 면역의 "과반"은 세 색 중 최다가 아니라
전체의 절반 초과다 — `지정색 수 > 전체 장착 보조 수 ÷ 2` (문구=GAME_DATA,
판정식=SUPPORTED_INFERENCE). 무색·복합색의 분모 포함 방식은 UNVERIFIED이므로
장부에 넣은 보조는 전부 분모에 포함해 보수적으로 계산한다(v6 색상 안전 규칙).

v6 실증(design.md §7.3): 빨강 6/전체 10 = 60% 통과 → 비빨강 +1 = 6/11 통과
→ 비빨강 +2 = 6/12 = 50% 실패. 여유분 = 조건 유지한 채 추가 가능한 비지정색 수.

## ⚠ 이 조건은 **한 노드의 것이다** (백로그 #55, 2026-08-10)

과반이 사는 것은 성유 전용 노터블 `passive.crystallised-immunities-5332` 하나의
면역뿐이다. 그런데 리포트가 그 사실을 말하지 않아서, 한 세션이 `satisfied: false`를
**빌드 위반**으로 읽고 「보조 4개가 섀시와 충돌한다」고 설계 문서에 적어 회피+ES
섀시를 재검토 대상에 올렸다 — 실측 후 통째로 철회했다. 거짓 위반은 참 위반의
신호를 죽인다(§0 ⑤). 그래서 판정에 **무엇을 사는 조건인지**를 항상 붙인다.

보고자는 원인을 "`reqStr`을 PoE1식 소켓 색으로 읽는다"로 추정했지만 아니다 —
PoE2 보조 젬에는 실제로 색이 있고(노드 문구가 `Socketed Support Gems are Blue`라고
말한다) KB에 결정적으로 수록돼 있다(red 187·blue 176·green 142·colorless 26).
"""

from __future__ import annotations

import functools
from dataclasses import dataclass

# 과반 조건의 **유일한 소비처**. 색 → 그 색이 과반일 때 사는 것.
CONDITION_NODE = "passive.crystallised-immunities-5332"
COLOR_GRANTS = {
    "blue": "냉각 면역",
    "red": "점화 면역",
    "green": "감전 면역",
}


@dataclass(frozen=True)
class SkillLinks:
    """스킬 하나의 장착 보조 장부 — (보조 이름, 색상) 나열.

    색상은 소문자 문자열("red"|"blue"|"green" 등). 비활성 스킬·교체 무기 세트의
    보조는 집계 방식이 UNVERIFIED — 장부에 넣지 않는 것이 안전 규칙(v6).

    색을 빈 문자열로 두면 **KB에서 찾는다**(`resolve_colors`) — 수기 전사는
    틀릴 수 있고 색은 젬의 요구 속성에서 결정적으로 도출되기 때문이다.
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
    # 이 판정이 **무엇의 조건인지** — 없으면 빌드 위반으로 오독된다(#55)
    applies_to: str = CONDITION_NODE
    grants: str = ""
    # 선언된 색과 KB 색이 어긋난 것들 (수기 전사 오류 — 집계 자체가 틀어진다)
    color_mismatches: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations


@functools.lru_cache(maxsize=1)
def _kb_colors() -> dict[str, str]:
    """보조 표시명(소문자) → 색. 색은 요구 속성에서 결정적으로 도출된 값이다."""
    from pok.kb.store import load as store_load

    out: dict[str, str] = {}
    for record in store_load().records.values():
        if record.type != "Support":
            continue
        color = str((record.raw.get("data") or {}).get("color") or "")
        if color:
            out[record.name_en.lower()] = color
            ko = str((record.raw.get("name") or {}).get("ko") or "").strip().lower()
            if ko:
                out[ko] = color
    return out


def resolve_colors(
    skills: tuple[SkillLinks, ...],
) -> tuple[tuple[SkillLinks, ...], tuple[str, ...]]:
    """빈 색을 KB로 채우고, **선언한 색이 KB와 다르면** 그 사실을 낸다.

    색은 젬의 요구 속성에서 결정적으로 나온다 — 호출자가 손으로 적으면 틀릴 수
    있고, 틀리면 과반 집계가 통째로 어긋난다. 감지되므로 도구가 말한다(철칙 5).
    """
    known = _kb_colors()
    resolved: list[SkillLinks] = []
    mismatches: list[str] = []
    for group in skills:
        pairs: list[tuple[str, str]] = []
        for name, declared in group.supports:
            kb_color = known.get(name.strip().lower(), "")
            if not declared:
                pairs.append((name, kb_color or "unknown"))
                if not kb_color:
                    mismatches.append(f"{name!r}: KB에 색이 없다 — 이름을 확인할 것")
                continue
            if kb_color and kb_color != declared:
                mismatches.append(f"{name!r}: 선언 {declared!r} ≠ KB {kb_color!r} (KB를 따랐다)")
            pairs.append((name, kb_color or declared))
        resolved.append(SkillLinks(skill=group.skill, supports=tuple(pairs)))
    return tuple(resolved), tuple(mismatches)


def check_color_majority(skills: tuple[SkillLinks, ...], color: str) -> ColorLedgerReport:
    """장착 보조 전수 집계 후 `지정색 > 전체 ÷ 2` 판정 + 여유분 계산."""
    skills, mismatches = resolve_colors(skills)
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
    grants = COLOR_GRANTS.get(color, "")
    violations: tuple[str, ...] = ()
    if not satisfied:
        # ⚠ 문구가 **무엇의 조건인지**로 시작한다 — 빌드 위반으로 읽히면 안 된다(#55)
        bought = f"{grants} " if grants else ""
        violations = (
            f"{CONDITION_NODE}({bought}성유 전용)의 조건 미충족: "
            f"{color} {matched}/{total} — 과반({color} > 전체÷2)에 {color} 보조 "
            f"{deficit}개 부족. **그 노드를 안 쓸 거면 위반이 아니다** — 색 과반이 사는 "
            f"것은 이 노드의 면역뿐이고, 보조 색은 캐릭터 속성 요구와 별개다",
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
        grants=grants,
        color_mismatches=mismatches,
    )
