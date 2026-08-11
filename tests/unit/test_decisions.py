"""문서의 기각 결정 ↔ 스펙 대조 — 백로그 #58 ② (2026-08-11).

선행 문서가 복점관을 「기각」으로 판정했는데 스펙에 그대로 남아 그 위에서 장비
5슬롯 실측 전체가 나왔다. 매 호출 `items_legal: True`였다 — **적법성은 「기각했었나」를
모른다.**

이 파일이 지키는 두 축:
1. 규약대로 적힌 기각은 **빠짐없이** 잡는다
2. 산문은 **읽지 않는다** — 거짓 경고는 참 경고의 신호를 죽인다(§0 ⑤)
"""

from __future__ import annotations

from pok.engine.decisions import (
    rejected_but_present,
    rejected_names,
    rejection_record_gap,
)

HEADING_DOC = """# 설계

#### 폐기: CoEA 화염폭풍
사유 5건…

### 폐기 유지: 끓어오르는 육체
"""

TABLE_DOC = """# 설계

| 유니크 | 판정 |
|---|---|
| **복점관** | 기각 (민첩 230 부족) |
| `무기 3개 완벽한 강철` | 기각 |
| 육신의 룬 | 채택 |
"""


def test_heading_convention_is_read() -> None:
    assert rejected_names(HEADING_DOC) == ("CoEA 화염폭풍", "끓어오르는 육체")


def test_table_cells_are_read_and_markup_stripped() -> None:
    """첫 칸이 대상이고 `**`·백틱은 표기이지 이름이 아니다."""
    names = rejected_names(TABLE_DOC)
    assert names == ("복점관", "무기 3개 완벽한 강철")
    assert "육신의 룬" not in names, "채택된 것을 기각으로 읽으면 안 된다"


def test_prose_is_not_read() -> None:
    """ "…는 소스 판독으로 기각됐다"에서 대상을 확정할 방법이 없다 — 지어내지 않는다."""
    prose = "처음 세운 가설은 소스 판독으로 **기각됐다**. 채택/기각 판정은 §10.4로 넘긴다."
    assert rejected_names(prose) == ()


def test_rejected_item_still_in_spec_is_reported() -> None:
    spec = {"items": [{"slot": "Body Armour", "text": "Rarity: UNIQUE\n복점관\nStellar Vest\n"}]}
    (found,) = rejected_but_present(spec, TABLE_DOC)
    assert found["slot"] == "Body Armour" and found["name"] == "복점관"
    assert "기각으로 기록" in found["why"]


def test_a_clean_spec_is_silent() -> None:
    spec = {"items": [{"slot": "Helmet", "text": "Rarity: RARE\n아무 투구\nGrinning Mask\n"}]}
    assert rejected_but_present(spec, TABLE_DOC) == []
    assert rejected_but_present(spec, "") == []


def test_partial_names_do_not_match() -> None:
    """부분 일치로 넓히면 「검은 화염」이 「검은 화염의 서약」을 잡는다."""
    doc = "#### 폐기: 검은 화염\n"
    spec = {"items": [{"slot": "Amulet", "text": "Rarity: UNIQUE\n검은 화염의 서약\nBase\n"}]}
    assert rejected_but_present(spec, doc) == []


def test_prose_only_rejections_are_flagged_as_a_record_gap() -> None:
    """기각을 말만 하고 규약으로 안 적으면 **기계가 못 읽는다**.

    실측: `artifacts/builds` 문서 14개 중 규약대로 적은 것은 4개뿐이었고,
    복점관이 계승된 것도 안 적은 쪽에서였다.
    """
    gap = rejection_record_gap("이 안은 기각됐다. 저 안도 기각. 폐기 사유는 §3에.")
    assert gap is not None and "규약 형식 기록이 0건" in gap

    # 규약대로 적었으면 조용하다 · 언급이 없어도 조용하다
    assert rejection_record_gap(HEADING_DOC) is None
    assert rejection_record_gap("그런 판정을 한 적이 없는 문서") is None
