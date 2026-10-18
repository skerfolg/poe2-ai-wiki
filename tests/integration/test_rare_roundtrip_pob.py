"""희귀 왕복 — **PoB가 만든 정본을 우리 검사기가 받는가** (#148).

단위 시험(`tests/unit/test_rare_roundtrip.py`)은 손으로 쓴 텍스트로 판정 논리를
잠근다. 여기서 잠그는 것은 다른 것이다: **PoB `Craft()`의 실제 출력**이 검사기를
통과하는가. 그 둘이 어긋나 있던 것이 #148이었고, 손으로 만든 입력으로는 못 잡는다
(§0 ⑭ — 손으로 만든 입력으로 「울린다」를 재면 실물 경로가 죽어 있어도 초록이다).

실측 2026-09-09: 아래 명세의 PoB 정본이 수정 전 `legal: False`였다 —
`+162 to Evasion Rating` + `96% increased Evasion Rating`을 인접 하이브리드
`localincreasedevasionandbase1`로 탐욕 매칭해 둘 다 「티어 범위 밖」이 됐다.
"""

from __future__ import annotations

import pytest


def _snapshot_ready() -> bool:
    from pok.pob.versions import resolve_snapshot

    try:
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _snapshot_ready(), reason="external/pob 스냅샷 없음")

# ⭑ 보고 세션이 실제로 쓴 베이스다. `Stone Greaves`(힘·방어도)로 쓰면 회피 접사가
#   스폰 불가라 ILLEGAL이 뜨는데 그건 **정상 판정**이다 — 재현이 성립하지 않는다.
_SPEC = """Rarity: RARE
Test Boots
Drakeskin Boots
Item Level: 82
Crafted: true
Prefix: {range:0.5}IncreasedLife9
Prefix: {range:0.5}LocalIncreasedEvasionRatingPercent7
Prefix: {range:0.5}LocalIncreasedEvasionRating7_
"""


@pytest.fixture(scope="module")
def crafted() -> str:
    from pok.pob.roundtrip import build_items

    built = build_items({"boots": _SPEC}).get("boots", "")
    assert built, "PoB Craft()가 아이템을 못 만들었다"
    return built


def test_craft가_선언과_문구를_함께_낸다(crafted: str) -> None:
    """#148의 전제 — PoB 정본은 **두 형식을 한 텍스트에** 담는다.

    이게 사실이 아니면 「선언을 권위로 삼는다」는 수정 자체가 성립하지 않는다.
    """
    assert "Prefix: " in crafted, "선언이 남아 있어야 한다"
    assert "+135 to maximum Life" in crafted, "렌더 문구도 함께 있어야 한다"


def test_pob_정본이_검사기를_통과한다(crafted: str) -> None:
    """**계산되는 형식이 불법 판정되던** 자리 — #148 얼굴 ①."""
    from pok.mcp.tools.build import check_item_legality

    report = check_item_legality(crafted)
    bad = [v for v in report["lines"] if v["status"] not in ("LEGAL", "CONDITIONAL")]
    assert not bad, f"PoB 자신의 출력이 거부됐다: {bad}"
    assert report["legal"], report["errors"]


def test_렌더된_정본은_계산_불가로_찍히지_않는다(crafted: str) -> None:
    """얼굴 ③의 신고가 **정상 아이템에 붙으면** 거짓 경보다(§0 ⑪)."""
    from pok.engine.items import unbuilt_declarations

    assert unbuilt_declarations({"items": [{"slot": "Boots", "text": crafted}]}) == []


def test_crafted_없는_명세는_접사가_통째로_빠진다() -> None:
    """⛔ `Crafted: true`가 없으면 `Craft()`가 선언을 **전부 조용히 버린다**.

    렌더로 우회하려던 세션이 **같은 조용한 0을 다시 밟는** 자리라, 사실을 시험으로
    박아 둔다. 실측 2026-09-09: 그 한 줄 유무로 접사 0개 / `+135 to maximum Life`로
    갈렸다. `optimize_rare`는 이 줄을 넣는다(`rares.py`) — 위험한 것은 손으로 쓴 명세다.
    """
    from pok.pob.roundtrip import build_items

    without = _SPEC.replace("Crafted: true\n", "")
    built = build_items({"boots": without}).get("boots", "")
    assert built, "아이템 자체는 만들어진다 — 그래서 조용하다"
    assert "+135 to maximum Life" not in built, "접사가 빠지는 것이 현재 동작이다"
    assert "Prefix: " not in built, "선언도 함께 사라진다"


# 2026-10-19 실제 jewel-final2-26725의 세 번째 접두가 선언에만 남고
# 효과에서는 사라졌다. 우리 어댑터가 native Craft의 list.limit를 전달해야 한다.
_JEWEL_PREFIXES = ("JewelIgniteEffect", "JewelMaceDamage", "JewelAttackDamage")
_JEWEL_SUFFIXES = (
    "JewelMaximumFireResistance",
    "JewelStunThreshold",
    "JewelBleedingDuration",
)


def _jewel_spec(prefixes: int, suffixes: int) -> str:
    lines = ["Rarity: RARE", "Native Jewel Regression", "Ruby", "Crafted: true"]
    lines += [f"Prefix: {{range:0.5}}{key}" for key in _JEWEL_PREFIXES[:prefixes]]
    lines += [f"Suffix: {{range:0.5}}{key}" for key in _JEWEL_SUFFIXES[:suffixes]]
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def jewel_paths() -> tuple[dict[str, str], dict[str, str]]:
    from pok.pob.daemon import shared_daemon
    from pok.pob.roundtrip import build_items, roundtrip

    specs = {f"{p}/{s}": _jewel_spec(p, s) for p, s in ((2, 2), (3, 2), (2, 3), (3, 3))}
    # Do not let an unavailable daemon silently turn this into fallback-only coverage.
    assert shared_daemon() is not None
    daemon = build_items(specs)
    # This is the actual one-shot subprocess used when no daemon is available.
    fallback = {r.label: r.rebuilt for r in roundtrip(specs) if not r.error}
    assert daemon.keys() == specs.keys() == fallback.keys()
    return daemon, fallback


@pytest.mark.parametrize("split", ["2/2", "3/2", "2/3", "3/3"])
def test_jewel_craft_daemon_and_fallback_match(
    jewel_paths: tuple[dict[str, str], dict[str, str]],
    split: str,
) -> None:
    daemon, fallback = jewel_paths
    assert daemon[split] == fallback[split]


@pytest.mark.parametrize(
    "split,extra",
    [
        ("3/2", "10% increased Attack Damage"),
        ("2/3", "8% increased Bleeding Duration"),
    ],
)
def test_fifth_jewel_affix_is_rendered_and_legal(
    jewel_paths: tuple[dict[str, str], dict[str, str]],
    split: str,
    extra: str,
) -> None:
    from pok.mcp.tools.build import check_item_legality
    from pok.pob.roundtrip import build_items

    built = jewel_paths[0][split]
    assert extra in built, "native Craft must render the third affix, not only its declaration"
    report = check_item_legality(built)
    assert report["legal"], report["errors"]
    assert not report.get("not_computable"), report
    assert build_items({"again": built})["again"] == built


def test_six_jewel_affixes_are_rendered_but_rejected(
    jewel_paths: tuple[dict[str, str], dict[str, str]],
) -> None:
    from pok.mcp.tools.build import check_item_legality

    built = jewel_paths[0]["3/3"]
    assert "10% increased Attack Damage" in built
    assert "8% increased Bleeding Duration" in built
    report = check_item_legality(built)
    assert not report["legal"], "rendering all declarations must not weaken the total-five gate"
    assert report["errors"]


def test_normal_two_by_two_jewel_render_is_unchanged(
    jewel_paths: tuple[dict[str, str], dict[str, str]],
) -> None:
    built = jewel_paths[0]["2/2"]
    assert built.splitlines() == [
        "Rarity: RARE",
        "Native Jewel Regression",
        "Ruby",
        "Crafted: true",
        "Prefix: {range:0.5}JewelIgniteEffect",
        "Prefix: {range:0.5}JewelMaceDamage",
        "Suffix: {range:0.5}JewelMaximumFireResistance",
        "Suffix: {range:0.5}JewelStunThreshold",
        "LevelReq: 0",
        "Implicits: 0",
        "+1% to Maximum Fire Resistance",
        "10% increased Ignite Magnitude",
        "11% increased Damage with Maces",
        "11% increased Stun Threshold",
    ]
