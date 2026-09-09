"""희귀 아이템 왕복이 막혀 있던 자리 — #148.

세 얼굴이 한 뿌리다: **PoB 아이템 텍스트는 선언(`Prefix:`)과 렌더 문구를 함께
담는데, 두 도구가 그 텍스트를 다르게 읽었다**(§0 ④ 판정 주체가 둘이면 어긋난다).

    계산되는 형식(렌더 문구) → `check_item_legality`가 **불법** 판정
    적법한 형식(선언형)     → `compute_pob`이 **조용히 버림**

우회로가 없어서 보고 세션은 신발을 확정하지 못했다.
"""

from __future__ import annotations

import pytest

# 회피 접사가 실제로 스폰되는 베이스 — 보고 세션이 쓴 것과 같다.
# ⚠ `Stone Greaves`(힘·방어도)로 쓰면 「이 베이스에 스폰 불가」가 맞게 뜬다.
_HEAD = """Rarity: RARE
Test Boots
Drakeskin Boots
Item Level: 82
"""
_DECL = """Prefix: IncreasedLife9
Prefix: LocalIncreasedEvasionRatingPercent7
Prefix: LocalIncreasedEvasionRating7_
"""
_LIFE = "+135 to maximum Life"
_EVA_FLAT = "+162 to Evasion Rating"
_EVA_PCT = "96% increased Evasion Rating"


def _check(text: str) -> dict:
    from pok.mcp.tools.build import check_item_legality

    return check_item_legality(text)


# ── 얼굴 ① — 판정이 줄 순서에 의존했다 ──────────────────────────────────────


@pytest.mark.parametrize(
    "order",
    [
        (_LIFE, _EVA_FLAT, _EVA_PCT),
        (_EVA_PCT, _EVA_FLAT, _LIFE),
        (_EVA_FLAT, _LIFE, _EVA_PCT),
        (_EVA_PCT, _LIFE, _EVA_FLAT),
    ],
)
def test_판정이_줄_순서에_의존하지_않는다(order: tuple[str, ...]) -> None:
    """인접 두 줄을 하이브리드로 **탐욕 매칭**하던 것이 원인이었다.

    실측 2026-09-09: `+162 to Evasion Rating` + `96% increased Evasion Rating`은
    `localincreasedevasionandbase1`(티어 밖 ILLEGAL)로, 이웃을 `+135 to maximum
    Life`로 바꾸면 `localincreasedevasionandlife1`로 잡혔다. 선언이 있으면 후보를
    그 하나로 좁혀 순서가 판정을 못 바꾼다.
    """
    report = _check(_HEAD + _DECL + "\n".join(order) + "\n")
    assert report["legal"], f"순서 {order}에서 불법 판정: {report['errors']}"


def test_렌더_문구가_선언된_모드로_해석된다() -> None:
    """문구 한 줄이 후보 **55건**에 걸린다 — 선언이 그중 하나를 못 박는다."""
    report = _check(_HEAD + _DECL + f"{_LIFE}\n{_EVA_FLAT}\n{_EVA_PCT}\n")
    by_line = {row["line"]: row["modifier_id"] for row in report["lines"]}
    assert by_line[_EVA_FLAT] == "modifier.localincreasedevasionrating7-alt1"
    assert by_line[_EVA_PCT] == "modifier.localincreasedevasionratingpercent7"
    assert by_line[_LIFE] == "modifier.increasedlife9"


def test_선언이_없으면_기존_경로가_그대로_돈다() -> None:
    """좁히기는 **선언이 있을 때만**이다 — 평문형 검사를 바꾸지 않는다."""
    report = _check(_HEAD + f"{_LIFE}\n")
    assert [row["status"] for row in report["lines"]] == ["LEGAL"]


# ── 얼굴 ② — 선언 접두 3개가 4개로 세어졌다 ─────────────────────────────────


def test_접사가_이중_계수되지_않는다() -> None:
    """선언과 문구가 **다른 id**로 잡히면 한 접사가 둘로 셌다.

    실측: `LocalIncreasedEvasionRating7_` → `…rating7-alt1`인데 문구
    `+162 to Evasion Rating`은 **룬**(`modifier.rune-of-foundations`)으로 잡혔다.
    """
    report = _check(_HEAD + _DECL + f"{_LIFE}\n{_EVA_FLAT}\n{_EVA_PCT}\n")
    assert not any("한도" in e for e in report["errors"]), report["errors"]
    ids = {row["modifier_id"] for row in report["lines"] if row["modifier_id"]}
    assert len(ids) == 3, f"접두 3개가 {len(ids)}개로 셌다: {ids}"


# ── 얼굴 ③ — `compute_pob`이 선언형을 조용히 버린다 ─────────────────────────


def test_선언만_있는_아이템을_신고한다() -> None:
    """PoB 아이템 파서는 `Prefix:`를 스탯으로 적용하지 않는다 — 경고가 없었다.

    실측: 접두를 바꿔 두 번 돌렸는데 `CombinedDPS`가 **소수점까지 동일**했고
    회피는 베이스+룬 값이었다. 조립은 정상으로 보이고 수치만 낮다(§0 ①).
    """
    from pok.engine.items import unbuilt_declarations

    spec = {"items": [{"slot": "Boots", "text": _HEAD + "Sockets: S S\n" + _DECL}]}
    reported = unbuilt_declarations(spec)
    assert len(reported) == 1
    assert reported[0]["slot"] == "Boots"
    assert len(reported[0]["declared"]) == 3
    # 대안 경로를 **함께** 낸다 — 금지하려면 대안을 먼저 준다(철칙 5 따름정리)
    assert "build_items" in reported[0]["fix"]


def test_문구가_있으면_신고하지_않는다() -> None:
    """하이브리드는 선언 1개가 줄 2개를 낸다 — 개수 대조로는 못 가른다.

    거짓 경보는 게이트 우회를 학습시키므로(§0 ⑪) **문구가 하나라도 있으면** 침묵한다.
    """
    from pok.engine.items import unbuilt_declarations

    spec = {"items": [{"slot": "Boots", "text": _HEAD + _DECL + f"{_LIFE}\n"}]}
    assert unbuilt_declarations(spec) == []


def test_게이트도_계산_불가를_말한다() -> None:
    """한쪽만 신고하면 세션은 **통과한 쪽만 보고** 넘어간다(§0 ④).

    `legal: True`와 「계산된다」는 **다른 축**이다 — 선언형은 줄별 전부 LEGAL이면서
    접사가 하나도 안 들어간다.
    """
    report = _check(_HEAD + "Sockets: S S\n" + _DECL)
    assert report["legal"], "선언형 자체는 적법하다 — 형식이 아니라 계산이 문제다"
    assert report["not_computable"], "적법한데 계산 안 되는 것을 말해야 한다"


def test_평문형은_계산_불가로_찍히지_않는다() -> None:
    from pok.engine.items import unbuilt_declarations

    spec = {"items": [{"slot": "Boots", "text": _HEAD + f"{_LIFE}\n{_EVA_FLAT}\n"}]}
    assert unbuilt_declarations(spec) == []
