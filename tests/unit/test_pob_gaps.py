"""PoB 미모델링 표시 — 계산에서 조용히 빠지는 것을 KB에 남긴다 (이관 4 C1·C3).

PoB는 계산 오라클이지만 전지하지 않다. `external/pob/<스냅샷>/`은 재현성을 위해
손대지 않으므로(AD-2), **KB에 표시하고 대체 조립 경로를 안내**한다(B-3 선례).
"""

from __future__ import annotations

from pok.kb.pob_gaps import (
    matchable_slot_keys,
    scan_rune_slot_gaps,
    scan_unparsed_mod_texts,
)


def test_matchable_set_includes_pob_base_types() -> None:
    """`GetSocketedAugmentTypes()`가 내는 것은 baseType과 specificType 둘이다.

    `weapon`·`armour`·`caster`를 빠뜨리면 정상 룬까지 미매칭으로 잡힌다 —
    실측 2026-08-05: 3건이어야 할 것이 124건으로 나왔다.
    """
    keys = matchable_slot_keys()
    assert {"weapon", "armour", "caster"} <= keys, "baseType 3종"
    assert {"quarterstaff", "buckler"} <= keys, "specificType 특수 매핑"
    assert "staff" in keys and "bow" in keys, "itemType(= item_class)"


def test_composite_slot_keys_are_the_only_rune_gap() -> None:
    """`martial weapon wand or staff` 같은 복합 키는 정확 일치로 절대 안 잡힌다."""
    gaps = scan_rune_slot_gaps()
    assert {g.record_id for g in gaps} == {
        "modifier.idol-of-the-martyr",
        "modifier.idol-of-the-pharisee",
        "modifier.idol-of-the-sycophant",
    }
    assert all("martial weapon wand or staff" in g.detail for g in gaps)
    assert all("대체 조립" in g.workaround for g in gaps), "막다른 길로 끝내지 않는다"


def test_radius_grant_lines_are_flagged() -> None:
    """반경 부여는 `ModParser`에 패턴이 없어 통째로 계산 밖이다.

    증상: 서로 다른 주얼 소켓의 델타가 완전히 동일하게 나와 "반경은 값어치 없음"으로
    오독된다. 규모가 크다 — 흔한 모드 계열이 전부 여기 해당한다.
    """
    gaps = scan_unparsed_mod_texts()
    ids = {g.record_id for g in gaps}
    assert "modifier.jewelbleedingeffect" in ids, "이관 노트가 지목한 것"
    assert len(gaps) > 100, "소수가 아니라 계열 전체다"
    assert all(g.kind == "radius-grant" for g in gaps)


def test_flags_are_visible_from_the_record() -> None:
    """조회하면 바로 보여야 세션이 실측 불가를 안다."""
    from pok.index.search import get_entry

    data = get_entry("modifier.idol-of-the-sycophant", fields=["data"])["data"]
    assert data["pob_modeling"]["supported"] is False
    assert "추산" in data["pob_modeling"]["workaround"]
