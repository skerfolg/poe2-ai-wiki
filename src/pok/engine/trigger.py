"""메타 젬 발동률 계산 — 백로그 B-10.

PoB 0.5.4b `CalcTriggers.lua`에 **메타 젬 에너지 모델이 아예 없다**(configTable
핸들러 부재). 트리거 빌드의 핵심 지표를 오라클이 못 재서, 빌드 테스트 2회차에서
세션이 손계산했고 D28에 따라 충족이 아닌 **측정 큐**로 남겼다.

여기는 그 손계산을 결정적 연산으로 옮긴 것이다. **판단은 하지 않는다**(AD-3):
"발동률이 충분한가"는 목표 프로파일이 볼 일이고, 여기는 초당 몇 번인지만 낸다.

## 계산

    최종 Power   = 기본 Power x 희귀도 배율          (유니크는 고정 20)
    에너지/타격  = Power x 젬의 Power당 에너지 x (1 + 획득 증가)
    최대 에너지  = 10 x (소켓 스펠 기본 시전시간 합 / 0.1초)
    발동 간격    = 최대 에너지 / (에너지/타격 x 초당 타격)

입력은 전부 KB에서 온다 — `mechanic.monster-power`(Power·배율)와 젬 레코드의
`energy_per_power`·`max_energy_per_100ms`(B-9에서 poe2db 원문으로 수록).

## 다룰 수 있는 것과 없는 것

Power 기반 젬만 계산한다. 에너지 획득 형태가 6종이라(고정 `Block 25`·이동거리
`2/m`·소환수 Power·자원 `1/20 Mana` 등) 나머지는 `energy_stats` 원문을 읽어
사람·에이전트가 판단한다. **계산 못 하는 것을 계산한 척하지 않는 게 요점이다** —
`unsupported` 사유를 반드시 낸다.

⚠ Power 등급은 **예상치**다(KB `mechanic.monster-power.estimate_note`). poe2db는
"평균 1·강함 2~3·약함 0.5"라는 범위 서술만 주고 몬스터별 표는 공개돼 있지 않다.
그래서 결과에도 그 가정을 실어 보낸다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

# poe2db 실측 (KB mechanic.monster-power와 같은 값 — 엔진은 KB를 import하지 않는다)
RARITY_MULTIPLIER = {"normal": 1.0, "magic": 2.0, "rare": 5.0}
UNIQUE_POWER = 20.0
DEFAULT_BASE_POWER = 1.0  # "평균 몬스터" — 등급을 모를 때의 가정


@dataclass(frozen=True)
class Enemy:
    """대상 몬스터 — 발동률의 분자를 정하는 쪽."""

    rarity: str = "normal"  # normal|magic|rare|unique
    base_power: float = DEFAULT_BASE_POWER

    @property
    def power(self) -> float:
        """최종 Power. **유니크는 배율이 아니라 고정 20이다.**"""
        if self.rarity == "unique":
            return UNIQUE_POWER
        return self.base_power * RARITY_MULTIPLIER.get(self.rarity, 1.0)


@dataclass(frozen=True)
class MetaGem:
    """메타 젬 — KB 레코드의 `energy_per_power`·`max_energy_per_100ms`가 그대로 온다."""

    name: str
    energy_per_power: dict[str, float]  # {"Freeze": 10.0, "Ignite": 1.0}
    max_energy_per_100ms: float = 10.0
    max_energy_flat: float | None = None  # 최대 에너지가 고정인 젬 (Feral Invocation 500)
    energy_gain_increase_pct: float = 0.0  # 품질·Impetus 등 "increased Energy gained"
    # 한계치 비례 항이 붙는 트리거들 (백로그 #43). 젬 원문의
    # *"modified by the percentage of the enemy's Ailment Threshold the Hit will deal"* —
    # **이 절이 지배 항이다.** 한계치는 대략 대상 생명력의 절반이라 약한 몬스터일수록
    # 한 방이 한계치의 몇 배가 되어 에너지가 폭증한다.
    #
    # ⚠ 같은 젬 안에서도 트리거마다 다르다: CoEA는 **Ignite에만** 붙고 Freeze·Shock엔
    # 없다. 그래서 젬 단위가 아니라 **트리거 단위**로 들고 있어야 한다.
    threshold_scaled: frozenset[str] = frozenset()


_THRESHOLD_CLAUSE = re.compile(
    r"modified by the percentage of the enemy'?s Ailment Threshold", re.I
)
# 「Gains N Energy per Power of enemies you **<트리거>** …」 — 절이 어느 트리거 줄에
# 붙었는지 읽는다. 젬 단위로 뭉뚱그리면 CoEA에서 Freeze까지 못 재게 된다.
_ENERGY_LINE = re.compile(r"Gains\s+[\d.]+\s+Energy per Power of enemies you\s+(\w+)", re.I)


def threshold_scaled_triggers(stats: Sequence[str]) -> frozenset[str]:
    """KB 젬 원문에서 **한계치 비례 항이 붙은 트리거**를 읽는다 (#43).

    판정을 손으로 적지 않는다 — 젬 원문이 정본이고, 패치로 절이 붙거나 빠지면
    수집만 다시 하면 따라온다. 실측 2026-08-10: CoC는 `Critically`에, CoEA는
    **`Ignite`에만** 붙고 Freeze·Shock엔 없다.

    ⚠ 원문이 줄바꿈으로 잘려 들어온 레코드가 있다("…enemies you Freeze with" /
    "Hits from Skills"). 그래서 **줄을 이어 붙여** 훑는다 — 줄 단위로 보면 절이
    다음 줄에 있는 경우를 놓친다.
    """
    joined = " ".join(" ".join(str(s).split()) for s in stats)
    out: set[str] = set()
    for match in _ENERGY_LINE.finditer(joined):
        tail = joined[match.end() : match.end() + 200]
        # 다음 에너지 줄 전까지가 이 트리거의 서술이다
        nxt = _ENERGY_LINE.search(tail)
        segment = tail[: nxt.start()] if nxt else tail
        if _THRESHOLD_CLAUSE.search(segment):
            out.add(match.group(1))
    return frozenset(out)


class UnmeasurableTriggerError(ValueError):
    """이 트리거는 **우리가 못 잰다** — 틀린 수를 내는 대신 사유를 낸다 (#43).

    `ValueError`를 상속해 기존 호출자의 예외 처리가 그대로 듣는다(조용히 통과하지
    않는다). 다만 타입으로 갈 수 있어야 "못 잼"과 "잘못 부름"을 구분한다.
    """


@dataclass(frozen=True)
class TriggerRate:
    gem: str
    trigger: str  # 어느 사건으로 에너지를 얻는가 (Freeze·Ignite·…)
    enemy_power: float
    energy_per_hit: float
    max_energy: float
    hits_to_trigger: float
    seconds_per_trigger: float
    triggers_per_second: float
    assumptions: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.triggers_per_second > 0


def max_energy(gem: MetaGem, socketed_cast_time_s: float) -> float:
    """최대 에너지 — 소켓 스펠의 **기본 시전시간 합**으로 정해진다.

    원문: `Has 10 maximum Energy per 0.1 seconds of base cast time of Socketed Spells`.
    고정값을 가진 젬(`Maximum Energy is 500`)은 시전시간과 무관하다.
    """
    if gem.max_energy_flat is not None:
        return gem.max_energy_flat
    # 0.6 / 0.1 이 5.999…로 떨어져 최대 에너지가 59.99…가 된다 — 발동 타격 수가
    # 경계에서 한 번 어긋날 수 있어 여기서 정리한다
    return round(gem.max_energy_per_100ms * (socketed_cast_time_s / 0.1), 6)


def compute_trigger_rate(
    gem: MetaGem,
    trigger: str,
    *,
    enemy: Enemy | None = None,
    hits_per_second: float,
    socketed_cast_time_s: float,
) -> TriggerRate:
    """발동 간격·초당 발동 횟수. 충분한지는 판단하지 않는다(AD-3)."""
    target = enemy or Enemy()
    per_power = gem.energy_per_power.get(trigger)
    if per_power is None:
        known = ", ".join(sorted(gem.energy_per_power)) or "없음"
        raise ValueError(
            f"{gem.name}: '{trigger}'로는 에너지를 얻지 않는다 (가능: {known}). "
            f"Power 기반이 아닌 젬이면 KB 레코드의 energy_stats 원문을 읽어야 한다"
        )
    if hits_per_second <= 0 or socketed_cast_time_s <= 0:
        raise ValueError("hits_per_second와 socketed_cast_time_s는 0보다 커야 한다")

    # ⛔ 한계치 비례 항이 붙는 트리거는 **재지 않는다** (#43). 그 항이 지배적이라
    # 빼고 계산한 값은 틀린 정도가 아니라 **방향이 반대**다 — 실측 보고 2026-08-10:
    # 현재 모델이 normal(Power 1)에서 33.3초/발동을 냈는데, 약한 몬스터는 한 방이
    # 한계치의 몇 배라 실제로는 훨씬 **빠르다**. 그 표를 읽으면 설계가 뒤집힌다.
    #
    # 한계치는 우리가 모르는 값이다(대상 생명력의 함수). 모르는 것을 지어내는 대신
    # **못 잰다고 말한다** — 조용한 0의 반대 실수(조용한 오답)를 막는 자리다.
    if trigger in gem.threshold_scaled:
        raise UnmeasurableTriggerError(
            f"{gem.name}의 '{trigger}'는 **상태 이상 한계치 비례 항**이 붙는다 — "
            f'젬 원문: "modified by the percentage of the enemy\'s Ailment Threshold". '
            f"한계치는 대상 생명력의 함수라 우리가 모르고, 이 항이 **지배적**이라 "
            f"빼고 계산하면 방향이 반대로 나온다(실측: 약한 몬스터일수록 빨라지는데 "
            f"모델은 느려진다고 냈다). 인게임 실측이나 PoB 모델이 생기기 전에는 "
            f"이 트리거의 발동률을 근거로 쓰지 말 것"
        )
    energy_per_hit = target.power * per_power * (1 + gem.energy_gain_increase_pct / 100.0)
    cap = max_energy(gem, socketed_cast_time_s)
    hits = cap / energy_per_hit
    seconds = hits / hits_per_second

    assumptions = [
        f"대상 {target.rarity} · 기본 Power {target.base_power:g} → 최종 {target.power:g}",
        f"타격당 에너지 {energy_per_hit:g} = Power {target.power:g} x {per_power:g}"
        + (f" x 획득 +{gem.energy_gain_increase_pct:g}%" if gem.energy_gain_increase_pct else ""),
        f"최대 에너지 {cap:g}"
        + (
            " (젬 고정값)"
            if gem.max_energy_flat is not None
            else f" = {gem.max_energy_per_100ms:g} x ({socketed_cast_time_s:g}s / 0.1s)"
        ),
    ]
    if target.rarity != "unique":
        # 등급별 기본 Power는 범위 서술뿐이라 이 가정이 결과에 그대로 실린다
        assumptions.append(
            "⚠ 기본 Power는 **예상치** — poe2db는 '평균 1·강함 2~3·약함 0.5' 범위만 주고 "
            "몬스터별 표는 공개돼 있지 않다"
        )
    return TriggerRate(
        gem=gem.name,
        trigger=trigger,
        enemy_power=target.power,
        energy_per_hit=round(energy_per_hit, 3),
        max_energy=round(cap, 3),
        hits_to_trigger=round(hits, 3),
        seconds_per_trigger=round(seconds, 4),
        triggers_per_second=round(1 / seconds, 4) if seconds else 0.0,
        assumptions=tuple(assumptions),
    )
