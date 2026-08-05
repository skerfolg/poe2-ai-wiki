"""자원 소진 검사 — D27 ④ (성유 1회성·보조 슬롯 한도·룬 소켓).

근거(태스크 #35 수록분):
- 성유: crafting-rules/anoint-rules.json — 아이템당 성유 부여는 동시에 1개만
  (v6: "목걸이 기존 성유 고정, 추가 주입 불가능" — 기존 부여 위에 다른 노드를
  주입으로 해결할 수 없다)
- 보조 슬롯: mechanic.support-gem-slots — 액티브 젬당 보조 최대 5개
- 룬 소켓: 아이템 베이스의 `data.socket_limit` (1,625건 수록, PoB `socketLimit`)

## 미사용 자원도 보고한다 (2026-08-05 실측 사고)

한 빌드가 **룬 소켓 16칸을 0칸 쓴 채로 "제약 5종 통과"로 기록됐다.** 검사기가
룬을 자원 축으로 보지 않았기 때문이다 — **없는 축은 위반도 없다.** 나중에 그 16칸을
채우자 3티어 전부 DPS +37~47%·EHP +34~72%가 나왔고, 마지막 병목까지 접사 한 칸
쓰지 않고 풀렸다. "통과"가 거짓 안심이었다.

그래서 이 검사기는 **한도 초과(위반)뿐 아니라 미사용 여유(`unused`)도 낸다.**
미사용 자체는 위반이 아니다 — 비용 때문에 의도적으로 비울 수 있고, 그 판단은
호출자 몫이다(AD-3). 다만 **보이지 않으면 판단할 수도 없다.**

설계 문서 쪽 짝은 BUILD_DESIGN §2-3-d의 "빈 칸도 왜 비우는지 적는다"이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pok.engine.constraints.colors import SkillLinks


@dataclass(frozen=True)
class AnointPlan:
    """아이템 하나의 성유 상태 — 기존 부여와 설계가 요구하는 부여."""

    item: str
    existing: str | None = None  # 이미 부여된 성유 노드 (없으면 None)
    planned: str | None = None  # 설계가 이 아이템에 요구하는 성유 노드


@dataclass(frozen=True)
class SocketPlan:
    """아이템 하나의 룬 소켓 상태 — 총 칸과 채운 칸.

    `sockets`는 베이스의 `data.socket_limit`(KB 수록분)에서 온다. 채운 칸은
    설계가 배치한 룬 수다.
    """

    item: str
    sockets: int
    filled: int = 0


@dataclass(frozen=True)
class ExhaustionReport:
    support_slots: tuple[tuple[str, int, int], ...]  # (스킬, 사용 수, 한도)
    slot_headroom: tuple[tuple[str, int], ...]  # (스킬, 잔여 슬롯)
    violations: tuple[str, ...]
    rune_sockets: tuple[tuple[str, int, int], ...] = ()  # (아이템, 채움, 총)
    # 미사용 여유 — **위반이 아니다.** 보이지 않으면 판단할 수도 없어서 낸다.
    unused: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def rune_fill_pct(self) -> float:
        """룬 소켓 충전율 — 0%가 조용히 지나가지 않게 하는 한 줄 지표."""
        total = sum(total for _, _, total in self.rune_sockets)
        filled = sum(filled for _, filled, _ in self.rune_sockets)
        return round(filled / total * 100.0, 1) if total else 0.0


def check_exhaustion(
    skills: tuple[SkillLinks, ...],
    anoints: tuple[AnointPlan, ...] = (),
    *,
    max_supports_per_skill: int,
    sockets: tuple[SocketPlan, ...] = (),
) -> ExhaustionReport:
    """소진 자원 장부 검사 — 한도 초과·성유 중복은 위반, 미사용 여유는 `unused`로."""
    violations: list[str] = []
    slots: list[tuple[str, int, int]] = []
    headroom: list[tuple[str, int]] = []
    unused: list[str] = []
    for grp in skills:
        used = len(grp.supports)
        slots.append((grp.skill, used, max_supports_per_skill))
        headroom.append((grp.skill, max_supports_per_skill - used))
        if used > max_supports_per_skill:
            violations.append(
                f"{grp.skill}: 보조 {used}개 > 한도 {max_supports_per_skill} "
                f"(mechanic.support-gem-slots)"
            )
    for plan in anoints:
        if plan.existing and plan.planned and plan.planned != plan.existing:
            violations.append(
                f"{plan.item}: 성유 중복 배분 — 기존 {plan.existing!r} 위에 "
                f"{plan.planned!r} 추가 불가 (anoint-rules: 아이템당 1개). "
                f"직접 경로·주얼·장비로 확보 필요"
            )
    rune_rows: list[tuple[str, int, int]] = []
    for socket in sockets:
        rune_rows.append((socket.item, socket.filled, socket.sockets))
        if socket.filled > socket.sockets:
            violations.append(
                f"{socket.item}: 룬 {socket.filled}개 > 소켓 {socket.sockets}칸 "
                f"(베이스 socket_limit 초과)"
            )
        elif socket.filled < socket.sockets:
            unused.append(f"{socket.item}: 룬 소켓 {socket.sockets - socket.filled}칸 미사용")

    total_sockets = sum(p.sockets for p in sockets)
    total_filled = sum(min(p.filled, p.sockets) for p in sockets)
    if total_sockets and total_filled == 0:
        # 전량 미사용은 개별 항목만 봐선 놓치기 쉽다 — 총계로 한 번 더 드러낸다
        unused.append(
            f"⚠ 룬 소켓 {total_sockets}칸이 **전부 비어 있다** — 설계가 이 자원 축을 "
            f"아예 쓰지 않았다. 비우는 것이 의도라면 사유를 문서에 적을 것"
            f"(BUILD_DESIGN §2-3-d)"
        )

    return ExhaustionReport(
        support_slots=tuple(slots),
        slot_headroom=tuple(headroom),
        violations=tuple(violations),
        rune_sockets=tuple(rune_rows),
        unused=tuple(unused),
    )
