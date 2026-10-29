"""룬 소켓 최적화 — 표기·규칙·그리디 (백로그 #33).

룬은 이 프로젝트에서 **두 번** 통째로 빠졌다: 16칸 0% 사용으로 검사 5종을 통과했고
(나중에 채우자 DPS +37~47%), 21칸을 채우자 **IgniteDPS +69.6%**였다.
`check_constraints(exhaustion.sockets)`가 미사용을 **보고만** 하고 채워 주지 않아서다.
"""

from __future__ import annotations

from typing import Any

import pytest

from pok.engine.runes import (
    RuneOption,
    check_rune_rules,
    enumerate_slot_runes,
    needs_rune_declaration,
    optimize_runes,
    render_runed,
)

_BASE = "Rarity: RARE\nProbe\nAttuned Wand\nItem Level: 80"
SPEC: dict[str, Any] = {
    "class_name": "Sorceress",
    "ascendancy": "Sorceress1",
    "items": [
        {"slot": "Weapon 1", "text": _BASE + "\nCorrupted", "socket_sources": ["exceptional"]}
    ],
}


def test_render_emits_declaration_form_not_bare_rune_lines() -> None:
    """`{rune}` 줄만 적으면 **증폭이 조용히 빠진다** — 선언 3종이 다 있어야 한다.

    PoB는 `modLine.augmentType == "Rune"`일 때만 `socketedRuneEffectModifier`를 곱하고,
    그 표식은 `Sockets:`/`Rune:` 선언에서 온다(`Item.lua:2192-2209`).
    실측 2026-08-09(룬 효과 +200% 완드): 손기입 Δ+26.5 vs 선언 형식 Δ+79.4 — **3.00배**.
    그리고 `Rune:`만 있고 시드 줄이 없으면 **Δ 0**이다.
    """
    rune = RuneOption("modifier.x", "Greater Iron Rune", ("30% increased Spell Damage",))
    text = render_runed(_BASE, [rune, rune])
    lines = text.splitlines()
    assert "Sockets: S S" in lines, "소켓 선언이 없으면 augmentType이 안 붙는다"
    assert lines.count("Rune: Greater Iron Rune") == 2, "칸마다 선언이 있어야 한다"
    assert "{rune}30% increased Spell Damage" in lines, "시드 줄이 없으면 델타가 0이다"


def test_hand_written_rune_lines_are_flagged() -> None:
    """「`render_runed`를 쓰라」는 **문서 규율이라 안 지켜졌다** — 검사기가 잡는다(철칙 5).

    선언이 없으면 모드는 들어가고 증폭만 빠져 **오류 없이 3.00배** 적게 계산된다.
    """
    hand = f"{_BASE}\n{{rune}}30% increased Spell Damage"
    assert needs_rune_declaration(hand), "손기입이 통과하면 규율에 강제가 없는 것이다"
    assert "3.00배" in needs_rune_declaration(hand)[0]
    assert needs_rune_declaration(f"{_BASE}\nRune: Greater Iron Rune\n{{rune}}30% x"), (
        "`Sockets:` 없이 `Rune:`만으로는 augmentType이 안 붙는다"
    )


def test_declared_and_runeless_items_pass() -> None:
    """게이트는 **양방향**으로 잠근다 — 정상을 막으면 신호가 죽는다(§0 ⑤).

    `render_runed` 산출물과 룬이 없는 아이템은 아무 말도 하지 않아야 한다.
    """
    rune = RuneOption("modifier.x", "Greater Iron Rune", ("30% increased Spell Damage",))
    assert needs_rune_declaration(render_runed(_BASE, [rune, rune])) == ()
    assert needs_rune_declaration(_BASE) == ()


def test_render_replaces_existing_socket_line() -> None:
    """이미 소켓 줄이 있으면 갈아 끼운다 — PoB는 두 줄의 소켓을 합친다."""
    rune = RuneOption("modifier.x", "Greater Iron Rune", ("30% increased Spell Damage",))
    text = render_runed(f"{_BASE}\nSockets: S S S S S", [rune])
    assert text.count("Sockets:") == 1


@pytest.mark.parametrize("implicit_header", ["", "Implicits: 0\n"])
def test_rune_declarations_precede_modifiers(implicit_header: str) -> None:
    """Late declarations are retained as explicit mods and duplicated on save (#193)."""
    rune = RuneOption("new", "Perfect Iron Rune", ("20% increased Spell Damage",))
    given = f"{_BASE}\n{implicit_header}80% increased Spell Damage\nCorrupted"
    rendered = render_runed(given, [rune]).splitlines()
    assert rendered.index("Rune: Perfect Iron Rune") < rendered.index("80% increased Spell Damage")
    if implicit_header:
        assert rendered.index("Rune: Perfect Iron Rune") < rendered.index("Implicits: 0")
    assert render_runed("\n".join(rendered), []) == given


@pytest.mark.parametrize("rarity", ["NORMAL", "MAGIC"])
def test_two_line_identity_header_precedes_rune_declarations(rarity: str) -> None:
    rune = RuneOption("new", "Perfect Iron Rune", ("20% increased Spell Damage",))
    text = f"Rarity: {rarity}\nAttuned Wand\n80% increased Spell Damage"
    lines = render_runed(text, [rune]).splitlines()
    assert lines[:4] == [
        f"Rarity: {rarity}",
        "Attuned Wand",
        "Sockets: S",
        "Rune: Perfect Iron Rune",
    ]


def test_late_rune_declarations_are_rejected_even_without_effect_seeds() -> None:
    mod = "80% increased Spell Damage"
    late = f"{_BASE}\n{mod}\nSockets: S\nRune: Greater Iron Rune"
    assert "옵션 본문 뒤" in needs_rune_declaration(late, mod_lines=[mod])[0]
    early = f"{_BASE}\nSockets: S\nRune: Greater Iron Rune\n{mod}"
    assert needs_rune_declaration(early, mod_lines=[mod]) == ()


def test_prose_mentioning_runes_is_not_a_late_declaration() -> None:
    mods = ["80% increased Spell Damage", "Socketed Runes have increased effect", "Some Rune: text"]
    assert needs_rune_declaration("\n".join([_BASE, *mods]), mod_lines=mods) == ()


@pytest.mark.parametrize(
    "identity,mod",
    [
        ("Rarity: RARE\nProbe\nAttuned Wand", "80% increased Spell Damage"),
        (
            "Rarity: UNIQUE\nThe Unborn Lich\nStellar Amulet",
            "70% increased Desecrated Modifier magnitudes",
        ),
    ],
)
def test_legality_attaches_late_declaration_gate_to_rare_and_unique(
    identity: str, mod: str
) -> None:
    from pok.common.paths import knowledge_dir
    from pok.engine.legality import ItemLegalityChecker

    checker = ItemLegalityChecker(knowledge_dir())
    head = f"{identity}\nItem Level: 82"
    declarations = "Sockets: S\nRune: Greater Iron Rune"
    invalid = checker.check(f"{head}\n{mod}\n{declarations}")
    assert not invalid.is_legal
    assert any("옵션 본문 뒤" in error for error in invalid.errors)
    valid = checker.check(f"{head}\n{declarations}\n{mod}")
    assert not any("옵션 본문 뒤" in error for error in valid.errors)


def test_late_declarations_fail_compute_validation_and_strict_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pok.engine.assemble as assembly
    from pok.mcp.tools.build import _items_legal
    from pok.pob.buildxml import BuildSpec, ItemSpec

    base = f"{_BASE}\n80% increased Spell Damage"
    late = base + "\nSockets: S\nRune: Greater Iron Rune\n{rune}30% increased Spell Damage"
    fixed = render_runed(
        base, [RuneOption("iron", "Greater Iron Rune", ("30% increased Spell Damage",))]
    )

    def reached_oracle(*args: object, **kwargs: object) -> None:
        raise RuntimeError("passed strict item validation")

    monkeypatch.setattr(assembly, "run_build", reached_oracle)
    for text, legal in ((late, False), (fixed, True)):
        item = {"slot": "Weapon 1", "text": text}
        assert _items_legal({"items": [item]})["items_legal"] is legal
        spec = BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            items=(ItemSpec(slot="Weapon 1", text=text),),
        )
        if legal:
            with pytest.raises(RuntimeError, match="passed strict item validation"):
                assembly.assemble(spec, "rune-layout-regression")
        else:
            with pytest.raises(assembly.IllegalBuildError, match="옵션 본문 뒤"):
                assembly.assemble(spec, "rune-layout-regression")


def test_render_replaces_old_rune_declarations_and_mods() -> None:
    old = RuneOption("old", "Greater Old Rune", ("old bonus",))
    new = RuneOption("new", "Perfect New Rune", ("new bonus",))
    base = _BASE + "\n200% increased effect of Socketed Runes\n{crafted}ordinary modifier"
    previous = render_runed(base, [old, old])
    replaced = render_runed(previous, [new])
    assert replaced == render_runed(base, [new])
    assert "old bonus" not in replaced
    assert replaced.count("Rune:") == 1
    assert render_runed(previous, []) == base
    assert render_runed(replaced, [new]) == replaced


@pytest.mark.parametrize(
    "tag_prefix", ["{enchant}{rune}", "{rune}{enchant}", "{range:0.5}{RUNE}{enchant}"]
)
def test_native_tagged_runes_are_replaced_without_consuming_other_implicits(
    tag_prefix: str,
) -> None:
    native = (
        f"{_BASE}\nSockets: S S\nRune: Greater Old Rune\nRune: Greater Old Rune"
        f"\nImplicits: 4\n{tag_prefix}old first bonus\n{{enchant}}ordinary enchantment"
        "\n{enchant}{rune}old second bonus\nordinary implicit"
        "\n200% increased effect of Socketed Runes\nText mentioning {rune} later"
    )
    clean = (
        f"{_BASE}\nImplicits: 2\n{{enchant}}ordinary enchantment\nordinary implicit"
        "\n200% increased effect of Socketed Runes\nText mentioning {rune} later"
    )
    rune = RuneOption("new", "Perfect New Rune", ("new bonus",))
    assert render_runed(native, []) == clean
    assert render_runed(native, [rune]) == render_runed(clean, [rune])
    assert render_runed(render_runed(native, [rune]), [rune]) == render_runed(clean, [rune])


def test_reoptimization_measures_runeless_baseline_and_replaces_existing_runes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    old = RuneOption("old", "Greater Old Rune", ("old bonus",))
    new = RuneOption("new", "Perfect New Rune", ("new bonus",))
    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", lambda *_: [new])
    spec = {
        **SPEC,
        "items": [
            {
                "slot": "Weapon 1",
                "text": render_runed(_BASE, [old, old]),
                "socket_sources": ["exceptional"],
            }
        ],
    }
    calls: list[str] = []

    def compute(candidate: dict[str, Any]) -> dict[str, float]:
        text = candidate["items"][0]["text"]
        calls.append(text)
        return {"CombinedDPS": 100 + 10 * text.count("{rune}")}

    fill = optimize_runes(spec, "Weapon 1", {"CombinedDPS": 1}, sockets=2, compute=compute)
    assert fill is not None
    assert calls[0] == _BASE
    assert all("Old Rune" not in text and "old bonus" not in text for text in calls)
    assert fill.text == render_runed(_BASE, [new, new])
    assert fill.delta == {"CombinedDPS": 20}
    assert calls[-1] == fill.text


def test_rune_rules_match_user_confirmed_constraints() -> None:
    """유산 1개 · 고유명 같은 이름 1개 · 일반은 중복 가능 (사용자 확인 2026-08-09)."""
    legacy_a = RuneOption("a", "Legacy of Cursecarver", ("x",))
    legacy_b = RuneOption("b", "Legacy of Adonia's Ego", ("y",))
    named = RuneOption("c", "Fenumus' Rune of Agony", ("z",))
    generic = RuneOption("d", "Greater Iron Rune", ("w",))

    assert check_rune_rules([legacy_a]) == ()
    assert check_rune_rules([legacy_a, legacy_b]), "유산은 전 장비 통틀어 1개"
    assert check_rune_rules([named, named]), "고유명은 같은 이름 1개"
    assert check_rune_rules([named, generic]) == (), "다른 이름끼리는 병용 가능"
    assert check_rune_rules([generic, generic, generic]) == (), "일반은 중복 가능"


def test_enumeration_drops_bonded_lines() -> None:
    """`Bonded:`는 샤먼 전용 조건부인데 PoB가 조건을 안 본다 — 시드로 쓰면 과대 계상."""
    options = enumerate_slot_runes("Attuned Wand")
    assert options, "완드에 붙는 룬이 있어야 한다"
    assert not any(line.startswith("Bonded:") for o in options for line in o.lines)


def test_greedy_respects_sockets_and_rules() -> None:
    """칸 수를 넘지 않고, 규칙을 어기는 조합은 고르지 않는다 (가짜 오라클)."""

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        text = "\n".join(str(i.get("text", "")) for i in spec.get("items") or [])
        # 룬 줄 하나당 +10 — 많이 박을수록 좋다고 말해 칸 한도를 시험한다
        return {"CombinedDPS": 100.0 + 10.0 * text.count("{rune}")}

    fill = optimize_runes(SPEC, "Weapon 1", {"CombinedDPS": 1.0}, sockets=2, compute=compute)
    assert fill is not None
    assert len(fill.chosen) == 2, "소켓 수를 넘지 않는다"
    assert check_rune_rules(fill.chosen) == (), "채택 조합은 규칙을 지켜야 한다"
    assert fill.text.count("Rune: ") == 2
    # 단독 실측은 **전량** 남는다 — "이 부위엔 쓸 룬이 없다"도 근거가 된다
    assert len(fill.measured) == len(enumerate_slot_runes("Attuned Wand"))


def test_no_sockets_means_no_fill() -> None:
    """칸이 없으면 아무것도 만들지 않는다 — 없는 것을 채웠다고 말하지 않는다."""
    assert optimize_runes(SPEC, "Weapon 1", {"CombinedDPS": 1.0}, sockets=0) is None


def test_best_generic_is_reused_before_lower_scoring_distinct_runes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A legal duplicate must compete with lesser distinct choices for every socket."""
    options = [
        RuneOption("best", "Perfect Alpha Rune", ("alpha",)),
        RuneOption("lesser", "Greater Alpha Rune", ("lesser",)),
        RuneOption("named", "Named Rune", ("named",)),
    ]
    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", lambda *_: options)
    calls: list[str] = []

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        text = spec["items"][0]["text"]
        calls.append(text)
        return {
            "CombinedDPS": 100.0
            + sum(
                text.splitlines().count("Rune: " + rune.name) * value
                for rune, value in zip(options, (10, 7, 8), strict=True)
            )
        }

    fill = optimize_runes(SPEC, "Weapon 1", {"CombinedDPS": 1}, sockets=3, compute=compute)
    assert fill is not None
    assert [r.label for r in fill.chosen] == ["best", "best", "best"]
    assert fill.delta == {"CombinedDPS": 30.0}
    assert len(fill.measured) == 3
    assert [step["marginal_delta"]["CombinedDPS"] for step in fill.selection_steps] == [10] * 3
    assert calls[-1] == fill.text, "The exact returned text must be recomputed last."


def test_each_socket_uses_actual_marginal_gain_after_a_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    options = [
        RuneOption("capped", "Perfect Capped Rune", ("capped",)),
        RuneOption("uncapped", "Greater Uncapped Rune", ("uncapped",)),
    ]
    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", lambda *_: options)

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        lines = spec["items"][0]["text"].splitlines()
        return {
            "CombinedDPS": (
                100.0
                + min(1, lines.count("Rune: Perfect Capped Rune")) * 10
                + lines.count("Rune: Greater Uncapped Rune") * 7
            )
        }

    fill = optimize_runes(SPEC, "Weapon 1", {"CombinedDPS": 1}, sockets=3, compute=compute)
    assert fill is not None
    assert [r.label for r in fill.chosen] == ["capped", "uncapped", "uncapped"]
    assert fill.delta == {"CombinedDPS": 24.0}
    assert [step["marginal_delta"]["CombinedDPS"] for step in fill.selection_steps] == [10, 7, 7]


@pytest.mark.parametrize("exclude_legacy", [False, True])
def test_reselection_preserves_named_and_legacy_limits_before_calculation(
    monkeypatch: pytest.MonkeyPatch,
    exclude_legacy: bool,
) -> None:
    options = [
        RuneOption("named", "Named Rune", ("named",)),
        RuneOption("legacy-a", "Legacy of A", ("a",)),
        RuneOption("legacy-b", "Legacy of B", ("b",)),
        RuneOption("generic", "Perfect Generic Rune", ("generic",)),
    ]
    monkeypatch.setattr("pok.engine.runes.enumerate_slot_runes", lambda *_: options)

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        lines = spec["items"][0]["text"].splitlines()
        assert lines.count("Rune: Named Rune") <= 1
        assert sum(line.startswith("Rune: Legacy of ") for line in lines) <= 1
        if exclude_legacy:
            assert not any(line.startswith("Rune: Legacy of ") for line in lines)
        return {
            "CombinedDPS": 100.0
            + sum(
                lines.count("Rune: " + rune.name) * value
                for rune, value in zip(options, (12, 11, 10, 5), strict=True)
            )
        }

    fill = optimize_runes(
        {
            "items": [
                {
                    "slot": "Body Armour",
                    "text": "Rarity: UNIQUE\nMorior Invictus\nGrand Regalia\nCorrupted",
                }
            ]
        },
        "Body Armour",
        {"CombinedDPS": 1},
        sockets=5,
        compute=compute,
        exclude_legacy=exclude_legacy,
    )
    assert fill is not None
    expected = ["named"] + ([] if exclude_legacy else ["legacy-a"])
    expected += ["generic"] * (5 - len(expected))
    assert [r.label for r in fill.chosen] == expected
    assert check_rune_rules(fill.chosen) == ()


def test_조건부_줄을_버리지_않고_갈라서_낸다() -> None:
    """`Bonded:`를 조용히 버리면 「없다」와 「조건부다」가 구별되지 않는다 (#112 · AD-8).

    실측 2026-08-25: 룬 287건 중 **227건 · 487줄**이 그렇게 사라지고 있었다.
    시드에는 여전히 `lines`만 쓴다 — 바뀐 것은 **조건부 줄을 노출한다**는 것이다.
    """
    opts = enumerate_slot_runes("Felled Greatclub")
    assert opts, "철퇴 룬 후보가 있어야 한다"
    with_bonded = [o for o in opts if o.bonded_lines]
    assert with_bonded, "조건부 줄을 가진 룬이 실재한다"
    for o in with_bonded:
        assert all(ln.startswith("Bonded:") for ln in o.bonded_lines)
        assert not any(ln.startswith("Bonded:") for ln in o.lines), "시드에는 안 섞인다"


def test_조건이_없는_줄은_그대로_시드다() -> None:
    """⛔ 반대 방향 — 조건부를 노출한다고 무조건부까지 흔들리면 안 된다."""
    opts = enumerate_slot_runes("Felled Greatclub")
    assert any(o.lines for o in opts), "조건 없는 줄이 그대로 있어야 한다"
