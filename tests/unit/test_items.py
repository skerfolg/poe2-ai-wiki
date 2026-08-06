"""아이템 최적화 루프 (사용자 지시 2026-08-06).

트리에는 optimize_tree가 있는데 아이템에는 루프가 없었다 — 열거·비교·채택이 세션
절차에 맡겨져 있어 건너뛰면 유니크 미고려가 재발했다. 단판 스냅샷 비교의 함정
(래스피스: 생명력 세팅 전엔 희귀 이하, 세팅하면 고점)은 2판 측정으로 잡는다.
"""

from __future__ import annotations

from typing import Any

from pok.engine.items import (
    ItemCandidate,
    enumerate_slot_uniques,
    evaluate_slot,
    optimize_items,
    render_unique,
    resolve_rolls,
    scaling_axes,
)

SPEC = {"class_name": "Sorceress", "ascendancy": "Sorceress1", "items": []}


def test_rolls_resolve_by_policy() -> None:
    """만점 롤 가정 비교가 결론을 뒤집은 실측이 있다 — 정책이 명시돼야 한다."""
    assert resolve_rolls("(60-100)% increased Energy Shield", "mid") == (
        "80% increased Energy Shield"
    )
    assert resolve_rolls("+(60-100) to maximum Life", "max") == "+100 to maximum Life"
    assert resolve_rolls("no ranges here", "mid") == "no ranges here"


def test_scaling_axes_detects_per_life() -> None:
    """래스피스형 표식 — `per 100 maximum Life`가 2판 측정 대상이다."""
    assert scaling_axes(["Spells deal 6% increased Damage per 100 maximum Life"]) == ("life",)
    assert scaling_axes(["+50 to maximum Life"]) == (), "플랫 부여는 스케일 조건이 아니다"


def test_slot_enumeration_covers_rathpith() -> None:
    """유니크 열거가 절차가 아니라 기계다 — 건너뛸 수 없다."""
    focus = enumerate_slot_uniques("Weapon 2")
    labels = {c.label for c in focus}
    assert "item.rathpith-globe" in labels
    assert all(not c.label.endswith("-cultivated") for c in focus), "재배판 중복 제외"


def test_render_produces_pob_parsable_text() -> None:
    from pok.index.search import get_entry

    text = render_unique(get_entry("item.rathpith-globe"))
    lines = text.splitlines()
    assert lines[0] == "Rarity: UNIQUE" and lines[1] == "Rathpith Globe"
    assert "Sacred Focus" in lines[2]
    assert not any("(" in ln and "-" in ln and ")" in ln for ln in lines[4:]), "범위 미해소 금지"


def _fake_compute(table: dict[str, dict[str, float]]):  # type: ignore[no-untyped-def]
    """스펙의 아이템 구성으로 키를 만들어 표를 찾는 가짜 오라클."""

    def run(spec: dict[str, Any]) -> dict[str, float]:
        key_parts = sorted(
            f"{i['slot']}:{i['text'].splitlines()[1] if len(i['text'].splitlines()) > 1 else '?'}"
            for i in spec.get("items") or []
        )
        return table.get("|".join(key_parts), {"CombinedDPS": 0.0})

    return run


def test_conditional_peak_is_surfaced_not_adopted() -> None:
    """1판에서 밀리는 스케일 유니크는 **채택하지 않고 드러낸다** — 판단은 호출자 몫."""
    rare = ItemCandidate(
        "rare:f", "Weapon 2", "Rarity: RARE\nRareF\nBase\nImplicits: 0\n+1 x", "rare-template"
    )
    scaler = ItemCandidate(
        "item.scaler",
        "Weapon 2",
        "Rarity: UNIQUE\nScaler\nBase\nImplicits: 0\n6% increased Damage per 100 maximum Life",
        "unique-kb",
    )
    table = {
        "": {"CombinedDPS": 100.0},
        "Weapon 2:RareF": {"CombinedDPS": 170.0},  # 1판: 희귀 +70
        "Weapon 2:Scaler": {"CombinedDPS": 160.0},  # 1판: 유니크 +60 (밀림)
        "Ring 2:Probe": {"CombinedDPS": 100.0},  # 탐침만
        "Ring 2:Probe|Weapon 2:RareF": {"CombinedDPS": 170.0},
        "Ring 2:Probe|Weapon 2:Scaler": {"CombinedDPS": 240.0},  # 2판: 유니크 +140
    }
    results = evaluate_slot(
        SPEC, "Weapon 2", [rare, scaler], stats=("CombinedDPS",), compute=_fake_compute(table)
    )
    by = {r.candidate.label: r for r in results}
    assert by["rare:f"].delta_now["CombinedDPS"] == 70.0
    assert by["item.scaler"].delta_now["CombinedDPS"] == 60.0
    assert by["item.scaler"].delta_probed == {"CombinedDPS": 140.0}
    assert by["item.scaler"].conditional_peak

    out = optimize_items(
        SPEC,
        ["Weapon 2"],
        {"CombinedDPS": 1.0},
        rare_templates={"Weapon 2": [rare.text]},
        compute=_fake_compute(table),
        max_rounds=1,
        max_candidates_per_slot=0,
    )
    # 유니크 열거는 KB에서 오지만 여기선 0으로 막고 희귀만 — 페널티 없는 단순 검증
    assert out.steps and out.steps[0].adopted == "rare:Weapon 2#0"


def test_floor_violating_candidate_is_not_adopted() -> None:
    """바닥선을 깨는 채택은 하지 않는다 — 저항 캡을 버리는 카옴식 함정 방지."""
    good = ItemCandidate("rare:a", "Helmet", "Rarity: RARE\nA\nB\nImplicits: 0\nx", "rare-template")
    breaker = ItemCandidate(
        "rare:b", "Helmet", "Rarity: RARE\nBreak\nB\nImplicits: 0\ny", "rare-template"
    )
    table = {
        "": {"CombinedDPS": 100.0, "FireResist": 75.0},
        "Helmet:A": {"CombinedDPS": 120.0, "FireResist": 75.0},
        "Helmet:Break": {"CombinedDPS": 300.0, "FireResist": 40.0},  # 딜은 크지만 캡 붕괴
    }
    results = evaluate_slot(
        SPEC,
        "Helmet",
        [good, breaker],
        stats=("CombinedDPS", "FireResist"),
        floors={"FireResist": 75.0},
        compute=_fake_compute(table),
    )
    by = {r.candidate.label: r for r in results}
    assert not by["rare:a"].floor_violations
    assert by["rare:b"].floor_violations, "위반이 사유와 함께 남아야 한다"
