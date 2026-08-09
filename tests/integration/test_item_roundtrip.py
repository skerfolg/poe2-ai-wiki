"""아이템 왕복 검사 — 우리가 만든 것과 PoB가 쓰는 것이 같은가 (백로그 #34 수용 기준 1).

사용자 지시: *"내가 직접 만드는 아이템과 너가 만드는 아이템이 동일한 것."*
규격은 사용자가 올린 PoB 코드가 아니라 **PoB 소스**다 — `Item.lua::BuildRaw()`가
PoB 자신이 아이템을 쓸 때 쓰는 함수이므로 그 출력이 정본이다(AD-1).
"""

from __future__ import annotations

import pytest

from pok.pob.roundtrip import invariants, roundtrip


def _snapshot_ready() -> bool:
    from pok.pob.versions import resolve_snapshot

    try:
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _snapshot_ready(), reason="external/pob 스냅샷 없음")

_WAND = ["Rarity: RARE", "Probe Wand", "Attuned Wand", "Item Level: 80"]


@pytest.fixture(scope="module")
def rebuilt() -> dict[str, str]:
    items = {
        "plain": "\n".join([*_WAND, "80% increased Spell Damage"]),
        "runes-declared": "\n".join(
            [*_WAND, "Sockets: S S", "Rune: Greater Body Rune", "Rune: Greater Body Rune"]
        ),
        "runes-handwritten": "\n".join(
            [
                *_WAND,
                "Sockets: S S",
                "Rune: Greater Body Rune",
                "Rune: Greater Body Rune",
                "{rune}+50 to maximum Energy Shield",
                "{rune}+50 to maximum Energy Shield",
            ]
        ),
    }
    return {r.label: r.rebuilt for r in roundtrip(items) if not r.error}


def test_pob_rewrites_our_text_into_its_own_form(rebuilt: dict[str, str]) -> None:
    """되쓴 텍스트는 **선언 줄을 갖춘다** — 우리가 쓰던 최소 텍스트와 다르다.

    이 차이가 곧 "사람이 만든 것과 다른 물건"이다. 생성기가 고쳐지면 이 테스트를
    **일치 검사로 좁혀** 회귀를 잠근다(#34 수용 기준 1).
    """
    plain = rebuilt["plain"].splitlines()
    assert any(line.startswith("Implicits:") for line in plain), plain
    assert any(line.startswith("Quality:") for line in plain), plain
    assert "80% increased Spell Damage" in plain, "모드 줄 자체는 살아 있어야 한다"


def test_rune_lines_are_pob_generated_not_ours(rebuilt: dict[str, str]) -> None:
    """`{rune}` 줄은 **우리가 쓰는 게 아니다** — `Sockets:`+`Rune:`에서 PoB가 만든다.

    실측 2026-08-09: 선언만 준 것과 `{rune}` 줄까지 손으로 쓴 것이 **같은 텍스트로**
    되쓰였다. 즉 손기입 줄은 `UpdateRunes()`가 덮어쓴다 — 그 줄을 우리가 관리하려
    들면 겹치거나(모리오르 4소켓에 6줄) 값이 어긋난다(#34 D).
    """
    assert rebuilt["runes-declared"] == rebuilt["runes-handwritten"]
    lines = [ln for ln in rebuilt["runes-declared"].splitlines() if "{rune}" in ln]
    assert lines, "선언만 줘도 룬 효과 줄이 생긴다"
    # PoB는 같은 룬 2개를 **합쳐서** 쓴다(50+50 → 100) — 우리가 2줄로 쓰면 어긋난다
    assert any("+100" in ln for ln in lines), lines


def test_invariants_catch_declaration_mismatch() -> None:
    """선언과 개수가 어긋나면 인게임에서 못 만드는 물건이다 (#34 수용 기준 2)."""
    bad = "\n".join(
        [
            *_WAND,
            "Sockets: S",
            "Rune: A",
            "Rune: B",
            "Implicits: 0",
            "{rune}x",
            "{rune}y",
        ]
    )
    problems = invariants(bad)
    assert any("소켓" in p for p in problems), problems

    good = "\n".join([*_WAND, "Sockets: S S", "Rune: A", "Rune: B", "Implicits: 0"])
    assert not invariants(good), "정상을 막으면 신호가 죽는다(§0 ⑤)"
