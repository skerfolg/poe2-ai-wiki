"""Item을 **속성으로 조회할 수단**이 없던 자리 — #146·#147.

둘은 같은 뿌리다: Item에 닿는 축이 **이름 하나뿐**이라 세션이 이름 토큰으로
훑게 되고, 그러면 갭이 **0건이 아니라 그럴듯한 부분집합**으로 나와서 안 보인다.
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter

# ── #146 — 효과 문구로 유니크를 찾는다 ──────────────────────────────────────
# 정본에 문장이 **그대로 있는데** 검색이 0건이었다. 게다가 조용하지도 않고
# **Modifier가 대신 나와서** 세션은 "모드는 있는데 담체가 없다"로 읽었다 —
# 실제로는 담체가 KB에 있었다(§0 ⑧의 아이템판).


def test_유니크를_효과_문구로_찾는다() -> None:
    """재현 그대로(백로그 #146): 둘 다 0건이었다."""
    from pok.index.search import search

    # `item.crown-of-eyes`의 explicits에 이 문장이 그대로 있다
    hits = search(
        query="Increases and Reductions to Spell damage also apply to Attacks", type_="Item"
    )
    assert "item.crown-of-eyes" in {h.id for h in hits}

    # 세션이 **이름만 들고 30분을 헤맨** 자리 — 효과로는 닿지 못했다
    hits = search(query="more Unarmed Damage per 5 Strength", type_="Item", limit=10)
    assert "item.facebreaker" in {h.id for h in hits}


def test_아이템_토큰이_실제로_색인된다() -> None:
    """`Unarmed` 토큰 카운트가 Item 안에서 **0이었다** — 타입 전체에 하나도 없었다."""
    from pok.index.search import search

    assert len(search(query="Unarmed", type_="Item", limit=99)) > 0


def test_한글_효과_문구도_색인된다() -> None:
    """`explicits_ko`(36건)도 같은 갭이었다 — Item은 한글 보유율이 29%라 있는 건 쓴다."""
    from pok.index.search import search

    hits = search(query="이 아이템에는 영혼 핵만 장착 가능", type_="Item", limit=20)
    assert "item.atziris-splendour" in {h.id for h in hits}


# ── #147 — 부위·방어 유형으로 열거한다 ──────────────────────────────────────


def test_부위로_베이스_전량을_연다() -> None:
    """`query="Boots"`는 217건 중 16건만 봤다 — 이름군이 Boots/Sandals/Greaves로 갈린다."""
    from pok.index.search import search

    by_category = search(category="boots", type_="Item", limit=999)
    assert len(by_category) > 200, "부위 전량이 나와야 한다 (이름군 3종 합산)"

    by_name = search(query="Boots", type_="Item", limit=999)
    assert len(by_name) < len(by_category), "이름 토큰은 부분집합이다 — 그게 함정이었다"


def test_방어_유형으로_거른다() -> None:
    """세션이 **없다고 판정하고 보고까지 한** 조합 — 실제로는 있다."""
    from pok.index.search import search

    dual = search(sub_type="Evasion/Energy Shield", type_="Item", limit=999)
    assert len(dual) > 100

    # 「신발에는 회피/ES 듀얼 베이스가 없다」 — 빌드의 치명타 축이 여기 걸려 있었다
    boots = search(category="boots", sub_type="Evasion/Energy Shield", type_="Item", limit=999)
    assert boots, "회피/ES 신발 베이스는 실재한다"


def test_표기_대소문자를_접는다() -> None:
    """`describe_type`이 보여 준 표기를 그대로 넣어도 걸려야 한다 (B-1 — 표기 불일치)."""
    from pok.index.search import search

    upper = {h.id for h in search(sub_type="Evasion/Energy Shield", type_="Item", limit=999)}
    lower = {h.id for h in search(sub_type="evasion/energy shield", type_="Item", limit=999)}
    assert upper and upper == lower


def test_0건이면_부위_경로를_가리킨다() -> None:
    """진단이 **도구를 지목**해야 한다 — 문서 지침만으로는 안 꺼내진다(철칙 5)."""
    from pok.index.search import diagnose_empty

    # Item의 tags는 비어 있다 — 세션은 여기서 "그 부위가 KB에 없다"로 읽었다
    tagged = diagnose_empty(tags=["boots"], type_="Item")
    assert any("category" in r for r in tagged.reasons)

    # 이름 토큰으로 훑는 습관 자체가 함정이라 0건 진단에도 붙인다
    named = diagnose_empty(query="zzzqqnonexistentboots", type_="Item")
    assert any("describe_type" in r for r in named.reasons)


# ── 강제 지점 — 새 문장 필드가 조용히 색인 밖에 남지 않게 (철칙 5) ────────────


def _is_prose(value: object) -> bool:
    """플레이어가 읽는 문장인가 — 공백이 있고 짧지 않은 문자열."""
    return isinstance(value, str) and " " in value.strip() and len(value.strip()) > 12


# 문장이지만 **일부러 색인하지 않는** 필드 + 사유.
# ⛔ 여기 추가하는 것은 "검색으로 못 찾게 만든다"는 결정이다 — #146이 바로 그
# 결정을 **아무도 내리지 않은 채** 생긴 갭이었다. 사유 없이 넣지 말 것.
_NOT_INDEXED = {
    "engine_stats": "PoE 엔진 내부 스탯 식별자(`is area damage [1]`) — 문구는 `stats`에 있다",
    "pob_key": "PoB 내부 키 — 식별자이지 문구가 아니다",
    "acquisition": "조달 경로 열거값(`crafting-currency`) — 분류이지 효과가 아니다",
    "acquisition_note": "우리가 단 주석 — 게임 문구가 아니다(레코드 `notes`와 같은 층)",
    "bonded_condition": "우리가 단 주석 — 게임 문구가 아니다",
    "granted_by": "이 스킬을 주는 아이템 이름 — 관계축이라 `related`가 답한다",
    "sub_type": "분류값 — 이제 `search_kb(sub_type=...)` 필터로 닿는다(#147)",
    "item_class": "분류값 — `category`와 같은 축이다",
    "requires": "요구 스탯(`Level 65, 34 Str`) — 수치축이라 `find_by_value`가 답한다",
}
_MIN_RECORDS = 20  # 이보다 드물면 오탈자·1회성 필드일 수 있어 강제하지 않는다


def test_index_covers_prose_fields() -> None:
    """정본의 **문장 필드는 색인되거나, 사유와 함께 제외되거나** 둘 중 하나다.

    #146은 `explicits`가 색인 밖이라는 걸 **아무도 몰랐던** 결함이다. 수집이 새
    문장 필드를 추가하면 검색은 조용히 그것을 못 찾는데, 실패하는 것이 없어서
    발견은 빌드 세션이 30분 헤맨 뒤에야 온다. 이 시험이 그 자리를 막는다.
    """
    from pok.index.build import _BODY_FIELDS

    handled = set(_BODY_FIELDS) | {"per_slot", "minion_stats", "grants"}
    counts: Counter[str] = Counter()
    root = pathlib.Path(__file__).resolve().parents[2] / "knowledge" / "game-data"
    for path in sorted(root.rglob("*.ndjson")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                data = (json.loads(line).get("data") or {}) if line else {}
                for key, value in data.items():
                    if _is_prose(value) or (
                        isinstance(value, list) and any(_is_prose(v) for v in value)
                    ):
                        counts[key] += 1

    unaccounted = {
        key: n
        for key, n in counts.items()
        if n >= _MIN_RECORDS and key not in handled and key not in _NOT_INDEXED
    }
    assert not unaccounted, (
        f"문장을 담은 필드가 색인에도 제외 목록에도 없다: {unaccounted}. "
        f"검색으로 못 찾는 채 남으면 세션은 '**KB에 없다**'로 오독한다(#146). "
        f"`_BODY_FIELDS`에 넣거나 `_NOT_INDEXED`에 사유와 함께 적을 것"
    )
