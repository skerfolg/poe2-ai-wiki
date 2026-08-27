"""적대 조합 — **A가 만드는 것을 B가 금지한다** (#131).

기존 그래프는 **생산·소비**를 본다(A가 X를 만들고 B가 X를 쓴다). 여기는 축이 다르다 —
A가 X를 만드는데 B가 **X 자체를 금지**한다. §0 ⑧의 역방향으로, 「없는 공백」이 아니라
**「있는 충돌」**을 못 보던 자리다.

계기(2026-08-27 실측): `Xoph's Pyre`와 불의 화신이 정면 적대해 **젬 한 칸이 완전히
무효**가 되는데(두 구성의 최종 DPS가 1,556,109로 동일) 아무 신호가 없었다. 사용자가
인게임에서 발견했다.
"""

from __future__ import annotations

import pytest

from pok.kb import store as kb_store
from pok.kb.graph.antagonists import (
    DAMAGE_GROUPS,
    DAMAGE_TYPES,
    Prohibition,
    _node_index,
    report_for_spec,
    scan_antagonists,
    scan_prohibitions,
)
from pok.kb.store import Store


@pytest.fixture(scope="module")
def store() -> Store:
    return kb_store.load()


def test_계기가_된_짝을_찾아낸다(store: Store) -> None:
    """`Xoph's Pyre`(Fire→Extra Chaos) x 불의 화신(Deal no Non-Fire).

    빌드가 든 것만 좁히면 **그 사고 하나**가 그대로 나온다 — 전수는 「무엇이 적대할 수
    있나」이고 좁히면 「지금 내 빌드에서 무엇이 죽고 있나」다.
    """
    pairs = scan_antagonists(store, carrier_ids={"support.xophs-pyre", "passive.avatar-of-fire"})
    assert pairs, "계기가 된 적대 짝을 못 찾았다"
    hit = pairs[0]
    assert hit.prohibition.carrier_id == "passive.avatar-of-fire"
    assert hit.producer_id == "support.xophs-pyre"
    assert hit.damage_type == "Chaos"


def test_금지는_적은데_파급이_크다(store: Store) -> None:
    """실측 2026-08-27: 금지 담체 **8종**인데 불의 화신 하나가 생산 담체 **188종**을 죽인다.

    적다고 무시하면 안 되는 이유다 — 「몇 건인가」가 아니라 **「무엇을 죽이는가」**로 잰다.
    """
    bans = {b.carrier_id for b in scan_prohibitions(store)}
    assert "passive.avatar-of-fire" in bans
    aof = [
        p for p in scan_antagonists(store) if p.prohibition.carrier_id == "passive.avatar-of-fire"
    ]
    assert len({p.producer_id for p in aof}) > 50, (
        "파급 규모가 크게 줄었다 — 어휘가 좁아졌는지 볼 것"
    )


def test_배타_금지는_자신을_뺀_전부를_죽인다() -> None:
    """`Deal no Non-Fire`는 **화염 외 전부**를, `Deal no Chaos`는 **카오스만** 죽인다."""
    excl = Prohibition("x", "X", "Passive", "Fire", True, "Deal no Non-Fire Damage")
    assert set(excl.killed_types) == set(DAMAGE_TYPES) - {"Fire"}
    plain = Prohibition("y", "Y", "Support", "Chaos", False, "Deal no Chaos Damage")
    assert plain.killed_types == ("Chaos",)


def test_자기_자신은_적대가_아니다(store: Store) -> None:
    """⛔ 한 레코드가 금지와 생산을 함께 가질 수 있다 — 그건 설계이지 충돌이 아니다."""
    assert all(p.producer_id != p.prohibition.carrier_id for p in scan_antagonists(store))


def test_트리_노드는_숫자_id로_들어온다(store: Store) -> None:
    """⚠ 이 회귀가 존재하는 이유 — 처음 짤 때 `passive.{nid}`로 조회했고 **0건**이 맞았다.

    스펙의 `tree_nodes`는 `passive.avatar-of-fire`가 아니라 `18684` 같은 **정수**다.
    계기가 된 불의 화신이 바로 트리 키스톤이라, 이 갭을 못 봤으면 신고기가 정작 그
    사고에 대해 **조용히 0건**을 냈을 것이다.
    """
    idx = _node_index(store)
    aof = store.records["passive.avatar-of-fire"]
    nid = int((aof.raw.get("data") or {}).get("node_id"))
    assert idx.get(nid) is not None
    assert idx[nid].id == "passive.avatar-of-fire"

    spec = {
        "tree_nodes": [nid],
        "skills": [{"gems": [{"name": "Xoph's Pyre"}]}],
    }
    kills = {r["kills"] for r in report_for_spec(store, spec)}
    assert "Chaos" in kills, "키스톤을 트리에서 못 읽고 있다"


def test_신고이지_거부가_아니다(store: Store) -> None:
    """⛔ 적대라도 **의도한 선택**일 수 있다 — 대가를 알고 쓴다.

    거부하면 #117·#118과 같은 거짓 거부가 된다. 반환은 사실만 싣고 판정은 호출자 몫(AD-3).
    """
    spec = {
        "items": [{"text": "Deal no Non-Fire Damage"}],
        "skills": [{"gems": [{"name": "Xoph's Pyre"}]}],
    }
    rows = report_for_spec(store, spec)
    assert rows and all({"prohibition", "kills", "why"} <= set(r) for r in rows)


def test_금지가_없으면_아무것도_신고하지_않는다(store: Store) -> None:
    """게이트를 만들 때는 **반대 방향을 같은 커밋에서 잰다** — #127·#129에서 두 번 증명됐다.

    소음을 내면 읽히지 않고, 읽히지 않는 신고는 없는 것과 같다(§0 ⑤).
    """
    assert report_for_spec(store, {}) == []
    assert report_for_spec(store, {"skills": [{"gems": [{"name": "Xoph's Pyre"}]}]}) == []
    assert report_for_spec(store, {"items": [{"text": "Deal no Non-Fire Damage"}]}) == []


def test_묶음_금지를_버리지_않는다(store: Store) -> None:
    """⚠ 이 회귀가 존재하는 이유 — `Deal no **Elemental** Damage`가 **조용히 사라졌었다**.

    「비-타입 금지(`Deal no Spell/Melee`)는 뺀다」는 규칙이 **「묶음 금지도 뺀다」로 새어
    나갔다**. `Elemental`은 타입이 아니지만 **펴면 타입이다**. 그 새어나감 때문에
    Brutality I~III가 **카오스만** 죽이는 것으로 보고됐다 — 실제로는 화염·냉기·번개도
    죽인다. 정본 7건이 통째로 축 밖이었고 적대 짝이 679 → **1,994**로 바뀌었다.
    """
    assert DAMAGE_GROUPS["Elemental"] == ("Fire", "Cold", "Lightning")
    bans = {b.carrier_id: b for b in scan_prohibitions(store) if b.subject == "Elemental"}
    assert bans, "묶음 금지가 다시 사라졌다"

    brutality = [b for b in scan_prohibitions(store) if b.carrier_id == "support.brutality-i"]
    killed = {t for b in brutality for t in b.killed_types}
    assert killed == {"Fire", "Cold", "Lightning", "Chaos"}, (
        f"Brutality가 죽이는 축이 틀렸다: {killed}"
    )


def test_묶음의_여집합도_편다() -> None:
    """`Deal no Non-Elemental`은 **원소를 남기고** 물리·카오스를 죽인다."""
    non_ele = Prohibition("x", "X", "Modifier", "Elemental", True, "Deal no Non-Elemental Damage")
    assert set(non_ele.killed_types) == {"Physical", "Chaos"}


def test_타입도_묶음도_아닌_금지는_뺀다(store: Store) -> None:
    """⛔ `Deal no Spell/Melee/Projectile Damage`는 이 축이 아니다 — 섞으면 어휘가 흐려진다."""
    subjects = {b.subject for b in scan_prohibitions(store)}
    assert subjects <= set(DAMAGE_TYPES) | set(DAMAGE_GROUPS)
    assert all(b.killed_types for b in scan_prohibitions(store)), "죽이는 게 없는 금지가 실렸다"


def test_출고_경로에도_묶음_누수가_없다(store: Store) -> None:
    """⚠ 같은 누수가 **두 자리**에 있었다 — 스캔에서 고치고 `report_for_spec`을 빠뜨렸다.

    `report_for_spec`이 `assemble_pob` 출고에 실제로 실리는 경로다. 스캔만 고쳤으면
    전수 조회는 맞는데 **정작 빌드 신고가 죽어 있었다**(형태 ⑭ — 고칠 자리가 둘인데
    하나만 고치면 실물 경로가 조용히 침묵한다).
    """
    spec = {
        "skills": [{"gems": [{"name": "Brutality I"}]}],
        "items": [{"text": "Gain 20% of Physical Damage as Extra Cold Damage"}],
    }
    kills = {r["kills"] for r in report_for_spec(store, spec)}
    assert "Cold" in kills, "묶음 금지(Deal no Elemental)가 출고 경로에서 빠졌다"


def test_금지_어휘가_둘이다(store: Store) -> None:
    """⚠ `Cannot deal`만 쓰는 담체가 있다 — **어센던시 하나가 통째로 빠져 있었다**.

    `mechanic.elemental-archon`이 *"Cannot deal Non-Elemental Damage with Spells"*로
    물리·카오스 주문을 죽이는데, `Deal no`만 보던 초판은 이 담체를 **한 건도** 안 냈다.
    백로그가 요구한 어휘 전수(`Deal no`·`Cannot`·`no Non-`)를 절반만 한 결과다.
    """
    bans = {b.carrier_id: b for b in scan_prohibitions(store)}
    archon = bans.get("mechanic.elemental-archon")
    assert archon is not None, "`Cannot deal` 어휘가 다시 빠졌다"
    assert set(archon.killed_types) == {"Physical", "Chaos"}


def test_무기_로컬_속성은_금지가_아니다(store: Store) -> None:
    """⛔ `No Physical Damage`는 **「이 무기에 물리가 없다」**이지 「물리를 못 낸다」가 아니다.

    캐릭터는 다른 출처로 물리를 낸다 — 금지로 세면 정본 6건이 통째로 오탐이 된다
    (`uniquelocalnoweaponphysicaldamage1~4` · `Skysliver` · `The Sentry`).
    """
    ids = {b.carrier_id for b in scan_prohibitions(store)}
    assert not any("localnoweaponphysical" in i for i in ids)
    assert "item.skysliver" not in ids and "item.the-sentry" not in ids
