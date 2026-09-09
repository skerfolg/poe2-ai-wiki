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
