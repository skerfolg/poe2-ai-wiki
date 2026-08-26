"""아이템 최적화 루프 (사용자 지시 2026-08-06).

트리에는 optimize_tree가 있는데 아이템에는 루프가 없었다 — 열거·비교·채택이 세션
절차에 맡겨져 있어 건너뛰면 유니크 미고려가 재발했다. 단판 스냅샷 비교의 함정
(래스피스: 생명력 세팅 전엔 희귀 이하, 세팅하면 고점)은 2판 측정으로 잡는다.
"""

from __future__ import annotations

from typing import Any

import pytest

from pok.engine.items import (
    ItemCandidate,
    enumerate_slot_uniques,
    evaluate_slot,
    optimize_items,
    render_unique,
    resolve_rolls,
    scaling_axes,
)


def _pob_snapshot_ready() -> bool:
    """CI엔 `external/pob` 스냅샷이 없다 — PoB 소스를 읽는 시험은 건너뛴다."""
    from pok.pob.versions import resolve_snapshot

    try:
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


needs_pob_snapshot = pytest.mark.skipif(
    not _pob_snapshot_ready(), reason="external/pob 스냅샷 없음 (유니크 원문 = PoB 소스)"
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


@needs_pob_snapshot
def test_render_uses_pob_source_not_our_assembly() -> None:
    """유니크 원문은 **PoB가 갖고 있다** — 우리가 조립하지 않는다 (#34 B).

    ⚠ 옛 판은 롤 범위를 **우리가 해소**했고 이 시험이 그걸 강제했다. #34로 방향이
    뒤집혔다: 범위는 `{range:R}`로 두고 **PoB가 푼다**. 우리가 풀면 인게임에 없는
    값이 나온다(실측 2026-08-09: `+12.5 to Dexterity`).
    """
    from pok.index.search import get_entry

    text = render_unique(get_entry("item.rathpith-globe"))
    lines = text.splitlines()
    assert lines[0] == "Rarity: UNIQUE" and lines[1] == "Rathpith Globe"
    assert "Sacred Focus" in lines[2]
    # PoB 원문의 표식 — 우리가 만든 텍스트에는 없던 것들이다
    assert any("{range:" in ln or "(" in ln for ln in lines), "범위는 PoB가 푼다"


def test_render_falls_back_to_kb_without_the_pob_snapshot() -> None:
    """스냅샷이 없어도 **아이템은 나와야 한다** — 없으면 CI에서 조립이 통째로 막힌다.

    ⚠ 이 폴백이 없는 줄 알고 시험을 스냅샷 전제로 썼다가 **CI 두 판이 다 깨졌다**
    (실측 2026-08-10). 스냅샷 의존은 `needs_pob_snapshot`으로 표시하고, 폴백은
    폴백대로 시험한다 — 둘 다 실제 경로다.
    """
    import pok.pob.uniques as uniques_mod
    from pok.index.search import get_entry

    original = uniques_mod.unique_raw
    uniques_mod.unique_raw = lambda name, root=None: None  # type: ignore[assignment]
    try:
        text = render_unique(get_entry("item.rathpith-globe"))
    finally:
        uniques_mod.unique_raw = original  # type: ignore[assignment]

    lines = text.splitlines()
    assert lines[0] == "Rarity: UNIQUE" and lines[1] == "Rathpith Globe"
    assert "Sacred Focus" in lines[2]
    assert any(ln.startswith("Implicits:") for ln in lines), "KB 조립 경로의 선언"


@needs_pob_snapshot
def test_variant_uniques_carry_their_variant_lines() -> None:
    """변형 유니크는 `Variant:` 목록째로 온다 — 모드와 변형의 연결이 거기 있다.

    KB `variants`는 **이름 목록뿐**이라 어느 모드가 어느 변형인지 모른다. 그래서
    손으로 조립하면 PoB가 오류를 냈다(모리오르 사고, #34 B).
    """
    from pok.pob.uniques import UnknownVariantError, variants
    from pok.pob.uniques import render_unique as render_variant

    names = variants("Morior Invictus")
    assert len(names) > 20, names
    text = render_variant("Morior Invictus", "Spirit")
    assert text is not None
    assert f"Selected Variant: {names.index('Spirit') + 1}" in text
    assert sum(1 for ln in text.splitlines() if ln.startswith("Selected Variant:")) == 1

    # 없는 변형은 **예외** — 조용히 무시하면 "골랐는데 안 반영됨"이 된다(§0 ①)
    with pytest.raises(UnknownVariantError):
        render_variant("Morior Invictus", "그런 변형 없음")


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


def test_full_enumeration_is_default_and_truncation_is_reported() -> None:
    """조용한 절단 = 조용한 카옴 누락 — 기본은 전수, 자르면 반드시 알린다."""
    full = enumerate_slot_uniques("Weapon 1")
    assert len(full) > 40, "limit 기본값이 전수가 아니면 후보가 말없이 빠진다"
    out = optimize_items(
        SPEC,
        ["Weapon 1"],
        {"CombinedDPS": 1.0},
        compute=lambda spec: {"CombinedDPS": 0.0},
        max_rounds=1,
        max_candidates_per_slot=5,
    )
    assert any("절단" in n for n in out.notes)


def test_charm_flask_jewel_slots_enumerate() -> None:
    """플라스크·호신부·주얼 — 매핑 밖이라 후보 0건이던 493-434 구멍의 해소."""
    assert len(enumerate_slot_uniques("Charm 1")) > 0
    assert len(enumerate_slot_uniques("Flask 1")) > 0
    jewels = enumerate_slot_uniques("Jewel")
    assert len(jewels) > 0
    charm_bases = {c.text.splitlines()[2] for c in enumerate_slot_uniques("Charm 1")}
    assert all("Charm" in b for b in charm_bases), "호신부 슬롯에 플라스크가 섞이면 안 된다"


def test_jewel_without_sockets_is_reported_unmeasured() -> None:
    """소켓을 안 주면 주얼은 '없다'가 아니라 '안 쟀다'로 보고된다."""
    out = optimize_items(
        SPEC,
        ["Jewel"],
        {"CombinedDPS": 1.0},
        compute=lambda spec: {"CombinedDPS": 0.0},
        max_rounds=1,
    )
    assert any("미측정" in n for n in out.notes)


def test_req_shortfall_blocks_candidate_but_not_for_base_faults() -> None:
    """착용 불가(요구 미달)는 채택 금지 — 단 기반 스펙의 미달을 후보 탓하지 않는다."""
    heavy = ItemCandidate(
        "rare:plate",
        "Body Armour",
        "Rarity: RARE\nPlate\nBase\nImplicits: 0\nx",
        "rare-template",
    )

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        worn = any("Plate" in str(i.get("text", "")) for i in spec.get("items") or [])
        stats = {"CombinedDPS": 150.0 if worn else 100.0, "Str": 7.0, "ReqInt": 140.0, "Int": 60.0}
        if worn:
            stats["ReqStr"] = 121.0  # 후보가 새로 유발한 미달 → 차단
        for item in spec.get("items") or []:
            if "Strength" in str(item.get("text", "")):
                stats["Str"] = 200.0  # 속성 탐침 반영
        return stats

    r = evaluate_slot(SPEC, "Body Armour", [heavy], stats=("CombinedDPS",), compute=compute)[0]
    assert r.req_shortfall == {"str": 114.0}, "ReqStr 121 vs Str 7 — 착용 불가 검출"
    assert "int" not in r.req_shortfall, "기반 스펙의 Int 미달(젬 요구)은 후보 탓이 아니다"
    assert r.blocked and r.delta_probed is not None, "속성 탐침 2판으로 '지불 시 이득'을 낸다"

    out = optimize_items(
        SPEC,
        ["Body Armour"],
        {"CombinedDPS": 1.0},
        rare_templates={"Body Armour": [heavy.text]},
        compute=compute,
        max_rounds=1,
        max_candidates_per_slot=0,
    )
    assert not out.steps, "1판 +50이어도 착용 불가면 채택하지 않는다"
    assert any("기반 스펙 자체가 요구 속성 미달" in n for n in out.notes)


def test_demand_supply_chain_is_measured_and_beats_single(monkeypatch: Any) -> None:
    """축 수요-공급 연쇄 실측 — 탐침(가정)이 아닌 실제 문맥이 단독 최선을 이기면 채택.

    쌍(2개)에서 멈추지 않는다(사용자 지시: 쌍만으로는 고차원 빌드 불가) — 개선이
    계속되면 3개째(고유+희귀+희귀)까지 이어 붙는 것을 잠근다.
    """
    import pok.engine.items as items_mod

    scaler = "Rarity: UNIQUE\nScaler\nBase\nImplicits: 0\n6% increased Damage per 100 maximum Life"
    ring = "Rarity: RARE\nLifeRing\nGold Ring\nImplicits: 0\n+80 to maximum Life"
    belt = "Rarity: RARE\nLifeBelt\nHeavy Belt\nImplicits: 0\n+100 to maximum Life"

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        names = sorted(str(i.get("text", "")).splitlines()[1] for i in spec.get("items") or [])
        table = {
            "": 100.0,
            "Scaler": 160.0,
            "LifeRing": 100.0,
            "LifeBelt": 100.0,
            "LifeRing|Scaler": 250.0,  # 2연쇄 +150 — 단독 합(+60)을 넘는 시너지
            "LifeBelt|Scaler": 240.0,
            "LifeBelt|LifeRing|Scaler": 400.0,  # 3연쇄 +300 — 쌍에서 멈추면 못 여는 고점
            "Probe": 100.0,
            "Probe|Scaler": 240.0,
            "LifeRing|Probe": 100.0,
            "LifeBelt|Probe": 100.0,
        }
        return {"CombinedDPS": table.get("|".join(names), 100.0)}

    def stub(slot: str, root: Any = None, *, limit: Any = None) -> list[ItemCandidate]:
        if slot == "Weapon 2":
            return [ItemCandidate("item.scaler", slot, scaler, "unique-kb")]
        return []

    monkeypatch.setattr(items_mod, "enumerate_slot_uniques", stub)
    out = items_mod.optimize_items(
        SPEC,
        ["Weapon 2", "Ring 1", "Belt"],
        {"CombinedDPS": 1.0},
        rare_templates={"Ring 1": [ring], "Belt": [belt]},
        compute=compute,
        max_rounds=1,
    )
    assert {(s.slot, s.adopted) for s in out.steps} == {
        ("Weapon 2", "item.scaler"),
        ("Ring 1", "rare:Ring 1#0"),
        ("Belt", "rare:Belt#0"),
    }, "3연쇄 전 구성원 채택 — 고유+희귀+희귀"
    lengths = {len(c.members) for c in out.chains}
    assert 2 in lengths and 3 in lengths, "2연쇄를 거쳐 3연쇄까지 확장 실측"
    trio = next(c for c in out.chains if len(c.members) == 3)
    # 방어 축이 항상 측정에 포함되므로(#18) 델타 dict에 0짜리 축들이 함께 온다 —
    # 문제의 축만 본다.
    assert trio.delta_chain["CombinedDPS"] == 300.0
    assert trio.synergy["CombinedDPS"] == 240.0, "연쇄 - 단독합 — 곱연산 맞물림이 수치로 남는다"
    assert trio.axis_path == ("life", "life")


def test_defensive_only_candidate_is_surfaced_not_adopted() -> None:
    """딜 가중만 주면 순수 방어 유니크는 **점수가 정확히 0**이라 절대 채택되지 않는다.

    "딜 가중을 준 사람 책임"으로 보이지만 딜 가중이 **기본 사용 패턴**이고, 그 패턴에서
    한 부류가 통째로 안 보이는 것이 결함이다(백로그 #18 — 사용자 지적: 여러 세션이
    고점 세팅에서 마법사의 피를 **항상** 무시했다). 실측 2026-08-09(허리띠 20종·딜
    가중): 채택 가능 후보 **0건**인데 그중 12종이 EHP를 올렸다.

    채택은 여전히 가중치가 정한다(AD-3) — **보이게만** 한다.
    """
    tanky = ItemCandidate(
        "unique:tank", "Belt", "Rarity: UNIQUE\nTank\nB\nImplicits: 0\n+100 to maximum Life", "u"
    )
    useless = ItemCandidate(
        "unique:meh", "Belt", "Rarity: UNIQUE\nMeh\nB\nImplicits: 0\nnothing", "u"
    )
    table = {
        "": {"CombinedDPS": 100.0, "TotalEHP": 1000.0, "Life": 500.0},
        "Belt:Tank": {"CombinedDPS": 100.0, "TotalEHP": 1600.0, "Life": 600.0},  # 딜 0 · 방어 +600
        "Belt:Meh": {"CombinedDPS": 100.0, "TotalEHP": 1000.0, "Life": 500.0},  # 아무것도 안 바뀜
    }
    out = optimize_items(
        SPEC,
        ["Belt"],
        {"CombinedDPS": 1.0},
        rare_templates={"Belt": [tanky.text, useless.text]},
        compute=_fake_compute(table),
        max_rounds=1,
        max_candidates_per_slot=0,
    )
    assert not out.steps, "딜이 안 오르므로 채택은 여전히 없어야 한다"
    labels = {d.candidate.label for d in out.defensive_only}
    assert labels == {"rare:Belt#0"}, f"방어 개선분만 실려야 한다: {labels}"
    assert out.defensive_only[0].delta_now["TotalEHP"] == 600.0
    assert any("방어 축이 없다" in n for n in out.notes), "가중치에 방어 축이 없다는 경고"


def test_defensive_axes_are_measured_even_when_not_weighted() -> None:
    """방어 축을 안 재면 "딜 0 · 방어 양수"를 **판정할 근거 자체가 없다**.

    PoB 1회 실행이 전 스탯을 주므로 축을 더 담는 비용은 0이다.
    """
    cand = ItemCandidate("unique:x", "Belt", "Rarity: UNIQUE\nX\nB\nImplicits: 0\n+1 x", "u")
    table = {
        "": {"CombinedDPS": 100.0, "TotalEHP": 1000.0},
        "Belt:X": {"CombinedDPS": 100.0, "TotalEHP": 1200.0},
    }
    out = optimize_items(
        SPEC,
        ["Belt"],
        {"CombinedDPS": 1.0},  # 방어 축을 **주지 않았는데도**
        rare_templates={"Belt": [cand.text]},
        compute=_fake_compute(table),
        max_rounds=1,
        max_candidates_per_slot=0,
    )
    assert out.defensive_only, "가중치에 없어도 방어 축이 측정돼 있어야 한다"
    assert "TotalEHP" in out.defensive_only[0].delta_now


def test_유니크_후보가_파싱_갭을_싣는다() -> None:
    """PoB가 문구를 못 읽는 유니크를 후보가 **스스로 신고한다** (#123).

    `optimize_rare`는 접사 풀에 대해 이걸 이미 낸다(`rares.py:530` — 건수·전량 목록·
    「이 조립은 바닥값이지 고점이 아니다」). **유니크 경로만 안 하고 있었다** —
    `items.py`의 `pob_modeling` 참조가 0건이었다.

    ⛔ 규모가 코너 케이스가 아니다. 실측 2026-08-25: 열거 대상 유니크 **468종 중 214종
    (45.7%)**이 파싱 갭을 갖는다. 그 델타 0이 실측인지 미측정인지 호출자가 알 방법이
    없으면, 「아무도 안 쓴다」의 원인이 **약해서가 아니라 계산기가 못 읽어서**인 경우가
    조용히 섞인다 — 그 목록은 배제 목록이 아니라 **미탐색 목록**이다.
    """
    pool = enumerate_slot_uniques("Body Armour")
    assert pool, "갑옷 유니크 후보가 있어야 한다"
    gapped = [c for c in pool if c.pob_unmeasurable]
    assert gapped, "갑옷 풀에 파싱 갭 유니크가 실재한다(실측 43%)"
    assert all(c.unparsed for c in gapped), "갭이면 못 읽은 줄을 함께 실어야 한다"


def test_읽히는_유니크는_갭으로_찍히지_않는다() -> None:
    """⛔ 반대 방향 — 전부 갭으로 찍으면 신고가 잡음이 되어 아무도 안 읽는다.

    `pob_computable is False`(계산 자체가 안 되는 것)는 열거에서 이미 빠지므로,
    남은 후보 중 상당수는 **정상적으로 읽힌다**.
    """
    pool = enumerate_slot_uniques("Body Armour")
    clean = [c for c in pool if not c.pob_unmeasurable]
    assert clean, "읽히는 후보도 있어야 한다 — 전부 갭이면 판정이 틀린 것이다"
    assert all(c.unparsed == () for c in clean), "갭이 아니면 못 읽은 줄도 없어야 한다"


def test_호출자_라벨_후보는_갭_표식이_기본값이다() -> None:
    """`rare-template` 등 KB 밖에서 온 후보는 판정 근거가 없다 — **모른다를 0으로 읽지 않게**
    기본값이 「갭 아님」이고 못 읽은 줄도 비어 있다.
    """
    c = ItemCandidate(label="x", slot="Amulet", text="", source="rare-template")
    assert c.pob_unmeasurable is False and c.unparsed == ()
