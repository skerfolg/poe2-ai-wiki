"""P1b ③: PoB 유니크 텍스트 블록 파싱 — 변형(variant) 처리가 핵심."""

from __future__ import annotations

from pathlib import Path

from pok.kb.ingest.uniques import parse_block, parse_pob_uniques

MULTI_VARIANT = """
Astramentis
Stellar Amulet
Variant: Pre 0.2.0
Variant: Current
Implicits: 1
{tags:attribute}+(5-7) to all Attributes
{variant:1}{tags:attribute}+(80-100) to all Attributes
{variant:2}{tags:attribute}+(50-100) to all Attributes
{tags:physical,attack}-4 Physical Damage taken from Attack Hits
"""

NO_VARIANT = """
Fixation of Yix
Stellar Amulet
Implicits: 1
{tags:attribute}+(5-7) to all Attributes
{tags:life}+100 to maximum Life
"""


def test_current_variant_only() -> None:
    """마지막 Variant(=현재 패치본)의 모드만 남기고 과거 값은 버린다."""
    item = parse_block(MULTI_VARIANT, "amulet")
    assert item is not None
    assert item.name == "Astramentis"
    assert item.base_type == "Stellar Amulet"
    assert item.variants == ["Pre 0.2.0", "Current"]
    assert item.implicits == ["+(5-7) to all Attributes"]
    assert item.explicits == [
        "+(50-100) to all Attributes",  # variant 2 = Current
        "-4 Physical Damage taken from Attack Hits",  # variant 태그 없음 = 공통
    ]
    assert "+(80-100) to all Attributes" not in item.explicits, "과거 패치 값 오염 금지"
    assert item.mod_tags == ["attack", "attribute", "physical"]


def test_no_variant_item() -> None:
    item = parse_block(NO_VARIANT, "amulet")
    assert item is not None
    assert item.variants == []
    assert item.implicits == ["+(5-7) to all Attributes"]
    assert item.explicits == ["+100 to maximum Life"]


def test_malformed_block_returns_none() -> None:
    assert parse_block("OnlyOneLine", "amulet") is None
    assert parse_block("", "amulet") is None


def test_parse_real_pob_data() -> None:
    """실제 PoB 데이터가 파싱되는지 (클론이 있을 때만)."""
    d = Path(__file__).resolve().parents[2] / "external/pob/5d173cb/src/Data/Uniques"
    if not d.is_dir():
        return  # 클론 없는 환경(CI)에서는 건너뛴다
    items = parse_pob_uniques(d)
    assert len(items) > 400
    assert len({i.name for i in items}) == len(items), "이름 중복 없음"
    astra = next(i for i in items if i.name == "Astramentis")
    assert astra.base_type == "Stellar Amulet"


PAGE_HTML = """
<html><body>
<div class="card"><h5 class="card-header">Armour Unique /2</h5>
 <div class="card-body"><div class="row">
  <div><span>Bramblejack</span><span>Rusted Cuirass</span><span>Requires:</span>
       <span>Level 1</span><span>+(60-100) to maximum Life</span></div>
  <div><span>Blackbraid</span><span>Fur Plate</span><span>Requires:</span>
       <span>Level 4</span><span>10 Str</span><span>+(40-60) to Armour</span></div>
 </div></div></div>
<div class="card"><h5 class="card-header">Cultivated Uniques /1</h5>
 <div class="card-body"><div class="row">
  <div><span>Bramblejack</span><span>Rusted Cuirass</span>
       <span>+(90-150) to maximum Life</span></div>
 </div></div></div>
</body></html>
"""


def test_page_parse_requires_and_groups() -> None:
    from pok.kb.ingest.uniques_page import parse_page

    items = parse_page(PAGE_HTML)
    assert len(items) == 3
    bramble = items[0]
    assert bramble.name == "Bramblejack"
    assert bramble.base_type == "Rusted Cuirass"
    assert bramble.requires == "Level 1", "요구사항은 모드와 분리된다"
    assert bramble.mods == ["+(60-100) to maximum Life"]

    black = items[1]
    assert black.requires == "Level 4, 10 Str", "능력치 요구가 여러 개여도 모두 잡는다"
    assert black.mods == ["+(40-60) to Armour"]

    assert items[2].class_group == "cultivated", "재배판은 별도 분류"


def test_cultivated_gets_distinct_id() -> None:
    """같은 이름의 재배판은 별개 아이템이므로 id가 갈린다."""
    from pok.kb.ingest.uniques_page import _to_record

    base = {
        "name_en": "Bramblejack",
        "name_ko": "가시나무 갑옷",
        "base_type": "Rusted Cuirass",
        "base_type_ko": None,
        "class_group": "armour",
        "category": "body",
        "requires": None,
        "implicits": [],
        "explicits": [],
        "variants": [],
        "mod_tags": [],
        "in_pob": True,
    }
    cultivated = {**base, "class_group": "cultivated"}
    assert _to_record(base, "t")["id"] == "item.bramblejack"
    assert _to_record(cultivated, "t")["id"] == "item.bramblejack-cultivated"
