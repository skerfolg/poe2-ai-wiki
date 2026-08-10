"""조립 manifest — 대리 측정 주입의 계보와 함정 경고 (#3)."""

from __future__ import annotations


def test_rune_substitution_warns_about_lost_amplification() -> None:
    """주입 줄은 룬으로 인식되지 않아 증폭이 **안 곱해진다** (#3 확장).

    실측 2026-08-09(`Greater Body Rune` 2개 · 룬 효과 +200%):
    정본 표기 ES **+300** vs `substitutes` 주입 **+100** — 3배 과소다.
    문서 규율로 두면 안 지켜지므로 조립이 자동으로 붙인다(철칙 5).
    """
    from pok.engine.assemble import _rune_amplification_warning
    from pok.pob.buildxml import BuildSpec, ItemSpec

    runed = ItemSpec(
        slot="Weapon 1",
        text="Rarity: RARE\nProbe\nAttuned Wand\n200% increased effect of Socketed Runes",
        substitutes=("+50 to maximum Energy Shield",),
    )
    warning = _rune_amplification_warning(
        BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(runed,))
    )
    assert "안 곱해진다" in warning and "Weapon 1(+200%)" in warning

    # 게이트는 양방향 — 룬 효과가 없거나 주입이 없으면 아무 말도 하지 않는다
    plain = ItemSpec(slot="Weapon 1", text="Rarity: RARE\nProbe\nAttuned Wand",
                     substitutes=("+50 to maximum Energy Shield",))  # fmt: skip
    assert not _rune_amplification_warning(
        BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(plain,))
    )
    assert not _rune_amplification_warning(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            items=(ItemSpec(slot="Weapon 1", text=runed.text),),
        )
    )
