"""조건 레버리지 — 같은 저울에서 재고, 사전 작업 의존도를 수치로 (이관 4 D1·D2).

## D1 — 앵커 비교는 같은 저울에서

빌드 세션이 앵커의 21,302,501과 우리 302,794를 나란히 놓고 **"70배 차이"**로 읽었다.
실제로는 앵커 쪽만 조건이 전부 켜진 상태였다. 같은 조건으로 맞추면:

    우리 빌드   조건 off 302,794   조건 on   412,098   → x1.36
    21M 앵커    조건 off 1,118,557 조건 on 21,302,501 → x19.0

**같은 저울에서는 3.7배**다. 이 절차 없이는 앵커 비교가 전부 오독이다.

## D2 — 그 비율 자체가 강건성 지표다

조건 ON/OFF 비율이 곧 **사전 작업 의존도**다. 실측: 21M 앵커 19.0배, 갈퀴질 창
2.1/1.88배, 우리 1.36배. 높을수록 실전에서 무너진다 — 사용자 판정:
*"한방 큰 데미지를 위해 사전 작업이 너무 많다. 이론상 가능해도 추구해서는 안 된다."*

목표 상태에 상한(예: ≤ 3배)을 걸 수 있도록 **재기만 한다**. 얼마가 적정인지는
판단이라 여기서 정하지 않는다(AD-3).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# 전투 중 "만족시켜야 켜지는" 것들. `buff`·`override` 같은 설정성 항목은 뺀다 —
# 그건 사전 작업이 아니라 빌드 구성이다.
CONDITIONAL_PREFIXES = ("condition", "enemyCondition", "multiplier")


def conditional_keys(config: Mapping[str, Any]) -> tuple[str, ...]:
    """이 빌드가 켜 둔 **조건성** config만."""
    return tuple(k for k in config if str(k).startswith(CONDITIONAL_PREFIXES))


@dataclass(frozen=True)
class LeverageReading:
    """한 빌드의 조건 on/off 실측."""

    label: str
    stat: str
    off: float
    on: float
    conditions: tuple[str, ...]

    @property
    def leverage(self) -> float:
        """조건이 만드는 배수 — 높을수록 사전 작업 의존이 크다."""
        return round(self.on / self.off, 3) if self.off else 0.0


@dataclass(frozen=True)
class LeverageComparison:
    """둘을 **같은 저울에서** 비교한 결과 (D1의 2x2)."""

    ours: LeverageReading
    other: LeverageReading

    @property
    def ratio_off(self) -> float:
        """조건 전부 끈 상태의 비 — 빌드 자체의 힘."""
        return round(self.other.off / self.ours.off, 3) if self.ours.off else 0.0

    @property
    def ratio_on(self) -> float:
        return round(self.other.on / self.ours.on, 3) if self.ours.on else 0.0

    @property
    def naive_ratio(self) -> float:
        """**틀린 읽기** — 상대의 조건 on을 우리 조건 off와 나눈 것.

        이 값을 결과에 함께 내는 이유는, 세션이 실제로 이 숫자를 보고 오판했기
        때문이다. 옆에 나란히 두면 무엇이 어긋났는지 바로 보인다.
        """
        return round(self.other.on / self.ours.off, 3) if self.ours.off else 0.0

    @property
    def notes(self) -> tuple[str, ...]:
        out = [
            f"같은 저울(조건 off): {self.ratio_off}배 · 조건 on끼리: {self.ratio_on}배",
            f"⚠ 상대 on ÷ 우리 off = {self.naive_ratio}배 — **이렇게 읽으면 안 된다** "
            f"(실측 2026-08-05에 세션이 이 값을 '70배 차이'로 보고했다)",
        ]
        gap = self.other.leverage / self.ours.leverage if self.ours.leverage else 0.0
        if gap >= 2:
            out.append(
                f"상대의 조건 레버리지가 {round(gap, 2)}배 크다 "
                f"({self.other.leverage}x vs {self.ours.leverage}x) — 그 빌드는 "
                f"사전 작업에 더 의존한다. 수치를 그대로 목표로 삼기 전에 볼 것"
            )
        return tuple(out)


def measure_leverage(
    build_spec: dict[str, Any],
    *,
    stat: str = "CombinedDPS",
    label: str = "",
    compute: Any = None,
) -> LeverageReading:
    """같은 빌드를 **조건 끄고/켜고** 두 번 재서 레버리지를 낸다.

    `compute`는 `(spec) -> {stat: value}` 함수다(주입 가능 — 테스트·대체 오라클용).
    기본은 `compute_pob`을 쓴다.
    """
    if compute is None:
        # **`mcp`를 import하지 않는다** — 의존 방향은 mcp → engine 단방향이다(§4).
        # 처음에 `mcp.tools.build.compute_pob`을 불렀다가 lint-imports가 잡았다.
        from pok.engine.compute import compute_pob as _compute
        from pok.pob.buildxml import spec_from_dict

        def compute(spec: dict[str, Any]) -> dict[str, float]:
            return dict(_compute(spec_from_dict(spec)).stats)

    config = dict(build_spec.get("config") or {})
    keys = conditional_keys(config)
    off_spec = {**build_spec, "config": {k: v for k, v in config.items() if k not in keys}}
    on_stats = compute(build_spec)
    off_stats = compute(off_spec)
    return LeverageReading(
        label=label or str(build_spec.get("class_name", "build")),
        stat=stat,
        off=float(off_stats.get(stat, 0.0)),
        on=float(on_stats.get(stat, 0.0)),
        conditions=keys,
    )


def compare_on_same_scale(
    ours: dict[str, Any],
    other: dict[str, Any],
    *,
    stat: str = "CombinedDPS",
    labels: Sequence[str] = ("ours", "anchor"),
    compute: Any = None,
) -> LeverageComparison:
    """2x2 교차 측정 — 우리와 상대를 **각각 조건 off/on 두 번씩** 잰다 (D1)."""
    return LeverageComparison(
        ours=measure_leverage(ours, stat=stat, label=labels[0], compute=compute),
        other=measure_leverage(other, stat=stat, label=labels[1], compute=compute),
    )


@dataclass(frozen=True)
class OperatingCost:
    """빌드를 **굴리는 데 드는 손품** — DPS·EHP 밖에 있던 축 (이관 4 D3).

    실측 2026-08-05: 21M 앵커는 적 상태 9종을 동시에 유지하며 **초당 0.3회**,
    다른 앵커는 **초당 0.1회**(10초에 한 번)다. 지금 도구로는 이런 빌드가
    "DPS 우수"로만 읽힌다. `BUILD_DESIGN` 헤더에 `운용 목표: 1버튼/2버튼` 칸이
    있는데 기계 검증이 없었다.

    여기서 내는 값은 `evaluate_objective`의 `measured`에 그대로 넣어 사전식 목표로
    쓴다 — 얼마가 적정인지는 판단이라 정하지 않는다(AD-3).
    """

    enemy_conditions: int  # 유지해야 할 적 상태 수
    self_conditions: int  # 유지해야 할 자기 버프·상태 수
    skill_groups: int  # 눌러야 하는 스킬 그룹 수
    hits_per_second: float  # 낮을수록 한 방 의존

    def as_measured(self) -> dict[str, float]:
        """목표 판정에 넣을 수 있는 형태."""
        return {
            "EnemyConditionsToMaintain": float(self.enemy_conditions),
            "SelfConditionsToMaintain": float(self.self_conditions),
            "SkillGroupCount": float(self.skill_groups),
            "HitsPerSecond": self.hits_per_second,
            "OperatingLoad": float(
                self.enemy_conditions + self.self_conditions + self.skill_groups
            ),
        }


def measure_operating_cost(
    build_spec: Mapping[str, Any], *, hits_per_second: float = 0.0
) -> OperatingCost:
    """스펙에서 운용 비용을 센다 — config의 조건 수와 스킬 그룹 수.

    `hits_per_second`는 PoB `Speed`에서 오지만, 빌드에 따라 주력기가 아닌 스킬의
    속도가 잡힐 수 있어 **호출자가 명시**한다(0이면 미측정으로 남는다).
    """
    config = dict(build_spec.get("config") or {})
    enemy = sum(1 for k in config if str(k).startswith(("enemyCondition", "conditionEnemy")))
    own = sum(
        1
        for k in config
        if str(k).startswith(CONDITIONAL_PREFIXES)
        and not str(k).startswith(("enemyCondition", "conditionEnemy"))
    )
    return OperatingCost(
        enemy_conditions=enemy,
        self_conditions=own,
        skill_groups=len(build_spec.get("skills") or []),
        hits_per_second=hits_per_second,
    )
