"""Unique innate text must not hide a separate corruption socket outcome."""

from __future__ import annotations

import pytest

from pok.engine.item_sockets import audit_item_sockets


@pytest.mark.parametrize(
    ("name", "base", "slot", "corruption", "innate"),
    [
        (
            "Ab Aeterno",
            "Grand Cuisses",
            "Boots",
            "4% increased Movement Speed",
            "20% increased Movement Speed",
        ),
        (
            "Apep's Supremacy",
            "Voodoo Focus",
            "Weapon 2",
            "20% increased Energy Shield",
            "150% increased Energy Shield",
        ),
    ],
    ids=["ab-aeterno-movement-speed", "apeps-supremacy-energy-shield"],
)
@pytest.mark.parametrize("tag", ["{enchant}", ""], ids=["enchant-tag", "implicit-without-tag"])
@pytest.mark.parametrize("sockets", [2, 3], ids=["two-sockets-fit", "third-socket-conflicts"])
def test_unique_explicit_with_same_words_does_not_erase_implicit_corruption(
    name: str, base: str, slot: str, corruption: str, innate: str, tag: str, sockets: int
) -> None:
    # The unique's innate explicit and the corruption share their normalised
    # words, but live in different layers and have different permitted rolls.
    # Normal 1 + exceptional 1 is already paid for; the corruption enchantment
    # consumes the only Vaal outcome, so it cannot also supply socket number 3.
    text = "\n".join(
        [
            "Rarity: UNIQUE",
            name,
            base,
            "Sockets: " + " ".join(["S"] * sockets),
            "Implicits: 1",
            tag + corruption,
            innate,
            "Corrupted",
        ]
    )
    report = audit_item_sockets(
        {"items": [{"slot": slot, "text": text, "socket_sources": ["exceptional"]}]}
    )
    assert len(report["items"]) == 1, report
    item = report["items"][0]
    assert len(item["corruption_mods"]) == 1, report
    assert item["corruption_outcome_limit"] == 1
    assert item["corruption_socket_allowance"] == 0
    assert item["budget"] == 2
    assert report["legal"] is (sockets == 2), report
    if sockets == 3:
        assert any("룬 홈 3칸" in problem for problem in report["problems"]), report


def test_runemastered_atziris_splendour_keeps_its_six_soul_core_sockets() -> None:
    cores = ["Atmohua", "Azcapa", "Cholotl", "Citaqualotl", "Jiquani", "Opiloti"]
    text = "\n".join(
        [
            "Rarity: UNIQUE",
            "Atziri's Splendour",
            "Runemastered Sacrificial Regalia",
            "Sockets: S S S S S S",
            *[f"Rune: Soul Core of {name}" for name in cores],
        ]
    )
    report = audit_item_sockets({"items": [{"slot": "Body Armour", "text": text}]})
    assert report["legal"] is True, report
    assert report["items"][0]["fixed_limit"] == 6
    assert report["items"][0]["allowed_augment_types"] == ["SoulCore"]


def test_runemastered_atziris_splendour_cannot_accept_runes_even_with_only_two_sockets() -> None:
    text = "\n".join(
        [
            "Rarity: UNIQUE",
            "Atziri's Splendour",
            "Runemastered Sacrificial Regalia",
            "Sockets: S S",
            "Rune: Adept Rune",
            "Rune: Body Rune",
        ]
    )
    report = audit_item_sockets({"items": [{"slot": "Body Armour", "text": text}]})
    assert report["legal"] is False, report
    assert report["items"][0]["fixed_limit"] == 6
    assert report["items"][0]["allowed_augment_types"] == ["SoulCore"]
    assert any("SoulCore" in problem for problem in report["problems"]), report


@pytest.mark.parametrize("base", ["Runemastered Sacrificial Mantle", "Adorned Wraps"])
def test_atziris_title_on_an_unrelated_known_base_does_not_grant_six_sockets(base: str) -> None:
    text = f"Rarity: UNIQUE\nAtziri's Splendour\n{base}\nSockets: S S S S S S"
    report = audit_item_sockets({"items": [{"slot": "Body Armour", "text": text}]})
    assert report["legal"] is False, report
    assert report["items"], "The control must use a known base, not fail at name parsing"
    assert report["items"][0]["fixed_limit"] == 0
