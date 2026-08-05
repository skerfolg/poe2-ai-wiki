"""스킬 세트 충전율 — 빈 역할 칸과 남은 정신력을 드러낸다 (이관 4 D5).

사용자 지적(2026-08-05): *"다른 유저 PoB에 비해 우리 빌드는 주력기 하나만 설정돼
있다. 주어진 정신력 내에서 최대 효율을 내는 스킬들을 쓰고, 도움이 될 스킬을 설정할
수 있어야 한다."*

실측 대비 — 타 유저 앵커 **13·20·28개** 스킬 그룹, 우리 산출물 **1개**. 정신력 100 중
**0 사용**. `BUILD_DESIGN §2-3-d`가 "스킬 세트 전체가 설계 대상이고 빈 칸도 결정"이라고
이미 못 박았는데 **두 빌드 연속 어겼다.**

## 규율만으로는 또 어긴다

같은 세션이 **룬은 안 빠뜨렸다** — `exhaustion.sockets`가 "16칸 0% 사용"을 ⚠로
보고했기 때문이다. 차이는 규율이 아니라 **검사기가 보여줬는가**였다.

그래서 같은 장치를 스킬 축에 붙인다: 역할 칸(BUILD_DESIGN §2-3-d의 표)을 훑어
비어 있는 자리와 남은 정신력을 낸다. **미사용은 위반이 아니다** — 비용·색상 제약으로
의도적으로 비울 수 있고 그 판단은 호출자 몫이다(AD-3). 다만 보이지 않으면 판단할
수도 없다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

# BUILD_DESIGN §2-3-d의 자리 표를 그대로 옮긴 것 — 문서와 검사기가 어긋나면 안 된다.
# 판정은 스킬 이름·효과 문구의 키워드로 하되, **못 맞히면 unclassified로 낸다**
# (억지로 배정하면 "채웠다"는 거짓 신호가 된다).
ROLE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("trigger", "트리거 엔진", r"cast on|trigger|invocation|spellslinger|when you"),
    ("buff", "버프·오라", r"herald|aura|rage|presence|banner|buff|reserv"),
    ("curse", "저주·디버프", r"curse|hex|mark|blasphemy|despair|enfeeble|exposure"),
    ("movement", "이동기", r"dash|leap|blink|roll|charge|whirl|traversal|shield charge"),
    ("minion", "소환수·토템", r"minion|summon|totem|skeleton|zombie|spectre|companion"),
    ("utility", "유틸", r"guard|ward|immun|recover|barrier|shield|cleanse|escape|banner"),
)
_MAIN_ROLE = ("main", "주력기")


@dataclass(frozen=True)
class SkillEntry:
    """설계가 배치한 스킬 하나."""

    name: str
    text: str = ""  # 효과 문구(KB `stats` 등) — 역할 판정에 쓴다
    reservation: float = 0.0  # 이 스킬이 점유하는 정신력(절대량)
    role: str = ""  # 호출자가 직접 지정하면 그것을 쓴다


@dataclass(frozen=True)
class RoleSlot:
    key: str
    label: str
    filled: tuple[str, ...]

    @property
    def empty(self) -> bool:
        return not self.filled


@dataclass(frozen=True)
class SkillSetReport:
    roles: tuple[RoleSlot, ...]
    unclassified: tuple[str, ...]
    total_skills: int
    spirit_pool: float | None
    spirit_used: float
    # 위반이 아니다 — 보이지 않으면 판단할 수도 없어서 낸다(룬 소켓과 같은 성격)
    notes: tuple[str, ...]

    @property
    def empty_roles(self) -> tuple[str, ...]:
        return tuple(r.label for r in self.roles if r.empty)

    @property
    def spirit_remaining(self) -> float | None:
        return None if self.spirit_pool is None else round(self.spirit_pool - self.spirit_used, 2)

    @property
    def fill_pct(self) -> float:
        filled = sum(1 for r in self.roles if not r.empty)
        return round(filled / len(self.roles) * 100.0, 1) if self.roles else 0.0


def _classify(entry: SkillEntry) -> str | None:
    if entry.role:
        return entry.role
    blob = f"{entry.name} {entry.text}".lower()
    for key, _label, pattern in ROLE_PATTERNS:
        if re.search(pattern, blob):
            return key
    return None


def check_skillset(
    skills: Iterable[SkillEntry | Mapping[str, object]],
    *,
    spirit_pool: float | None = None,
    main_skill: str = "",
) -> SkillSetReport:
    """역할 칸 충전율 + 정신력 잔여. 판단하지 않고 **비어 있음을 드러낸다**(AD-3)."""
    entries: list[SkillEntry] = []
    for raw in skills:
        if isinstance(raw, SkillEntry):
            entries.append(raw)
        else:
            entries.append(
                SkillEntry(
                    name=str(raw.get("name", "")),
                    text=str(raw.get("text", "")),
                    reservation=float(raw.get("reservation", 0.0) or 0.0),  # type: ignore[arg-type]
                    role=str(raw.get("role", "")),
                )
            )

    buckets: dict[str, list[str]] = {key: [] for key, _, _ in ROLE_PATTERNS}
    buckets[_MAIN_ROLE[0]] = []
    unclassified: list[str] = []
    for entry in entries:
        if main_skill and entry.name == main_skill:
            buckets[_MAIN_ROLE[0]].append(entry.name)
            continue
        key = _classify(entry)
        if key and key in buckets:
            buckets[key].append(entry.name)
        else:
            unclassified.append(entry.name)
    # 주력기를 지정하지 않았으면 분류 안 된 첫 스킬이 주력기일 가능성이 높다 —
    # 그래도 **임의로 배정하지 않는다**. 지정은 호출자 몫이고 여기선 사실만 낸다.

    slots: list[tuple[str, str]] = [_MAIN_ROLE, *((k, lb) for k, lb, _ in ROLE_PATTERNS)]
    roles = tuple(RoleSlot(key, label, tuple(buckets.get(key, ()))) for key, label in slots)
    used = round(sum(e.reservation for e in entries), 2)

    notes: list[str] = []
    empty = [r.label for r in roles if r.empty]
    if empty:
        notes.append(
            f"빈 역할 칸 {len(empty)}개: {', '.join(empty)} — 비우는 것이 의도라면 "
            f"**사유를 문서에 적을 것**(BUILD_DESIGN §2-3-d)"
        )
    if spirit_pool is not None:
        remaining = spirit_pool - used
        if remaining > 0:
            notes.append(
                f"정신력 {remaining:g} 남음 (총 {spirit_pool:g} 중 {used:g} 사용) — "
                f'후보는 `find_by_value("reservation.max", type="Skill", '
                f"maximum={remaining:g})`로 열거한다"
            )
        if used == 0 and spirit_pool > 0:
            notes.append(
                f"⚠ 정신력 {spirit_pool:g}을 **한 점도 쓰지 않았다** — 버프·저주·전령은 "
                f"대부분 점유로 사는 것이고, 안 쓰면 그 축이 통째로 비어 있는 것이다"
            )
    if len(entries) <= 2:
        notes.append(
            f"⚠ 스킬 그룹이 {len(entries)}개다 — 실측 대비 타 유저 빌드는 13~28개다. "
            f"메인기만 있으면 빌드가 아니라 스킬 하나다(BUILD_DESIGN §2-3-d)"
        )
    return SkillSetReport(
        roles=roles,
        unclassified=tuple(unclassified),
        total_skills=len(entries),
        spirit_pool=spirit_pool,
        spirit_used=used,
        notes=tuple(notes),
    )
