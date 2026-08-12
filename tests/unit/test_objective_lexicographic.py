"""사전식 목표가 그리디를 미는 방식을 잠근다 (#67 6차, 사용자 승인 2026-08-12).

가중 합산은 **한 축이 지배한다** — DPS 가중치가 크면 EHP가 바닥이어도 DPS 수가
항상 이긴다. "한쪽으로 쏠리지 않게"는 가중치를 손으로 맞춰서가 아니라 **경계를
채우면 다음 축으로 넘어가게** 해서 얻는다.
"""

from __future__ import annotations

from pok.engine.objective import Target
from pok.engine.tree.deltas import NodeDelta
from pok.engine.tree.optimize import Objective, _target_notes

_TARGETS = (
    Target("TotalEHP", ">=", 8000, "EHP 하한"),
    Target("CombinedDPS", ">=", 2_000_000, "딜 목표"),
)
_OBJ = Objective(weights={"CombinedDPS": 1.0, "TotalEHP": 0.5}, targets=_TARGETS)


def _nd(points: int = 1, **deltas: float) -> NodeDelta:
    return NodeDelta(
        node_id=1, name_en="x", name_ko="x", kind="notable", points=points, path=(1,), deltas=deltas
    )


def test_병목_축이_다른_축을_압도한다() -> None:
    """EHP가 하한 아래면 DPS 50% 증가보다 EHP 20% 증가가 이겨야 한다.

    가중 합산이었다면 DPS 가중치가 두 배라 정반대로 뽑는다.
    """
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 5000}
    assert _OBJ.focus(base).metric == "TotalEHP"
    assert _OBJ.score(_nd(TotalEHP=1000.0), base) > _OBJ.score(_nd(CombinedDPS=500_000.0), base)


def test_충족되면_다음_축으로_넘어간다() -> None:
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 8200}
    assert _OBJ.focus(base).metric == "CombinedDPS"
    assert _OBJ.score(_nd(CombinedDPS=500_000.0), base) > _OBJ.score(_nd(TotalEHP=1000.0), base)


def test_충족한_경계를_깨는_수는_배제된다() -> None:
    """이게 없으면 그리디가 EHP 경계를 헐어 DPS로 옮긴다 — 쏠림의 전형이다."""
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 8200}
    assert _OBJ.score(_nd(TotalEHP=-500.0, CombinedDPS=900_000.0), base) == float("-inf")
    # 경계를 안 깨는 만큼만 내주는 수는 살아 있다
    assert _OBJ.score(_nd(TotalEHP=-100.0, CombinedDPS=900_000.0), base) > 0


def test_전부_충족하면_가중합으로_돌아간다() -> None:
    base = {"CombinedDPS": 3_000_000, "TotalEHP": 9000}
    assert _OBJ.focus(base) is None
    plain = Objective(weights=_OBJ.weights)
    assert _OBJ.score(_nd(CombinedDPS=100.0), base) == plain.score(_nd(CombinedDPS=100.0), base)


def test_못_재는_축은_건너뛰고_그_사실을_말한다() -> None:
    """PoB가 못 재는 축을 목표로 걸면 델타가 전부 0이라 **한 걸음도 못 민다**.

    조용히 넘어가면 "최적화했는데 안 올랐다"로 읽힌다 — 안 오른 게 아니라
    안 재진 것이다(BACKLOG 형태 ②·#44).
    """
    obj = Objective(
        weights={"CombinedDPS": 1.0},
        targets=(Target("TriggerRate", ">=", 5, "발동률"), Target("CombinedDPS", ">=", 2e6)),
    )
    base = {"CombinedDPS": 1_000_000}  # TriggerRate 없음 = 측정 불가
    assert obj.focus(base).metric == "CombinedDPS", "못 재는 축에 걸려 멈추면 안 된다"
    notes = _target_notes(obj, base)
    assert any("재지 못했다" in n for n in notes), "못 잰 사실을 말하지 않으면 0으로 읽힌다"


def test_목표가_없으면_기존_동작_그대로() -> None:
    plain = Objective(weights={"CombinedDPS": 1.0, "TotalEHP": 0.5})
    base = {"CombinedDPS": 1_000_000, "TotalEHP": 5000}
    assert plain.score(_nd(CombinedDPS=100_000.0), base) == 0.1
    assert plain.focus(base) is None
