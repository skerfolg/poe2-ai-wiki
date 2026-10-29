"""룬 홈의 획득 경로와 타락 결과 공존 — 사용자 v20 장갑 반례의 회귀."""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest

from pok.engine.item_sockets import audit_item_sockets
from pok.engine.runes import RuneFill, RuneOption, optimize_runes

_CORRUPTION = "{custom}{range:0.5}(15-25)% increased Evasion and Energy Shield"
_BASE = "Rarity: RARE\nEngineered Gloves\nAdorned Wraps\nItem Level: 80"
_V20_GLOVES = "\n".join(
    [
        "Rarity: RARE",
        "Engineered Gloves",
        "Adorned Wraps",
        "Evasion: 315",
        "Energy Shield: 102",
        "Crafted: true",
        "Prefix: {range:0.5}LocalBaseEvasionRatingAndEnergyShield4",
        "Prefix: {range:0.5}LocalIncreasedEvasionAndEnergyShield7",
        "Prefix: {range:0.5}AddedPhysicalDamage9",
        "Suffix: {range:0.5}AlloyDamagingAilmentDuration1",
        "Suffix: {range:0.5}CriticalMultiplier5",
        "Suffix: {range:0.5}FireResist8",
        "Quality: 20",
        "LevelReq: 65",
        "Implicits: 0",
        "+72 to Evasion Rating",
        "+24 to maximum Energy Shield",
        "96% increased Evasion and Energy Shield",
        "Adds 16 to 27 Physical Damage to Attacks",
        "32% increased Critical Damage Bonus",
        "+43% to Fire Resistance",
        "23% increased Duration of Damaging Ailments on Enemies",
        _CORRUPTION,
        "Corrupted",
        "Sockets: S S S",
        "Rune: Courtesan Mannan's Rune of Cruelty",
        "Rune: Idol of Sirrius",
        "Rune: Perfect Iron Rune",
        "{rune}20% increased Magnitude of Damaging Ailments you inflict",
        "{rune}8% increased Attack Speed",
        "{rune}20% increased Armour, Evasion and Energy Shield",
    ]
)


def _spec(text: str, *, exceptional: bool = False) -> dict[str, Any]:
    return {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "items": [
            {
                "slot": "Gloves",
                "text": text,
                "socket_sources": ["exceptional"] if exceptional else [],
            }
        ],
    }


def _gloves(sockets: int, *, corrupted: bool = False, modifier: bool = False) -> str:
    lines = [_BASE]
    if modifier:
        lines.append(_CORRUPTION)
    if corrupted:
        lines.append("Corrupted")
    lines.append("Sockets: " + " ".join(["S"] * sockets))
    return "\n".join(lines)


def test_v20_modifier_corruption_and_third_socket_do_not_share_one_outcome() -> None:
    report = audit_item_sockets(_spec(_V20_GLOVES))
    assert report["legal"] is False
    assert report["items"] and report["problems"]
    assert any("Gloves" in problem for problem in report["problems"])


@pytest.mark.parametrize(("corrupted", "modifier"), [(False, False), (True, False), (True, True)])
def test_exceptional_second_glove_socket_does_not_consume_a_corruption_outcome(
    corrupted: bool, modifier: bool
) -> None:
    report = audit_item_sockets(
        _spec(_gloves(2, corrupted=corrupted, modifier=modifier), exceptional=True)
    )
    assert report["legal"] is True, report
    assert report["problems"] == []


@pytest.mark.parametrize("exceptional", [False, True])
def test_third_glove_socket_needs_an_acquisition_route(exceptional: bool) -> None:
    report = audit_item_sockets(_spec(_gloves(3), exceptional=exceptional))
    assert report["legal"] is False, report
    assert report["problems"]


def test_corruption_can_supply_the_third_socket_without_a_modifier_outcome() -> None:
    report = audit_item_sockets(_spec(_gloves(3, corrupted=True), exceptional=True))
    assert report["legal"] is True, report
    assert report["problems"] == []


def test_corrupted_marker_does_not_grant_two_mutually_exclusive_outcomes() -> None:
    report = audit_item_sockets(_spec(_gloves(3, corrupted=True, modifier=True), exceptional=True))
    assert report["legal"] is False, report


def test_twice_corrupted_can_supply_a_second_outcome_but_not_a_second_extra_socket() -> None:
    three = _gloves(3, corrupted=True, modifier=True).replace(
        "\nCorrupted\n", "\nTwice Corrupted\n"
    )
    assert audit_item_sockets(_spec(three, exceptional=True))["legal"] is True
    four = three.replace("Sockets: S S S", "Sockets: S S S S")
    assert audit_item_sockets(_spec(four, exceptional=True))["legal"] is False


def test_ordinary_second_socket_is_not_inferred_from_pob_limit_or_item_rarity() -> None:
    assert audit_item_sockets(_spec(_gloves(1)))["legal"] is True
    assert audit_item_sockets(_spec(_gloves(2)))["legal"] is False
    assert audit_item_sockets(_spec(_gloves(2, corrupted=True)))["legal"] is True


def test_repeated_exceptional_source_does_not_grant_repeated_extra_sockets() -> None:
    spec = _spec(_gloves(3), exceptional=True)
    spec["items"][0]["socket_sources"] = ["exceptional", "exceptional"]
    assert audit_item_sockets(spec)["legal"] is False


def test_unverified_socket_source_cannot_supply_a_missing_socket() -> None:
    spec = _spec(_gloves(2))
    spec["items"][0]["socket_sources"] = ["unverified-extra-socket"]
    assert audit_item_sockets(spec)["legal"] is False


def test_handwritten_fixed_socket_modifier_is_not_a_real_unique_exception() -> None:
    text = _gloves(3) + "\nHas 3 Sockets"
    assert audit_item_sockets(_spec(text))["legal"] is False


@pytest.mark.parametrize(
    ("sockets", "exceptional", "modifier"), [(2, False, True), (3, True, True), (4, True, False)]
)
def test_runic_meridians_grant_coexists_with_the_distinct_corruption_route(
    sockets: int, exceptional: bool, modifier: bool
) -> None:
    spec = _spec(_gloves(sockets, corrupted=True, modifier=modifier), exceptional=exceptional)
    spec.update(class_name="Monk", ascendancy="Monk1", tree_nodes=[20437, 39552])
    report = audit_item_sockets(spec)
    assert report["legal"] is True, report
    assert report["items"][0]["tree_grant"] == 1


def test_another_ascendancys_runic_meridians_cannot_supply_gemling_sockets() -> None:
    spec = _spec(_gloves(3, corrupted=True, modifier=True), exceptional=True)
    spec["tree_nodes"] = [20437, 39552]
    report = audit_item_sockets(spec)
    assert report["legal"] is False, report
    assert report["items"][0]["tree_grant"] == 0


def test_atziris_splendour_fixed_six_sockets_are_not_reduced_to_the_base_allowance() -> None:
    text = "Rarity: UNIQUE\nAtziri's Splendour\nSacrificial Regalia\nSockets: S S S S S S"
    spec = {"items": [{"slot": "Body Armour", "text": text}]}
    report = audit_item_sockets(spec)
    assert report["legal"] is True, report
    assert report["items"][0]["fixed_limit"] == 6


def test_unique_name_alone_does_not_give_a_rare_item_the_fixed_socket_exception() -> None:
    text = "Rarity: RARE\nAtziri's Splendour\nSacrificial Regalia\nSockets: S S S S S S"
    report = audit_item_sockets({"items": [{"slot": "Body Armour", "text": text}]})
    assert report["legal"] is False, report
    assert report["items"][0]["fixed_limit"] == 0


def test_obtainable_unique_sockets_still_respect_the_native_editor_control_limit() -> None:
    text = "Rarity: UNIQUE\nMorior Invictus\nGrand Regalia\nCorrupted\nSockets: S S S S S S S"
    report = audit_item_sockets(
        {
            "class_name": "Monk",
            "ascendancy": "Monk1",
            "tree_nodes": [20437, 39552],
            "items": [{"slot": "Body Armour", "text": text}],
        }
    )
    assert report["legal"] is False, report
    assert any("PoB" in problem for problem in report["problems"])


@pytest.mark.parametrize(
    ("slot", "base", "ordinary"),
    [
        ("Helmet", "Ancestral Tiara", 1),
        ("Body Armour", "Altar Robe", 2),
        ("Gloves", "Adorned Wraps", 1),
        ("Boots", "Hunting Shoes", 1),
        ("Weapon 1", "Attuned Wand", 1),
        ("Weapon 1", "Felled Greatclub", 2),
    ],
)
def test_equipment_classes_separate_ordinary_exceptional_and_corruption_sockets(
    slot: str, base: str, ordinary: int
) -> None:
    def sample(sockets: int, *, exceptional: bool = False, corrupted: bool = False):
        text = f"Rarity: RARE\nAcquisition regression\n{base}\nSockets: "
        text += " ".join(["S"] * sockets)
        if corrupted:
            text += "\nCorrupted"
        return {
            "items": [
                {
                    "slot": slot,
                    "text": text,
                    "socket_sources": ["exceptional"] if exceptional else [],
                }
            ]
        }

    assert audit_item_sockets(sample(ordinary))["legal"] is True
    assert audit_item_sockets(sample(ordinary + 1))["legal"] is False
    assert audit_item_sockets(sample(ordinary + 1, exceptional=True))["legal"] is True
    assert (
        audit_item_sockets(sample(ordinary + 2, exceptional=True, corrupted=True))["legal"] is True
    )


@pytest.mark.parametrize(
    ("slot", "base", "ordinary", "grant"),
    [
        ("Helmet", "Ancestral Tiara", 1, 1),
        ("Body Armour", "Altar Robe", 2, 2),
        ("Gloves", "Adorned Wraps", 1, 1),
        ("Boots", "Hunting Shoes", 1, 1),
    ],
)
def test_runic_meridians_grants_the_actual_amount_to_each_armour_slot(
    slot: str, base: str, ordinary: int, grant: int
) -> None:
    text = f"Rarity: RARE\nRunic regression\n{base}\nSockets: "
    text += " ".join(["S"] * (ordinary + grant))
    spec = {
        "class_name": "Monk",
        "ascendancy": "Monk1",
        "tree_nodes": [20437, 39552],
        "items": [{"slot": slot, "text": text}],
    }
    report = audit_item_sockets(spec)
    assert report["legal"] is True, report
    assert report["items"][0]["tree_grant"] == grant


def test_pob_socket_limit_three_does_not_override_the_acquisition_check() -> None:
    observed = [
        {
            "id": "1",
            "slot": "Gloves",
            "name": "Engineered Gloves",
            "base": "Adorned Wraps",
            "rarity": "RARE",
            "sockets": 3,
            "limit": 3,
            "limitSource": "base",
            "grant": 0,
            "corrupted": True,
        }
    ]
    report = audit_item_sockets(_spec(_V20_GLOVES), observed=observed)
    assert report["legal"] is False, report


@pytest.mark.parametrize(
    "text",
    [_gloves(0), _gloves(0, corrupted=True, modifier=True), _V20_GLOVES],
    ids=["ordinary-base", "modifier-corruption", "original-v20"],
)
def test_optimizer_refuses_unobtainable_socket_budget_before_any_measurement(
    monkeypatch: pytest.MonkeyPatch, text: str
) -> None:
    option = RuneOption("rune.probe", "Perfect Iron Rune", ("20% increased Armour",))
    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", lambda *_: [option])
    calculate = Mock(side_effect=AssertionError("invalid socket budget reached the oracle"))
    with pytest.raises(ValueError):
        optimize_runes(_spec(text), "Gloves", {"Evasion": 1}, sockets=3, compute=calculate)
    calculate.assert_not_called()


@pytest.mark.parametrize(
    ("sockets", "corrupted", "exceptional"), [(1, False, False), (2, False, True), (3, True, True)]
)
def test_optimizer_retains_every_obtainable_socket(
    monkeypatch: pytest.MonkeyPatch, sockets: int, corrupted: bool, exceptional: bool
) -> None:
    option = RuneOption("rune.probe", "Perfect Iron Rune", ("20% increased Armour",))
    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", lambda *_: [option])

    def calculate(spec: dict[str, Any]) -> dict[str, float]:
        assert spec["items"][0].get("socket_sources", []) == (
            ["exceptional"] if exceptional else []
        )
        count = spec["items"][0]["text"].splitlines().count("Rune: Perfect Iron Rune")
        return {"Evasion": 100.0 + 10 * count}

    filled = optimize_runes(
        _spec(_gloves(0, corrupted=corrupted), exceptional=exceptional),
        "Gloves",
        {"Evasion": 1},
        sockets=sockets,
        compute=calculate,
    )
    assert filled is not None
    assert len(filled.chosen) == sockets
    assert filled.delta == {"Evasion": 10.0 * sockets}
    assert audit_item_sockets(_spec(filled.text, exceptional=exceptional))["legal"] is True


def test_public_rune_result_keeps_the_acquisition_source_in_its_receipt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pok.engine.provenance import derivation_context, stale_components
    from pok.mcp.tools.tree import optimize_runes as tool

    source = _spec(_gloves(0), exceptional=True)
    filled_text = _gloves(2)
    filled = RuneFill(slot="Gloves", chosen=(), text=filled_text, delta={}, measured=())
    monkeypatch.setattr("pok.engine.runes.optimize_runes", lambda *args, **kwargs: filled)
    output = tool(source, "Gloves", {"Evasion": 1}, sockets=2)
    final = _spec(filled_text, exceptional=True)
    final["derived_from"] = output["derived_from"]
    assert output["socket_sources"] == ["exceptional"]
    assert output["derived_from"]["runes"]["items_sig"] == derivation_context(final)["items_sig"]
    assert stale_components(final) == []


def test_replacing_the_item_does_not_transfer_its_exceptional_drop_source() -> None:
    from pok.engine.items import _replace_slot

    source = _spec(_gloves(2), exceptional=True)
    changed = _replace_slot(source, "Gloves", "Rarity: RARE\nDifferent item\nFists of Stone")
    assert not changed["items"][0].get("socket_sources")
    assert source["items"][0]["socket_sources"] == ["exceptional"]


def test_changed_socket_acquisition_invalidates_an_existing_tree_measurement_context() -> None:
    from pok.engine.provenance import stale_components, stamp

    source = _spec(_gloves(2), exceptional=True)
    source["derived_from"] = {"tree": stamp(source, "tree", tool="optimize_tree")}
    assert stale_components(source) == []
    source["items"][0]["socket_sources"] = []
    stale = stale_components(source)
    assert any(row["component"] == "tree" and "items:" in row["why"] for row in stale)


@pytest.mark.parametrize("declaration", ["Sockets: S\nSockets: S\nSockets: S", "Sockets: SSS"])
def test_all_native_socket_declarations_are_counted_before_corruption_validation(
    declaration: str,
) -> None:
    text = f"{_BASE}\n{declaration}\nImplicits: 0\n{_CORRUPTION}\nCorrupted"
    report = audit_item_sockets(_spec(text))
    assert report["items"][0]["sockets"] == 3, (
        "PoB accumulates every S character across declarations"
    )
    assert report["legal"] is False, report


@pytest.mark.parametrize(
    ("names", "legal"),
    [
        (["Bear Idol", "Idol of Eeshta"], False),
        (["Bear Idol", "Perfect Iron Rune"], True),
        (["Perfect Iron Rune", "Perfect Iron Rune"], True),
    ],
)
def test_runic_meridians_adds_rune_only_capacity(names: list[str], legal: bool) -> None:
    text = "Rarity: RARE\nRunic type regression\nAncestral Tiara\nSockets: S S\n"
    text += "\n".join(f"Rune: {name}" for name in names)
    spec = {
        "class_name": "Monk",
        "ascendancy": "Monk1",
        "tree_nodes": [20437, 39552],
        "items": [{"slot": "Helmet", "text": text}],
    }
    report = audit_item_sockets(spec)
    assert report["legal"] is legal, report
    if not legal:
        assert any("Rune 전용" in problem for problem in report["problems"]), report


@pytest.mark.parametrize(
    ("name", "base", "slot", "sockets", "allowed", "rejected"),
    [
        (
            "Atziri's Splendour",
            "Sacrificial Regalia",
            "Body Armour",
            6,
            "Soul Core of Jiquani",
            "Perfect Iron Rune",
        ),
        (
            "Atziri's Splendour",
            "Sacrificial Regalia",
            "Body Armour",
            6,
            "Soul Core of Jiquani",
            "Idol of Sirrius",
        ),
        (
            "Runeseeker's Call",
            "Runic Fork",
            "Weapon 1",
            5,
            "Perfect Iron Rune",
            "Soul Core of Jiquani",
        ),
        (
            "Runeseeker's Call",
            "Runic Fork",
            "Weapon 1",
            5,
            "Perfect Iron Rune",
            "Idol of Sirrius",
        ),
    ],
)
def test_unique_socket_types_use_actual_augment_types(
    name: str, base: str, slot: str, sockets: int, allowed: str, rejected: str
) -> None:
    text = f"Rarity: UNIQUE\n{name}\n{base}\nSockets: " + " ".join(["S"] * sockets)
    for augment, legal in ((allowed, True), (rejected, False)):
        spec = {"items": [{"slot": slot, "text": text + f"\nRune: {augment}"}]}
        report = audit_item_sockets(spec)
        assert report["legal"] is legal, report


def test_optimizer_does_not_fill_a_runic_meridians_socket_with_a_higher_scoring_idol(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = [
        RuneOption("idol", "Bear Idol", ("10% increased Area of Effect",), augment_type="Idol"),
        RuneOption(
            "idol2", "Idol of Eeshta", ("15% increased Cost Efficiency",), augment_type="Idol"
        ),
        RuneOption("rune", "Perfect Iron Rune", ("20% increased Armour",), augment_type="Rune"),
    ]
    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", lambda *_: options)
    source = {
        "class_name": "Monk",
        "ascendancy": "Monk1",
        "tree_nodes": [20437, 39552],
        "items": [
            {"slot": "Helmet", "text": "Rarity: RARE\nRunic type regression\nAncestral Tiara"}
        ],
    }

    def calculate(candidate: dict[str, Any]) -> dict[str, float]:
        lines = candidate["items"][0]["text"].splitlines()
        idols = lines.count("Rune: Bear Idol") + lines.count("Rune: Idol of Eeshta")
        runes = lines.count("Rune: Perfect Iron Rune")
        assert idols <= 1, "the Rune-only socket must not be measured with an Idol in it"
        return {"Evasion": 100 + 10 * idols + runes}

    filled = optimize_runes(source, "Helmet", {"Evasion": 1}, sockets=2, compute=calculate)
    assert filled is not None
    assert [rune.augment_type for rune in filled.chosen] == ["Idol", "Rune"]
    final = {**source, "items": [{"slot": "Helmet", "text": filled.text}]}
    assert audit_item_sockets(final)["legal"] is True


@pytest.mark.parametrize("rarity", ["NORMAL", "MAGIC"])
def test_optimizer_uses_the_audited_base_for_two_line_native_item_headers(
    monkeypatch: pytest.MonkeyPatch, rarity: str
) -> None:
    text = f"Rarity: {rarity}\nAdorned Wraps\nItem Level: 80"
    seen_bases: list[str] = []
    rune = RuneOption("rune", "Perfect Iron Rune", ("20% increased Armour",), augment_type="Rune")

    def enumerate_options(base: str, root: Any) -> list[RuneOption]:
        seen_bases.append(base)
        return [rune] if base == "Adorned Wraps" else []

    def calculate(candidate: dict[str, Any]) -> dict[str, float]:
        return {"Evasion": 100 + candidate["items"][0]["text"].count("Rune: Perfect Iron Rune")}

    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", enumerate_options)
    filled = optimize_runes(_spec(text), "Gloves", {"Evasion": 1}, sockets=1, compute=calculate)
    assert filled is not None
    assert seen_bases == ["Adorned Wraps"], "Item Level is not the base of a normal/magic item"
    assert len(filled.chosen) == 1


def test_assembly_rechecks_native_observed_socket_count_before_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pok.engine.assemble as assembly
    from pok.pob.buildxml import BuildSpec, ItemSpec
    from pok.pob.runner import PobResult

    observed = {
        "id": "1",
        "slot": "Gloves",
        "name": "Engineered Gloves",
        "base": "Adorned Wraps",
        "rarity": "RARE",
        "sockets": 3,
        "limit": 3,
        "limitSource": "base",
        "grant": 0,
        "corrupted": False,
        "unknownRunes": [],
    }
    native = PobResult({}, {"items": [observed]}, (), (), False)
    run = Mock(return_value=native)
    record = Mock(side_effect=AssertionError("a native socket-count mismatch was exported"))
    monkeypatch.setattr(assembly, "run_build", run)
    monkeypatch.setattr(assembly, "record_build", record)
    spec = BuildSpec(
        class_name="Mercenary",
        ascendancy="Mercenary3",
        items=(ItemSpec(slot="Gloves", text=_gloves(1)),),
    )
    with pytest.raises(assembly.IllegalBuildError, match="불일치"):
        assembly.assemble(spec, "socket-count-mismatch")
    run.assert_called_once()
    record.assert_not_called()
