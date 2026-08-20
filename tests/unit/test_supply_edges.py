"""공급 엣지 스캔(#91) — 2026-08-19 수동 조사를 골든으로 회귀 고정.

수동 조사(스태킹 축 전수 → 연계 사슬 그래프)가 손으로 확인한 앵커들이
도구에서도 그대로 나와야 한다. 특히 **함정 4건**(BACKLOG #91)의 회귀를 막는다:
① 구변형 부활(Prism Guardian) ② 정적/전역 혼동(가짜 순환) ③ 잡음(초당·플로우)
④ 배타 누락(전직 잠금·슬롯).
"""

from __future__ import annotations

import pytest

from pok.kb import store as kb_store
from pok.kb.graph.supply import (
    SupplyScan,
    _parse_line,
    scan_supply_edges,
    trace_chains,
)
from pok.kb.store import Store


@pytest.fixture(scope="module")
def store() -> Store:
    return kb_store.load()


@pytest.fixture(scope="module")
def scan(store: Store) -> SupplyScan:
    return scan_supply_edges(store)


def _edges_of(scan: SupplyScan, carrier_id: str) -> list:
    return [e for e in scan.edges if e.carrier_id == carrier_id]


# ── 순수 파서 — 분류 규칙 단위 ──────────────────────────────────────────


def test_parser_supply_flat() -> None:
    [(src, kind, target, _, scope, per)] = list(
        _parse_line("+2 maximum Energy Shield per 5 Strength")
    )
    assert (src, kind, target, scope, per) == ("strength", "supply", "energy_shield", "global", "5")


def test_parser_payoff_when_target_is_not_an_axis() -> None:
    [(src, kind, target, text, _, _)] = list(
        _parse_line("(8-12)% increased Spell Damage per 10 Spirit")
    )
    assert (src, kind, target) == ("spirit", "payoff", None)
    assert "Spell Damage" in text


def test_parser_derived_stat_is_payoff() -> None:
    """Spirit **Reservation Efficiency**는 Spirit 총량이 아니다 — 함정 ④의 이웃."""
    [(src, kind, target, _, _, _)] = list(
        _parse_line(
            "1% increased Spirit Reservation Efficiency of Buff Skills per 100 Maximum Life"
        )
    )
    assert (src, kind, target) == ("life", "payoff", None)


def test_parser_recipient_is_payoff() -> None:
    """ "Minions deal … per 5 Dexterity"는 소환수 수 공급이 아니다."""
    [(_, kind, target, _, _, _)] = list(
        _parse_line("Minions deal 1% increased Damage per 5 Dexterity")
    )
    assert (kind, target) == ("payoff", None)


def test_parser_skips_per_second_but_keeps_real_source() -> None:
    """비율 표기(per second)는 소스가 아니다 — 진짜 소스만 남는다 (함정 ③)."""
    [(src, kind, _, _, _, _)] = list(
        _parse_line("Regenerate 0.05 Life per second per Maximum Energy Shield")
    )
    assert (src, kind) == ("energy_shield", "payoff")


def test_parser_flow_scope() -> None:
    """소모 이벤트는 스택이 아니라 플로우다 — scope로 표시되고 사슬에선 빠진다."""
    [(src, _, _, _, scope, _)] = list(
        _parse_line("Skills deal 8% increased Damage per Combo consumed, up to 40%")
    )
    assert (src, scope) == ("combo", "flow")


def test_parser_non_axis_event_source_is_dropped() -> None:
    """ "per Enemy Hit"는 축이 아니다 — 엣지가 아예 안 나온다."""
    assert list(_parse_line("Gain 25 Life per Enemy Hit with Attacks")) == []


def test_parser_equal_to_form() -> None:
    [(src, kind, target, _, _, per)] = list(
        _parse_line("Your maximum Energy Shield is equal to (200-300)% of your Strength")
    )
    assert (src, kind, target) == ("strength", "supply", "energy_shield")
    assert per == "(200-300)%"


def test_parser_as_extra_form() -> None:
    [(src, kind, target, _, _, _)] = list(
        _parse_line("Gain (4-6)% of maximum Mana as Extra maximum Energy Shield")
    )
    assert (src, kind, target) == ("mana", "supply", "energy_shield")


def test_parser_as_extra_damage_is_not_supply() -> None:
    """피해 전환("Cold Damage as Extra Chaos")은 축 공급이 아니다."""
    results = list(_parse_line("Gain 1% of Cold Damage as Extra Chaos Damage per Frenzy Charge"))
    assert all(kind == "payoff" for _, kind, *_ in results)


# ── 골든 앵커 — 2026-08-19 수동 조사 재현 ───────────────────────────────


def test_rathpith_double_payoff(scan: SupplyScan) -> None:
    """래스피스 구체: 생명 하나로 치확+피해 2갈래, 대가 줄 동반."""
    edges = _edges_of(scan, "item.rathpith-globe")
    payoffs = [e for e in edges if e.kind == "payoff" and e.source_axis == "life"]
    assert len(payoffs) == 2
    assert {e.slot for e in payoffs} == {"focus"}
    assert any("cost an additional" in c for e in payoffs for c in e.costs)


def test_beidat_life_to_spirit_with_lock_and_cost(scan: SupplyScan) -> None:
    """Beidat's Will: 생명→정신력 supply + 전직 잠금 + 점유 대가 (함정 ④)."""
    [edge] = [e for e in _edges_of(scan, "passive.beidats-will-46644") if e.kind == "supply"]
    assert (edge.source_axis, edge.target_axis) == ("life", "spirit")
    assert edge.ascendancy is not None and "Infernalist" in edge.ascendancy
    assert any("Reserves 25% of Life" in c for c in edge.costs)


def test_prism_guardian_stale_variant_stays_dead(scan: SupplyScan) -> None:
    """함정 ①: 현행 Prism Guardian에 생명→정신력 supply가 있으면 회귀다."""
    edges = _edges_of(scan, "item.prism-guardian")
    assert not any(e.kind == "supply" and e.target_axis == "spirit" for e in edges)


def test_inherent_bonuses_come_from_kb_not_constants(scan: SupplyScan) -> None:
    """속성 고유 보너스 3종이 Mechanic 정의문에서 나온다 (패치 갱신 추종)."""
    pairs = {(e.source_axis, e.target_axis) for e in scan.edges if e.carrier_kind == "mechanic"}
    assert {("strength", "life"), ("intelligence", "mana"), ("dexterity", "accuracy")} <= pairs


def test_crimson_power_is_item_static(scan: SupplyScan) -> None:
    """함정 ②: 아이템 ES→생명은 정적 판독 — 전역 사슬에 못 들어간다."""
    [edge] = [e for e in _edges_of(scan, "passive.crimson-power-31223") if e.kind == "supply"]
    assert edge.scope == "item_static"


def test_cost_chain_covenant(scan: SupplyScan) -> None:
    """비스탯 축: 마나 코스트→생명 코스트 (The Covenant)."""
    assert any(
        e.kind == "supply" and (e.source_axis, e.target_axis) == ("mana_cost", "life_cost")
        for e in _edges_of(scan, "item.the-covenant")
    )


def test_cultivated_duplicates_are_skipped_with_reason(scan: SupplyScan) -> None:
    """함양 사본(#66)은 담체 이중 계상 — 조용히가 아니라 사유와 함께 빠진다."""
    assert not any(e.carrier_id.endswith("-cultivated") for e in scan.edges)
    assert any(r.startswith("cultivated_duplicate") for r, _ in scan.skipped)


def test_no_modifier_carriers(scan: SupplyScan) -> None:
    """함정 ①: 접사 레코드는 구변형을 되살린다 — 스캔 대상이 아니다."""
    assert all(e.carrier_kind in ("item", "passive", "mechanic", "derived") for e in scan.edges)


def test_penetrate_survives_kb_line_wrap(scan: SupplyScan) -> None:
    """개행으로 잘린 문장을 잇는다 — 아마존 Penetrate(명중→물리 피해)가 그 실증.

    KB 노드 stats가 툴팁 줄바꿈을 보존해 "… equal" / "to 25% of the Accuracy …"
    두 줄이었고, 마커가 잘려 명중 스태킹의 핵심 보상이 통째로 빠졌다
    (실측 2026-08-19, 사용자 테스트 "아까처럼 스태킹 연계는 못 찾나?").
    """
    edges = _edges_of(scan, "passive.penetrate-41008")
    assert any(e.source_axis == "accuracy" and e.kind == "payoff" for e in edges)


def test_anoint_route_is_visible(scan: SupplyScan) -> None:
    """성유 노터블(전직·트리 위치 무관 획득)은 acquisition으로 표시된다 —
    힘→명중 다리(Nimble Strength)가 성유라는 것이 설계 정보다."""
    [edge] = [e for e in _edges_of(scan, "passive.nimble-strength-40292") if e.kind == "supply"]
    assert edge.acquisition == "anointable"


def test_spirit_minion_bridge_is_derived_not_curated(scan: SupplyScan, store: Store) -> None:
    """정신력→소환수 다리는 **구조화 필드에서 파생**된다 — 코드 표 큐레이션이 아니라.

    1차 구현(코드 표)은 사용자 판정으로 기각됐다(2026-08-19): "새 규칙마다 수동
    추가는 운영이 안 된다". Skill.data.reservation x minion 태그에서 매 스캔
    계산하므로 새 시즌 소환수 스킬이 정본에 들어오면 다리가 자동 갱신된다.
    다리가 없으면 생명→정신력→소환수 사슬(Beidat's Will → Hysseg's Claw)이 끊긴다.
    """
    derived = [e for e in scan.edges if e.carrier_kind == "derived"]
    [bridge] = [e for e in derived if (e.source_axis, e.target_axis) == ("spirit", "minion_count")]
    assert bridge.carrier_id == "kb:skill.reservation"
    assert "파생" in bridge.evidence and "예:" in bridge.evidence  # 건수+실례가 근거다
    trace = trace_chains(store, "life", depth=3)
    assert any(c.axes == ("life", "spirit", "minion_count") for c in trace.chains)
    assert dict(trace.payoff_counts).get("minion_count", 0) >= 2  # Hysseg's·Dark Defiler


def test_unsourced_axes_are_visible(scan: SupplyScan) -> None:
    """공급 경로 없는 축은 침묵하지 않는다 — 다리 갭 가시성의 절반.

    속성은 비례 공급이 구조적으로 0(플랫뿐)이라 여기 항상 나온다 — 순환 부재
    발견과 같은 사실의 다른 면이다. 이 목록에서 축이 빠지는 것은 공급 엣지가
    새로 생겼다는 뜻이니, 그것대로 뉴스다.
    """
    assert "strength" in scan.unsourced_axes
    assert "spirit" not in scan.unsourced_axes  # Beidat's Will이 공급한다


# ── 사슬 순회 ────────────────────────────────────────────────────────────


def test_trace_strength_reaches_rathpith_via_life(store: Store) -> None:
    """사용자 예시: 힘 스택 → 생명(고유 보너스) → 생명 payoff(래스피스)."""
    trace = trace_chains(store, "strength", depth=2)
    assert any(c.axes[:2] == ("strength", "life") for c in trace.chains)
    assert dict(trace.payoff_counts).get("life", 0) >= 2  # 래스피스 2갈래 포함


def test_trace_uses_global_scope_only(store: Store) -> None:
    """함정 ②③: 정적 판독·플로우 엣지는 사슬에 못 들어간다."""
    trace = trace_chains(store, "strength", depth=3)
    for chain in trace.chains:
        assert all(e.scope == "global" for e in chain.edges)


def test_no_viable_cycles(store: Store) -> None:
    """2026-08-19 구조 발견: 순환은 구조적으로 없다 — 생기면 그것 자체가 뉴스다.

    (진짜 순환이 새 패치에서 생겼다면 이 테스트를 지우지 말고 #91에 기록할 것.)
    """
    for axis in ("strength", "life", "mana", "intelligence", "evasion"):
        trace = trace_chains(store, axis, depth=4, max_chains=200)
        assert all(not c.viable for c in trace.cycles), (axis, trace.cycles)


def test_stacking_jargon_diagnosis_points_here() -> None:
    """강제 지점(철칙 5): '스태킹' 은어 0건 진단이 이 도구를 가리킨다.

    문서 지침만으로는 도구가 안 꺼내진다 — "스태킹 빌드 찾아줘" 세션이
    `search_kb`에서 막혔을 때 진단이 `scan_supply_edges`/`trace_chains`로
    보내야 구현만 해놓고 한 번도 안 꺼내지는 일이 없다(사용자 지적 2026-08-19).
    """
    from pok.index.search import diagnose_empty

    for query in ("stacking build", "스태킹 빌드"):
        diag = diagnose_empty(query=query)
        assert any("scan_supply_edges" in r and "trace_chains" in r for r in diag.reasons), query


def test_conflict_annotation_on_slot_collision(store: Store) -> None:
    """함정 ④: 같은 슬롯을 두 담체가 요구하면 사슬에 충돌이 표시된다."""
    trace = trace_chains(store, "strength", depth=3, max_chains=200)
    flagged = [c for c in trace.chains if c.conflicts]
    assert any("슬롯 충돌" in conflict for c in flagged for conflict in c.conflicts)
