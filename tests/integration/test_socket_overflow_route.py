"""6칸을 넘는 룬 칸의 **대안 경로**가 실제로 값을 재현하는가 (#120, 환경 없으면 skip).

PoB는 룬 소켓을 6칸까지만 표현한다(`ItemsTab.lua:696`이 드롭다운을 6개만 만들고
`UpdateRuneControls`(:2016)가 `itemSocketCount`까지 돌며 인덱싱한다 → 7칸부터
**아이템을 클릭하는 순간 예외**). 인게임에서는 마셜 아티스트 `Runic Meridians`
(갑옷 +2)에 타락 1칸이 겹치면 7칸이 나올 수 있으므로, 「막는다」로 끝내면 그 구성은
아예 못 재게 된다.

⛔ **금지하려면 대안 경로를 먼저 만든다**(철칙 5 따름정리). 그 경로가 값을 재현하는지
여기서 잰다 — 재현 못 하면 거부 사유에 적은 우회로가 거짓말이 된다.
"""

from __future__ import annotations

import pytest

from pok.pob.buildxml import BuildSpec, ItemSpec, to_xml
from pok.pob.runner import run_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")

_RUNE = "Perfect Body Rune"  # 갑옷에서 +75 to maximum Life
_SEED = "{rune}+75 to maximum Life"


def _robe(sockets: int, config: tuple[tuple[str, str], ...] = ()) -> BuildSpec:
    """⚠ `Sockets:`·`Rune:`·시드 줄 **셋 다** 있어야 한다.

    `Item.lua:1046~1058`은 `#self.runeModLines > 0`일 때만 `UpdateRunes()`를 부른다 —
    시드 줄이 없으면 선언만 있고 **Δ 0**이다(`engine/runes.py` 모듈 주석의 그 함정).
    """
    return BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        items=(
            ItemSpec(
                slot="Body Armour",
                text=(
                    "Rarity: RARE\nPok Robe\nAltar Robe\nItem Level: 80\n"
                    f"Sockets: {' '.join('S' for _ in range(sockets))}\n"
                    + "\n".join([f"Rune: {_RUNE}"] * sockets)
                    + "\n"
                    + "\n".join([_SEED] * sockets)
                ),
            ),
        ),
        config=config,
    )


def test_넘치는_칸을_customMods로_재현한다() -> None:
    """4칸 = 3칸 + `customMods` 한 줄. 소수점까지 같아야 우회로라 부를 수 있다."""
    full = run_xml(to_xml(_robe(4)), use_cache=False).stats["Life"]
    short = run_xml(to_xml(_robe(3)), use_cache=False).stats["Life"]
    assert full > short, "룬 한 칸이 실제로 값을 낸다(전제 확인)"

    routed = run_xml(
        to_xml(_robe(3, config=(("customMods", "+75 to maximum Life"),))), use_cache=False
    ).stats["Life"]
    assert routed == full, f"우회로가 값을 재현해야 한다: {routed} vs {full}"


def test_여러_줄_customMods가_통째로_사라지지_않는다() -> None:
    """`&#10;`으로 나가면 PoB가 **조용히 전부 버린다** — 그 회귀를 여기서 잠근다.

    실측 2026-08-25: 엔티티로 내보낸 두 줄짜리 설정이 「설정 없음」과 완전히 같은
    수치를 냈다(Life 2025 · Spirit 208). 오류도 경고도 없었다(BACKLOG 형태 ①).
    """
    plain = run_xml(to_xml(_robe(3)), use_cache=False).stats
    both = run_xml(
        to_xml(_robe(3, config=(("customMods", "+75 to maximum Life\n+14 to Spirit"),))),
        use_cache=False,
    ).stats
    assert both["Life"] > plain["Life"], "첫 줄이 적용돼야 한다"
    assert both["Spirit"] > plain["Spirit"], "**둘째 줄**이 적용돼야 한다(개행이 살아 있다)"
