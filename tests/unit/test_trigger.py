"""B-10 메타 젬 발동률 — PoB가 모델링하지 않는 축의 결정적 계산."""

from __future__ import annotations

import pytest

from pok.engine.trigger import Enemy, MetaGem, compute_trigger_rate, max_energy

CAST_ON_AILMENT = MetaGem(
    "Cast on Elemental Ailment",
    energy_per_power={"Freeze": 10.0, "Ignite": 1.0, "Shock": 1.0},
)


def test_unique_power_is_flat_not_multiplied() -> None:
    """유니크는 **배율이 아니라 고정 20**이다 — poe2db 실측."""
    assert Enemy("normal", 1.0).power == 1.0
    assert Enemy("magic", 1.0).power == 2.0
    assert Enemy("rare", 2.0).power == 10.0, "기본 2인 강한 몬스터가 Rare면 2x5"
    assert Enemy("unique", 1.0).power == 20.0
    assert Enemy("unique", 3.0).power == 20.0, "기본 Power와 무관하게 고정"


def test_max_energy_comes_from_socketed_cast_time() -> None:
    """`Has 10 maximum Energy per 0.1 seconds of base cast time of Socketed Spells`."""
    assert max_energy(CAST_ON_AILMENT, 0.6) == 60.0
    assert max_energy(CAST_ON_AILMENT, 0.1) == 10.0
    flat = MetaGem("Feral Invocation", {"Hit": 1.0}, max_energy_flat=500.0)
    assert max_energy(flat, 0.6) == 500.0, "고정값 젬은 시전시간과 무관"


def test_coefficient_differs_per_trigger_within_one_gem() -> None:
    """같은 젬 안에서도 사건마다 계수가 다르다 — 빙결 10, 점화·감전 1.

    외부 설계 문서(THOR)의 `3 x Power`를 그대로 믿었다면 전부 틀렸을 값이다.
    """
    kw = {"enemy": Enemy("rare"), "hits_per_second": 4.0, "socketed_cast_time_s": 0.6}
    freeze = compute_trigger_rate(CAST_ON_AILMENT, "Freeze", **kw)
    ignite = compute_trigger_rate(CAST_ON_AILMENT, "Ignite", **kw)
    assert freeze.energy_per_hit == 50.0 and ignite.energy_per_hit == 5.0
    assert freeze.triggers_per_second == pytest.approx(ignite.triggers_per_second * 10, rel=1e-3)


def test_energy_gain_increase_applies() -> None:
    """품질·Impetus(+40%) 같은 "increased Energy gained"."""
    boosted = MetaGem("x", {"Freeze": 10.0}, energy_gain_increase_pct=40.0)
    base = compute_trigger_rate(
        CAST_ON_AILMENT, "Freeze", hits_per_second=4.0, socketed_cast_time_s=0.6
    )
    fast = compute_trigger_rate(boosted, "Freeze", hits_per_second=4.0, socketed_cast_time_s=0.6)
    assert fast.energy_per_hit == pytest.approx(base.energy_per_hit * 1.4)


def test_unsupported_trigger_says_why_instead_of_guessing() -> None:
    """계산 못 하는 것을 계산한 척하지 않는다 — 형태가 6종이라 Power형만 다룬다."""
    with pytest.raises(ValueError, match="Freeze, Ignite, Shock"):
        compute_trigger_rate(
            CAST_ON_AILMENT, "Block", hits_per_second=4.0, socketed_cast_time_s=0.6
        )


def test_estimate_assumption_is_carried_into_the_result() -> None:
    """Power 등급은 예상치다 — 그 가정이 결과에 실려 나가야 소비자가 안다."""
    normal = compute_trigger_rate(
        CAST_ON_AILMENT, "Freeze", hits_per_second=4.0, socketed_cast_time_s=0.6
    )
    assert any("예상치" in a for a in normal.assumptions)
    # 유니크는 고정값이라 등급 가정이 끼지 않는다
    unique = compute_trigger_rate(
        CAST_ON_AILMENT,
        "Freeze",
        enemy=Enemy("unique"),
        hits_per_second=4.0,
        socketed_cast_time_s=0.6,
    )
    assert not any("예상치" in a for a in unique.assumptions)


def test_threshold_scaled_triggers_are_read_from_the_gem_text() -> None:
    """한계치 비례 항은 **원문에서 읽는다** — 손으로 적으면 패치에 안 따라온다 (#43).

    ⚠ 같은 젬 안에서도 트리거마다 다르다: CoEA는 **Ignite에만** 붙고 Freeze·Shock엔
    없다. 젬 단위로 뭉뚱그리면 잴 수 있는 것까지 못 재게 된다(§0 ⑤).
    """
    from pok.engine.trigger import threshold_scaled_triggers

    coea = [
        "Gains 10 Energy per Power of enemies you Freeze with",
        "Hits from Skills",
        "Gains 1 Energy per Power of enemies you Ignite with Hits from Skills, modified by "
        "the percentage of the enemy's Ailment Threshold the Ignite",
        "Gains 1 Energy per Power of enemies you Shock with",
    ]
    assert threshold_scaled_triggers(coea) == frozenset({"Ignite"})
    assert threshold_scaled_triggers(["Maximum Energy is 500"]) == frozenset()


def test_threshold_scaled_trigger_refuses_instead_of_answering_wrong() -> None:
    """지배 항을 빼고 계산하면 **방향이 반대**다 — 틀린 수 대신 사유를 낸다 (#43).

    실측 보고 2026-08-10: 현재 모델이 normal(Power 1)에서 33.3초/발동을 냈는데,
    한계치는 대략 대상 생명력의 절반이라 **약한 몬스터일수록 빠르다.** 그 표를
    읽으면 설계가 뒤집힌다 — 실제로 뒤집혔다.
    """
    import pytest

    from pok.engine.trigger import MetaGem, UnmeasurableTriggerError, compute_trigger_rate

    gem = MetaGem(
        name="CoEA",
        energy_per_power={"Ignite": 1.0, "Freeze": 10.0},
        threshold_scaled=frozenset({"Ignite"}),
    )
    with pytest.raises(UnmeasurableTriggerError, match="한계치"):
        compute_trigger_rate(gem, "Ignite", hits_per_second=3.0, socketed_cast_time_s=1.0)

    # 게이트는 양방향 — 절이 없는 트리거는 그대로 잰다
    rate = compute_trigger_rate(gem, "Freeze", hits_per_second=3.0, socketed_cast_time_s=1.0)
    assert rate.seconds_per_trigger > 0
