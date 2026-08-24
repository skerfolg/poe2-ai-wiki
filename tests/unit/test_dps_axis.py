"""`CombinedDPS`를 언제 믿으면 안 되는가 (#113).

`Modules/CalcOffence.lua:6136`이 밑값을 `showAverage`에 따라 고른다 — 참이면
`AverageDamage`(1회 평균 피해)라 **속도 배수가 빠진다**. 실측: 공격 속도 접미 28%를
빼도 `CombinedDPS` Δ0, 평타x속도는 -9.7%.

⚠ 이 플래그는 스킬 **피해 모델**의 결함 표지가 아니다 — `TotalDPS`는 정상이다.
BACKLOG §3이 그 오독을 뒤집었고, 여기서 재는 것은 축 선택 하나뿐이다.
"""

from __future__ import annotations

from pok.engine.dps_axis import COMBINED, HIT_DPS, axis_for, classify


def test_속도가_들어_있으면_기본_축을_쓴다() -> None:
    """가산분이 없으면 `CombinedDPS == TotalDPS`다 — 밑값이 TotalDPS였다는 증거."""
    stats = {"CombinedDPS": 83772.0, "TotalDPS": 83772.0, "AverageDamage": 134989.0}
    assert classify(stats) == "speed_included"
    assert axis_for(stats) == COMBINED


def test_속도가_빠졌으면_적중_딜_축으로_간다() -> None:
    """#113 실측 그대로 — `CombinedDPS`가 `AverageDamage`와 같고 `TotalDPS`와 다르다."""
    stats = {"CombinedDPS": 134989.0, "TotalDPS": 83772.0, "AverageDamage": 134989.0}
    assert classify(stats) == "speed_missing"
    assert axis_for(stats) == HIT_DPS


def test_드라이버_신고가_수치_추론을_이긴다() -> None:
    """`mainSkillShowsAverage`가 있으면 그것이 확실하다 (#113 · 프로토콜 판 2)."""
    ambiguous = {"CombinedDPS": 200.0, "TotalDPS": 100.0, "AverageDamage": 150.0}
    assert classify(ambiguous) == "unknown"  # 가산분이 있어 수치로는 못 가른다
    assert classify(ambiguous, {"mainSkillShowsAverage": 1}) == "speed_missing"
    assert classify(ambiguous, {"mainSkillShowsAverage": 0}) == "speed_included"


def test_모르면_모른다고_한다() -> None:
    """⛔ 가산분(DoT·상태이상)이 있으면 밑값을 되짚을 수 없다 — 확신을 지어내지 않는다.

    `unknown`을 `speed_included`로 뭉개면 **없는 확신**이 생긴다(BACKLOG 형태 ①).
    축은 기본값을 그대로 둬서 기존 동작이 바뀌지 않게 한다.
    """
    ambiguous = {"CombinedDPS": 200.0, "TotalDPS": 100.0, "AverageDamage": 150.0}
    assert classify(ambiguous) == "unknown"
    assert axis_for(ambiguous) == COMBINED


def test_축이_없으면_모른다() -> None:
    """옛 관측처럼 축이 덜 실린 행 — 없는 키를 0으로 읽어 판정하지 않는다(#109)."""
    assert classify({"CombinedDPS": 100.0}) == "unknown"
    assert axis_for({}) == COMBINED


def test_속도_배수가_1이면_무해하다() -> None:
    """셋이 전부 같으면 `speed_included`로 잡히는데, 그때는 곱할 것이 없어 결과가 같다."""
    stats = {"CombinedDPS": 500.0, "TotalDPS": 500.0, "AverageDamage": 500.0}
    assert axis_for(stats) == COMBINED


def test_집계가_속도없는_빌드의_축을_갈아_끼운다() -> None:
    """강제 지점은 **집계 한 곳**이다 (#113 · 철칙 5).

    소비처마다 축을 고르게 하면 안 고른 곳이 뚫린다(형태 ⑦ — 관문을 패턴마다 달면
    안 단 패턴이 뚫린다). 원시 스탯이 있는 곳은 집계뿐이므로 여기서 갈아 끼우고,
    키 이름은 `CombinedDPS`로 **유지**한다 — 바꾸면 소비처가 조용히 빈 축을 읽는다.
    """
    from pok.engine.counterfactual_aggregate import _swap_dps_axis

    speed_missing = {"CombinedDPS": 134989.0, "TotalDPS": 83772.0, "AverageDamage": 134989.0}
    swapped = _swap_dps_axis(speed_missing)
    assert swapped["CombinedDPS"] == 83772.0, "속도가 든 값으로 갈려야 한다"
    assert speed_missing["CombinedDPS"] == 134989.0, "원본을 건드리지 않는다"


def test_TotalDPS가_없는_옛_행은_손대지_않는다() -> None:
    """⛔ 없는 키를 0으로 바꿔 넣으면 「재서 0」과 「안 잼」이 섞인다 (#109)."""
    from pok.engine.counterfactual_aggregate import _swap_dps_axis

    old_row = {"CombinedDPS": 100.0, "AverageDamage": 100.0}
    assert _swap_dps_axis(old_row) is old_row
