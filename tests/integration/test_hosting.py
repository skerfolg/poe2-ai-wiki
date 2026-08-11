"""담체↔페이로드 질의 — PoB 타입 시스템 대조 (사용자 요청 2026-08-11).

판정 로직은 `CalcTools.lua`를 전사한 것이라, **PoB가 바뀌면 여기서 깨져야 한다.**
알려진 사례로 잠근다.
"""

from __future__ import annotations

import pytest

from pok.engine.hosting import can_host, find_carriers, find_payloads
from pok.pob.catalog import skill_gates

# CI는 PoB를 통째로 받지 않고 카탈로그용 8개 파일만 받는다 — `Data/Skills/`에는
# `sup_dex.lua` **하나뿐**이다(`.github/workflows/ci.yml`). 여기서 대조하는 스킬들은
# `act_int`·`act_str`·`other`에 있어 CI엔 없다. 형상 확인: `bash scripts/ci_shape_test.sh`
_REQUIRED = ("BallLightningPlayer", "SupportMetaTotemSpellTotemPlayer", "LivingBombPlayer")


def _skill_data_ready() -> bool:
    """대조에 쓸 스킬 정의가 실제로 있는가.

    ⚠ 다른 통합 시험처럼 `resolve_snapshot()`으로 가드하면 **안 걸린다** — 그건
    `HeadlessWrapper.lua` 유무를 보는 것이고 여기 필요한 것은 스킬 정의다.
    파일 존재로 에두르지 않고 **쓸 것을 직접 묻는다.**
    """
    gates = skill_gates()
    return all(name in gates for name in _REQUIRED)


pytestmark = pytest.mark.skipif(
    not _skill_data_ready(),
    reason="PoB `Data/Skills/` 전량 없음 (CI 형상은 sup_dex.lua 하나뿐)",
)


def test_spell_totem_hosts_ball_lightning() -> None:
    """구형 번개는 주문 토템에 들어간다 — 이 세션에서 손으로 알아내야 했던 것."""
    out = find_carriers("Ball Lightning")
    assert out["ok"]
    assert "Spell Totem" in {c["carrier"] for c in out["carriers"]}


def test_item_granted_skill_cannot_be_socketed() -> None:
    """까부르는 화염은 `fromItem`이라 젬 소켓 자체가 안 된다.

    실측 2026-08-11: `Totemable` 플래그만 보고 "토템에 들어간다"고 판단해
    설계가 한 바퀴 헛돌았다. 경고가 반드시 붙어야 한다.
    """
    out = find_carriers("His Winnowing Flame")
    assert out["ok"]
    assert "fromItem" in out.get("warning", "")

    payloads = {p["skill"] for p in find_payloads("Spell Totem", limit=500)["payloads"]}
    assert "His Winnowing Flame" not in payloads


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
