"""타임리스 주얼이 부여하는 키스톤 수록 계약 (2026-08-16, 사용자 지시).

트리 수집은 poe2db 트리를 읽으므로 **트리에 없는 이 키스톤들을 못 본다** — 래더
프로파일에 `unmapped:<이름>`으로만 남아 있었다(실측: 7종 · 최다 `Black Scythe
Training` 129벌). 여기서 잠그는 것은 두 가지다: **PoE1 잔재를 섞지 않는 것**과
**트리 노드가 아니라는 사실을 레코드가 말하는 것**.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pok.kb.ingest.timeless_keystones import build_records, keystones

_RAW = Path("artifacts/ingest-raw/0.5.4b/pob")
pytestmark = pytest.mark.skipif(
    not (_RAW / "legionpassives.json").exists(),
    reason="PoB 덤프(legionpassives.json) 없음 — 원시 스냅샷 필요",
)


def test_PoE2_정복자만_싣는다() -> None:
    """⛔ 같은 파일에 PoE1 정복자 20종이 남아 있고, 그중 `Eternal Youth`·
    `Glancing Blows`·`Dance with Death`·`Wind Dancer`는 **PoE2 트리에 같은 이름의
    진짜 노드가 있다**. 그대로 실으면 트리 노드와 중복된 레코드가 생겨 조회가 갈린다.
    """
    got = keystones(_RAW)
    assert {e["conqueror"] for e in got} == {"kalguur", "abyss"}
    names = {e["name"] for e in got}
    assert len(got) == 8, "PoE2 정복자 키스톤은 kalguur 3 + abyss 5다"
    assert not (names & {"Eternal Youth", "Glancing Blows", "Dance with Death", "Wind Dancer"}), (
        "PoE1 잔재가 섞였다 — 트리 노드와 이름이 겹친다"
    )


def test_트리_노드가_아니라고_레코드가_말한다() -> None:
    """`node_id`가 없는 것만으로는 「수집이 빠뜨린 트리 노드」와 구별되지 않는다.
    `on_tree: false`와 `grant`가 있어야 **취득 경로**로 읽힌다(형태 ①)."""
    recs = build_records(_RAW, patch="0.5.4b", pob_commit="x")
    assert recs
    for r in recs:
        data = r["data"]
        assert data["kind"] == "keystone"
        assert data["on_tree"] is False
        assert "node_id" not in data, "트리에 없는데 노드 번호를 주면 트리 연산에 섞인다"
        assert data["grant"]["via"] == "timeless-jewel"
        assert data["grant"]["jewel"] in {"item.heroic-tragedy", "item.undying-hate"}
        assert r["relations"] == [{"rel": "requires", "target": data["grant"]["jewel"]}]


def test_주얼_대응이_정복자별로_갈린다() -> None:
    """래더 2,689벌 전수에서 예외 0건으로 확인된 대응이다 —
    `Heroic Tragedy` → kalguur 3종 · `Undying Hate` → abyss 5종."""
    recs = build_records(_RAW, patch="0.5.4b", pob_commit="x")
    by_jewel: dict[str, set[str]] = {}
    for r in recs:
        by_jewel.setdefault(r["data"]["grant"]["jewel"], set()).add(r["data"]["grant"]["conqueror"])
    assert by_jewel == {
        "item.heroic-tragedy": {"kalguur"},
        "item.undying-hate": {"abyss"},
    }


def test_정본에_실려_있고_래더_매핑이_닿는다() -> None:
    """수록의 목적은 래더 프로파일의 `unmapped:`를 없애는 것이다 — 레코드만 있고
    매핑이 안 닿으면 아무것도 안 고쳐진다."""
    from pok.engine.ladder_aggregate import _keystone_ids

    shard = Path("knowledge/game-data/tree/timeless-keystones.ndjson")
    ids = {
        json.loads(line)["id"] for line in shard.read_text(encoding="utf-8").splitlines() if line
    }
    assert len(ids) == 8

    mapping = _keystone_ids()
    for name in ("black scythe training", "sacrifice of flesh", "knightly tenets"):
        assert mapping.get(name, "").startswith("passive.timeless-"), name
