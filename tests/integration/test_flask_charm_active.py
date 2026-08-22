"""장착 슬롯이 **활성**으로 나가는지 (BACKLOG #98).

PoB는 `active = child.attrib.active == "true"`로 읽는다(`Classes/ItemsTab.lua:1159`).
속성을 안 쓰면 **전부 비활성**이 되고, 비활성 플라스크·호신부는 `env.flasks`/
`env.charms`에 안 들어간다(`Modules/CalcSetup.lua:1095-1110`).

실측 2026-08-20(수정 전): 래더 기준 빌드에서 **플라스크·호신부를 통째로 빼도**
DPS·Life·TotalEHP가 전부 Δ 0.0이었다 — 반사실 캠페인 2,689벌 전량이 플라스크
없이 측정된 셈이다. 그 위에 세운 `NodeValue` 2,665종도 같은 결손을 물려받았다.

⛔ 이 시험이 깨지면 **측정 전체가 조용히 반쪽이 된다** — 값이 안 나오는 게 아니라
「없는 것을 있다고 세지 않을 뿐」이라 어떤 게이트에도 안 걸린다(철칙 4의 전형).
"""

from __future__ import annotations

import dataclasses

import pytest

from pok.pob.buildxml import spec_from_dict, to_xml
from pok.pob.daemon import PobDaemon
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


# ⛔ CI에는 PoB 스냅샷이 없다 — 다른 통합 시험과 **같은 규약**을 쓴다.
#    이걸 안 붙여 CI가 깨졌다(2026-08-22). XML 규약 시험은 PoB가 필요 없지만
#    파일 단위로 건너뛰므로, 그쪽은 단위 시험이 이미 잠근다.
pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

_FLASK = "\n".join(
    [
        "Rarity: MAGIC",
        "Substantial Ultimate Life Flask of the Abundant",
        "Ultimate Life Flask",
        "Item Level: 65",
        "Quality: 20",
        "LevelReq: 60",
    ]
)


def _spec(slot: str = "Flask 1"):
    return spec_from_dict(
        {
            "class_name": "Witch",
            "ascendancy": "Witch1",
            "level": 90,
            "tree_nodes": [],
            "items": [{"slot": slot, "text": _FLASK}],
        },
        validate_catalog=False,
    )


def test_슬롯이_active로_나간다() -> None:
    """속성 자체가 XML에 있어야 한다 — 없으면 PoB가 조용히 비활성 처리한다."""
    xml = to_xml(_spec())
    slot = next(line for line in xml.splitlines() if "<Slot" in line)
    assert 'active="true"' in slot, f"active 속성이 없다: {slot.strip()}"


def test_플라스크가_계산에_실제로_들어간다() -> None:
    """XML 속성만 보는 것으로는 부족하다 — PoB가 **먹었는지**를 본다.

    비활성이면 `env.flasks`에 안 들어가 플라스크 관련 출력이 아예 안 생긴다
    (실측 2026-08-20 수정 전: `LifeFlaskRecovery` 자체가 없었다).
    """
    spec = _spec()
    bare = dataclasses.replace(spec, items=())
    with PobDaemon() as daemon:
        with_flask = daemon.compute_build(spec).stats or {}
        without = daemon.compute_build(bare).stats or {}
    assert with_flask.get("LifeFlaskRecovery"), (
        "플라스크를 꽂았는데 회복 출력이 없다 — 슬롯이 비활성이다(#98 재발)"
    )
    assert not without.get("LifeFlaskRecovery"), "대조군에 플라스크 출력이 있다"


def test_호신부_슬롯도_같은_규약을_탄다() -> None:
    """⚠ 호신부는 벨트가 슬롯을 줘야 실제 효과가 붙으므로 여기선 XML 규약만 본다 —
    실효 검증은 벨트를 낀 빌드에서 한다."""
    assert 'active="true"' in to_xml(_spec("Charm 1"))
