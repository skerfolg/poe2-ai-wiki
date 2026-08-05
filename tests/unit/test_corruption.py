"""부패 강화 기제 + 조달 경로 표시 (이관 5 C11).

세션이 `Gain (35-50)% of Damage as Extra Physical`을 **유니크** 무기에 얹어 계산하고
+147,750(전체 증가분의 71%)을 보고했다. 희생의 오브는 **희귀(Rare)** 전용이라
성립하지 않는 계획이었다. 요구-수급 규율을 어긴 게 아니라, **소스를 열거할 데이터가
없어서** 규율이 작동할 수 없었다.
"""

from __future__ import annotations

from pok.index.search import get_entry


def test_mechanic_record_states_rare_only() -> None:
    """유니크 대상이 아니라는 것이 조회로 바로 나와야 한다."""
    data = get_entry("mechanic.corruption-upgrade", fields=["data"])["data"]
    joined = " ".join(data["stats"])
    assert "유니크는 대상이 아니다" in joined
    assert "희귀(Rare)" in joined
    assert len(data["orbs"]) >= 3, "오브 계열이 연결돼 있어야 조달 경로를 판단한다"


def test_mods_without_spawn_pool_are_flagged() -> None:
    """ "존재한다"와 "얻을 수 있다"는 다르다 — 그 차이를 레코드가 말해야 한다.

    `corruptionupgrade*` 190건은 PoB `item-exclusive`에서 왔고 132건만 poe2db
    스폰 풀에도 있다. `spawn_weights`가 없는 것은 조달 경로가 확인되지 않은 것이다.
    """
    data = get_entry("modifier.corruptionupgradeonehanddamagegainedaschaos", fields=["data"])[
        "data"
    ]
    assert "조달 경로 미확인" in data["acquisition_note"]
    assert "mechanic.corruption-upgrade" in data["acquisition_note"], "기제로 갈 길을 준다"
    assert not data.get("spawn_weights")


def test_mod_with_spawn_pool_is_not_flagged() -> None:
    """스폰 풀이 있는 모드까지 경고하면 신호가 소음이 된다."""
    data = get_entry("modifier.corruptionupgradeweaponelementaldamagetwohand1", fields=["data"])[
        "data"
    ]
    assert data.get("spawn_weights")
    assert "acquisition_note" not in data
