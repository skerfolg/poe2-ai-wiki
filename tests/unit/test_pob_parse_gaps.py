"""pob/parse_gaps — PoB 판정 프로토콜 해석과 레코드 표기 (PoB 부팅 없이).

부팅이 필요한 실측 대조는 tests/integration/test_pob_parse_gaps.py.
"""

from __future__ import annotations

import pytest

from pok.pob.parse_gaps import (
    NodeParseGap,
    ParseGapError,
    RecordParseGap,
    UnparsedLine,
    parse_dump_lines,
)

_HEADER = 'POK_TREE:{"version":"0_5","nodes":4912}'
_GAP = (
    'POK_GAP:{"id":11428,"name":"Exhaust All Power","lines":['
    '{"i":1,"text":"Archon recovery period expires 30% slower",'
    '"status":"unknown","rest":"Archon recovery period expires 30% slower "},'
    '{"i":2,"text":"Archon Buffs also grant 30% increased Critical Hit Chance",'
    '"status":"ok","rest":""}]}'
)


def test_헤더와_갭을_읽는다() -> None:
    dump = parse_dump_lines([_HEADER, _GAP, "POK_OK"], snapshot="5d173cb")
    assert dump.tree_version == "0_5"
    assert dump.scanned == 4912  # 분모 — 비율을 말하려면 필요하다
    assert dump.snapshot == "5d173cb"
    gap = dump.gaps[11428]
    assert gap.name == "Exhaust All Power"
    # status가 갭이 아닌 줄(ok)은 버린다 — 아니면 정상 줄까지 미모델링으로 표기된다
    assert [line.index for line in gap.lines] == [1]
    assert gap.lines[0].kind == "unknown"


def test_POK_OK_없으면_실패() -> None:
    """부분 출력을 성공으로 읽으면 '갭 0건'이 되어 **없는 안전**을 보고한다."""
    with pytest.raises(ParseGapError, match="POK_OK"):
        parse_dump_lines([_HEADER, _GAP], snapshot="x")


def test_헤더_없으면_실패() -> None:
    with pytest.raises(ParseGapError, match="POK_TREE"):
        parse_dump_lines([_GAP, "POK_OK"], snapshot="x")


def test_갭이_없으면_빈_덤프() -> None:
    dump = parse_dump_lines([_HEADER, "POK_OK"], snapshot="x")
    assert dump.gaps == {}


def _gap(*kinds: str) -> NodeParseGap:
    return NodeParseGap(
        node_id=1,
        name="n",
        lines=tuple(
            UnparsedLine(index=i + 1, text=f"line {i}", kind=k, remainder="rest")
            for i, k in enumerate(kinds)
        ),
    )


def test_부분과_전량을_구분해_적는다() -> None:
    """'전 줄이 안 세진다'와 '4줄 중 1줄'은 판단이 다르다 — 문장이 구분해야 한다."""
    partial = RecordParseGap("passive.x-1", _gap("extra"), total_lines=4).as_modeling("abc")
    full = RecordParseGap("passive.x-1", _gap("extra", "unknown"), total_lines=2).as_modeling("abc")
    assert "4줄 중 1줄" in partial["detail"]
    assert "전 줄 2줄" in full["detail"]
    assert "extra·unknown" in full["detail"]


def test_표기_형태() -> None:
    modeling = RecordParseGap("passive.x-1", _gap("extra"), total_lines=1).as_modeling("5d173cb")
    assert modeling["supported"] is False
    assert modeling["kind"] == "tree-line-unparsed"
    # 스냅샷이 없으면 이 판정이 어느 PoB 기준인지 알 수 없어 낡음을 판별하지 못한다
    assert modeling["snapshot"] == "5d173cb"
    assert modeling["unparsed"] == [
        {"line": 1, "text": "line 0", "kind": "extra", "remainder": "rest"}
    ]
