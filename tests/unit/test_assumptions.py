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


def test_ascendancy_entry_requires_start_node() -> None:
    """어센던시 노드를 찍었으면 시작 노드도 있어야 한다."""
    assert check_ascendancy_entry([SANGUIMANCY]) != ""
    assert check_ascendancy_entry([SANGUIMANCY, BLOOD_MAGE_START]) == ""
    assert check_ascendancy_entry([]) == ""


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
        "items": [
            {
                "slot": "Ring 1",
                "text": "Rarity: RARE\nR\nGold Ring\nImplicits: 0\n"
                "15% increased Magnitude of Bleeding you inflict",
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
    assert len(bad.blocking) == 3, "해금 불가 + 어센던시 진입 + 근거 없는 config"
    clean = check_assumptions(
        {
            "class_name": "Witch",
            "ascendancy": "Witch2",
            "tree_nodes": [SANGUIMANCY, BLOOD_MAGE_START],
            "config": {"enemyLevel": 82},
        }
    )
    assert clean.blocking == (), "정상 빌드는 통과해야 한다"
