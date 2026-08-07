"""PoB 미모델링 표시 — 계산에서 조용히 빠지는 것을 KB에 남긴다 (이관 4 C1·C3).

PoB는 계산 오라클이지만 전지하지 않다. `external/pob/<스냅샷>/`은 재현성을 위해
손대지 않으므로(AD-2), **KB에 표시하고 대체 조립 경로를 안내**한다(B-3 선례).
"""

from __future__ import annotations

from pok.kb.pob_gaps import (
    matchable_slot_keys,
    scan_rune_slot_gaps,
    scan_unparsed_mod_texts,
    scannable_lines,
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


def test_radius_grant_is_not_flagged_anymore() -> None:
    """반경 부여는 미모델링이 **아니었다** — 판정의 전제 두 개가 다 무너졌다.

    ① 관측된 519건은 전부 오염된 한글에만 매칭했다(영문 근거 0건, 2026-08-07).
    ② PoB에 패턴이 있다: `Modules/ModParser.lua:7041`의
       `^(%w+) Passive Skills in Radius also grant (.*)$`.
    지목됐던 `jewelbleedingeffect`가 PoB에서 한 줄인 건 **실제로 한 줄이기 때문**이고,
    KB에 있던 반경 줄은 별개 모드(`JewelRadiusBleedingEffect`)의 것이 섞인 것이었다.
    """
    assert not any(g.kind == "radius-grant" for g in scan_unparsed_mod_texts())


def test_scanner_never_reads_korean() -> None:
    """판정 근거는 영문뿐 — 한글은 신뢰할 수 없는 입력이었다.

    `texts_ko`를 근거로 삼으면 수집 오염이 그대로 미모델링 판정이 된다. 그 플래그는
    세션이 **측정 방법을 바꾸는 근거**로 쓰이므로, 틀리면 표기 오류가 아니라 작업
    계획의 왜곡이다(실측: 한 세션이 최적화 회차를 늘릴 뻔했다).
    """
    lines = scannable_lines(
        {
            "texts": ["(5-15)% increased Magnitude of Bleeding you inflict"],
            "texts_ko": ["반경 내 주요 패시브 스킬이 출혈 강도 (3-7) % 증가도 부여"],
            "per_slot": {"weapon": ["Bonded: 8% increased Physical Damage"]},
        }
    )
    assert lines == [
        "(5-15)% increased Magnitude of Bleeding you inflict",
        "Bonded: 8% increased Physical Damage",
    ], "texts·per_slot만 — texts_ko는 판정 축이 아니다"


def test_every_flag_has_english_grounds() -> None:
    """플래그가 붙은 레코드는 **영문**에 근거가 있어야 한다.

    붙은 근거를 한글에서 찾을 수 있으면 그건 수집 오염이 판정으로 승격된 것이다 —
    실측 2026-08-07: `radius-grant` 519건이 정확히 그랬고 영문 근거는 0건이었다.
    """
    from pok.kb.pob_gaps import scannable_lines
    from pok.kb.store import load

    for record in load().records.values():
        data = record.raw.get("data") or {}
        modeling = data.get("pob_modeling")
        if not isinstance(modeling, dict):
            continue
        assert scannable_lines(data), f"{record.id}: 영문 줄이 없는데 미모델링 판정이 붙었다"


def test_clean_jewel_mod_carries_only_its_own_lines() -> None:
    """조회 경로에서 본 결과 — 옆 모드의 줄도, 그로 인한 오탐 플래그도 없다.

    `jewelspellcriticalchance`는 오염 시절 한글 2줄(둘째 줄은 반경 주얼판의 것)에
    `radius-grant`가 붙어 있었다.
    """
    from pok.index.search import get_entry

    data = get_entry("modifier.jewelspellcriticalchance", fields=["data"])["data"]
    assert data["texts"] == ["(5-15)% increased Critical Hit Chance for Spells"]
    assert data["texts_ko"] == ["주문 치명타 명중 확률 (5-15) % 증가"], "자기 줄 하나뿐"
    assert "pob_modeling" not in data, "반경 부여는 PoB가 파싱한다 (ModParser.lua:7041)"


def test_flags_are_visible_from_the_record() -> None:
    """조회하면 바로 보여야 세션이 실측 불가를 안다."""
    from pok.index.search import get_entry

    data = get_entry("modifier.idol-of-the-sycophant", fields=["data"])["data"]
    assert data["pob_modeling"]["supported"] is False
    assert "추산" in data["pob_modeling"]["workaround"]
