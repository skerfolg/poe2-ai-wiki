"""3층 교차 조인(#95 남은 것 ①②③) — 어휘 통일과 층 병합.

세 그래프가 각각은 도는데 **경계에서 끊겼다**. 실측 2026-08-21: 축 어휘가 28종 vs
32종인데 공유가 **2종뿐**(`combo`·`rage`)이었고, 이름 드리프트도 있었다
(`curse_count`↔`curse`, `minion_count`↔`minion`).
"""

from __future__ import annotations

import pytest

from pok.kb import store as kb_store
from pok.kb.graph.crosswalk import cross_edges, trace_cross_chains
from pok.kb.graph.mechanism import scan_state_edges
from pok.kb.graph.supply import scan_supply_edges
from pok.kb.store import Store


@pytest.fixture(scope="module")
def store() -> Store:
    return kb_store.load()


def test_이름_드리프트가_사라졌다(store: Store) -> None:
    """같은 개념을 두 그래프가 다르게 부르면 교차가 원리적으로 불가능하다."""
    supply_axes = {a.axis for a in scan_supply_edges(store).axes}
    assert "curse_count" not in supply_axes and "minion_count" not in supply_axes
    assert "curse" in supply_axes and "minion" in supply_axes


def test_충전은_종류별로_갈린다(store: Store) -> None:
    """`power_charge` 소비자와 `frenzy_charge` 생산자를 뭉치면 가짜 사슬이 난다.

    종류를 말하지 않는 일반 토큰(`ConsumesCharges`)만 `charge`로 남는다.
    """
    state_axes = {a.axis for a in scan_state_edges(store).axes}
    assert {"power_charge", "frenzy_charge", "endurance_charge"} <= state_axes


def test_지면_효과는_종류별로_갈린다(store: Store) -> None:
    """점화 지대 생산자와 냉각 지대 소비자는 다른 축이다 — 종류가 페이오프를 가른다."""
    axes = {a.axis for a in scan_state_edges(store).axes}
    assert any(a.startswith("ground_") and a != "ground_effect" for a in axes), sorted(axes)


def test_어휘_통일로_공유_축이_늘었다(store: Store) -> None:
    """통일 전 2종(`combo`·`rage`) → 통일 후 7종. 교차가 일어날 수 있는 자리다."""
    _, _, shared = cross_edges(store)
    assert len(shared) >= 7, shared
    assert {"combo", "rage", "curse", "minion", "power_charge"} <= set(shared)


def test_두_층의_페이오프가_합산된다(store: Store) -> None:
    """조인의 실익은 **페이오프 병합**이다 — 한 층만 보면 그 축의 값을 과소평가한다.

    실측 2026-08-21: `power_charge`는 supply층 2 + state층 58 = **60**.
    스탯 그래프만 보면 2건짜리 축으로 보인다.
    """
    _, payoffs, _ = cross_edges(store)
    supply_only = {a.axis: a.payoffs for a in scan_supply_edges(store).axes}
    assert payoffs["power_charge"] > supply_only.get("power_charge", 0) * 5


def test_층_꼬리표가_마디마다_붙는다(store: Store) -> None:
    """층마다 전이의 뜻이 다르다 — supply는 비례, state는 소비다. 뭉개지 않는다."""
    trace = trace_cross_chains(store, from_axis="strength", depth=3)
    assert trace.chains
    for chain in trace.chains:
        assert len(chain.layers) == len(chain.axes) - 1
        assert set(chain.layers) <= {"supply", "state"}


def test_교차_전이가_아직_0이라는_사실을_고정한다(store: Store) -> None:
    """⚠ 이 테스트는 **현재의 구조적 사실**을 박아 둔 것이지 목표가 아니다.

    실측 2026-08-21: 어휘를 통일해 공유 축이 7종이 됐는데도 **층을 넘나드는 전이는
    0건**이다. 방향이 겹치지 않기 때문이다 — supply는 스탯(`life`·`mana`·`spirit`…)에
    도착하고, state는 상태·객체(`freeze`·`corpse`·`charge`…)에서 출발한다. 유일한
    접점인 `minion`은 **소비하는 담체가 없어** 막다른 길이다.

    즉 「스탯을 쌓아 상태를 연다」는 연결이 정본에 아직 드러나 있지 않다. 이것이
    수집 갭인지 게임 구조인지는 **판정 대기**다 — 예: `육체의 연회`는 시체를 먹고
    생명을 **회복**하는데, 회복은 최대치 증가가 아니라 `supply.py`가 일부러 제외한다.

    이 값이 0이 아니게 되면 **그것 자체가 뉴스다** — 테스트를 지우지 말고 #95에
    기록할 것.
    """
    trace = trace_cross_chains(store, depth=4, max_chains=300, cross_only=True)
    crossing = [c for c in trace.chains if c.crosses_layers]
    assert crossing == [], [c.axes for c in crossing]


def test_조인은_새_그래프를_만들지_않는다(store: Store) -> None:
    """엣지는 각 그래프가 낸 것을 그대로 쓴다 — 판정 로직을 복제하면 어긋난다."""
    edges, _, _ = cross_edges(store)
    layers = {e.layer for e in edges}
    assert layers == {"supply", "state"}
    assert all(e.evidence for e in edges)  # 근거 문구가 보존된다(AD-8)
