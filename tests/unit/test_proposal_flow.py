"""M5 전개·저장 계약.

전개는 결정적(점수 없음), 저장은 **출처 분리**(LLM/엔진/PoB) — 섞이면 가설이
측정된 사실로 굳는다(M5 함정 ②).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pok.engine.proposal import validate
from pok.engine.proposal_flow import (
    expand,
    proposal_id,
    record_measurement,
    save,
)
from pok.kb.store import load

_store = load()

_STACKING = validate(
    {
        "title": "힘 스태킹 사슬",
        "mechanism": "스태킹",
        "premise": ["strength"],
        "route": "stacking-supply",
        "bundle": ["힘 축 담체를 그래프에서 전개"],
    }
)
_TRIGGER = validate(
    {
        "title": "치명타 시전 루프",
        "mechanism": "트리거 연쇄",
        "premise": ["Cast on Critical"],
        "route": "trigger-rate",
        "bundle": ["Cast on Critical + Comet"],
    }
)


def test_스태킹은_그래프로_전개된다() -> None:
    """LLM 기억이 아니라 정본에서 — 담체마다 근거 문구가 붙는다(AD-8)."""
    got = expand(_STACKING, _store)
    assert got.bundles, "힘 축 전개가 비었다 — 공급 그래프가 죽었나"
    first = got.bundles[0]
    assert first["origin"] == "supply-graph"
    assert all(c["evidence"] for c in first["carriers"]), "근거 없는 담체"
    assert "conflicts" in first, "배타 재료가 빠졌다 — 게이트가 먼저다(함정 ①)"


def test_전개기_없는_경로는_그대로_가되_그_사실을_말한다() -> None:
    """전개기 부재도 갭이다 — 쌓이면 만들 근거가 된다."""
    got = expand(_TRIGGER, _store)
    assert got.bundles[0]["origin"] == "proposal"
    assert any("전개기가 없다" in n for n in got.notes)


def test_축을_못_찾으면_전개_0건과_사유() -> None:
    p = validate(
        {
            **{
                "title": "모호한 전제",
                "mechanism": "스태킹",
                "premise": ["뭔가 좋은 것"],
                "route": "stacking-supply",
                "bundle": ["?"],
            }
        }
    )
    got = expand(p, _store)
    assert got.bundles == ()
    assert any("못 찾았다" in n for n in got.notes)


def test_저장은_출처를_구획으로_가른다(tmp_path: Path) -> None:
    """⛔ LLM 출처와 PoB 출처가 같은 필드에 섞이면 가설이 측정으로 굳는다(함정 ②)."""
    exp = expand(_TRIGGER, _store)
    path = save("0-5", _TRIGGER, exp, proposed_by={"model": "test", "session": "t"}, base=tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc) >= {"proposal", "expansion", "measurements"}
    assert doc["proposal"]["proposed_by"]["model"] == "test"
    assert doc["measurements"] == [], "측정 전인데 뭔가 들어 있다"

    record_measurement(path, {"bundle": 0, "deltas": {"CombinedDPS": 1.0}, "pob_commit": "abc"})
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert len(doc["measurements"]) == 1
    assert doc["measurements"][0]["pob_commit"] == "abc"


def test_낸_주체_없는_저장은_거부한다(tmp_path: Path) -> None:
    """어느 모델·세션의 가설인지 없으면 재현·교차 검증이 불가능하다(함정 ③)."""
    with pytest.raises(ValueError, match="proposed_by"):
        save("0-5", _TRIGGER, expand(_TRIGGER, _store), proposed_by={}, base=tmp_path)


def test_계보_없는_측정은_거부한다(tmp_path: Path) -> None:
    path = save(
        "0-5", _TRIGGER, expand(_TRIGGER, _store), proposed_by={"model": "t"}, base=tmp_path
    )
    with pytest.raises(ValueError, match="pob_commit"):
        record_measurement(path, {"deltas": {}})


def test_같은_제안은_같은_id_멱등() -> None:
    assert proposal_id(_TRIGGER) == proposal_id(_TRIGGER)
    assert proposal_id(_TRIGGER) != proposal_id(_STACKING)
