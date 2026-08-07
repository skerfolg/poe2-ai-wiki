# ruff: noqa: E501  (임베디드 JSON 픽스처는 원본 형태 보존이 우선)
"""P1b ④ 보강: poe2db 모드 카탈로그 파서 + PoB 교차 (픽스처, 네트워크 없음)."""

from __future__ import annotations

import json
from pathlib import Path

from pok.kb.ingest.essences import parse_page as parse_essence_page
from pok.kb.ingest.mod_catalog import (
    _norm_text,
    align_key,
    aligned_ko_texts,
    build_ko_line_index,
    match_key,
    parse_desecrated,
    parse_modsview,
    process_catalog,
)

# ModsView 임베디드 JSON (클래스 페이지 원형 축약)
MODSVIEW_HTML = """
<html><body><div id="ModifiersCalc"></div>
<script>
$(function() {
    new ModsView({"baseitem":{"href":"Amulets"},"config":{},"gen":{},"opt":{},
    "normal":[
      {"Name":"of the Brute","Level":"1","ModGenerationTypeID":"2",
       "ModFamilyList":["Strength"],"DropChance":"1000",
       "str":"<span class='mod-value'>+(5<span class=\\"ndash\\">—</span>8)</span> to <a href=\\"Strength\\">Strength</a>",
       "spawn_no":["ring","amulet","default"],
       "mod_no":["<span class=\\"badge bg-primary craftingattribute\\" data-tag=\\"attribute\\">Attribute</span>"]}
    ],
    "perfect_essence":[
      {"Name":"<a href=\\"runic_alloy\\"><img src=\\"x.webp\\"/>Celestial Alloy</a>",
       "Level":"65","ModGenerationTypeID":"2",
       "ModFamilyList":["AccuracyAttackSpeedHybrid"],"DropChance":"0",
       "str":"+(327<span class=\\"ndash\\">—</span>427) to Accuracy Rating (5<span class=\\"ndash\\">—</span>8)% increased Attack Speed",
       "spawn_no":[],"mod_no":[]}
    ],
    "chronomancy":[
      {"Name":"of Chronomancy","Level":"1","ModGenerationTypeID":"2",
       "ModFamilyList":["SkillEffectDuration"],"DropChance":"500",
       "str":"(15<span class=\\"ndash\\">—</span>19)% increased Skill Effect Duration",
       "spawn_no":["boots"],"mod_no":[]}
    ],
    "corrupted":[],"desecrated":[]});
});
</script></body></html>
"""

DESECRATED_HTML = """
<html><body>
<div class="card"><h5 class="card-header">Desecrated Mods /2</h5>
<table><tr><th>Name</th><th>Level</th><th>Pre/Suf</th><th>Description</th></tr>
<tr><td>Amanamu's</td><td>65</td><td>Prefix</td>
    <td><span class="mod-value">2</span> to <span class="mod-value">4</span>
        <a href="Fire_Damage">Fire</a> Thorns damage per 100 maximum Life
        <span class="badge bg-primary" data-tag="amanamu_mod"><i>amanamu</i></span>
        <span class="badge bg-primary" data-tag="fire">Fire</span></td></tr>
<tr><td>Kurgal's</td><td>65</td><td>Suffix</td>
    <td>(5 <span class="ndash">—</span> 10)% increased Armour
        <span class="badge bg-primary" data-tag="kurgal_mod"><i>kurgal</i></span></td></tr>
</table></div>
<div class="card"><h5 class="card-header">Jewels Desecrated Mods /1</h5>
<table><tr><th>Name</th><th>Level</th><th>Pre/Suf</th><th>Description</th></tr>
<tr><td>Lightless</td><td>1</td><td>Prefix</td>
    <td>(5 <span class="ndash">—</span> 10)% increased Armour</td></tr>
</table></div>
</body></html>
"""

ESSENCE_LIST_HTML = """
<html><body>
<div class="card"><h5 class="card-header">Essence /2</h5>
<div class="row">
 <div><span>Lesser Essence of the Body</span><span>Stack Size:</span><span>1 / 10</span>
      <span>Armour or Belt:</span><span>+(30 — 39) to maximum Life</span></div>
 <div><span>Essence of Delirium</span><span>Stack Size:</span><span>1 / 10</span>
      <span>Body Armour: Allocates a random Notable Passive Skill</span></div>
</div></div>
</body></html>
"""


def test_parse_modsview_pools_and_fields() -> None:
    pools = parse_modsview(MODSVIEW_HTML)
    assert set(pools) == {"normal", "perfect_essence", "chronomancy"}, "빈 풀은 생략"

    n = pools["normal"][0]
    assert n["affix_name"] == "of the Brute"
    assert (n["ilvl"], n["affix_type"]) == (1, "suffix")
    assert n["families"] == ["Strength"]
    assert n["drop_chance"] == 1000, "poe2db 가중치 — PoB의 성긴 자리를 채우는 값"
    assert n["text"] == "+(5-8) to Strength"
    assert n["spawn_tags"] == ["ring", "amulet", "default"]
    assert n["mod_tags"] == ["attribute"]

    # Alloy 계열: Name이 화폐 링크 HTML → 평문으로 정리된다
    p = pools["perfect_essence"][0]
    assert p["affix_name"] == "Celestial Alloy"
    assert "(5-8)% increased Attack Speed" in p["text"]


def test_parse_desecrated_tables() -> None:
    out = parse_desecrated(DESECRATED_HTML)
    assert set(out) == {"equipment", "jewel"}
    eq = out["equipment"]
    assert len(eq) == 2
    assert eq[0]["affix_name"] == "Amanamu's"
    assert eq[0]["affix_type"] == "prefix"
    assert eq[0]["mod_tags"] == ["amanamu_mod", "fire"], "배지 태그는 분리 수집"
    assert "amanamu" not in eq[0]["text"], "배지를 뺀 것이 효과 텍스트"
    assert eq[1]["text"].startswith("(5-10)% increased Armour")


def test_essence_page_parse() -> None:
    items = parse_essence_page(ESSENCE_LIST_HTML)
    assert [e["name"] for e in items] == ["Lesser Essence of the Body", "Essence of Delirium"]
    assert items[0]["tier"] == "lesser" and items[0]["family"] == "Essence of the Body"
    assert items[1]["tier"] == "normal", "섬망의 에센스 — 실존 (E-1 판정 근거)"


def _write_fixture(raw: Path, out: Path) -> dict[str, object]:
    (raw / "poe2db" / "us").mkdir(parents=True)
    (raw / "modifiers").mkdir(parents=True)
    (raw / "poe2db" / "us" / "Amulets.html").write_text(MODSVIEW_HTML, encoding="utf-8")
    (raw / "modifiers" / "desecrated.us.html").write_text(DESECRATED_HTML, encoding="utf-8")
    out.mkdir(parents=True)
    # PoB 쪽 보류 모드 3종: 이름키 매칭 / 결합 텍스트 매칭 / 미매칭
    pob_mods = [
        {
            "pob_key": "Strength1",
            "affix_type": "suffix",
            "affix_name": "of the Brute",
            "texts": ["+(5-8) to Strength"],
            "group": "Strength",
            "ilvl": 1,
            "spawn_weights": {"default": 0},
            "origins": ["item"],
            "acquisition": [],
        },
        {
            "pob_key": "AlloyAccuracyAttackSpeedHybrid1",
            "affix_type": "suffix",
            "affix_name": "Verisium",
            "texts": ["+(327-427) to Accuracy Rating", "(5-8)% increased Attack Speed"],
            "group": "AlloyHybridSomethingElse",
            "ilvl": 65,
            "spawn_weights": {"default": 0},
            "origins": ["item"],
            "acquisition": [],
        },
        {
            "pob_key": "AttackAndCastSpeed1",
            "affix_type": "suffix",
            "affix_name": "of Zeal",
            "texts": ["(3-4)% increased Attack and Cast Speed"],
            "group": "AttackAndCastSpeed",
            "ilvl": 15,
            "spawn_weights": {"default": 0},
            "origins": ["item"],
            "acquisition": [],
        },
    ]
    (out / "mods.json").write_text(json.dumps(pob_mods), encoding="utf-8")
    return {
        "categories": {"modifier-pages": {"items": ["Amulets", "MissingPage"]}},
    }


def test_process_catalog_cascade_matching(tmp_path: Path) -> None:
    """C 판정의 핵심 — 계단식 매칭(이름키 → 패밀리+ilvl → 결합 텍스트)."""
    raw, out = tmp_path / "raw", tmp_path / "out"
    plan = _write_fixture(raw, out)

    report = process_catalog(raw, out, plan)  # type: ignore[arg-type]
    assert report["pages_parsed"] == 1
    assert report["pages_missing"] == ["MissingPage"], "미도착 페이지는 명시 (조용한 스킵 금지)"
    assert report["catalog_entries"] == 3
    assert report["desecrated_tables"] == {"equipment": 2, "jewel": 1}

    hm = report["held_membership"]
    assert hm["held_total"] == 3
    assert hm["confirmed_by_key"] == 1, "of the Brute — 이름키"
    assert hm["confirmed_by_text"] == 1, "Alloy hybrid — 두 줄 결합 텍스트"
    assert hm["unmatched"] == 1 and hm["unmatched_sample"] == ["AttackAndCastSpeed1"], (
        "of Zeal — poe2db 어느 풀에도 없음 = 진짜 죽은 모드 후보"
    )
    assert hm["confirmed_pools"].get("perfect_essence") == 1

    cat = json.loads((out / "mod_catalog.json").read_text(encoding="utf-8"))
    assert match_key("of the Brute", ["Strength"], 1) in cat
    assert (raw / "modifiers" / "catalog-report.json").exists(), "리포트 = 데이터 repo 증거"


def test_norm_text_absorbs_notation_differences() -> None:
    """poe2db와 PoB의 표기 차이(범위 공백·% 공백·대시)를 흡수해야 대조가 성립한다."""
    assert _norm_text("(15 — 19) % increased Skill Effect Duration") == _norm_text(
        "(15-19)% increased Skill Effect Duration"
    )


def test_align_key_ignores_html_derived_spacing() -> None:
    """poe2db는 `get_text(" ")`로 뽑아 쉼표·괄호 앞을 띄운다 — 의미가 아니라 부산물이다.

    남겨 두면 같은 줄이 다른 줄로 보여 한글이 통째로 떨어져 나간다(실측: 5건).
    """
    assert align_key("(20-30)% increased Global Armour, Evasion and Energy Shield") == align_key(
        "(20-30) % increased global armour , evasion and energy shield"
    )
    assert align_key("+(4-5) maximum stacks of Puppet Master") == align_key(
        "+ (4-5) maximum stacks of puppet master"
    )


def test_ko_index_drops_conflicting_lines_instead_of_guessing() -> None:
    """한 영문 줄에 서로 다른 한글이 붙으면 **빼고 보고한다** — 임의로 고르지 않는다.

    전역화가 안전한지는 짐작하지 말고 여기서 재는 것이 요점이다 (실측 0.5.4b:
    3,427줄 중 충돌 0건).
    """
    catalog = {
        "a": {"ko_by_text": {"+(5-8) to strength": "힘 +(5-8)"}},
        "b": {"ko_by_text": {"+(5-8) to Strength": "힘 +(5-8)"}},  # 표기만 다름 → 같은 줄
        "c": {"ko_by_text": {"adds fire damage": "화염 피해 추가"}},
        "d": {"ko_by_text": {"Adds Fire Damage": "불 피해 추가"}},  # 진짜 충돌
    }
    index, conflicts = build_ko_line_index(catalog)
    assert index[align_key("+(5-8) to Strength")] == "힘 +(5-8)", "표기 차이는 흡수"
    assert conflicts == [align_key("adds fire damage")], "충돌은 색인에서 빠지고 보고된다"
    assert align_key("adds fire damage") not in index


def test_aligned_ko_is_all_or_nothing() -> None:
    """줄 하나라도 짝이 없으면 통째로 포기한다 — 틀린 번역보다 없는 번역이 낫다.

    이게 `len(texts) == len(texts_ko)`를 **구조적으로** 보장한다(철칙 5). 통째로
    붙이던 시절 옆 모드의 줄이 섞여 1,536건이 오염됐고, 그 오염이 `radius-grant`
    오탐 519건을 낳았다 (2026-08-07).
    """
    ko_lines = {
        align_key("+(5-8) to Strength"): "힘 +(5-8)",
        align_key("Notable Passive Skills in Radius also grant +(2-3) to Strength"): (
            "반경 내 주요 패시브 스킬이 힘 +(2-3)도 부여"
        ),
    }
    assert aligned_ko_texts(["+(5-8) to Strength"], ko_lines) == ["힘 +(5-8)"], (
        "슬롯에 반경판이 함께 있어도 자기 줄만 온다"
    )
    # 하이브리드: PoB 두 줄 ↔ poe2db 한 줄 → 짝을 못 맞추면 접는다 (KB_INGEST §3b와 동일 판정)
    assert aligned_ko_texts(["+(5-8) to Strength", "Adds Fire Damage"], ko_lines) == []
    assert aligned_ko_texts([], ko_lines) == []
