"""코드가 드는 **스탯 축 이름이 PoB에 실재하는가** (백로그 #18 후속, 2026-08-09).

없는 키를 재면 델타가 **늘 0**으로 나온다. 그건 이 프로젝트가 반복해 데인
「조용한 0」의 또 다른 얼굴이다 — 그리고 그것을 고치는 코드 자체가 그 함정에 빠졌다.

실측 2026-08-09: 방어 축 자동 측정(#18)에 `MovementSpeed`라고 적었는데 PoB의 실제
키는 **`MovementSpeedMod`**다. 후보 20종이 전부 `이동 0.000`으로 찍혔는데도 그대로
넘어갔고, `[빌드]` 세션의 이관 보고를 받고서야 알았다.

유닛 테스트로는 못 잡는다 — 가짜 오라클은 우리가 준 키를 그대로 돌려주기 때문이다.
**PoB에 실제로 물어야만** 드러난다.
"""

from __future__ import annotations

import pytest

from pok.engine.items import _DEFENSIVE_AXES
from pok.pob.buildxml import BuildSpec, to_xml
from pok.pob.runner import run_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


needs_pob_run = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


@needs_pob_run
def test_방어_축_이름이_전부_PoB에_있다() -> None:
    """하나라도 없으면 그 축은 **영원히 0**이고, 아무도 그걸 모른다."""
    stats = run_xml(
        to_xml(BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", level=90))
    ).stats
    missing = [axis for axis in _DEFENSIVE_AXES if axis not in stats]
    assert not missing, (
        f"PoB에 없는 축 {missing} — 델타가 늘 0으로 나온다. "
        f"이동속도 계열의 실제 키 예: "
        f"{sorted(k for k in stats if 'ovement' in k)}"
    )
