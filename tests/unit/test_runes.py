"""룬 소켓 최적화 — 표기·규칙·그리디 (백로그 #33).

룬은 이 프로젝트에서 **두 번** 통째로 빠졌다: 16칸 0% 사용으로 검사 5종을 통과했고
(나중에 채우자 DPS +37~47%), 21칸을 채우자 **IgniteDPS +69.6%**였다.
`check_constraints(exhaustion.sockets)`가 미사용을 **보고만** 하고 채워 주지 않아서다.
"""

from __future__ import annotations

from typing import Any

from pok.engine.runes import (
    RuneOption,
    check_rune_rules,
    enumerate_slot_runes,
    optimize_runes,
    render_runed,
)

_BASE = "Rarity: RARE\nProbe\nAttuned Wand\nItem Level: 80"
SPEC: dict[str, Any] = {
    "class_name": "Sorceress",
    "ascendancy": "Sorceress1",
    "items": [{"slot": "Weapon 1", "text": _BASE}],
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


def test_render_replaces_existing_socket_line() -> None:
    """이미 소켓 줄이 있으면 갈아 끼운다 — 두 줄이 남으면 PoB가 뒤엣것만 읽는다."""
    rune = RuneOption("modifier.x", "Greater Iron Rune", ("30% increased Spell Damage",))
    text = render_runed(f"{_BASE}\nSockets: S S S S S", [rune])
    assert text.count("Sockets:") == 1


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
