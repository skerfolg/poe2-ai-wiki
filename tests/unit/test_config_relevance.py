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


def test_부정_문구는_관련성이_아니다() -> None:
    """`Cannot inflict …`에 걸린 키워드는 관련이 아니라 **반대**다.

    실측 2026-08-21: 원소 작렬(`Cannot inflict Freeze, Shock or Ignite`)에
    `multiplierFreezeShockIgniteOnEnemy`가 붙었다. 그 힌트를 좇아 config를
    1↔20으로 바꿔도 값이 안 변하는 것을 **PoB 버그로 의심하고 백로그에 올렸다** —
    거짓 힌트는 없는 결함을 조사하게 만든다.
    """
    from pok.engine.constraints.config_relevance import find_unset_options

    negated = find_unset_options(
        {"skill.probe": ["Cannot inflict Freeze, Shock or Ignite", "Pulse radius is 5 metres"]},
        [],
    )
    assert not any(u.var == "multiplierFreezeShockIgniteOnEnemy" for u in negated), negated


def test_승수형_config는_소비하는_per_문구가_있어야_관련이다() -> None:
    """`ifMult` config는 승수를 **세울** 뿐이다 — 쓰는 접사가 없으면 값이 안 변한다.

    PoB에서 이 승수의 유일한 소비처는 `ModParser`의 `per freeze, shock and ignite
    on enemy` 문구다. 그 문구가 빌드에 없으면 켜라고 알릴 이유가 없다.
    """
    from pok.engine.constraints.config_relevance import find_unset_options

    # 키워드는 다 있지만 "per …"가 없다 → 관련 아님
    mentions_only = find_unset_options(
        {"skill.probe": ["Deals more damage to enemies with Freeze, Shock and Ignite"]}, []
    )
    assert not any(u.var == "multiplierFreezeShockIgniteOnEnemy" for u in mentions_only)

    # 실제 소비 문구가 있으면 관련이다
    consumer = find_unset_options(
        {"passive.probe": ["10% increased Damage per Freeze, Shock and Ignite on Enemy"]}, []
    )
    assert any(u.var == "multiplierFreezeShockIgniteOnEnemy" for u in consumer), consumer


def test_승수형_필터가_기존_진짜_양성을_죽이지_않는다() -> None:
    """절개 스택(#이관 3의 회귀 사례)은 계속 나와야 한다 — 필터는 좁게만 자른다."""
    from pok.engine.constraints.config_relevance import find_unset_options
    from pok.kb import store as kb_store

    stats = (kb_store.load().get("support.incision").raw["data"].get("stats")) or []
    found = {u.var for u in find_unset_options({"support.incision": stats}, [])}
    assert "multiplierIncisionStackCount" in found, sorted(found)
