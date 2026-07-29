"""P1b: 파서(②) + KI-8 판정 매트릭스 + 리포트 end-to-end (픽스처, 네트워크 없음)."""

from __future__ import annotations

import json
from pathlib import Path

from pok.kb.ingest.parse import parse_detail, parse_name_only
from pok.kb.ingest.process import GHOST, IMPLEMENTED, NO_POB, POB_ONLY, _classify, process_patch


def _detail_html(name: str, *, acquisition: bool, tags: str = "Spell , Fire") -> str:
    from_card = (
        '<div class="card"><div class="card-header">From /1</div>'
        '<a href="/us/Uncut_Skill_Gem">Uncut Skill Gem</a></div>'
        if acquisition
        else ""
    )
    return f"""
    <html><head><title>{name} - PoE2DB, Path of Exile Wiki us</title>
    <meta property="og:description" content="{name} 설명."></head><body>
    <span class="typeLine">{name}</span>
    <span class="Stats">{tags} Tier: 7</span>
    {from_card}
    <div class="card"><div class="card-header">Level Effect /40</div></div>
    </body></html>
    """


def test_parse_detail_full() -> None:
    page = parse_detail(_detail_html("Spark", acquisition=True))
    assert page.name == "Spark"
    assert page.tags == ["Spell", "Fire"]
    assert page.tier == 7
    assert page.acquisition == ["Uncut Skill Gem"] and page.acquisition_count == 1
    assert page.has_level_effect

    ghost = parse_detail(_detail_html("Bane", acquisition=False))
    assert ghost.acquisition == [] and ghost.acquisition_count is None


def test_parse_name_only_kr() -> None:
    html = "<html><head><title>스파크 - PoE2DB, Path of Exile Wiki kr</title></head></html>"
    assert parse_name_only(html) == "스파크"


def test_classify_matrix() -> None:
    """KI-8 판정 매트릭스 4분면."""
    assert _classify(True, True) == IMPLEMENTED
    assert _classify(False, False) == GHOST
    assert _classify(True, False) == NO_POB
    assert _classify(False, True) == POB_ONLY


def test_process_end_to_end(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    (raw / "poe2db" / "us").mkdir(parents=True)
    (raw / "poe2db" / "kr").mkdir(parents=True)
    (raw / "pob").mkdir(parents=True)

    (raw / "fetch-plan.json").write_text(
        json.dumps(
            {
                "patch": "t",
                "source": "poe2db",
                "langs": ["us", "kr"],
                "categories": {
                    "skill-gems": {
                        "listed_count": 3,
                        "planned_count": 2,
                        "items": ["Spark", "Bane"],
                    },
                    # Spark는 두 카테고리에 실림 → dedup 검증
                    "spirit-gems": {"listed_count": 1, "planned_count": 1, "items": ["Spark"]},
                },
            }
        ),
        encoding="utf-8",
    )
    (raw / "poe2db/us/Spark.html").write_text(
        _detail_html("Spark", acquisition=True), encoding="utf-8"
    )
    (raw / "poe2db/kr/Spark.html").write_text(
        "<html><head><title>스파크 - PoE2DB kr</title></head></html>", encoding="utf-8"
    )
    (raw / "poe2db/us/Bane.html").write_text(
        _detail_html("Bane", acquisition=False), encoding="utf-8"
    )
    (raw / "pob/gems.json").write_text(
        json.dumps(
            {
                "Metadata/SkillGemSpark": {"name": "Spark", "gemType": "Spell"},
                "Metadata/OldPoE1Gem": {"name": "Ancient Relic", "gemType": "Spell"},
            }
        ),
        encoding="utf-8",
    )

    report = process_patch(raw, tmp_path / "out")
    assert report["totals"]["processed"] == 2, "카테고리 중복 dedup"
    assert report["totals"][IMPLEMENTED] == 1
    assert report["ghosts"] == ["Bane"], "획득 없음 ∧ PoB 없음 → 유령"
    assert report["pob_unmatched"] == ["Ancient Relic"], "PoB 잔재 역방향 감지 (기준 ②)"

    items = json.loads((tmp_path / "out/intermediate.json").read_text(encoding="utf-8"))
    spark = next(i for i in items if i["slug"] == "Spark")
    assert spark["name_ko"] == "스파크"
    assert sorted(spark["categories"]) == ["skill-gems", "spirit-gems"]
    assert (raw / "report.json").exists(), "리포트 = 데이터 repo 증거"
