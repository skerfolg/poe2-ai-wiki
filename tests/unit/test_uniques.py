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


# 재배 카드가 base_type 자리에 모드 조각을 담은 형태 (0.5.4b 실측 47건의 최소 재현)
BROKEN_CULTIVATED_HTML = """
<html><body>
<div class="card"><h5 class="card-header">Armour Unique /2</h5>
 <div class="card-body"><div class="row">
  <div><span>Bramblejack</span><span>Rusted Cuirass</span>
       <span>+(60-100) to maximum Life</span></div>
  <div><span>Tabula Rasa</span><span>Simple Robe</span></div>
 </div></div></div>
<div class="card"><h5 class="card-header">Cultivated Uniques /1</h5>
 <div class="card-body"><div class="row">
  <div><span>Bramblejack</span><span>(100</span><span>-150) to maximum Life</span></div>
 </div></div></div>
</body></html>
"""

POB_LUA = """
[[
Bramblejack
Rusted Cuirass
{tags:life}+(60-100) to maximum Life
]]
[[
Ghostwrithe
Silk Robe
]]
"""


def test_process_report_carries_verification(tmp_path: Path) -> None:
    """⑥⑦⑧이 유니크 리포트에 자동으로 실린다 (KB_INGEST §4)."""
    import json

    from pok.kb.ingest.uniques_page import process

    raw, pob_dir, out = tmp_path / "raw", tmp_path / "pob", tmp_path / "out"
    (raw / "uniques").mkdir(parents=True)
    pob_dir.mkdir(parents=True)
    (raw / "uniques/us.html").write_text(BROKEN_CULTIVATED_HTML, encoding="utf-8")
    (raw / "uniques/kr.html").write_text(BROKEN_CULTIVATED_HTML, encoding="utf-8")
    (pob_dir / "body.lua").write_text(POB_LUA, encoding="utf-8")

    report = process(raw, pob_dir, out)
    assert report["cultivated_base_inherited"] == 1, "재배판은 동명 일반판의 베이스를 승계"
    assert report["unresolved_base_type"] == []
    items = json.loads((out / "uniques.json").read_text(encoding="utf-8"))
    cult = next(i for i in items if i["class_group"] == "cultivated")
    assert cult["base_type"] == "Rusted Cuirass", "모드 조각 '(100'이 아니라 진짜 베이스"

    v = report["verification"]
    cross = v["6_cross_source"][0]
    assert cross["duplicate_key_conflict_in_poe2db"]["count"] == 0, (
        "⑥ 승계 후에는 동명 재배판과 일반판의 base_type이 같다"
    )
    assert cross["only_in_pob"]["sample"] == ["Ghostwrithe"], "⑥ 양방향 — PoB 단독"

    floor = v["7_substance_floor"][0]
    assert floor["checked"] == 3
    assert [x["name"] for x in floor["empty"]["sample"]] == ["Tabula Rasa"], (
        "⑦ 모드가 하나도 없는 수록 항목"
    )

    acq = v["8_acquisition_coverage"][0]
    assert (acq["entity_type"], acq["coverage"]) == ("unique", 0.0), (
        "⑧ 드랍 출처 미수집 — 0 자체가 누락 신호"
    )
    assert json.loads((raw / "uniques/report.json").read_text(encoding="utf-8"))["verification"]


VARIANT_BASE = """
Voll's Protector
{variant:1}Ironclad Vestments
{variant:2}Plated Vestments
Variant: Pre 0.1.1
Variant: Pre 0.4.0
Variant: Current
{variant:1}(100-150)% increased Armour and Energy Shield
{variant:2}(150-200)% increased Armour and Energy Shield
25% reduced maximum Mana
"""

META_BEFORE_BASE = """
Hand of Wisdom and Action
Variant: Pre 0.2.0
Variant: Current
Source: Drops from unique{Xesht, We That Are One}
{variant:1}Furtive Wraps
{variant:2}Spiral Wraps
+(15-25) to Dexterity
"""


def test_variant_base_type_falls_back_to_last_declared() -> None:
    """현재 변형에 베이스 선언이 없으면 마지막 선언분을 쓴다 (poe2db와 일치)."""
    item = parse_block(VARIANT_BASE, "body")
    assert item is not None
    assert item.base_type == "Plated Vestments", "변형 3엔 선언이 없어 변형 2의 베이스"
    assert item.explicits == ["25% reduced maximum Mana"], "과거 변형 전용 모드는 버린다"


def test_base_type_after_meta_lines() -> None:
    """메타 줄(Variant/Source)이 이름과 베이스 사이에 끼어도 베이스를 찾는다."""
    item = parse_block(META_BEFORE_BASE, "gloves")
    assert item is not None
    assert item.base_type == "Spiral Wraps", "예전엔 'Variant: Pre 0.2.0'을 베이스로 잡았다"
    assert item.explicits == ["+(15-25) to Dexterity"]


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


def test_jewel_fixes_scope() -> None:
    """주얼 보정은 13종(15레코드)에만 닿고 다른 항목은 건드리지 않는다 (task #32)."""
    from pok.kb.ingest.jewel_fixes import JEWEL_FIXES, apply_jewel_fixes

    assert len(JEWEL_FIXES) == 15
    items = [
        {"name_en": "Megalomaniac", "class_group": "other", "explicits": ["Allocates"]},
        {"name_en": "Astramentis", "class_group": "other", "explicits": ["+(50-100)"]},
    ]
    assert apply_jewel_fixes(items) == 1
    assert items[0]["explicits"] == [
        "Allocates Passive Skill",
        "Allocates Passive Skill",
        "Allocates Passive Skill",
        "Corrupted",
    ]
    assert items[1]["explicits"] == ["+(50-100)"]  # 비대상 불변


def test_jewel_fixes_no_fragments() -> None:
    """보정 결과에 조각 줄("+"·"(1"·"—" 따위)이 남지 않는다."""
    from pok.kb.ingest.jewel_fixes import JEWEL_FIXES

    for (name, _), fix in JEWEL_FIXES.items():
        for line in fix.get("explicits", []) + fix.get("explicits_ko", []):
            assert len(line) > 3 or line == "타락", (name, line)
            assert "—" not in line, (name, line)
