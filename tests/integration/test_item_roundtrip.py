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


def test_spec_alone_reproduces_the_users_own_item() -> None:
    """명세만 주면 **사용자가 손으로 쓴 것과 같은 값**이 나온다 (#34 근본 해결).

    사용자 정본(`20260809-2.txt`)의 `Ancestral Tiara`에서 명세 줄만 떼어 넣었다.
    문구·수치·방어값을 우리가 조립하지 않아도 PoB가 만든다 — 그게 이 결함의 해법이다.
    """
    from pok.pob.roundtrip import build_items

    spec = "\n".join(
        [
            "Rarity: RARE",
            "New Item",
            "Ancestral Tiara",
            "Crafted: true",
            "Prefix: {range:1}LocalIncreasedEnergyShield8",
            "Prefix: {range:1}IncreasedLife10",
            "Suffix: {range:1}ColdResist8",
            "Suffix: {range:1}CriticalStrikeChance5",
            "Sockets: S S S",
            "Rune: Perfect Iron Rune",
            "LevelReq: 80",
        ]
    )
    built = build_items({"tiara": spec})["tiara"].splitlines()
    # 사용자 정본과 **값까지** 같아야 한다 (직접 쓴 파일에서 그대로 옮긴 문구들)
    for line in (
        "+73 to maximum Energy Shield",
        "+174 to maximum Life",
        "34% increased Critical Hit Chance",
        "+45% to Cold Resistance",
    ):
        assert line in built, f"{line!r}가 없다 — 명세→문구 생성이 깨졌다"
    # 우리가 안 쓴 것도 PoB가 채운다: 방어값·빈 칸·선언
    assert any(ln.startswith("Energy Shield:") for ln in built), built
    assert "Prefix: None" in built, "빈 접사 칸도 PoB가 쓴다"
    assert "Rune: None" in built, "빈 소켓도 PoB가 쓴다"


def test_custom_mods_survive_and_are_told_apart() -> None:
    """커스텀 데이터가 **커스텀으로** 들어가는가 (사용자 요청 2026-08-09).

    사용자 정본 목걸이에 `{custom}+7% to Fire Spell Critical Hit Chance`가 있다.
    `Craft()`는 `explicitModLines`를 통째로 지우지만 **`custom` 표식은 보존한다**
    (L1698) — 그래서 명세만 줘도 살아남는다.
    """
    from pok.pob.roundtrip import build_items

    spec = "\n".join(
        [
            "Rarity: RARE",
            "New Item",
            "Lapis Amulet",
            "Crafted: true",
            "Prefix: {range:1}SpellDamage6",
            "Catalyst: Sibilant",
            "CatalystQuality: 40",
            "LevelReq: 61",
            "{custom}+7% to Fire Spell Critical Hit Chance",
        ]
    )
    built = build_items({"목걸이": spec})["목걸이"]
    assert "{custom}+7% to Fire Spell Critical Hit Chance" in built, built


def test_catalyst_scales_exactly_like_the_users_file() -> None:
    """촉매가 접사 수치를 올린다 — `Craft()`의 `getCatalystScalar`(#34 C).

    사용자 정본에 같은 목걸이가 촉매 20/40 두 벌 있어 대조가 된다:
    20 → `36% increased Spell Damage`·`+3 to Level` / 40 → `42%`·`+4`.
    """
    from pok.pob.roundtrip import build_items

    base = [
        "Rarity: RARE",
        "New Item",
        "Lapis Amulet",
        "Crafted: true",
        "Prefix: {range:1}SpellDamage6",
        "Suffix: {range:1}GlobalSpellGemsLevel3",
        "Catalyst: Sibilant",
        "LevelReq: 61",
    ]
    built = build_items({str(q): "\n".join([*base, f"CatalystQuality: {q}"]) for q in (20, 40)})
    assert "36% increased Spell Damage" in built["20"], built["20"]
    assert "+3 to Level of all Spell Skills" in built["20"]
    assert "42% increased Spell Damage" in built["40"], built["40"]
    assert "+4 to Level of all Spell Skills" in built["40"]


def test_the_checker_accepts_its_own_generated_item() -> None:
    """수용 기준 3 — 검사기가 **자기 도구의 출력**을 통과시킨다 (#34).

    처음엔 못 했다. 실측 2026-08-09에 셋이 걸렸다:
    ① `BuildRaw`의 스펙 줄 10종이 모드로 오독됨(#30 계열, 목록이 부족했다)
    ② 촉매로 오른 수치를 "티어 범위 밖"으로 거부 — 검사기가 촉매를 몰랐다
    ③ PoB 정본에는 `Item Level:`이 **없어서**(`LevelReq:`만 있다) ilvl을 1로 보고
      고티어 접사를 전부 거부
    """
    from pok.common.paths import knowledge_dir
    from pok.engine.legality import ItemLegalityChecker
    from pok.pob.roundtrip import build_items

    spec = "\n".join(
        [
            "Rarity: RARE",
            "New Item",
            "Lapis Amulet",
            "Crafted: true",
            "Prefix: {range:1}IncreasedEvasionRatingPercent7",
            "Prefix: {range:1}SpellDamage6",
            "Suffix: {range:1}GlobalSpellGemsLevel3",
            "Suffix: {range:1}CriticalMultiplier6",
            "Catalyst: Sibilant",
            "CatalystQuality: 40",
            "LevelReq: 61",
            "{custom}+7% to Fire Spell Critical Hit Chance",
        ]
    )
    report = ItemLegalityChecker(knowledge_dir()).check(build_items({"a": spec})["a"])
    assert report.is_legal, [
        (v.status, v.line, v.reason[:120]) for v in report.verdicts if v.status != "LEGAL"
    ] + list(report.errors)
    custom = next(v for v in report.verdicts if "{custom}" in v.line)
    assert custom.status == "CONDITIONAL", "커스텀은 미수록(UNKNOWN)과 다르다"
    assert "실재한다" in custom.reason, "KB에 있는 모드면 그걸 쓰라고 말해야 한다"
