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
    """어느 하나만 쓰면 그래프가 조각난다 — 네 출처가 모두 엣지를 내야 한다.

    `type`(구조화 토큰) · `text`(상태이상 술어) · `object`(월드 객체, #95) ·
    `umbrella`(상위 상태 전파, #96).
    """
    sources = {e.source for e in scan.edges}
    assert sources == {"type", "text", "object", "umbrella"}


def test_소비_판정은_술어_텍스트에서_나오지_않는다(scan: StateScan) -> None:
    """상태이상 **술어**는 「없앤다」를 구분 못 한다 — 소비는 거기서 나오면 안 된다.

    "against Chilled Enemies"는 냉각을 **먹지 않는다**(페이오프일 뿐). 이 구분이
    무너지면 같은 상태를 두 번 먹는 불가능한 연쇄가 사슬로 나온다.

    ⚠ 단 **객체 출처는 예외다**(#95): `Consume a Corpse`·`detonate`는 문구 자체가
    **제거를 명시**하므로 소비로 읽는 것이 옳다. 상태이상 술어와 성격이 다르다.
    """
    consume_sources = {e.source for e in scan.edges if e.kind == "consume"}
    assert consume_sources <= {"type", "object"}
    assert "text" not in consume_sources


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
    """3단 이상 사슬이 실제로 나온다 — 쌍만 내던 기존 도구와의 차이.

    ⚠ 특정 사슬은 **출발 축을 지정해** 확인한다. 전체 순회는 `max_chains` 상한에
    걸리므로(축이 늘면 먼저 잘린다) 거기서 특정 경로를 찾으면 테스트가 축 개수에
    따라 깨진다 — 실제로 충전을 종류별로 가른 뒤 그렇게 깨졌다(#95).
    """
    trace = trace_mechanism_chains(store, depth=4, max_chains=200)
    assert [c for c in trace.chains if len(c.axes) >= 3]

    freeze = trace_mechanism_chains(store, from_axis="freeze", depth=3)
    assert any(c.axes[:2] == ("freeze", "infusion") for c in freeze.chains)


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


# ── 월드 객체 축 (#95) ──────────────────────────────────────────────────


def test_객체_연쇄가_잡힌다(scan: StateScan) -> None:
    """「A가 만든 객체를 B가 대상으로 쓴다」 — 상태 그래프에도 호스팅 도구에도 없던 축.

    사용자 지적 2026-08-21: "번개 차원 이동은 구형 번개를 대상으로 사용할 수 있다."
    구조화 타입에도 통제 어휘에도 없어 어느 도구에도 안 잡혔다.
    """
    warp = [
        e for e in scan.edges if e.axis == "ball_lightning" and e.carrier_name == "Lightning Warp"
    ]
    assert warp and warp[0].kind == "consume"
    assert "Ball Lightning" in warp[0].evidence
    assert warp[0].source == "object"


def test_자기_서술은_연쇄가_아니다() -> None:
    """`Fissure duration is 8 seconds`는 그 스킬이 **자기 객체의 속성**을 말하는 것이다.

    안 거르면 이론 쌍이 872 → 3,455로 **4배 부풀려진다**(실측 2026-08-21).
    """
    from pok.kb.graph.mechanism import object_edges_of

    assert object_edges_of(["Ice Crystal duration is 8 seconds"]) == ()
    assert object_edges_of(["Shockwave radius is 2 metres"]) == ()
    assert object_edges_of(["Limit 8 Fissures"]) == ()
    # 진짜 연쇄는 살아남는다
    real = object_edges_of(["Bolts that hit an Ice Crystal cause it to explode."])
    assert any(a == "ice_crystal" and k == "consume" for a, k, _ in real)


def test_객체_부정문은_관계가_아니다() -> None:
    """#93의 교훈(극성)을 객체 축에도 적용한다 — `cannot`은 반대다."""
    from pok.kb.graph.mechanism import object_edges_of

    assert object_edges_of(["Cannot consume Corpses"]) == ()


def test_한_문장이_생성과_소비를_함께_말할_수_있다() -> None:
    """`Consume a Corpse to create a Zombie` — 둘 다 내야 사슬이 이어진다."""
    from pok.kb.graph.mechanism import object_edges_of

    kinds = {k for _, k, _ in object_edges_of(["Consume a Corpse to create a short-lived Zombie."])}
    assert kinds == {"produce", "consume"}


def test_객체_축이_상태_그래프와_한_그래프에_있다(scan: StateScan) -> None:
    """세 번째 평행 그래프를 만들지 않는다 — 축 어휘 분열을 키우지 않기 위해서다.

    실측 배경: #91(28축) vs #92(32축)인데 공유가 2종뿐이라 교차 순회가 불가능했다.
    객체는 생산/소비 의미론이 상태와 같으므로 같은 스캔에 얹는다.
    """
    sources = {e.source for e in scan.edges}
    assert {"type", "text", "object"} <= sources
    axes = {a.axis for a in scan.axes}
    assert {"corpse", "ice_crystal", "shockwave"} <= axes  # 객체
    assert {"freeze", "charge", "infusion"} <= axes  # 상태·자원


def test_객체가_낀_전이가_실제로_나온다(store: Store) -> None:
    """객체 축이 붙으면서 새 전이가 열려야 한다 — 안 열리면 축만 늘고 사슬은 그대로다."""
    transitions = find_transitions(scan_state_edges(store))
    obj = {"corpse", "ball_lightning", "frostbolt", "ice_crystal", "shockwave"}
    crossing = {(t.from_axis, t.to_axis) for t in transitions if obj & {t.from_axis, t.to_axis}}
    assert len(crossing) >= 10, sorted(crossing)
    assert ("corpse", "minion") in crossing  # 시체 → 소환수 (좀비 소환 등)


# ── 우산 상태 (#96) ─────────────────────────────────────────────────────


def test_우산_관계는_정본에서_유도된다(store: Store) -> None:
    """「A는 B로도 친다」를 **손으로 적지 않는다** — 정본 Mechanic 문구에서 읽는다.

    사용자 지적 2026-08-20: "새로운 규칙을 찾을 때마다 수동으로 추가하라고 할 수도
    없고말야. 서비스를 운영한다고 생각하면 이런 구조로는 서비스 못하잖아."

    정본은 세 가지 표현형으로 말한다 — 셋 다 읽어야 경로가 안 빠진다:
      ① "Pinned targets count as Immobilised."
      ② "… due to being Frozen, Pinned, Heavy Stunned, or Electrocuted."
      ③ "Usually this occurs because the enemy is Ignited."
    """
    from pok.kb.graph.mechanism import umbrella_relations

    pairs = {(r.source_axis, r.target_axis) for r in umbrella_relations(store)}
    # 속박은 네 경로 **전부** 있어야 한다 — 하나라도 빠지면 공급이 실제보다 적게 세어진다.
    assert {"freeze", "pin", "stun", "electrocute"} == {s for s, t in pairs if t == "immobilise"}
    assert ("ignite", "burning") in pairs
    for relation in umbrella_relations(store):
        assert relation.evidence, "근거 문구 없이는 사람이 판정할 수 없다(AD-8)"


def test_우산_전파가_거짓_공급갭을_지운다(scan: StateScan) -> None:
    """속박·연소는 **자기 이름의 공급 문구가 거의 없다** — 하위 상태가 만들어 준다.

    실측 2026-08-21: 전파 전 속박은 생산 3(그나마 1건은 부정문 오독)·페이오프 18이라
    「공급이 마름」으로 판정됐다. 실제로는 동결·기절·전기충격·고정이 전부 속박을
    만든다 — 도구가 그걸 몰라 **없는 공백을 보고했다**.
    """
    by_axis = {a.axis: a for a in scan.axes}
    assert by_axis["immobilise"].producers >= 20
    assert by_axis["burning"].producers >= 3
    assert "immobilise" not in scan.unproduced_axes
    assert "burning" not in scan.unproduced_axes


def test_우산_엣지는_근거_두_줄을_단다(scan: StateScan) -> None:
    """담체가 하위를 만든다는 문구 + 하위가 상위로 친다는 정본 규칙, 둘 다 필요하다."""
    derived = [e for e in scan.edges if e.source == "umbrella"]
    assert derived
    for edge in derived:
        assert "⟶" in edge.evidence, edge.evidence
        assert edge.kind == "produce"  # 우산은 생산만 전파한다(소비는 상위≠하위)


def test_부정문은_우산_관계가_아니다() -> None:
    """ "You do not count as your own Ally"·"Slam attacks do not count as Strikes"."""
    from pok.kb.graph.mechanism import _UMB_NEGATION

    assert _UMB_NEGATION.search("Slam attacks do not count as ")
    assert not _UMB_NEGATION.search("Pinned targets count as ")


def test_목록_마지막_항목이_조용히_빠지지_않는다() -> None:
    """ "A, B, C, **or** D"의 D는 분리 잔여물 `or `를 달고 나온다 — 안 털면 사라진다."""
    from pok.kb.graph.mechanism import _axis_of_state_name

    assert _axis_of_state_name("or Electrocuted") == "electrocute"
    assert _axis_of_state_name("Heavy Stunned") == "stun"  # 강도는 같은 축으로 접는다
    assert _axis_of_state_name("Pinned") == "pin"


def test_회전수_제약이_엣지에_붙는다(scan: StateScan) -> None:
    """전이의 **유무**만 내면 회전수가 안 보인다 (#124).

    「8초마다 다시 깔아야 하는 사슬」과 「상시 사슬」이 같아 보인다 —

    「연결된다」가 「쓸 수 있다」가 아니다. 실측 2026-08-25: 상태 엣지 1,208건 중
    담체가 `cooldown_s`를 가진 것이 **408건**이다(담체 207종이 여러 축에 걸린다).

    ⚠ `cooldown_s`와 `duration_s`는 **다른 것**이다 — 쿨다운은 「얼마나 자주 걸 수 있나」,
    지속은 「한 번 걸면 얼마나 가나」. 쿨다운 4초·지속 8초면 상시 유지되지만 쿨다운
    8초·지속 4초면 절반은 꺼져 있다. 하나로 뭉치면 그 구분이 사라진다.
    """
    with_cd = [e for e in scan.edges if e.cooldown_s is not None]
    assert with_cd, "쿨다운을 가진 담체의 엣지가 있어야 한다"
    assert any(e.cooldown_s and e.cooldown_s > 0 for e in with_cd), "회전이 제약되는 엣지"


def test_쿨다운_0과_모름은_다르다(scan: StateScan) -> None:
    """⛔ **세 상태가 갈려야 한다** — 0 · 양수 · None (실측 2026-08-25).

        0     명시적 「쿨다운 없다」  304건  → 상시 걸 수 있다
        >0    회전 제약              104건  → 사슬 회전수를 이것이 정한다
        None  모른다                 800건  → 담체에 필드가 없다

    0과 None을 뭉치면 「상시 걸 수 있다」와 「모른다」가 같아진다 — 정확히 반대 성질이다.
    """
    zero = [e for e in scan.edges if e.cooldown_s == 0]
    positive = [e for e in scan.edges if e.cooldown_s and e.cooldown_s > 0]
    unknown = [e for e in scan.edges if e.cooldown_s is None]
    assert zero and positive and unknown, "세 상태가 모두 실재한다"


def test_모르는_회전수는_None이지_0이_아니다(scan: StateScan) -> None:
    """⛔ `None`은 「제약 없음」이 아니라 **모른다**다.

    0으로 채우면 「상시」로 오독된다 — 없는 것을 0으로 읽지 않는다는 이 저장소의
    반복 규율과 같은 자리다(#109 계열).
    """
    unknown = [e for e in scan.edges if e.cooldown_s is None]
    assert unknown, "회전수를 모르는 엣지가 대부분이다"
    assert all(e.cooldown_s is None for e in unknown), "모르는 것을 0으로 바꾸지 않는다"


def test_문구의_지속을_읽는다(scan: StateScan) -> None:
    """근거 문구에 `for N seconds`가 있으면 읽는다 (§0 ⑧).

    관계가 **문구에 있는데** 도구가 안 읽으면 「없는 공백」을 보고한다 — #96이 그 형태였다.
    """
    with_dur = [e for e in scan.edges if e.duration_s is not None]
    assert with_dur, "문구에 지속이 명시된 엣지가 있어야 한다"
    assert all(e.duration_s and e.duration_s > 0 for e in with_dur)


def test_지면_축은_동시_보유_한도가_1이다(scan: StateScan) -> None:
    """와류는 원소 지면을 **하나만** 흡수한다 (#124 · 사용자 인게임 판정 2026-08-25).

    「연결된다」가 「쓸 수 있다」가 아니다 — 먼저 붙은 지면이 자리를 차지하고, 맵의 잡
    지면이 선점하면 강한 지면으로 **덮어쓰지 못한다**. 지면 축 둘을 잇는 사슬은
    「둘 다 켜진다」가 아니라 **「둘 중 하나」**다.

    ⚠ 정본 문구는 이걸 **명시하지 않는다**(`"takes on that element"`가 단수를 함의할 뿐).
    근거는 사용자 판정이다(AD-3) — `insight.whirlwind-absorbs-one-ground-only`.
    """
    ground = [e for e in scan.edges if e.axis.startswith("ground")]
    assert ground, "지면 축 엣지가 있어야 한다"
    assert all(e.concurrent_cap == 1 for e in ground), "지면은 동시에 하나만 붙는다"


def test_한도를_모르는_축은_None이지_무제한이_아니다(scan: StateScan) -> None:
    """⛔ `None`은 「한도 없음」이 아니라 **모른다**다 (#109 계열).

    무제한으로 읽으면 「얼마든지 쌓인다」가 되어 정반대 결론이 나온다.
    """
    unknown = [e for e in scan.edges if e.concurrent_cap is None]
    assert unknown, "한도를 모르는 축이 대부분이다"
    assert not any(e.axis.startswith("ground") for e in unknown), (
        "지면 축은 판정이 있으므로 None이면 안 된다"
    )
