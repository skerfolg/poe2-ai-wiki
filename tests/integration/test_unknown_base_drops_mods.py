"""베이스가 불명이면 PoB가 **모드를 조용히 버린다** (백로그 #28 → #27로 흡수).

빌드 세션 관찰: 같은 줄 `+40% to Fire Resistance`를 **장갑에 넣으면 반영이 안 되고
신발에 넣으면 됐다.** 슬롯 차이로 보였다.

엔진 세션 재현(2026-08-09) — **슬롯이 아니라 베이스였다**:

    Gloves  Silk Gloves(가짜)      FireResist -50.0  → 조용히 버려짐
    Gloves  Adherent Cuffs(실존)   FireResist -10.0  → 반영
    Boots   Silk Boots(가짜)       FireResist -50.0  → 조용히 버려짐
    Boots   Adherent Leggings(실존) FireResist -10.0  → 반영

즉 별건 결함이 아니라 **#27의 증상**이다. 관찰자의 의심이 맞았다.

무서운 건 버린다는 사실이 아니라 **조용히** 버린다는 것이다 — 오류도 경고도 없이
"그 장비를 낀 수치"로 읽힌다. #27이 `items_legal`로 그 침묵을 깼고, 이 테스트가
**PoB의 실제 동작과 그 가드를 함께** 잠근다.
"""

from __future__ import annotations

import pytest

from pok.mcp.tools.build import _items_legal
from pok.pob.buildxml import BuildSpec, ItemSpec, to_xml
from pok.pob.runner import run_xml
from pok.pob.versions import find_luajit, resolve_snapshot

_FAKE = "Silk Gloves"  # 실측 사고에 실제로 쓰였던 존재하지 않는 베이스
_REAL = "Adherent Cuffs"
_MOD = "+40% to Fire Resistance"


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


needs_pob_run = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


def _fire_resist(base: str | None) -> float:
    items = ()
    if base is not None:
        text = f"Rarity: RARE\nProbe\n{base}\nItem Level: 80\n{_MOD}"
        items = (ItemSpec(slot="Gloves", text=text),)
    spec = BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", level=90, items=items)
    return run_xml(to_xml(spec)).stats.get("FireResist", 0.0)


@needs_pob_run
def test_unknown_base_silently_drops_mods() -> None:
    """PoB의 실제 동작 — 이게 참이라서 가드가 필요하다."""
    bare = _fire_resist(None)
    assert _fire_resist(_FAKE) == bare, "가짜 베이스의 모드는 계산에 안 들어간다"
    assert _fire_resist(_REAL) > bare, "실존 베이스면 같은 줄이 반영된다"


@needs_pob_run
def test_the_guard_catches_what_pob_swallows() -> None:
    """조용히 버려지는 그 아이템을 `items_legal`이 잡아내는가 (#27).

    PoB가 침묵하는 자리에서 **우리가 말해야** 한다 — 안 그러면 세션은 그 수치를
    "그 장비를 낀 값"으로 읽는다(실측: 그렇게 20여 회 측정됐다).
    """
    spec = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "items": [
            {"slot": "Gloves", "text": f"Rarity: RARE\nProbe\n{_FAKE}\nItem Level: 80\n{_MOD}"}
        ],
    }
    out = _items_legal(spec)
    assert out["items_legal"] is False
    assert any(_FAKE in reason for reason in out["illegal_items"][0]["reasons"])
