"""근거 없는 가정 검사 — 인게임 대조로 드러난 결함의 회귀 (사용자 실증 2026-08-06).

생성본이 실제 캐릭터 대비 출혈 강도 x2.76(706,661 vs 239,936)이었고, 차액은
아이템·패시브가 아니라 ① 오라클 전용 해금 노드 7개 ② 공급원 없는 config에서
나왔다. PoB 계산기는 둘 다 검사하지 않고 스탯을 더해 준다.
"""

from __future__ import annotations

from typing import Any

from pok.engine.constraints.assumptions import (
    audit_config,
    check_ascendancy_entry,
    check_assumptions,
    check_locked_nodes,
)

# 오라클 전용 해금 노드 (PoB unlockConstraint = {"ascendancy": "Oracle", "nodes": [5571]})
ORACLE_ONLY = [60014, 48079, 8248]
BLOOD_MAGE_START = 59822
SANGUIMANCY = 8415  # 블러드 메이지 노터블


def test_locked_nodes_are_detected_for_wrong_ascendancy() -> None:
    """블러드 메이지가 오라클 전용 노드를 찍으면 잡아야 한다 — 인게임 불가."""
    locked = check_locked_nodes(ORACLE_ONLY, "Witch2")
    assert {n.node_id for n in locked} == set(ORACLE_ONLY)
    assert all(n.locked_to == "Oracle" for n in locked)
    assert any(
        "출혈 지속시간" in " ".join(n.stats) or "Bleeding Duration" in " ".join(n.stats)
        for n in locked
    ), "부풀림의 정체(지속시간)가 보여야 한다"


def test_locked_nodes_pass_for_the_owning_ascendancy() -> None:
    """오라클 본인에게는 위반이 아니다 — 검사가 정상 빌드를 막으면 안 된다."""
    assert check_locked_nodes(ORACLE_ONLY, "Oracle") == ()


def test_ascendancy_entry_is_reachability_not_list_membership() -> None:
    """어센던시 노드는 **시작 노드에서 닿으면** 된다 — 목록에 있을 필요는 없다 (#26).

    옛 판정식("시작 노드가 `tree_nodes`에 있는가")은 PoB 모델과 어긋나 **어느 쪽으로도
    통과할 수 없었다**: PoB는 시작 노드를 스스로 배정하고 포인트로 세지 않으므로
    목록에 넣으면 `pruned_nodes`에 잡혀 **비연결로 거부**되고, 빼면 이 검사가 거부했다.
    실측 2026-08-09(Witch1): 빼면 이 검사가 거부 / 넣으면 `pruned=(32699,)`.
    **어센던시 빌드를 하나도 조립할 수 없었다.**

    아래 첫 줄이 그 교착의 회귀다 — 옛 코드에서는 이것이 거부였다.
    """
    # 시작 노드를 안 적어도 통과해야 한다 (혈액술은 시작 노드에 인접)
    assert check_ascendancy_entry([SANGUIMANCY]) == ""
    # 적어도 통과한다 — 적는 것이 틀린 건 아니다(PoB가 무시할 뿐)
    assert check_ascendancy_entry([SANGUIMANCY, BLOOD_MAGE_START]) == ""
    assert check_ascendancy_entry([]) == ""


def test_ascendancy_node_unreachable_from_start_is_rejected() -> None:
    """게이트는 살아 있어야 한다 — **할당한 노드만 밟아** 못 닿으면 거부."""
    from pok.common.paths import knowledge_dir
    from pok.engine.tree.graph import TreeGraph

    graph = TreeGraph(knowledge_dir())
    start_adjacent = graph.adj[BLOOD_MAGE_START]
    stranded = next(
        node_id
        for node_id, node in graph.nodes.items()
        if node.ascendancy == graph.nodes[BLOOD_MAGE_START].ascendancy
        and node.kind != "ascendancy-start"
        and node_id not in start_adjacent
    )
    reason = check_ascendancy_entry([stranded])
    assert "닿지 않는다" in reason, reason


def test_ungrounded_config_is_flagged_grounded_is_not() -> None:
    """공급원 없는 config만 차단 — 있는 것은 '상시 가정'으로 남긴다."""
    spec: dict[str, Any] = {
        "class_name": "Witch",
        "config": {
            "multiplierWitheredStackCountSelf": 15,  # 시듦 부여원 없음
            "conditionEnemyBleeding": "true",  # 출혈은 아이템이 공급
            "enemyLevel": 82,  # 시나리오 설정 — 감사 대상 아님
            "conditionEnemyChilled": "false",  # 꺼짐
        },
        # ⚠ 강도 증가는 **공급이 아니다** — 출혈을 걸어 주는 문구가 따로 있어야 한다
        "items": [
            {
                "slot": "Ring 1",
                "text": "Rarity: RARE\nR\nGold Ring\nImplicits: 0\n25% chance to inflict Bleeding",
            }
        ],
    }
    by_var = {v.var: v for v in audit_config(spec)}
    assert by_var["multiplierWitheredStackCountSelf"].status == "ungrounded"
    assert by_var["conditionEnemyBleeding"].status == "grounded"
    assert by_var["enemyLevel"].status == "neutral", "적 스펙은 플레이어 파워가 아니다"
    assert by_var["conditionEnemyChilled"].status == "neutral", "꺼진 값은 파워를 안 만든다"


def test_report_blocks_only_on_real_impossibilities() -> None:
    bad = check_assumptions(
        {
            "class_name": "Witch",
            "ascendancy": "Witch2",
            "tree_nodes": [*ORACLE_ONLY, SANGUIMANCY],
            "config": {"multiplierWitheredStackCountSelf": 15},
        }
    )
    # #26 전에는 3건이었다 — 「어센던시 진입」이 함께 걸렸기 때문이다. 그런데 혈액술은
    # 시작 노드에 **인접**해 실제로 찍을 수 있는 배치라, 그 차단이 오거부였다.
    assert len(bad.blocking) == 2, "해금 불가 + 근거 없는 config (어센던시 진입은 정상 배치)"
    clean = check_assumptions(
        {
            "class_name": "Witch",
            "ascendancy": "Witch2",
            "tree_nodes": [SANGUIMANCY, BLOOD_MAGE_START],
            "config": {"enemyLevel": 82},
        }
    )
    assert clean.blocking == (), "정상 빌드는 통과해야 한다"


def test_status_config_needs_supply_not_mere_mention() -> None:
    """일반형 (사용자 지시 2026-08-06): 요구 문구를 공급으로 오인하면 안 된다.

    피 가시는 "Bleeding you inflict on Cursed targets is Aggravated" — 저주를
    **요구**한다. 이걸 공급으로 세는 바람에 conditionEnemyCursed가 통과했고,
    출혈 악화(100% more Base)가 성립해 강도가 x2.76 부풀었다.
    """
    demand_only = {
        "class_name": "Witch",
        "config": {"conditionEnemyCursed": "true"},
        "items": [
            {
                "slot": "Ring 1",
                "text": "Rarity: RARE\nR\nGold Ring\nImplicits: 0\n"
                "Bleeding you inflict on Cursed targets is Aggravated",
            }
        ],
    }
    verdict = next(v for v in audit_config(demand_only) if v.var == "conditionEnemyCursed")
    assert verdict.status == "ungrounded"
    assert "요구" in verdict.reason, "요구일 뿐이라는 근거가 보여야 한다"

    with_supply = {
        **demand_only,
        "items": [
            *demand_only["items"],
            {
                "slot": "Ring 2",
                "text": "Rarity: RARE\nS\nGold Ring\nImplicits: 0\n"
                "Curse Enemies with Despair on Hit",
            },
        ],
    }
    ok = next(v for v in audit_config(with_supply) if v.var == "conditionEnemyCursed")
    assert ok.status == "grounded", "실제 공급원이 있으면 통과해야 한다"


def test_demand_only_rule_generalizes_beyond_status_vocabulary() -> None:
    """일반형의 상위 층 (사용자 지시 2026-08-06): 어휘에 없는 축도 갈라야 한다.

    "특정 상태를 요구하는 기재가 요구할 뿐 공급하지는 않는다"는 문장 층위의 규칙이라
    통제 어휘(KD-2 33종) 밖의 축 — 불구·시듦·절개 — 에도 그대로 적용된다.
    표지는 조건 단어 **바로 앞**을 본다: "Bleeding you inflict on Cursed targets"의
    inflict는 출혈에 걸린 것이지 저주를 공급하지 않는다.
    """
    from pok.engine.constraints.assumptions import _is_demand_only, _stem_pattern

    def demand_only(lines: list[str], keyword: str) -> bool:
        return _is_demand_only(lines, [_stem_pattern(keyword)])

    assert demand_only(["Bleeding you inflict on Cursed targets is Aggravated"], "Cursed")
    assert demand_only(["25% increased Attack Damage against Maimed Enemies"], "Maimed")
    assert demand_only(["10% increased Damage against Withered Enemies"], "Withered")
    # 공급절이 하나라도 있으면 근거로 인정한다 (보수적 — 오탐이 게이트를 무력화한다)
    assert not demand_only(["Inflict 2 Withered on Hit"], "Withered")
    assert not demand_only(["Gain 1 Rage on Melee Hit"], "Rage")
    assert not demand_only(
        ["Hits from Supported Skills inflict 1 Incision",
         "3% more Magnitude per Incision consumed Recently, up to 30%"],
        "Incision",
    )  # fmt: skip


# 선행 노드 요구형 해금 (실측 2026-08-07, B-13 착수 중 발견) — `unlock_constraint`에
# `ascendancy` 없이 `nodes`만 있는 꼴 3건. 전직 대조만 하던 이전 판은 **그냥 통과**시켰다.
RENEGADE = 51850  # 탈주자의 길 — 노터블 3개를 먼저 찍어야 열린다
RENEGADE_PREREQS = [50239, 9535, 61309]


def test_선행_노드_없이_찍은_해금_노드를_잡는다() -> None:
    """PoB는 선행을 검사하지 않고 카오스 저항 +8%를 그대로 더해 준다."""
    (bad,) = check_locked_nodes([RENEGADE], "Witch2")
    assert bad.node_id == RENEGADE
    assert bad.locked_to == "", "전직 제약이 아니다 — 그래서 이전 검사가 놓쳤다"
    assert set(bad.missing_nodes) == set(RENEGADE_PREREQS)
    assert "선행 노드" in bad.why


def test_선행을_다_찍었으면_위반이_아니다() -> None:
    assert check_locked_nodes([RENEGADE, *RENEGADE_PREREQS], "Witch2") == ()


def test_해금_위반은_조립을_막는다() -> None:
    """검사가 보고만 하고 막지 않으면 규율은 안 지켜진다(철칙 5)."""
    spec: dict[str, Any] = {"class_name": "Witch", "tree_nodes": [RENEGADE], "ascendancy": "Witch2"}
    blocking = check_assumptions(spec).blocking
    assert any("해금 불가 노드" in b and "선행 노드" in b for b in blocking)


def test_전직은_코드로_줘도_해소된다() -> None:
    """빌드 스펙이 드는 값은 실명이 아니라 코드다 — 못 이으면 자기 노드가 위반이 된다."""
    assert check_locked_nodes(ORACLE_ONLY, "Druid1") == ()
