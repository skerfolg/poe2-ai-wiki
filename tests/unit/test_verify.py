"""완전성 기준 ⑥⑦⑧ 공통 검증기 (KB_INGEST §4) — 픽스처, 네트워크 없음.

각 기준이 잡아내야 할 실제 결함(2026-07-29 실증)을 최소 재현으로 고정한다.
"""

from __future__ import annotations

from pok.kb.ingest.verify import (
    SourceEntity,
    acquisition_coverage,
    cross_source,
    substance_floor,
    verification_block,
)

# ── ⑥ 교차 일관성 ───────────────────────────────────────────────


def test_cross_source_name_mismatch() -> None:
    """같은 id인데 소스마다 이름이 다르면 리포트 (Arsonist→Pyromancer 실측)."""
    r = cross_source(
        [SourceEntity("14265", "Arsonist")],
        [SourceEntity("14265", "Pyromancer")],
        labels=("poe2db", "pob"),
        compare_names=True,
    )
    assert r["matched"] == 1
    assert r["name_mismatch"]["count"] == 1
    assert r["name_mismatch"]["sample"][0] == {
        "key": "14265",
        "field": "name",
        "poe2db": "Arsonist",
        "pob": "Pyromancer",
    }


def test_cross_source_name_not_compared_when_key_is_the_name() -> None:
    """key가 곧 이름인 카테고리(젬·유니크)에선 이름 대조 항목을 내지 않는다."""
    r = cross_source(
        [SourceEntity("spark", "Spark")], [SourceEntity("spark", "Spark")], labels=("poe2db", "pob")
    )
    assert "name_mismatch" not in r


def test_cross_source_missing_is_bidirectional() -> None:
    """한쪽에만 있는 항목은 **양방향** 모두 리포트한다 (기준 ② 강화)."""
    r = cross_source(
        [SourceEntity("spark", "Spark"), SourceEntity("only-db", "Only DB")],
        [
            SourceEntity("spark", "Spark"),
            SourceEntity("only-pob", "Only PoB"),
            SourceEntity("bane", "Bane"),
        ],
        labels=("poe2db", "pob"),
        known_only_in_secondary={"bane"},  # 원장 승인된 PoE1 잔재
    )
    assert r["only_in_poe2db"] == {"count": 1, "sample": ["Only DB"]}
    assert r["only_in_pob"] == {"count": 1, "sample": ["Only PoB"]}
    assert r["known_excluded_from_only_in_pob"] == 1, "제외도 건수로 드러낸다"


def test_cross_source_fact_mismatch() -> None:
    r = cross_source(
        [SourceEntity("nebuloch", "Nebuloch", facts={"base_type": "Execratus Hammer"})],
        [SourceEntity("nebuloch", "Nebuloch", facts={"base_type": "Brigand Mace"})],
        labels=("poe2db", "pob"),
    )
    assert r["fact_mismatch"]["count"] == 1
    assert r["fact_mismatch"]["by_field"] == {"base_type": 1}
    row = r["fact_mismatch"]["sample"][0]
    assert (row["poe2db"], row["pob"], row["name"]) == (
        "Execratus Hammer",
        "Brigand Mace",
        "Nebuloch",
    )


def test_cross_source_fact_only_compared_when_both_sides_have_it() -> None:
    """한쪽에만 있는 필드는 불일치가 아니다 (없음 ≠ 다름)."""
    r = cross_source(
        [SourceEntity("x", "X", facts={"tier": "3"})],
        [SourceEntity("x", "X")],
        labels=("poe2db", "pob"),
    )
    assert r["fact_mismatch"]["count"] == 0


def test_cross_source_set_diff_is_directional() -> None:
    """집합 필드는 방향별 차집합으로 본다 — 통짜 비교하면 표기 차이로 전건 불일치."""
    r = cross_source(
        [SourceEntity("x", "X", sets={"tags": frozenset({"fire", "staged"})})],
        [SourceEntity("x", "X", sets={"tags": frozenset({"fire", "spell"})})],
        labels=("poe2db", "pob"),
    )
    diff = r["set_diff"]["tags"]
    assert diff["only_in_poe2db"]["sample"][0]["values"] == ["staged"]
    assert diff["only_in_pob"]["sample"][0]["values"] == ["spell"]


def test_cross_source_set_diff_absent_when_identical() -> None:
    r = cross_source(
        [SourceEntity("x", "X", sets={"tags": frozenset({"fire"})})],
        [SourceEntity("x", "X", sets={"tags": frozenset({"fire"})})],
        labels=("poe2db", "pob"),
    )
    assert "set_diff" not in r


def test_cross_source_duplicate_key_conflict() -> None:
    """한 소스 안의 중복 key 충돌 — 교차 대사가 볼 수 없는 사각지대.

    실측(0.5.4b): 유니크 목록의 재배(cultivated) 카드가 base_type 자리에 모드 텍스트
    조각을 담았고, 이름으로 dedup되면서 조용히 버려져 KB에 그대로 실렸다.
    """
    r = cross_source(
        [
            SourceEntity("greed's embrace", "Greed's Embrace", facts={"base_type": "Vaal Cuirass"}),
            SourceEntity("greed's embrace", "Greed's Embrace", facts={"base_type": "(100"}),
        ],
        [SourceEntity("greed's embrace", "Greed's Embrace", facts={"base_type": "Vaal Cuirass"})],
        labels=("poe2db", "pob"),
    )
    dup = r["duplicate_key_conflict_in_poe2db"]
    assert dup["count"] == 1
    assert dup["sample"][0]["poe2db#2"] == "(100"
    assert r["duplicate_key_conflict_in_pob"]["count"] == 0
    assert r["fact_mismatch"]["count"] == 0, "첫 항목이 살아남아 교차 대사는 통과한다"


def test_cross_source_duplicate_without_conflict_is_silent() -> None:
    """값이 같은 중복은 충돌이 아니다."""
    r = cross_source(
        [SourceEntity("x", "X", facts={"t": "1"}), SourceEntity("x", "X", facts={"t": "1"})],
        [SourceEntity("x", "X")],
        labels=("a", "b"),
    )
    assert r["duplicate_key_conflict_in_a"]["count"] == 0


def test_cross_source_sample_is_capped() -> None:
    r = cross_source(
        [SourceEntity(str(i), f"N{i}") for i in range(50)], [], labels=("a", "b"), sample=3
    )
    assert r["only_in_a"]["count"] == 50 and len(r["only_in_a"]["sample"]) == 3


# ── ⑦ 정보량 하한 ───────────────────────────────────────────────


def test_substance_floor_flags_empty_records() -> None:
    """수록 대상인데 실질 정보가 빈 레코드 — 마스터리 유형 혼입 차단."""
    r = substance_floor(
        [
            SourceEntity("1", "Chaos Inoculation", substance=("Maximum Life becomes 1",)),
            SourceEntity("9", "Armour Mastery", substance=()),
            SourceEntity("8", "Blank", substance=("   ",)),  # 공백만 = 빈 것
        ],
        scope="passive:included",
    )
    assert r["scope"] == "passive:included"
    assert r["checked"] == 3
    assert r["empty"]["count"] == 2
    assert [x["name"] for x in r["empty"]["sample"]] == ["Armour Mastery", "Blank"]


def test_substance_floor_exempts_structural_nodes() -> None:
    """주얼 슬롯·어센던시 시작점은 효과가 없는 게 정상 — 면제하되 건수는 남긴다."""
    r = substance_floor(
        [
            SourceEntity("5", "Jewel Socket", structural=True),
            SourceEntity("6", "Notable", substance=("x",)),
        ],
        scope="passive:included",
    )
    assert r["structural_exempt"] == 1
    assert r["checked"] == 1
    assert r["empty"]["count"] == 0


# ── ⑧ 획득 경로 커버리지 ─────────────────────────────────────────


def test_acquisition_coverage_ratio_and_routes() -> None:
    r = acquisition_coverage(
        [
            SourceEntity("1", "Notable A", acquisition=("tree-edge",)),
            SourceEntity("2", "Notable B", acquisition=("tree-edge", "liquid-emotion")),
            SourceEntity("3", "Far Shot", acquisition=()),
            SourceEntity("4", "Point Blank", acquisition=()),
        ],
        entity_type="passive",
    )
    assert r["entity_type"] == "passive"
    assert (r["total"], r["with_acquisition"], r["coverage"]) == (4, 2, 0.5)
    assert r["routes_top"] == {"tree-edge": 2, "liquid-emotion": 1}
    assert [x["name"] for x in r["missing"]["sample"]] == ["Far Shot", "Point Blank"]


def test_acquisition_coverage_zero_is_a_collection_signal() -> None:
    """전건 미수집이면 커버리지 0 — 그 0 자체가 누락 신호다 (조용히 넘어가지 않는다)."""
    r = acquisition_coverage([SourceEntity("1", "Astramentis")], entity_type="unique")
    assert r["coverage"] == 0.0 and r["missing"]["count"] == 1


def test_acquisition_coverage_empty_input() -> None:
    r = acquisition_coverage([], entity_type="gem")
    assert r == {
        "entity_type": "gem",
        "total": 0,
        "with_acquisition": 0,
        "coverage": 0.0,
        "routes_top": {},
        "distinct_routes": 0,
        "missing": {"count": 0, "sample": []},
    }


# ── 리포트 조립 ─────────────────────────────────────────────────


def test_verification_block_keys_are_uniform() -> None:
    """세 모듈이 같은 키로 리포트해야 사람이 한 눈에 비교한다."""
    block = verification_block()
    assert list(block) == ["6_cross_source", "7_substance_floor", "8_acquisition_coverage"]
    assert all(v == [] for v in block.values())
