"""engine/constraints — D27 제약 검사기 4종 (테스트 수치 = v6 설계 문서 실측).

근거 원문: artifacts/builds/20260731-ember-fusillade-설계v6/design.md (sha256 fc6090e9).
각 케이스의 기대값은 v6 문서의 표·수식에서 그대로 가져왔다 — 추측 수치 없음.
"""

from __future__ import annotations

import pytest

from pok.engine.constraints import (
    AnointPlan,
    Bundle,
    KbDefaults,
    ReservationEntry,
    SideEffect,
    SkillLinks,
    check_color_majority,
    check_exhaustion,
    check_point_budget,
    check_reservation,
    check_sustain,
    kb_defaults,
)

# ── KB 인용 상수 (태스크 #35 수록분) ─────────────────────────────────


@pytest.fixture(scope="module")
def defaults() -> KbDefaults:
    return kb_defaults()


def test_kb_상수는_정본에서_읽는다(defaults: KbDefaults) -> None:
    assert defaults.ascendancy_budget == 8  # mechanic.ascendancy-points
    assert defaults.max_supports_per_skill == 5  # mechanic.support-gem-slots
    assert defaults.low_life_threshold_pct == 35.0  # resource.life


# ── ① 포인트 예산 (v6 §1: 합 10 > 예산 8 → 분기 A/B 강제) ─────────────

_V6_BUNDLES = (
    Bundle("화염술사의 계약", 2, required=True),
    Bundle("변화된 살점→베이다트의 의지", 4, required=True),
    Bundle("웃는 번제", 2),
    Bundle("불꽃을 가져오는 자", 2),
)


def test_포인트_예산_v6_배타_분기(defaults: KbDefaults) -> None:
    report = check_point_budget(_V6_BUNDLES, budget=defaults.ascendancy_budget)
    assert not report.ok
    assert report.total_points == 10 and report.required_points == 6
    assert report.headroom == 2
    assert any("10 > 예산 8" in v for v in report.violations)
    # 배타 분기: 마지막 2포인트에서 웃는 번제 vs 불꽃을 가져오는 자 (극대 조합)
    assert set(report.branches) == {("웃는 번제",), ("불꽃을 가져오는 자",)}


def test_포인트_예산_안이면_통과() -> None:
    report = check_point_budget(_V6_BUNDLES[:3], budget=8)
    assert report.ok and report.total_points == 8
    assert report.branches == (("웃는 번제",),)


def test_필수_묶음만으로_예산_초과는_불가능_보고() -> None:
    report = check_point_budget(
        (Bundle("a", 5, required=True), Bundle("b", 4, required=True)), budget=8
    )
    assert not report.ok
    assert any("고정 조건 자체가 불가능" in v for v in report.violations)
    assert report.branches == ()


# ── ② 색상 장부 (v6 §7.3: 빨강 6/10 통과 → +1 통과 → +2 실패) ─────────

_V6_LINKS = (
    SkillLinks(
        "불씨 일제 사격",
        (
            ("처형 III", "red"),
            ("화염 조율", "red"),
            ("조프의 장작", "red"),
            ("신중한 시전", "blue"),
            ("라키아타의 흐름", "green"),
        ),
    ),
    SkillLinks(
        "CoEA 구형 번개",
        (
            ("앗지리의 성찬식", "blue"),
            ("묵직함", "red"),
            ("울네톨의 포옹", "red"),
            ("방어구 파괴 III", "red"),
        ),
    ),
    SkillLinks("일반 CoC 혜성", (("냉기 숙련", "blue"),)),
    SkillLinks("무료 CoC 뇌우", ()),
)


def test_색상_장부_v6_기본_6_10_통과() -> None:
    report = check_color_majority(_V6_LINKS, "red")
    assert report.satisfied and report.ok
    assert report.total == 10 and dict(report.counts)["red"] == 6
    assert report.headroom_additions == 1  # 비빨강 1개까지 추가 가능 (6/11 = 54.5%)


def test_색상_장부_비빨강_2추가시_실패() -> None:
    extra = (
        *_V6_LINKS[:3],
        SkillLinks("무료 CoC 뇌우", (("과잉 II", "green"),)),
        SkillLinks("이동기", (("아무 파랑", "blue"),)),
    )
    report = check_color_majority(extra, "red")
    assert not report.satisfied and not report.ok  # 6/12 = 50% — 절반 초과 아님
    assert report.total == 12
    assert report.deficit == 1  # 빨강 1개 보강하면 7/13 > 50%
    assert any("과반" in v for v in report.violations)


# ── ③ 점유 산수 (v6 §5.6: 효율 57% → 성찬식 42.04 + 베이다트 25 = 67.04) ──

_V6_RESERVES = (
    ReservationEntry("CoEA+앗지리의 성찬식", 66.0),
    ReservationEntry("베이다트의 의지", 25.0, fixed=True),
)


def test_점유_v6_효율57_잔여_32_96(defaults: KbDefaults) -> None:
    report = check_reservation(
        _V6_RESERVES, 57.0, low_life_threshold_pct=defaults.low_life_threshold_pct
    )
    assert report.ok
    assert dict(report.entries)["CoEA+앗지리의 성찬식"] == 42.04
    assert dict(report.entries)["베이다트의 의지"] == 25.0  # 고정 점유 — 효율 미적용
    assert report.total_reserved == 67.04
    assert report.remaining == 32.96
    assert report.low_life  # 게임 내 점유 정보창 성립 확인과 일치 (IN_GAME)
    assert report.max_efficiency_for_low_life_pct == 65.0  # v6 §5.7 경계와 일치


def test_점유_v6_효율16_잔여_18_10(defaults: KbDefaults) -> None:
    report = check_reservation(
        _V6_RESERVES, 16.0, low_life_threshold_pct=defaults.low_life_threshold_pct
    )
    assert dict(report.entries)["CoEA+앗지리의 성찬식"] == 56.9  # v6 §5.3 표
    assert report.total_reserved == 81.9 and report.remaining == 18.1


def test_점유_베이다트_없이는_로우라이프_아님(defaults: KbDefaults) -> None:
    report = check_reservation(
        (_V6_RESERVES[0],), 10.0, low_life_threshold_pct=defaults.low_life_threshold_pct
    )
    assert report.remaining == 40.0 and not report.low_life  # v6 §5.4


def test_점유_100_초과는_위반(defaults: KbDefaults) -> None:
    report = check_reservation(
        (*_V6_RESERVES, ReservationEntry("추가 점유", 40.0, fixed=True)),
        0.0,
        low_life_threshold_pct=defaults.low_life_threshold_pct,
    )
    assert not report.ok and any("총량 100" in v for v in report.violations)


# ── ③-b 정신력 축 (축별 점유 장부 — 같은 공식, pool만 다르다) ──────────


def test_점유_정신력_축_정액_계산() -> None:
    """실증(2026-08-04): 검사기가 생명력 %축 전용이라 정신력 정액 축을 못 다뤘다.
    수치는 KB 수록분 — CoC 100·존재감/격분/충전제어 각 30·신성 모독 저주당 60."""
    spirit = (
        ReservationEntry("일반 CoC", 100.0),
        ReservationEntry("압도적인 존재감", 30.0),
        ReservationEntry("전투 격분", 30.0),
        ReservationEntry("충전 제어", 30.0),
    )
    report = check_reservation(spirit, 0.0, pool=250.0)
    assert report.ok and report.total_reserved == 190.0 and report.remaining == 60.0
    assert report.low_life is None  # 생명력 전용 판정은 계산하지 않는다
    assert report.remaining_pct == 24.0  # 축이 달라도 같은 척도로 읽을 수 있다


def test_점유_정신력_축도_효율을_받는다() -> None:
    """신성 모독 5저주 300은 점유 효율의 영향을 받는다 (사용자 확인 2026-08-02)."""
    blasphemy = (ReservationEntry("신성 모독 5저주", 300.0),)
    report = check_reservation(blasphemy, 20.0, pool=500.0)
    assert report.total_reserved == 250.0  # 300 / 1.2
    assert report.remaining == 250.0


def test_점유_총량_초과는_축_무관_위반() -> None:
    over = (ReservationEntry("CoC", 100.0), ReservationEntry("CoEA", 100.0))
    report = check_reservation(over, 0.0, pool=150.0)
    assert not report.ok and any("총량 150" in v for v in report.violations)


def test_점유_총량_0이하는_거부() -> None:
    with pytest.raises(ValueError, match="pool"):
        check_reservation((ReservationEntry("x", 10.0),), 0.0, pool=0.0)


# ── ④ 자원 소진 (성유 1회성 + 보조 한도 5) ─────────────────────────────


def test_소진_성유_중복_배분은_위반(defaults: KbDefaults) -> None:
    report = check_exhaustion(
        _V6_LINKS,
        anoints=(AnointPlan("목걸이", existing="기존 성유", planned="불꽃과 하나 되기"),),
        max_supports_per_skill=defaults.max_supports_per_skill,
    )
    assert not report.ok
    assert any("성유 중복 배분" in v for v in report.violations)


def test_소진_보조_한도_5_초과는_위반(defaults: KbDefaults) -> None:
    six = SkillLinks("과적재", tuple((f"s{i}", "red") for i in range(6)))
    report = check_exhaustion((six,), max_supports_per_skill=defaults.max_supports_per_skill)
    assert not report.ok and any("한도 5" in v for v in report.violations)


def test_소진_v6_기본_장부는_통과(defaults: KbDefaults) -> None:
    report = check_exhaustion(
        _V6_LINKS,
        anoints=(AnointPlan("목걸이", existing="기존 성유", planned=None),),
        max_supports_per_skill=defaults.max_supports_per_skill,
    )
    assert report.ok
    assert dict((s, h) for s, h in report.slot_headroom)["불씨 일제 사격"] == 0  # 5/5


# ── ⑤ 지속 가능성 경계 (성립 질문의 산수 — 원본·경감·가용이 있으면 측정 전 계산) ──


def test_경계_경감_차이가_성립을_가른다() -> None:
    # 자해 원본 1,580(생명력 1,500+ES 80), 가용 = 로우라이프 잔여 33% = 495
    effect_75 = SideEffect("자해 폭발", 1580.0, mitigation_pct=75.0)
    effect_90 = SideEffect("자해 폭발", 1580.0, mitigation_pct=90.0)
    low = check_sustain((effect_75,), 495.0)
    high = check_sustain((effect_90,), 495.0)
    assert low.entries[0][1] == 395.0 and low.entries[0][2] == 79.8  # 가용의 79.8%
    assert high.entries[0][1] == 158.0 and high.entries[0][2] == 31.92
    assert low.ok and high.ok  # 즉사 경계는 아님 — 비율 판단은 호출자 몫 (AD-3)


def test_경계_즉사는_위반() -> None:
    report = check_sustain((SideEffect("자해 폭발", 1580.0, mitigation_pct=60.0),), 495.0)
    assert not report.ok  # 실효 632 ≥ 가용 495
    assert any("초과" in v for v in report.violations)


def test_경계_필요_경감_역산() -> None:
    report = check_sustain(
        (SideEffect("자해 폭발", 1580.0, mitigation_pct=75.0),),
        495.0,
        target_pool_ratio_pct=50.0,
    )
    name, target, need = report.required_mitigation[0]
    assert (name, target) == ("자해 폭발", 50.0)
    assert need == 84.34  # 1 - 495x0.5/1580 — 이 경감의 수급은 요구-수급 장부로


def test_경계_가용_0이하는_거부() -> None:
    import pytest as _pytest

    with _pytest.raises(ValueError):
        check_sustain((SideEffect("x", 100.0),), 0.0)


# ── ④-b 룬 소켓 축 (2026-08-05 실측 사고) ─────────────────────────────
#
# 한 빌드가 룬 16칸을 0칸 쓴 채 "제약 5종 통과"로 기록됐다 — 검사기가 룬을 자원
# 축으로 안 봤기 때문이다. **없는 축은 위반도 없다.** 나중에 채우자 3티어 전부
# DPS +37~47%가 나왔다. 미사용은 위반이 아니지만 **보이지 않으면 판단도 못 한다.**


def test_룬_소켓_충전율을_보고한다(defaults: KbDefaults) -> None:
    from pok.engine.constraints import SocketPlan

    report = check_exhaustion(
        _V6_LINKS[:1],
        max_supports_per_skill=defaults.max_supports_per_skill,
        sockets=(SocketPlan("무기", 3, 3), SocketPlan("몸통", 4, 2)),
    )
    assert report.ok  # 미사용은 위반이 아니다
    assert report.rune_fill_pct == 71.4  # 5/7
    assert any("몸통" in u and "2칸 미사용" in u for u in report.unused)


def test_전량_미사용은_총계로_한_번_더_드러낸다(defaults: KbDefaults) -> None:
    """개별 항목만 보면 놓치기 쉽다 — v1이 정확히 그렇게 지나갔다."""
    from pok.engine.constraints import SocketPlan

    report = check_exhaustion(
        _V6_LINKS[:1],
        max_supports_per_skill=defaults.max_supports_per_skill,
        sockets=(SocketPlan("무기", 3, 0), SocketPlan("몸통", 4, 0)),
    )
    assert report.rune_fill_pct == 0.0
    assert any("전부 비어 있다" in u for u in report.unused)
    assert report.ok  # 그래도 위반은 아니다 — 판단은 호출자 몫(AD-3)


def test_소켓_초과는_위반이다(defaults: KbDefaults) -> None:
    from pok.engine.constraints import SocketPlan

    report = check_exhaustion(
        _V6_LINKS[:1],
        max_supports_per_skill=defaults.max_supports_per_skill,
        sockets=(SocketPlan("무기", 3, 5),),
    )
    assert not report.ok
    assert any("소켓 3칸" in v for v in report.violations)


def test_소켓을_안_주면_기존_동작_그대로(defaults: KbDefaults) -> None:
    report = check_exhaustion(_V6_LINKS[:1], max_supports_per_skill=defaults.max_supports_per_skill)
    assert report.rune_sockets == () and report.rune_fill_pct == 0.0 and report.ok


# ── 색 원장은 **한 노드의 조건**이다 (백로그 #55, 2026-08-10) ──


def test_색_원장_위반은_무엇의_조건인지_말한다() -> None:
    """`satisfied: false`를 **빌드 위반**으로 읽어 섀시를 갈아엎을 뻔했다.

    과반이 사는 것은 성유 전용 노터블 하나의 면역뿐인데 리포트가 그 말을 안 했다.
    거짓 위반은 참 위반의 신호를 죽인다(§0 ⑤).
    """
    from pok.engine.constraints.colors import CONDITION_NODE

    report = check_color_majority(
        (SkillLinks("구형 번개", (("점화 III", "red"), ("조프의 장작", "red"))),), "blue"
    )
    assert not report.satisfied
    assert report.applies_to == CONDITION_NODE
    assert report.grants == "냉각 면역"
    text = " ".join(report.violations)
    assert CONDITION_NODE in text, "어느 노드의 조건인지 없으면 빌드 위반으로 읽힌다"
    assert "안 쓸 거면 위반이 아니다" in text
    assert "속성" in text, "보조 색과 캐릭터 속성 요구가 다른 축임을 말해야 한다"


def test_색은_KB에서_채운다() -> None:
    """색은 요구 속성에서 결정적으로 나온다 — 손으로 전사하면 틀린다."""
    report = check_color_majority(
        (SkillLinks("구형 번개", (("점화 III", ""), ("조프의 장작", ""), ("화염 조율", ""))),),
        "red",
    )
    assert report.satisfied, "KB가 셋 다 red라고 안다"
    assert dict(report.counts)["red"] == 3
    assert not report.color_mismatches


def test_선언한_색이_KB와_다르면_알린다() -> None:
    """틀린 색 하나가 과반 집계를 통째로 뒤집는다 — 감지되므로 도구가 말한다."""
    report = check_color_majority((SkillLinks("구형 번개", (("점화 III", "blue"),)),), "red")
    assert report.satisfied, "KB 값(red)으로 세야 한다"
    assert any("점화 III" in m and "KB" in m for m in report.color_mismatches)
