"""측정이 **갈리는지**를 도구가 말하는가 (#132).

PoB가 같은 XML에 두 값을 내는 것이 실측됐다(2026-08-28, Mac · 녹아내린 폭발):
10회에 `251030 x7 / 169413 x3`(비율 1.481). 회피책은 「N회 재서 최빈값을 쓰고 절대값
대신 같은 회차 안의 비율로 판단하라」였는데 **문서에만 있었다** — 그래서 한 세션이
같은 파일을 184,055 → 122,617로 두 번 보고하고 「데몬 상태 누적」이라는 틀린 진단까지
냈다(철칙 5: 규율은 강제 지점이 있어야 한다).

여기서 잠그는 것은 **판정의 모양**이다. PoB를 띄우는 쪽은 통합 시험 몫이다.
"""

from __future__ import annotations

from pok.pob.runner import StabilityReading


def _reading(values: list[float]) -> StabilityReading:
    from collections import Counter

    return StabilityReading(
        axis="CombinedDPS",
        values=tuple(values),
        counts=tuple(Counter(values).most_common()),
    )


def test_한_값이면_안정이다() -> None:
    r = _reading([100.0] * 6)
    assert r.stable is True
    assert r.mode == 100.0
    assert r.ratio == 1.0


def test_갈리면_최빈값과_비율을_낸다() -> None:
    """실측 분포 그대로 — 7:3으로 갈렸을 때 대표값은 다수 쪽이다."""
    r = _reading([251030.0] * 7 + [169413.0] * 3)
    assert r.stable is False
    assert r.mode == 251030.0
    assert round(r.ratio, 3) == 1.482


def test_표본이_비어도_안_터진다() -> None:
    """진단 도구가 예외를 내면 정작 이상한 상황에서 못 쓴다."""
    r = _reading([])
    assert r.stable is True and r.mode == 0.0 and r.ratio == 0.0
