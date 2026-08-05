"""곱연산 축 장부 — "가산 한 항만 키우고 있지 않은가" (이관 건 2/2, 2026-08-05).

빌드의 파워는 **여러 인자의 곱**인데 파이프라인이 가산 항 하나만 부풀렸다.

    출혈 DPS = 명중피해 x 0.15 x (1 + Σ출혈강도) x Π(more) x 가중2배
    명중피해 = 기본피해 x (1 + Σ피해증가)        x Π(보조 more) x 치명타배율
                          ~~~~~~~~~~~~~~~~        ~~~~~~~~~~~~~~~~~~~~~~~~~
                          여기만 채웠다           여기는 1.0 근처로 방치

실측(빌드 세션 2026-08-05): 패시브 99포인트 + 가산 유니크가 낸 것보다 **곱연산 축
하나**(치명타 12%→94%)가 더 컸다(8.6배). 가산 항에 곱연산 기대를 걸면 "생명력을
올려 딜을 올린다"가 130만 생명력을 요구하는 무의미한 결론으로 간다.

방어도 같다. EHP는 풀 x 저항 x 방어도/회피 x 막기가 층으로 곱해지는데, "최대 생명력만
올린다"는 "피해 증가만 올린다"와 같은 실수다.

## 왜 보이지 않았나 — 네 번째 원인

PoB는 유효 빌드에서 **760종**을 낸다. 그런데 `DEFAULT_STATS`는 24종이었고 거기에
`CritEffect`도, 층별 경감률도 없었다. `optimize_tree`의 그리디 편향 이전에 **곱연산
축을 볼 창 자체가 닫혀 있었다.**

## 이 모듈은 드러내기만 한다 (사용자 결정 2026-08-05, AD-3)

"1.0인 인자를 먼저 채워라"는 **판단**이라 엔진에 넣지 않는다(철칙 3). 룬 소켓
선례가 그 방식으로 작동했다 — `unused`를 "위반이 아니다"라고 명시하고 드러내기만
했는데 세션이 16칸을 채웠다. 여기도 축별 현재 배수와 중립 근접 여부만 낸다.
"그럼 뭘 채울지"는 스킬·에이전트가 판단한다.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

# 중립에서 이만큼 안쪽이면 "사실상 미개발" — 실측 기준: CritEffect 1.09는 치명타
# 확률 9%짜리 기본 상태다(축을 키우면 2.0을 넘는다).
NEUTRAL_BAND = 0.15


@dataclass(frozen=True)
class MultiplierAxis:
    """곱연산 인자 하나 — 현재 배수와 중립값."""

    key: str
    label: str
    value: float
    neutral: float = 1.0
    source: str = ""  # 어느 PoB 스탯에서 왔는지 (재현·검증용)

    @property
    def undeveloped(self) -> bool:
        """중립 근처인가 — **위반이 아니라 신호다.**"""
        return self.value <= self.neutral * (1 + NEUTRAL_BAND)

    @property
    def penalised(self) -> bool:
        """중립보다 **나쁜가**. 미개발과 구분해야 신호가 정확하다 — 원소 저항 -50%는
        "아직 안 키웠다"가 아니라 피해를 1.5배 받고 있다는 적자다(실측 2026-08-05).
        """
        return self.value < self.neutral

    @property
    def state(self) -> str:
        if self.penalised:
            return "penalised"
        return "undeveloped" if self.undeveloped else "developed"

    @property
    def gain_if_doubled(self) -> float:
        """이 축을 2배로 키우면 전체가 몇 배 되나 — 한계 수익의 거친 지표.

        가산 항은 이미 큰 축에 더할수록 체감이 줄지만, 중립에 있는 곱연산 축은
        키우는 만큼 그대로 곱해진다. 그 비대칭을 한 숫자로 보이려는 것이다.
        """
        return round(2.0 if self.value <= 0 else (self.value * 2) / self.value, 3)


@dataclass(frozen=True)
class MultiplierLedger:
    axes: tuple[MultiplierAxis, ...]
    notes: tuple[str, ...]

    @property
    def undeveloped(self) -> tuple[MultiplierAxis, ...]:
        """중립 근처지만 손해는 아닌 축 — "여기 아직 안 열렸다"."""
        return tuple(a for a in self.axes if a.undeveloped and not a.penalised)

    @property
    def penalised(self) -> tuple[MultiplierAxis, ...]:
        """중립보다 나쁜 축 — 미개발이 아니라 **적자**다."""
        return tuple(a for a in self.axes if a.penalised)

    @property
    def product(self) -> float:
        """축들의 곱 — 가산 항을 뺀 "곱연산 총 배수"."""
        total = 1.0
        for axis in self.axes:
            total *= axis.value if axis.value > 0 else 1.0
        return round(total, 4)


def _res_multiplier(resist_pct: float) -> float:
    """저항 N% → 받는 피해 경감 배수. 75%면 4배 버틴다."""
    capped = min(resist_pct, 90.0)
    return round(100.0 / (100.0 - capped), 4) if capped < 100 else 10.0


def build_ledger(stats: Mapping[str, float]) -> MultiplierLedger:
    """PoB 스탯 → 곱연산 축 장부. **측정만 하고 순위나 지시는 내지 않는다**(AD-3).

    `stats`는 `compute_pob(..., ["*"])`의 반환이다 — 기본 24종으로는 이 축들이
    보이지 않으므로 전체를 넘겨야 한다.
    """
    axes: list[MultiplierAxis] = []
    notes: list[str] = []

    def get(key: str) -> float | None:
        value = stats.get(key)
        return float(value) if isinstance(value, int | float) else None

    # ── 공격 ────────────────────────────────────────────────────────────────
    crit = get("CritEffect")
    if crit is not None:
        axes.append(MultiplierAxis("crit", "치명타 실효 배수", round(crit, 4), 1.0, "CritEffect"))

    # ── 방어 ────────────────────────────────────────────────────────────────
    pool = (get("Life") or 0.0) + (get("EnergyShield") or 0.0)
    ehp = get("TotalEHP")
    if ehp is not None and pool > 0:
        # 풀 대비 EHP — 저항·방어도·회피·막기가 만드는 **총 배수**. 1.0이면
        # 층이 하나도 없다는 뜻이다("최대 생명력만 올린" 상태의 지표).
        axes.append(
            MultiplierAxis(
                "defence_layers",
                "방어 층 총 배수 (EHP / 생명력+ES)",
                round(ehp / pool, 4),
                1.0,
                "TotalEHP / (Life + EnergyShield)",
            )
        )

    resists = [get(f"{e}Resist") for e in ("Fire", "Cold", "Lightning")]
    known = [r for r in resists if r is not None]
    if known:
        worst = min(known)
        axes.append(
            MultiplierAxis(
                "elemental_resist",
                "원소 저항 경감 배수 (최저 속성 기준)",
                _res_multiplier(worst),
                1.0,
                "min(Fire|Cold|Lightning)Resist",
            )
        )
        if worst < 75.0:
            # 캡 미달은 곱연산 축이 통째로 덜 열린 것이다 — 사실만 적는다
            notes.append(
                f"최저 원소 저항 {worst:g}% (캡 75%) — 경감 배수 {_res_multiplier(worst)}x"
            )

    phys_reduction = get("PhysicalDamageReduction")
    if phys_reduction is not None:
        axes.append(
            MultiplierAxis(
                "physical_reduction",
                "물리 경감 배수 (방어도)",
                _res_multiplier(phys_reduction),
                1.0,
                "PhysicalDamageReduction",
            )
        )

    block = get("BlockChance")
    if block is not None:
        axes.append(
            MultiplierAxis(
                "block",
                "막기 배수",
                round(1.0 / (1.0 - min(block, 90.0) / 100.0), 4),
                1.0,
                "BlockChance",
            )
        )

    if not axes:
        notes.append(
            '곱연산 축을 하나도 읽지 못했다 — `compute_pob(..., stats=["*"])`로 '
            "전체 스탯을 넘겼는지 확인하라(기본 24종에는 이 축들이 없다)"
        )
    return MultiplierLedger(tuple(axes), tuple(notes))


def support_more_lines(gem_stats: Mapping[str, list[str]]) -> tuple[tuple[str, str], ...]:
    """소켓된 보조 젬의 `more` 문구를 모은다 — 곱연산 인자의 KB 쪽 절반.

    PoB 단일 스탯으로는 "보조 more 총합"이 나오지 않는다. 대신 젬 레코드의
    `stats`(2026-08-05 수록)에서 `more`가 든 줄을 뽑으면 무엇이 곱해지고 있는지
    열거할 수 있다. `increased`(가산)와 구분하는 게 요점이다.

    입력은 `{젬 id: data.stats}`이고, 반환은 `(젬 id, 문구)` 목록이다.
    """
    out: list[tuple[str, str]] = []
    for gem_id, lines in gem_stats.items():
        for line in lines:
            lowered = line.lower()
            if "more" in lowered and "increased" not in lowered:
                out.append((gem_id, line))
    return tuple(out)
