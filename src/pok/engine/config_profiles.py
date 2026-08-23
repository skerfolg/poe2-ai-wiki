"""측정 config 프로파일 — **원본을 기본으로, 가정은 명시할 때만** (2026-08-22).

## 기본값은 「빌드 원본 그대로」다

래더 복원본에는 **빌드 주인이 켜 둔 config가 그대로 실려 온다** — 실측: 기준 빌드에
quest 선택 8건(액트 보상: 저항 5%·능력치 5·호신부 슬롯 …)과 `conditionEnemyChilled`·
`conditionEnemyBleeding`이 이미 들어 있다. 그 사람이 자기 빌드 메커니즘에 맞게 켠
것이므로 **우리가 추측으로 덮을 이유가 없다.**

⛔ **상태이상 조건을 엔진이 일괄로 켜지 않는다**(사용자 정리 2026-08-22): 화염 주입
구형 번개 빌드는 점화를, 감전 빌드는 감전을 켜야 맞다 — 빌드 메커니즘에 달린
판단이라 엔진이 대신 못 한다. 일괄로 켜면 **그 상태이상을 못 거는 빌드의 수치가
부풀려진다**(실측: 뭉뚱그린 `ailment` 하나로 기준 빌드 DPS가 +97.6%였다).

## 그러면 프로파일은 왜 있나

「이 조건을 켜면 얼마나 달라지나」를 **명시적으로 물을 때**의 도구다. 반사실 측정의
기본 경로는 원본 config를 그대로 쓰고, 프로파일은 호출자가 의도적으로 얹는다.

조건을 **하나씩** 쪼개 둔 이유도 같다 — 뭉쳐 두면 어느 조건이 노드를 열었는지
측정이 말해 주지 않아 근거가 문구 추론에 기대게 된다.

## 액트 보상은 이미 처리된다

`data.questRewards`의 선택형 8건·고정형 21건은 PoB config로 들어오고 복원이 보존한다.
엔진이 따로 정할 것이 없다 — 확인만 하면 된다(`test_config_profiles`가 잠근다).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ConfigProfile:
    """측정 가정 하나 — 이름·근거·토글."""

    name: str
    why: str
    toggles: tuple[tuple[str, str | int | bool], ...]

    def apply(self, spec: Any) -> Any:
        """빌드의 **자기 config 위에** 얹는다 — 덮어쓰지 않는다.

        ⛔ 통째로 갈아 끼우면 빌드 작성자의 가정이 사라진다. 실측 2026-08-22:
        래더 블러드 메이지의 DPS가 1,362,791 → 1,293,578로 떨어졌다 — 프로파일
        효과가 아니라 **원본 config를 지운 손실**이다. 같은 키는 프로파일이 이긴다
        (그게 프로파일의 목적이므로).
        """
        merged: dict[str, str | int | bool] = dict(spec.config or ())
        merged.update(dict(self.toggles))
        return replace(spec, config=tuple(merged.items()))


# 기준선 — **원본 그대로**. 반사실 측정의 기본 경로가 이것이다.
BASELINE = ConfigProfile(
    name="baseline",
    why="빌드 원본 config 그대로 — 주인이 자기 메커니즘에 맞게 켜 둔 것을 존중한다",
    toggles=(),
)

# 보스전 — 단일 대상 딜 평가의 표준 상황. 상태이상과 달리 **빌드 메커니즘과 무관**하다.
BOSS = ConfigProfile(
    name="boss",
    why=(
        "보스전 — 적이 희귀/유니크. 단일 대상 딜 평가의 표준 상황이고, 상태이상과 달리 "
        "**빌드가 무엇을 하든 성립하는** 가정이다"
    ),
    toggles=(("enemyIsBoss", "Boss"), ("conditionEnemyRareOrUnique", True)),
)

# ── 상태이상 — **하나씩** 쪼갠다 ─────────────────────────────────────────
#
# ⛔ 뭉쳐 두면 어느 조건이 노드를 열었는지 측정이 말해 주지 않는다. 실측 2026-08-22:
#    감전·빙결·약점을 한 프로파일에 묶었더니 6건이 열렸는데 **어느 것 덕인지**는
#    노드 문구로 추론해야 했다 — 근거가 측정이 아니라 짐작이 된다.
# ⛔ 그리고 이것들은 **빌드가 실제로 거는지**에 달렸다. 호출자가 그 빌드를 알고
#    고를 때만 쓴다. 엔진이 기본으로 켜지 않는다.
SHOCKED = ConfigProfile(
    name="shocked",
    why="적이 감전 — 감전을 거는 빌드에서만 유효하다(번개 계열)",
    toggles=(("conditionEnemyShocked", True),),
)
FROZEN = ConfigProfile(
    name="frozen",
    why="적이 빙결 — 빙결을 거는 빌드에서만 유효하다(냉기 계열)",
    toggles=(("conditionEnemyFrozen", True),),
)
IGNITED = ConfigProfile(
    name="ignited",
    why="적이 점화 — 점화를 거는 빌드에서만 유효하다(화염 계열)",
    toggles=(("conditionEnemyIgnited", True),),
)
OPEN_WEAKNESS = ConfigProfile(
    name="open-weakness",
    why="적에게 약점 노출 — 약점을 여는 구성(몽크 콤보 계열)에서만 유효하다",
    toggles=(("conditionEnemyHasOpenWeakness", True),),
)

# ── 플레이어·적 **상태** — 프로파일로 충분하다 ────────────────────────────
#
# 노드가 만드는 것이 아니라 **상황**이다. 노드를 빼면 그 상황에 걸린 모드만 빠지므로
# 토글을 켜 두는 것만으로 델타가 잡힌다. (스택과 다르다 — `STACK_SOURCES` 참조.)
SPRINTING = ConfigProfile(
    name="sprinting",
    why="질주 중 — 주파·재위치 축을 재려면 켜야 한다. 질주는 노드가 아니라 플레이어 행동이다",
    toggles=(("conditionSprinting", True),),
)
OPEN_WEAKNESS_PRESENCE = ConfigProfile(
    name="open-weakness-presence",
    why=(
        "약점 드러난 적이 **발현 안에** 있다 — `open-weakness`(적 자신이 약점 노출)와 "
        "다른 토글이다(`conditionOpenWeaknessEnemyPresence`). 발현 반경 기재를 재려면 이쪽이다"
    ),
    toggles=(("conditionOpenWeaknessEnemyPresence", True),),
)
ALLIES = ConfigProfile(
    name="allies",
    why=(
        "인접 아군 1명 — **최소 가정**이다. 동료·토템·소환수 구성이면 호출자가 더 올린다. "
        "0이면 '접근' 계열 기재가 통째로 안 걸린다"
    ),
    toggles=(("multiplierNearbyAlly", 1),),
)

# 버프 스택 — PoB가 스택 수를 **사용자 입력**으로만 받으므로 안 넣으면 영원히 0이다.
STACKED = ConfigProfile(
    name="stacked",
    why=(
        "버프 스택 최대(Tailwind 10·Combo 10). PoB는 스택 수를 사용자 입력으로만 받는다. "
        "⛔ 이 프로파일만 켜면 델타는 **여전히 0이다** — `STACK_SOURCES` 결합이 함께 필요하다"
    ),
    toggles=(("multiplierTailwind", 10), ("multiplierCombo", 10)),
)

PROFILES: dict[str, ConfigProfile] = {
    p.name: p
    for p in (
        BASELINE,
        BOSS,
        SHOCKED,
        FROZEN,
        IGNITED,
        OPEN_WEAKNESS,
        OPEN_WEAKNESS_PRESENCE,
        SPRINTING,
        ALLIES,
        STACKED,
    )
}


# ── 스택은 프로파일만으로 **영원히 0이다** ────────────────────────────────
#
# PoB의 `BuildModList`는 config를 **`ifFlag`/`ifCond`와 무관하게** 적용한다
# (`Classes/ConfigTab.lua:891-901` — 그 조건들은 UI 표시용이다). 그래서
# `multiplierTailwind=10`을 켜 두면 **노드를 빼도 승수가 그대로 남아** 델타가 0이다.
# 「켜도 0이니 모델 갭」이라고 닫았던 것이 사실은 이 구조였다(실측 2026-08-22).
#
# 상태(질주·약점)와 갈리는 지점이 여기다 — 상태는 **상황**이라 노드와 독립이지만,
# 스택은 **노드가 생산하는 것**이라 노드를 빼면 0이 되어야 한다.
#
# ⚠ **이건 가정이다** — 「그 빌드에서 이 노드가 그 스택의 유일한 원천이다」. 그래서
#    `stack_coupler`는 **프로파일이 넣은 키만** 0으로 만든다. 빌드가 원래 들고 온
#    승수는 건드리지 않는다 — 그건 우리 가정이 아니라 주인의 선언이기 때문이다.
STACK_SOURCES: dict[int, tuple[tuple[str, str], ...]] = {
    30: (
        (
            "multiplierTailwind",
            "Gathering Winds가 Tailwind를 준다 — 스택당 스킬속도 2%·이동 1%·회피 10%(최대 10)",
        ),
    ),
    61586: (
        (
            "multiplierCombo",
            "Martial Master가 모든 공격을 콤보 생성으로 바꾼다 — 콤보 스택의 원천",
        ),
    ),
}


def stack_coupler(profile: ConfigProfile) -> Callable[[Any, int], Any]:
    """노드를 뺄 때 **그 노드가 공급하던 스택도 0으로** 만드는 후크를 낸다 (#111).

    `evaluate_removals(on_drop=...)`에 넘긴다. 프로파일이 넣은 키만 건드리므로,
    빌드가 자기 config로 들고 온 승수는 그대로 남는다.
    """
    owned = {k for k, _ in profile.toggles}

    def couple(spec: Any, node_id: int) -> Any:
        keys = [k for k, _ in STACK_SOURCES.get(int(node_id), ()) if k in owned]
        if not keys:
            return spec
        merged = dict(spec.config or ())
        for k in keys:
            merged[k] = 0
        return replace(spec, config=tuple(merged.items()))

    return couple
