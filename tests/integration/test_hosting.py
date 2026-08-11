"""담체↔페이로드 질의 — PoB 타입 시스템 대조 (사용자 요청 2026-08-11).

판정 로직은 `CalcTools.lua`를 전사한 것이라, **PoB가 바뀌면 여기서 깨져야 한다.**
알려진 사례로 잠근다.

#63 P2부터 재료는 KB `data.pob`다 — 정본은 git이라 CI에도 항상 있고, 예전처럼
`Data/Skills/` 부재로 통째로 스킵되지 않는다(스킵은 "검증했다"가 아니다).
여기 쓰는 스킬이 KB에서 빠지면 **스킵이 아니라 실패**해야 한다 — 정본의 구멍이다.
"""

from __future__ import annotations

from pok.engine.hosting import can_host, find_carriers, find_payloads
from pok.kb.skill_facts import skill_gates


def test_kb_carries_the_gates_this_file_needs() -> None:
    """전제 자체를 시험으로 — KB 수록이 무너지면 여기가 먼저 말한다."""
    gates = skill_gates()
    for name in ("BallLightningPlayer", "SupportMetaTotemSpellTotemPlayer", "LivingBombPlayer"):
        assert name in gates, f"KB data.pob에 {name}이 없다 — skill-types 수집이 빠졌나?"


def test_spell_totem_hosts_ball_lightning() -> None:
    """구형 번개는 주문 토템에 들어간다 — 이 세션에서 손으로 알아내야 했던 것."""
    out = find_carriers("Ball Lightning")
    assert out["ok"]
    assert "Spell Totem" in {c["carrier"] for c in out["carriers"]}


def test_item_granted_skill_cannot_be_socketed() -> None:
    """`fromItem` 스킬은 젬 소켓 자체가 안 된다 — 경고가 반드시 붙어야 한다.

    실측 2026-08-11(까부르는 화염): `Totemable` 플래그만 보고 "토템에 들어간다"고
    판단해 설계가 한 바퀴 헛돌았다. 원 사례(`His Winnowing Flame`)는 제외 원장의
    잔재 판정분이라(2026-07-29 승인) KB에 있는 fromItem 스킬로 같은 규칙을 잠근다.
    """
    out = find_carriers("Chaos Bolt")
    assert out["ok"]
    assert "fromItem" in out.get("warning", "")

    payloads = {p["skill"] for p in find_payloads("Spell Totem", limit=500)["payloads"]}
    assert "Chaos Bolt" not in payloads


def test_spell_totem_excludes_persistent_and_cooldown() -> None:
    """주문 토템의 배제 목록이 실제로 작동한다 (`Persistent`·`Cooldown`)."""
    gates = skill_gates()
    host = gates["SupportMetaTotemSpellTotemPlayer"]

    # 원소 착취 = Persistent → 배제
    assert not can_host(host, gates["SiphonElementsPlayer"]).ok
    # 베리시움 동력 공급 = Cooldown → 배제
    assert not can_host(host, gates["PoweredByVerisiumPlayer"]).ok
    # 살아있는 폭탄 = Spell + Totemable → 통과
    assert can_host(host, gates["LivingBombPlayer"]).ok


def test_type_expression_is_postfix_not_subset() -> None:
    """`{Spell, Totemable, AND}`는 **둘 다**여야 한다 — 집합 포함 검사가 아니다."""
    gates = skill_gates()
    host = gates["SupportMetaTotemSpellTotemPlayer"]
    assert host.require == ("Spell", "Totemable", "AND")

    # Spell이지만 Totemable이 아닌 스킬은 막혀야 한다
    non_totemable = [
        g
        for g in gates.values()
        if "Spell" in g.types and "Totemable" not in g.types and not g.is_support
    ]
    assert non_totemable, "표본이 없으면 이 시험이 무의미하다"
    assert not can_host(host, non_totemable[0]).ok


def test_payloads_are_deduped_and_named() -> None:
    """같은 젬의 변형이 한 이름으로 겹치거나 빈 이름이 새어 나오면 안 된다."""
    out = find_payloads("Spell Totem", limit=500)
    names = [p["skill"] for p in out["payloads"]]
    assert names == sorted(names)
    assert len(names) == len(set(names))
    assert all(n.strip() for n in names)
