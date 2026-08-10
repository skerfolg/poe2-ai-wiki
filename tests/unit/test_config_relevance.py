"""미설정 config 수집 — 조건을 요구하는 것은 젬만이 아니다 (#36)."""

from __future__ import annotations


def test_unset_config_sees_tree_nodes_and_items() -> None:
    """조건은 젬만 요구하는 게 아니다 — **할당 노드·장착 아이템**도 본다 (#36).

    실측 2026-08-09(점화 빌드): `conditionEnemyIgnited`가 미설정인데 **언급조차
    없어서** 두 노드가 조용한 0으로 찍혔다 — 하나는 그 0을 보고 트리에서 걷어냈다.

        24630 노호(1포인트)         Δ0 → config 켜면 **+4,282**
        51868 녹아내린 갑각(2포인트)  Δ0 → config 켜면 **+4,608** · EHP +1,417

    `from` 칸이 **누가 요구하는지**를 말해야 한다 — 젬 이름만 나오면 노드가 원인일
    때 추적이 끊긴다(요청안 2).
    """
    from pok.mcp.tools.build import _unset_config

    spec = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "tree_nodes": [24630],
        "skills": [],
        "items": [],
    }
    unset = _unset_config(spec)
    by_var = {u["var"]: u for u in unset}
    assert "conditionEnemyIgnited" in by_var, sorted(by_var)
    assert by_var["conditionEnemyIgnited"]["from"] == "passive.24630", by_var

    # 아이템 경로도 같다 — 스펙 줄이 아니라 **모드 줄**에서 조건을 읽는다
    with_item = _unset_config(
        {
            **spec,
            "tree_nodes": [],
            "items": [
                {
                    "slot": "Gloves",
                    "text": "Rarity: RARE\nProbe\nAdvanced Vaal Cuirass\n"
                    "Crafted: true\n40% increased Damage against Ignited Enemies",
                }
            ],
        }
    )
    assert any(u["var"] == "conditionEnemyIgnited" for u in with_item), with_item
    assert any(str(u["from"]).startswith("item:") for u in with_item), with_item

    # 게이트는 양방향 — 조건을 켜 두면 다시 말하지 않는다
    configured = _unset_config({**spec, "config": {"conditionEnemyIgnited": True}})
    assert not any(u["var"] == "conditionEnemyIgnited" for u in configured), configured
