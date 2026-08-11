"""아이템 파싱 갭 감사 — 무엇을 시험 문구로 삼는가 (#38).

⚠ PoB 원문(`external/pob` 스냅샷)을 읽는 시험은 **CI에 스냅샷이 없어** 건너뛴다.
그런데 건너뛰기만 하면 이 결함의 핵심 로직이 CI에서 한 번도 안 돌므로, 원문을
스텁으로 넣은 짝을 함께 둔다 — 스킵은 "검증했다"가 아니다.
"""

from __future__ import annotations

import pytest

from pok.pob.item_parse_gaps import scannable_lines
from pok.pob.versions import resolve_snapshot

PLACEHOLDER = "Can Allocate Passive Skills from the (Mercenary/Ranger)'s starting point"
DATA = {"rarity": "unique", "explicits": [PLACEHOLDER]}


def _snapshot_ready() -> bool:
    try:
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


needs_pob_snapshot = pytest.mark.skipif(
    not _snapshot_ready(), reason="external/pob 스냅샷 없음 (유니크 원문 = PoB 소스)"
)


def test_without_a_name_the_kb_wording_is_kept() -> None:
    """이름 없이 부르면 예전대로 KB 문구 — 옛 호출자가 조용히 달라지지 않는다."""
    assert any("(Mercenary/Ranger)" in ln for ln in scannable_lines(DATA))


@needs_pob_snapshot
def test_uniques_are_tested_with_pob_source_not_placeholders() -> None:
    """다변형 유니크는 **PoB 원문**으로 시험한다 (백로그 #38).

    KB `explicits`는 변형을 플레이스홀더 한 줄로 뭉친다:

        Can Allocate Passive Skills from the (Mercenary/Ranger/…)'s starting point

    PoB 패턴은 `"…from the (%a+)'s starting point"`(한 단어)라 슬래시가 든 이 줄은
    안 맞는다 — 그래서 `item.split-personality`가 "PoB 미지원"으로 기록됐다.
    변형을 확정한 줄은 정상 파싱된다(실측 2026-08-10: 플레이스홀더 unknown vs
    `Warrior` 정상). **PoB의 한계가 아니라 우리 시험 문구 선택의 문제**였다.
    """
    from_source = scannable_lines(DATA, "Split Personality")
    assert from_source, "PoB 원문을 못 찾으면 KB로 되돌아간다 — 여긴 있어야 한다"
    assert any("{variant:" in ln for ln in from_source), from_source[:3]
    assert not any("(Mercenary/Ranger" in ln for ln in from_source), "플레이스홀더가 남았다"
    # 스펙 줄은 모드가 아니다 — 섞이면 "못 읽는 줄"로 오판된다
    assert not any(ln.startswith(("Variant:", "Limited to:", "Source:")) for ln in from_source)


def test_pob_source_replaces_the_placeholder_even_without_a_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """스냅샷이 없어도 **선택 로직**은 검증한다 — 원문만 스텁으로 넣는다.

    위 시험이 CI에서 통째로 스킵되면서 결함이 한 번 새어 나갔다(2026-08-11 CI 실패):
    로컬엔 스냅샷이 있어 통과하고 CI에선 KB로 되돌아가 플레이스홀더가 남았다.
    환경에만 의존하는 검증은 **환경이 다르면 검증이 아니다**.
    """
    raw = "\n".join(
        [
            "Split Personality",
            "Cobalt Jewel",
            "Variant: Mercenary",
            "Variant: Ranger",
            "Limited to: 1",
            "{variant:1}Can Allocate Passive Skills from the Mercenary's starting point",
            "{variant:2}Can Allocate Passive Skills from the Ranger's starting point",
        ]
    )
    monkeypatch.setattr("pok.pob.uniques.unique_raw", lambda _name: raw)
    lines = scannable_lines(DATA, "Split Personality")
    # 스텁이 실제로 가로챘는지부터 못 박는다 — 스냅샷이 있는 기계에서 "통과"가
    # 스텁 덕인지 실물 덕인지 구분되지 않으면 이 시험은 아무것도 보장하지 않는다.
    assert len(lines) == 2, lines
    assert not any("(Mercenary/Ranger" in ln for ln in lines), "플레이스홀더가 남았다"
    assert not any(ln.startswith(("Variant:", "Limited to:", "Source:")) for ln in lines)
