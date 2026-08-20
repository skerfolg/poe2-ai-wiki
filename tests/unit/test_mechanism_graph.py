"""메커니즘 상태 그래프(#92) — 수동 실행(2026-08-20)의 발견을 회귀 고정.

이 그래프가 만들어진 계기: 탐색 도구 3종이 모두 0.5 신규 메커니즘을 못 봤다.
어휘(KD-2)에 축이 없으면 요구·공급이 **통째로 보이지 않는다** — 저주(2026-08-06)·
출혈(2026-08-04)에 이은 같은 형태의 세 번째 재발이라, 어휘 확장 자체를 테스트로 막는다.
"""

from __future__ import annotations

import pytest

from pok.kb import store as kb_store
from pok.kb.graph.mechanism import (
    StateScan,
    find_transitions,
    scan_state_edges,
    trace_mechanism_chains,
)
from pok.kb.graph.predicates import SUPPLIABLE_SUBJECTS
from pok.kb.store import Store

# vocab v2에서 추가된 0.5 축 — 하나라도 빠지면 그 축은 탐색에서 사라진다.
NEW_AXES = (
    "self.infusion.count",
    "self.combo.count",
    "self.ward.pct",
    "self.seal.count",
    "env.remnant.available",
    "env.fissure.count",
    "env.ground-effect",
)


@pytest.fixture(scope="module")
def store() -> Store:
    return kb_store.load()


@pytest.fixture(scope="module")
def scan(store: Store) -> StateScan:
    return scan_state_edges(store)


# ── 어휘 (KD-2 v2) ──────────────────────────────────────────────────────


def test_new_axes_are_in_controlled_vocabulary(store: Store) -> None:
    """0.5 신규 축이 통제 어휘에 있어야 술어가 살아난다 (없으면 전량 침묵)."""
    missing = [a for a in NEW_AXES if a not in store.subjects]
    assert not missing, f"어휘에 없는 축: {missing} — 그 축은 요구·공급이 안 보인다"


def test_new_axes_are_suppliable(store: Store) -> None:
    """전부 「무언가가 만들어 주는」 축이다 — 공급 개념이 서므로 갭 주장의 사정거리에 든다."""
    assert set(NEW_AXES) <= SUPPLIABLE_SUBJECTS


def test_new_axes_actually_match_canon(scan: StateScan) -> None:
    """어휘만 넣고 패턴이 안 맞으면 축은 여전히 비어 있다 — 실물로 확인한다.

    실측 2026-08-20: 룬 수호 54건·지면 효과 52건·잔류물 23건·균열 23건·주입 14건이
    정본 문구에 있었는데 축이 없어 도구가 한 건도 못 봤다.
    """
    by_axis = {a.axis: a for a in scan.axes}
    for axis in ("infusion", "combo", "ward", "seal", "remnant", "fissure", "ground_effect"):
        assert axis in by_axis, f"{axis} 축이 엣지를 하나도 못 냈다"
        total = by_axis[axis].producers + by_axis[axis].consumers + by_axis[axis].payoffs
        assert total >= 3, f"{axis}: 엣지 {total}건 — 패턴이 정본 문구를 못 읽는다"


# ── 융합 (구조화 타입 + 텍스트) ─────────────────────────────────────────


def test_both_sources_contribute(scan: StateScan) -> None:
    """어느 한쪽만 쓰면 그래프가 절반이다 — 두 출처가 모두 엣지를 내야 한다."""
    sources = {e.source for e in scan.edges}
    assert sources == {"type", "text"}


def test_consume_only_comes_from_structured_types(scan: StateScan) -> None:
    """텍스트는 「없앤다」를 구분 못 한다 — 소비 판정은 타입 출처에만 있어야 한다.

    이 구분이 무너지면 같은 상태를 두 번 먹는 불가능한 연쇄가 사슬로 나온다.
    """
    assert all(e.source == "type" for e in scan.edges if e.kind == "consume")


def test_freeze_axis_has_both_producer_and_consumer(scan: StateScan) -> None:
    """동결은 텍스트가 생산을(냉기 스킬), 타입이 소비를(SkillConsumesFreeze) 낸다."""
    freeze = [e for e in scan.edges if e.axis == "freeze"]
    assert any(e.kind == "produce" and e.source == "text" for e in freeze)
    assert any(e.kind == "consume" and e.source == "type" for e in freeze)


# ── 전이·사슬 ────────────────────────────────────────────────────────────


def test_snap_is_an_elemental_converter(scan: StateScan) -> None:
    """`Snap`은 원소 상태이상을 먹고 주입·잔류물을 만든다 — 수동 실행의 대표 발견."""
    transitions = [t for t in find_transitions(scan) if t.carrier_name == "Snap"]
    pairs = {(t.from_axis, t.to_axis) for t in transitions}
    assert {"freeze", "shock", "ignite"} <= {f for f, _ in pairs}
    assert {"infusion", "remnant"} <= {to for _, to in pairs}


def test_chain_paths_are_deduped_by_axes(store: Store) -> None:
    """같은 축 경로는 담체 수만큼 복제하지 않고 마디 선택지로 묶는다.

    실측 2026-08-20: 묶기 전에는 사슬 200건이 대부분 같은 경로의 중복이었다.
    """
    trace = trace_mechanism_chains(store, depth=4, max_chains=200)
    paths = [tuple(c.axes) for c in trace.chains]
    assert len(paths) == len(set(paths))
    multi = [c for c in trace.chains if any(len(o) > 1 for o in c.hop_options)]
    assert multi, "선택지가 여럿인 마디가 하나도 없다 — 묶기가 동작하지 않았다"


def test_multi_hop_chain_exists(store: Store) -> None:
    """3단 이상 사슬이 실제로 나온다 — 쌍만 내던 기존 도구와의 차이."""
    trace = trace_mechanism_chains(store, depth=4, max_chains=200)
    long_chains = [c for c in trace.chains if len(c.axes) >= 3]
    assert long_chains
    assert any(c.axes[:2] == ("freeze", "infusion") for c in trace.chains)


def test_hop_options_carry_evidence(store: Store) -> None:
    """마디마다 근거 문구가 붙어야 사람이 판정할 수 있다(AD-8)."""
    trace = trace_mechanism_chains(store, from_axis="freeze", depth=3)
    assert trace.chains
    for chain in trace.chains:
        for transition in chain.transitions:
            assert transition.evidence_in and transition.evidence_out


def test_unproduced_axes_are_reported(scan: StateScan) -> None:
    """생산자 없는 축은 침묵하지 않는다 — 수집 갭인지 어휘 갭인지 사람이 본다."""
    assert scan.unproduced_axes
    # 격노는 소비자(ConsumesRage)가 있는데 생산 패턴이 없다 — 알려진 어휘 갭이다.
    assert "rage" in scan.unproduced_axes
