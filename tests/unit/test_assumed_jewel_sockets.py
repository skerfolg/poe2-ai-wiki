"""가정 주얼로 산 소켓은 반환값에 명시된다 (철칙 5).

`jewel_templates`가 「설계물이 아니라 가정 탐침」이라는 규율은 독스트링에만 있었고
그래서 지켜지지 않았다 — 실측 2026-08-18: 한 세션이 소켓을 9~16포인트씩 사서 그 안을
가정치로 채운 트리를 산출물로 냈다. 정작 상위 빌드와 소켓 수는 같았고(10칸) 격차는
전부 내용물이었다.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from pok.mcp.tools.tree import _assumed_sockets


@dataclasses.dataclass
class _ND:
    node_id: int
    points: int
    jewel_text: str | None


@dataclasses.dataclass
class _Step:
    node_delta: Any


@dataclasses.dataclass
class _Out:
    steps: tuple[Any, ...]


def test_silent_when_no_assumed_jewel_was_used() -> None:
    out = _Out(steps=(_Step(_ND(1, 1, None)),))
    assert _assumed_sockets(out) == {}


def test_reports_sockets_points_and_warning() -> None:
    tpl = "Rarity: UNIQUE\nGrand Spectrum\nRuby\n"
    out = _Out(
        steps=(_Step(_ND(2491, 10, tpl)), _Step(_ND(54127, 16, tpl)), _Step(_ND(7, 1, None)))
    )
    got = _assumed_sockets(out)["assumed_jewel_sockets"]
    assert [s["node_id"] for s in got["sockets"]] == [2491, 54127]
    assert got["points"] == 26
    assert got["sockets"][0]["assumed"] == "Grand Spectrum"
    # 경고는 **두 가지**를 말해야 한다: 실물이 없으면 낭비 · 소켓 수는 상한이 아니다
    assert "낭비" in got["warning"]
    assert "소켓 **수**" in got["warning"]
