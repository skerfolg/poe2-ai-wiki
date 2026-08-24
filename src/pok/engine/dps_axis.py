"""딜을 어느 축에서 읽을 것인가 — `CombinedDPS`는 항상 옳지 않다 (#113).

`Modules/CalcOffence.lua:6136`이 밑값을 이렇게 고른다::

    local baseDPS = output[(skillData.showAverage and "AverageDamage") or "TotalDPS"]
    output.CombinedDPS = baseDPS

주력기에 `showAverage`가 서면 `CombinedDPS`의 밑값이 **1회 평균 피해**라 공격·시전
속도가 안 곱해진다. 실측: 공격 속도 접미 28%를 빼도 `CombinedDPS` Δ**0**인데
평타x속도는 **-9.7%**였다. 트리 최적화도 이 축으로 점수를 매기므로 **공격 속도
노드를 구조적으로 안 찍는다**(채택 35수 중 공격 속도 노터블 0건).

⚠ 이 플래그는 스킬 **피해 모델**의 결함 표지가 아니다 — `TotalDPS`(:4447 =
``Avg x (HitSpeed or Speed)``)는 정상이다. BACKLOG §3이 그 오독을 한 번 뒤집었고,
여기서 재는 것은 「`CombinedDPS`를 그대로 써도 되는가」 하나뿐이다.

**왜 수치로 판정하나** — 드라이버가 `mainSkillShowsAverage`를 싣게 했지만(#113·#119),
그 이전에 잰 관측에는 그 키가 없다. 그런데 #108로 **PoB가 낸 축 전부**를 담게 되어
`CombinedDPS`·`TotalDPS`·`AverageDamage`가 이미 행에 있다 — 옛 관측도 여기서 갈린다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

#: 속도가 곱해진 적중 딜. `showAverage` 빌드에서 `CombinedDPS` 대신 쓴다.
HIT_DPS = "TotalDPS"
#: PoB의 합산 딜(DoT·상태이상·임페일·미라주 가산 포함). 기본 축.
COMBINED = "CombinedDPS"

Verdict = Literal["speed_included", "speed_missing", "unknown"]


def classify(stats: Mapping[str, float], meta: Mapping[str, object] | None = None) -> Verdict:
    """이 관측의 `CombinedDPS`가 속도를 품고 있나.

    `meta`에 드라이버 신고(`mainSkillShowsAverage`)가 있으면 그것이 이긴다 — 수치
    추론보다 확실하다. 없으면 축 세 개로 가른다.

    ⛔ **모르면 `unknown`을 낸다.** `CombinedDPS`는 밑값에 DoT·상태이상 가산분이
    더해지므로, 가산분이 있으면 밑값이 무엇이었는지 되짚을 수 없다. 그 경우를
    `speed_included`로 뭉개면 **없는 확신**을 만든다(형태 ①).
    """
    if meta is not None:
        flag = meta.get("mainSkillShowsAverage")
        if isinstance(flag, int) and not isinstance(flag, bool):
            return "speed_missing" if flag == 1 else "speed_included"

    combined = stats.get(COMBINED)
    total = stats.get(HIT_DPS)
    average = stats.get("AverageDamage")
    if combined is None or total is None or average is None:
        return "unknown"
    if combined == total:
        # 밑값이 TotalDPS였고 가산분이 없다 — 속도가 들어 있다.
        # (total == average인 경우도 여기 걸리는데, 그때는 속도 배수가 1이라 무해하다.)
        return "speed_included"
    if combined == average:
        return "speed_missing"
    return "unknown"  # 가산분이 있어 밑값을 되짚을 수 없다


def axis_for(stats: Mapping[str, float], meta: Mapping[str, object] | None = None) -> str:
    """딜로 읽을 축 이름. `unknown`은 **기본 축을 그대로 둔다** — 판정은 호출자 몫이다.

    ⚠ `HIT_DPS`로 바뀌면 DoT·상태이상·임페일 가산분이 빠진다. 그건 `TotalDot` 등
    별도 축에 그대로 실려 있으니 **필요한 쪽이 더한다** — 여기서 합성하면 PoB
    재구현이 된다(AD-1).
    """
    return HIT_DPS if classify(stats, meta) == "speed_missing" else COMBINED
