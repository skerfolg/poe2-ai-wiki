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
