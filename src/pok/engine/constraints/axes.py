"""스케일링 축 완전성 보고 — "열거조차 안 한 축"을 드러낸다 (회차 종결 R2·R3).

사용자 교정 2판이 세션 생성본과 **61배** 차이를 실증했다. 격차의 성분 대부분이
"어려운 것"이 아니라 **열거조차 안 한 축**이었다:

    젬 레벨 +5      1.28x   축 자체를 미측정
    카옴의 심장     1.26x   슬롯을 저항 캡으로 "완료" 처리 — 유니크 열거 절차 없음
    성유            —       큐에 방치
    아이템 부여 스킬 —       전직이 주는 스킬조차 미등록
    호신부·플라스크  —       공란인 채 인지 밖

`multipliers` 장부는 **스탯 공간**만 본다 — 이건 **획득 공간**의 축 목록이다.
`exhaustion.sockets`가 룬을 구제한 방식 그대로: 규율(§2-3-c)은 이미 있었고 세션이
인용까지 하고 어겼다. 차이는 검사기가 보여줬는가다.

**미개발은 위반이 아니다**(AD-3) — 비용상 의도적으로 비울 수 있고 그 판단은 호출자
몫이다. 다만 보이지 않으면 판단할 수도 없다. 축마다 `covered | empty | unmeasured`
셋 중 하나를 낸다 — 검사기가 스펙만으로 알 수 없는 축(성유·품질 등 입력이 안 온 것)은
"없다"가 아니라 **"안 쟀다"**로 낸다. 없다고 단정하면 그게 또 조용한 거짓이 된다.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

GEM_LEVEL_CAP = 20  # 기본 최고 레벨 — 접미(+N to Level of …)로 넘길 수 있다
_ATTACK_MOD = re.compile(
    r"adds? \d+ to \d+|increased .*damage|% of damage|extra damage|critical", re.I
)
_GRANTS_SKILL = re.compile(r"grants? (?:level \d+ )?skill|스킬 부여", re.I)


@dataclass(frozen=True)
class AxisStatus:
    key: str
    label: str
    state: str  # covered | empty | unmeasured
    detail: str


@dataclass(frozen=True)
class AxesReport:
    axes: tuple[AxisStatus, ...]
    notes: tuple[str, ...]

    @property
    def empty_axes(self) -> tuple[str, ...]:
        return tuple(a.label for a in self.axes if a.state == "empty")

    @property
    def unmeasured_axes(self) -> tuple[str, ...]:
        return tuple(a.label for a in self.axes if a.state == "unmeasured")


def _gem_levels(build_spec: Mapping[str, Any]) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for group in build_spec.get("skills") or []:
        for gem in group.get("gems") or []:
            out.append((str(gem.get("name", "?")), int(gem.get("level", 0) or 0)))
    return out


def _item_texts(build_spec: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(item.get("slot", "?")): str(item.get("text", ""))
        for item in build_spec.get("items") or []
    }


def check_axes(
    build_spec: Mapping[str, Any],
    *,
    anointed_items: Sequence[str] = (),
    quality_checked: bool = False,
    slot_attack_deltas: Mapping[str, float] | None = None,
) -> AxesReport:
    """획득 공간의 축을 열거하고 각각 covered/empty/unmeasured로 판정한다.

    - `anointed_items`: 성유를 부여한 아이템 슬롯들 (스펙 텍스트로는 안 보일 수 있어
      호출자가 준다 — 안 주면 아이템 텍스트에서 `Allocates`를 찾아본다)
    - `quality_checked`: 젬 품질 축을 검토했는가 (설계 문서 기준 — 호출자 신고)
    - `slot_attack_deltas`: 슬롯별 공격 기여 실측 {슬롯: 델타}. **측정에는 PoB가
      필요해서** 스펙만으로는 못 낸다 — 안 주면 unmeasured로 낸다(없다고 단정하지
      않는다).
    """
    axes: list[AxisStatus] = []
    items = _item_texts(build_spec)

    # ① 젬 레벨 — +5가 1.28x였다. 축 존재를 몰랐던 게 아니라 열거를 안 했다
    gems = _gem_levels(build_spec)
    if not gems:
        axes.append(AxisStatus("gem_level", "젬 레벨", "empty", "스킬이 없다"))
    else:
        over = [(n, lv) for n, lv in gems if lv > GEM_LEVEL_CAP]
        if over:
            detail = (
                f"기본 캡({GEM_LEVEL_CAP}) 초과 {len(over)}건 — +레벨 접미·장비를 이미 쓴다: "
                + ", ".join(f"{n}={lv}" for n, lv in over[:4])
            )
            axes.append(AxisStatus("gem_level", "젬 레벨", "covered", detail))
        else:
            # 캡 이하 = **+레벨 장비 축이 통째로 미사용**이다. "20이면 최대"가 함정이다 —
            # 목걸이 접미 +3·장갑 +2로 캡을 넘기는 축이 있고, 실측 +5가 1.28x였다.
            # 세션 생성본이 정확히 이 상태(전부 20)로 출고됐다.
            top = max(lv for _, lv in gems)
            axes.append(
                AxisStatus(
                    "gem_level",
                    "젬 레벨",
                    "empty",
                    f"최고 {top}레벨 — 기본 캡({GEM_LEVEL_CAP})을 넘기는 +레벨 접미"
                    f"(목걸이 +3·장갑 +2)가 미사용이다 (실측: +5가 1.28x)",
                )
            )

    # ② 성유 — 큐에 방치됐던 축
    amulets = [slot for slot in items if "amulet" in slot.lower()]
    if anointed_items:
        axes.append(AxisStatus("anoint", "성유", "covered", f"부여: {', '.join(anointed_items)}"))
    elif any("allocates" in text.lower() for text in items.values()):
        axes.append(AxisStatus("anoint", "성유", "covered", "아이템 텍스트에 Allocates 존재"))
    elif amulets:
        axes.append(
            AxisStatus(
                "anoint",
                "성유",
                "empty",
                f"목걸이({', '.join(amulets)})가 있는데 성유 부여가 없다 — "
                f"노터블 하나를 공짜로 얻는 축이다",
            )
        )
    else:
        axes.append(AxisStatus("anoint", "성유", "unmeasured", "목걸이 슬롯이 스펙에 없다"))

    # ③ 아이템 부여 스킬 — 전직이 주는 것조차 미등록이었다
    granting = [slot for slot, text in items.items() if _GRANTS_SKILL.search(text)]
    skill_names = {
        str(g.get("name", "")).lower()
        for group in build_spec.get("skills") or []
        for g in group.get("gems") or []
    }
    if granting:
        axes.append(
            AxisStatus(
                "granted_skills",
                "아이템 부여 스킬",
                "covered" if skill_names else "empty",
                f"부여 아이템 {len(granting)}건({', '.join(granting)}) — 스킬 그룹에 "
                f"등록해야 계산·점유 장부에 들어간다. **부여 스킬은 정신력 0에서도 "
                f"쓸 수 있다**(mechanic.item-granted-skills)",
            )
        )
    else:
        axes.append(
            AxisStatus(
                "granted_skills",
                "아이템 부여 스킬",
                "unmeasured",
                "부여 문구를 가진 아이템이 스펙에 없다 — 전직·유니크가 주는 스킬을 "
                "빠뜨리지 않았는지 확인할 것",
            )
        )

    # ④ 호신부·플라스크 — 공란인 채 인지 밖이던 슬롯
    for key, label, pattern in (("charm", "호신부", "charm"), ("flask", "플라스크", "flask")):
        matching = [slot for slot in items if pattern in slot.lower()]
        axes.append(
            AxisStatus(
                key,
                label,
                "covered" if matching else "empty",
                f"슬롯 {len(matching)}건" if matching else "스펙에 없다 — 열거조차 안 한 축이다",
            )
        )

    # ⑤ 젬 품질 — 검토 신고가 없으면 안 쟀다고 낸다
    axes.append(
        AxisStatus(
            "quality",
            "젬 품질",
            "covered" if quality_checked else "unmeasured",
            "검토 신고됨" if quality_checked else "품질 축 검토가 신고되지 않았다",
        )
    )

    # ⑥ 슬롯별 공격 기여 — 측정에는 PoB가 필요하다
    if slot_attack_deltas is not None:
        dead = [slot for slot, delta in slot_attack_deltas.items() if abs(delta) < 1e-9]
        axes.append(
            AxisStatus(
                "slot_attack",
                "슬롯별 공격 기여",
                "covered" if not dead else "empty",
                f"공격 기여 0인 슬롯: {', '.join(dead)} — 방어 접사만 채운 슬롯이다"
                if dead
                else "전 슬롯이 공격에 기여",
            )
        )
    else:
        axes.append(
            AxisStatus(
                "slot_attack",
                "슬롯별 공격 기여",
                "unmeasured",
                "슬롯별 델타 미제공 — `evaluate_delta`로 각 슬롯을 빈 것과 비교해 "
                "잰 값을 넣으면 판정한다 (실측: 장신구 공격 플랫이 1.20x)",
            )
        )

    empty = [a for a in axes if a.state == "empty"]
    unmeasured = [a for a in axes if a.state == "unmeasured"]
    notes: list[str] = []
    if empty:
        notes.append(
            f"⚠ 비어 있는 축 {len(empty)}개: {', '.join(a.label for a in empty)} — "
            f"비우는 것이 의도라면 사유를 문서에 적을 것(BUILD_DESIGN §2-3-c). "
            f"실측: 열거 안 한 축들이 겹쳐 61배가 났다"
        )
    if unmeasured:
        notes.append(
            f"안 잰 축 {len(unmeasured)}개: {', '.join(a.label for a in unmeasured)} — "
            f"'없다'가 아니라 '안 쟀다'이다. 없다고 단정하면 그게 또 조용한 거짓이 된다"
        )
    return AxesReport(tuple(axes), tuple(notes))
