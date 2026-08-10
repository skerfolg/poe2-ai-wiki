"""아이템 파싱 갭 감사 — 무엇을 시험 문구로 삼는가 (#38)."""

from __future__ import annotations


def test_uniques_are_tested_with_pob_source_not_placeholders() -> None:
    """다변형 유니크는 **PoB 원문**으로 시험한다 (백로그 #38).

    KB `explicits`는 변형을 플레이스홀더 한 줄로 뭉친다:

        Can Allocate Passive Skills from the (Mercenary/Ranger/…)'s starting point

    PoB 패턴은 `"…from the (%a+)'s starting point"`(한 단어)라 슬래시가 든 이 줄은
    안 맞는다 — 그래서 `item.split-personality`가 "PoB 미지원"으로 기록됐다.
    변형을 확정한 줄은 정상 파싱된다(실측 2026-08-10: 플레이스홀더 unknown vs
    `Warrior` 정상). **PoB의 한계가 아니라 우리 시험 문구 선택의 문제**였다.
    """
    from pok.pob.item_parse_gaps import scannable_lines

    data = {
        "rarity": "unique",
        "explicits": ["Can Allocate Passive Skills from the (Mercenary/Ranger)'s starting point"],
    }
    # 이름 없이 부르면 예전대로 KB 문구 — 옛 호출자가 조용히 달라지지 않는다
    assert any("(Mercenary/Ranger)" in ln for ln in scannable_lines(data))

    from_source = scannable_lines(data, "Split Personality")
    assert from_source, "PoB 원문을 못 찾으면 KB로 되돌아간다 — 여긴 있어야 한다"
    assert any("{variant:" in ln for ln in from_source), from_source[:3]
    assert not any("(Mercenary/Ranger" in ln for ln in from_source), "플레이스홀더가 남았다"
    # 스펙 줄은 모드가 아니다 — 섞이면 "못 읽는 줄"로 오판된다
    assert not any(ln.startswith(("Variant:", "Limited to:", "Source:")) for ln in from_source)
