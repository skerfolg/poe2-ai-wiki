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

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

_ATTACK_MOD = re.compile(
    r"adds? \d+ to \d+|increased .*damage|% of damage|extra damage|critical", re.I
)
_GRANTS_SKILL = re.compile(r"grants? (?:level \d+ )?skill|스킬 부여", re.I)
_LEVEL_SUPPLY = re.compile(r"^(?:\{[^}]*\})*\+\d+ to (?:the )?Level of .+$", re.I)


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


def _main_gem(build_spec: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Resolve the selected active effect, not the highest-level gem in any group."""
    from pok.kb.skill_facts import gem_effects, skill_gates

    groups = list(build_spec.get("skills") or [])
    index = build_spec.get("main_socket_group", 1)
    if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= len(groups):
        return None
    group = groups[index - 1]
    if not group.get("enabled", True):
        return None
    pointer = group.get("main_active_skill", 1)
    if isinstance(pointer, bool) or not isinstance(pointer, int):
        return None
    gates, effects = skill_gates(), gem_effects()
    active: list[Mapping[str, Any]] = []
    for gem in group.get("gems") or []:
        if not gem.get("enabled", True):
            continue
        gem_id = gem.get("gem_id")
        if not gem_id:
            name = str(gem.get("name", "")).casefold()
            ids = {
                g.gem_id
                for g in gates.values()
                if name in {g.name.casefold(), g.name_ko.casefold()} and g.gem_id
            }
            if len(ids) != 1:
                return None
            gem_id = next(iter(ids))
        effect_ids = effects.get(str(gem_id), ())
        if not effect_ids or any(effect not in gates for effect in effect_ids):
            return None
        active.extend(gem for effect in effect_ids if not gates[effect].is_support)
    return active[pointer - 1] if 1 <= pointer <= len(active) else None


def _level_suppliers(build_spec: Mapping[str, Any]) -> list[str]:
    """Rendered, active supply candidates; wording alone does not prove applicability."""
    allocated = set(build_spec.get("tree_nodes") or [])
    candidates = list(build_spec.get("items") or []) + [
        jewel
        for jewel in build_spec.get("jewels") or []
        if jewel.get("socket_node_id") in allocated
    ]
    return [
        f"{item.get('slot', 'jewel@' + str(item.get('socket_node_id')))}: {line.strip()}"
        for item in candidates
        if item.get("active", True)
        for line in str(item.get("text", "")).splitlines()
        if _LEVEL_SUPPLY.fullmatch(line.strip())
    ]


def _gem_level_axis(
    build_spec: Mapping[str, Any], measurement: Mapping[str, Any] | None
) -> AxisStatus:
    suppliers = _level_suppliers(build_spec)
    supply_note = (
        "실물 +레벨 공급 후보: " + "; ".join(suppliers)
        if suppliers
        else "활성 실물의 +레벨 공급 문구가 확인되지 않았다"
    )
    gem = _main_gem(build_spec)
    if gem is None:
        return AxisStatus(
            "gem_level", "젬 레벨", "unmeasured", "활성 주력 젬을 식별하지 못했다 — " + supply_note
        )
    level, corrupt = gem.get("level", 20), gem.get("corrupt_level", 0)
    if (
        any(isinstance(v, bool) or not isinstance(v, int) for v in (level, corrupt))
        or level <= 0
        or corrupt < 0
    ):
        return AxisStatus("gem_level", "젬 레벨", "unmeasured", "주력 입력 레벨이 유효하지 않다")
    if corrupt and not gem.get("corrupted", False):
        return AxisStatus(
            "gem_level", "젬 레벨", "unmeasured", "corrupt_level과 corrupted 입력이 불일치한다"
        )
    input_level = level + corrupt
    detail = f"주력 {gem.get('name', '?')}: 입력 기본 {level}, 타락 추가 {corrupt}. {supply_note}. "
    if not measurement or measurement.get("build_spec") != build_spec:
        return AxisStatus(
            "gem_level",
            "젬 레벨",
            "unmeasured",
            detail + "동일 스펙의 오라클 GemLevel 미제공 — "
            "기본 레벨만으로 장비 채택·미사용을 단정하지 않는다",
        )
    stats = measurement.get("stats")
    effective = stats.get("GemLevel") if isinstance(stats, Mapping) else None
    if (
        isinstance(effective, bool)
        or not isinstance(effective, int | float)
        or not math.isfinite(effective)
        or effective <= 0
    ):
        return AxisStatus(
            "gem_level", "젬 레벨", "unmeasured", detail + "유효한 오라클 GemLevel이 없다"
        )
    detail += f"오라클 실효 {effective:g}, 입력 대비 {effective - input_level:+g}. "
    if effective > input_level:
        return AxisStatus(
            "gem_level",
            "젬 레벨",
            "covered",
            detail + "주력 추가 레벨 적용이 관측됐다. "
            "특정 장비별 인과·기여량은 이 값만으로 확정하지 않는다",
        )
    if effective < input_level:
        return AxisStatus(
            "gem_level",
            "젬 레벨",
            "unmeasured",
            detail + "입력보다 낮아 상한·감소·선택 문맥의 추가 확인이 필요하다",
        )
    return AxisStatus(
        "gem_level",
        "젬 레벨",
        "empty",
        detail + "현재 모델에서 주력의 순 추가 레벨이 관측되지 않았다 — "
        "비주력 공급·상쇄 여부나 장비 미사용을 단정하지 않는다",
    )


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
    gem_level_measurement: Mapping[str, Any] | None = None,
) -> AxesReport:
    """획득 공간의 축을 열거하고 각각 covered/empty/unmeasured로 판정한다.

    - `anointed_items`: 성유를 부여한 아이템 슬롯들 (스펙 텍스트로는 안 보일 수 있어
      호출자가 준다 — 안 주면 아이템 텍스트에서 `Allocates`를 찾아본다)
    - `quality_checked`: 젬 품질 축을 검토했는가 (설계 문서 기준 — 호출자 신고)
    - `slot_attack_deltas`: 슬롯별 공격 기여 실측 {슬롯: 델타}. **측정에는 PoB가
      필요해서** 스펙만으로는 못 낸다 — 안 주면 unmeasured로 낸다(없다고 단정하지
      않는다).
    - `gem_level_measurement`: {build_spec, stats} — 동일 입력의 compute_pob 결과.
      입력 기본레벨·실물 공급 후보·주력 실효레벨을 구분하며 장비별 인과는 추론하지 않는다.
    """
    axes: list[AxisStatus] = []
    items = _item_texts(build_spec)

    axes.append(_gem_level_axis(build_spec, gem_level_measurement))

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
                f"쓸 수 있고, 같은 스킬 젬을 직접 등록한 것과 중복해서 돈다**"
                f"(mechanic.item-granted-skills, #167)",
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
