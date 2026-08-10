"""소켓 그룹의 `slot`은 계산에 영향을 주지 않는다 — 백로그 #46 반증 (2026-08-10).

이관 보고는 "CoEA 그룹을 **아이템이 없는 `Helmet` 슬롯**에 넣었더니 PoB가 소켓을 세지
않아 젬이 활성화조차 안 됐다(`SpiritReserved = 0`)"였다. 그 모델대로 조립 게이트를
만들려다 먼저 재보니 **전부 같은 값**이 나왔다 — PoE2는 젬을 아이템에 소켓하지 않으므로
`slot`은 표시용이다. 게이트를 넣었다면 아이템 없는 스펙 전부를 막을 뻔했다(§0 ⑤).

보고된 `SpiritReserved = 0`의 진짜 원인은 아직 모른다. 이 테스트는 **원인이 슬롯이
아니라는 것**만 고정한다 — 같은 가설로 게이트를 다시 만들지 않기 위해서다.
"""

from __future__ import annotations

import pytest

from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec
from pok.pob.runner import run_build
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

HERALD = GemSpec(gem_id="Metadata/Items/Gems/SkillGemHeraldOfAsh", name="Herald of Ash", level=20)
WAND = ItemSpec(
    slot="Weapon 1", text="Rarity: NORMAL\nAttuned Wand\nAttuned Wand\nItem Level: 80\n"
)
HELMET = ItemSpec(
    slot="Helmet", text="Rarity: NORMAL\nFeathered Tiara\nFeathered Tiara\nItem Level: 80\n"
)


def _reserved(slot: str, items: tuple[ItemSpec, ...]) -> float | None:
    stats = run_build(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(SkillGroupSpec(gems=(HERALD,), slot=slot),),
            items=items,
        )
    ).stats
    value = stats.get("SpiritReserved")
    return None if value is None else float(value)


def test_empty_slot_reserves_the_same_spirit() -> None:
    empty = _reserved("Helmet", (WAND,))
    equipped = _reserved("Helmet", (WAND, HELMET))
    assert empty == equipped == 30.0, "빈 슬롯이라고 점유가 사라지지 않는다"


def test_slot_name_does_not_change_the_result() -> None:
    """슬롯명을 아예 틀리게 줘도 같다 — 조용한 폴백이 아니라 무관한 값이다."""
    assert _reserved("Weapon 1", (WAND,)) == _reserved("", (WAND,)) == 30.0


def test_stat_set_choice_changes_the_measurement() -> None:
    """모드 선택이 **실제로 값을 바꾸는지** 잰다 (백로그 #52).

    자식 원소로 내야만 먹는다 — 속성으로 내면 파트 1·2·3이 소수점까지 같아진다.
    맨몸 기준 실측 2026-08-10: 151.2 / 381.5 / 497.6 (장비를 갖추면 격차가 더 벌어져
    보고자 빌드에선 `WithIgniteDPS` 2,387 vs 47,329였다).
    """
    ball = "Metadata/Items/Gems/SkillGemBallLightning"

    def dps(index: int | None) -> float:
        gem = GemSpec(gem_id=ball, name="Ball Lightning", level=20, stat_set_index=index)
        stats = run_build(
            BuildSpec(
                class_name="Sorceress",
                ascendancy="Sorceress1",
                level=90,
                skills=(SkillGroupSpec(gems=(gem,), slot="Weapon 1"),),
                items=(WAND,),
            )
        ).stats
        return float(stats["TotalDPS"])

    parts = [dps(i) for i in (1, 2, 3)]
    assert len(set(parts)) == 3, f"세 모드가 같은 값이면 선택이 안 먹은 것이다: {parts}"
    assert parts[2] > parts[0] * 3, f"3번이 1번보다 크게 높아야 한다: {parts}"
    assert dps(None) == parts[0], "미지정은 PoB 기본값 1번과 같다 — 그래서 조용하다"
