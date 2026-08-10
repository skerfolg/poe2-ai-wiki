"""희귀 최적화 — "이 빌드의 최선 희귀" 생성 (사용자 승인 2026-08-06, 사고 4·5).

유니크와의 비교 상대인 희귀안이 세션 판단에 달려 있으면 채택 결론이 세션마다
흔들린다 — 접사 풀 열거·단독 실측·조립을 기계로 내리고 합법성 판정을 함께 낸다.
"""

from __future__ import annotations

from typing import Any

from pok.engine.rares import base_category, enumerate_base_affixes, optimize_rare

SPEC = {"class_name": "Sorceress", "ascendancy": "Sorceress1", "items": []}


def test_base_category_lookup() -> None:
    assert base_category("Sacred Focus") == "focus"
    assert base_category("존재하지 않는 베이스") is None


def test_affix_pool_is_deduped_by_group_at_top_tier() -> None:
    pool = enumerate_base_affixes("Sacred Focus")
    assert pool, "집중구 표준 접사 풀이 비면 안 된다"
    keys = [(a.origin, a.group) for a in pool]
    assert len(keys) == len(set(keys)), "출처·그룹별 최고 티어 1건만 — 티어 중복 금지"
    assert all(a.affix_type in ("prefix", "suffix", "corrupted") for a in pool)
    assert all("(" not in a.text for a in pool), "범위는 롤 정책으로 해소돼 있어야 한다"


def test_spawn_matching_uses_kb_base_spawn_tags() -> None:
    """스폰 판정은 베이스 정본 `spawn_tags` 기준 — 손 매핑 근사가 놓친 구멍의 회귀.

    사용자 지적 2026-08-06: category→태그 손 매핑이 집중구의 `int_armour` 태그를
    몰라 로컬 ES 접사·속성 접사(+지능)가 풀에서 통째로 빠졌다(14건 → 22건).
    """
    texts = " | ".join(a.text for a in enumerate_base_affixes("Sacred Focus"))
    assert "to Intelligence" in texts, "속성 부여 접사 — int_armour 태그로 집중구에 스폰"
    assert "to maximum Energy Shield" in texts, "로컬 ES 접사 — int_armour 태그"
    assert "to Cold Resistance" in texts, "저항 접미 — 방어구 공통 풀"
    plate = " | ".join(a.text for a in enumerate_base_affixes("Glorious Plate"))
    assert "to Intelligence" not in plate, "str_armour 판금엔 지능 접사가 스폰되지 않는다"


def test_optimize_rare_respects_affix_caps_and_scores() -> None:
    """단독 델타 상위 접두 3·접미 3만 조립 — 음수 점수 접사는 넣지 않는다."""

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        text = "\n".join(str(i.get("text", "")) for i in spec.get("items") or [])
        dps = 100.0
        if "increased Spell Damage" in text:
            dps += 50.0
        if "increased Cast Speed" in text:
            dps += 30.0
        if "Mana Regeneration" in text:
            dps -= 5.0  # 음수 점수 — 조립에서 빠져야 한다
        return {"CombinedDPS": dps}

    out = optimize_rare(
        SPEC,
        "Weapon 2",
        "Sacred Focus",
        {"CombinedDPS": 1.0},
        compute=compute,
        render_with_pob=False,
    )
    chosen_texts = "\n".join(r.option.text for r in out.chosen)
    assert "increased Spell Damage" in chosen_texts
    assert "Mana Regeneration" not in chosen_texts
    assert sum(r.option.affix_type == "prefix" for r in out.chosen) <= 3
    assert sum(r.option.affix_type == "suffix" for r in out.chosen) <= 3
    # 출력은 **명세**다 — 문구를 우리가 쓰지 않는다(#34 A). 값·티어·롤은 PoB가 만든다.
    assert "Crafted: true" in out.spec_text, out.spec_text
    assert "Prefix: {range:" in out.spec_text, out.spec_text
    # ⚠ `Item Level:`은 더 이상 쓰지 않는다 — PoB 정본(`BuildRaw`)에 그 줄이 없고
    # 검사기는 `LevelReq:`에서 역산한다(실측 2026-08-09). 옛 단서를 남겨 두면 다음
    # 세션이 "왜 없지"로 되돌아온다.
    assert "Item Level:" not in out.spec_text
    assert len(out.table) == len(enumerate_base_affixes("Sacred Focus")), (
        "단독 실측 전량 — 절단 없음"
    )


def test_all_grant_sources_are_enumerated_with_origin() -> None:
    """모든 속성 부여 경로 열거 (사용자 요구 2026-08-06) — 출처가 함께 남는다.

    desecrated·essence는 applicable_pages, corrupted·item은 spawn_weights로 매칭이
    다르다. essence 축은 2026-08-06 ingest 갭 해소(에센스 부여 매핑 수록)로 열렸다
    — 합금 모드의 origins(PoB 계보)는 item이라 계보가 아니라 granted_by가 판별한다.
    """
    pool = enumerate_base_affixes("Sacred Focus")
    origins = {a.origin for a in pool}
    assert origins == {"item", "desecrated", "corrupted", "essence"}
    assert all(a.affix_type == "corrupted" or a.origin != "corrupted" for a in pool), (
        "훼손 모드는 접사 칸 밖(corrupted 칸)으로 분류돼야 한다"
    )
    labels = [a.label for a in pool]
    assert len(labels) == len(set(labels)), "같은 모드가 두 출처로 이중 계상되면 안 된다"
    item_only = enumerate_base_affixes("Sacred Focus", origins=("item",))
    assert {a.origin for a in item_only} == {"item"}
    assert len(item_only) < len(pool), "출처 확장이 실제로 풀을 넓혀야 한다"


def test_essence_origin_enumerates_alloy_mods_including_staves() -> None:
    """에센스 전용 부여(합금) 열거 — Staves 불규칙 복수 조인의 회귀.

    페이지 슬러그 자동 유도("Staff"+"s"="Staffs")는 poe2db `Staves`와 어긋나
    지팡이 대상 에센스·훼손 접사가 통째로 빠진다 — 정본 kb.item_classes 조인 확인.
    """
    focus = enumerate_base_affixes("Sacred Focus", origins=("essence",))
    assert focus, "집중구에 에센스 전용 부여가 있어야 한다 (실측 0.5.4b: 7건)"
    assert {a.origin for a in focus} == {"essence"}
    texts = " | ".join(a.text for a in focus)
    assert "Exposure Effect" in texts, "Prismatic Alloy가 Foci에 부여 (개별 페이지 실측)"
    staff = enumerate_base_affixes("Gelid Staff", origins=("essence",))
    staff_texts = " | ".join(a.text for a in staff)
    assert "Elemental Infusions" in staff_texts, "Mystic Alloy가 Staves에 부여"


def test_corrupted_mod_capped_at_one_and_outside_legality() -> None:
    """훼손 모드는 1건 캡 + 조립 텍스트에 Corrupted 표기, 합법성 검사는 접사만."""

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        text = "\n".join(str(i.get("text", "")) for i in spec.get("items") or [])
        dps = 100.0
        if "increased Spell Damage" in text:
            dps += 50.0
        if "Attribute Requirements" in text:
            dps += 1.0  # 훼손 후보들에 양수 점수를 줘도 1건만 들어가야 한다
        if "increased Energy Shield" in text:
            dps += 2.0
        return {"CombinedDPS": dps}

    out = optimize_rare(
        SPEC,
        "Weapon 2",
        "Sacred Focus",
        {"CombinedDPS": 1.0},
        compute=compute,
        render_with_pob=False,
    )
    corrupted = [r for r in out.chosen if r.option.affix_type == "corrupted"]
    assert len(corrupted) == 1, "바알 오브는 1회 — 훼손 모드 캡 1"
    assert out.text.splitlines()[-1] == "Corrupted"
    assert any("도박" in n for n in out.notes), "훼손 조달의 도박성이 명시돼야 한다"


def test_jewel_pool_and_caps_come_from_canon() -> None:
    """주얼 회귀 (빌드 회차 2026-08-06 갭2): 접사 풀이 훼손 11건뿐이었다.

    origins 기본값에 'jewel'(377건)이 빠져 있었다. 한도도 장비 3/3 하드코딩이라
    정본 판 규칙(주얼 rare 2/2)과 어긋났다.
    """
    pool = enumerate_base_affixes("Diamond")
    origins = {a.origin for a in pool}
    assert "jewel" in origins, "주얼 전용 크래프팅 풀이 열거돼야 한다"
    assert len(pool) > 100, f"훼손 모드뿐이면 안 된다 (실측 갭: 11건) — 지금 {len(pool)}건"
    from pok.engine.rares import _affix_caps

    # ⚠ 이 시험은 한때 (2, 2)를 강제했고 **그게 결함이었다**(#34 E): 정본의
    # `season_override`(0.5 주얼 총 5모드)를 생성기가 안 읽어 4줄까지만 냈다.
    # 검사기는 이미 알고 있었으니 둘이 어긋나 있었던 것이다(§0 ④).
    assert _affix_caps("Diamond", None)[:3] == (3, 3, 5), "주얼 = 각 3, **총 5**"
    assert _affix_caps("Sacred Focus", None)[:3] == (3, 3, 6), "장비는 3/3·총 6"


def test_jewel_slot_without_socket_is_reported_invalid() -> None:
    """소켓 없는 주얼 측정은 델타 0이 된다 — '효과 없음'이 아니라 '측정 무효'로 낸다."""
    out = optimize_rare(
        SPEC,
        "Jewel",
        "Diamond",
        {"CombinedDPS": 1.0},
        compute=lambda spec: {"CombinedDPS": 100.0},
        render_with_pob=False,
    )
    assert any("소켓" in n for n in out.notes), "소켓 미지정을 말해야 한다"
    assert any("측정" in n and "무효" in n for n in out.notes), "전 델타 0은 측정 실패 신호"


def test_unallocated_socket_is_reported() -> None:
    """할당되지 않은 소켓도 PoB가 무시한다 — 트리 할당 여부를 대조해 경고."""
    spec = {**SPEC, "tree_nodes": (111, 222)}
    out = optimize_rare(
        spec,
        "Jewel@999",
        "Diamond",
        {"CombinedDPS": 1.0},
        compute=lambda s: {"CombinedDPS": 100.0},
        render_with_pob=False,
    )
    assert any("tree_nodes에 없다" in n for n in out.notes)


def test_base_implicit_is_written_into_template() -> None:
    """PoB는 베이스 암시적을 자동 적용하지 않는다 (갭3) — 텍스트에 기재해야 반영."""
    out = optimize_rare(
        SPEC,
        "Ring 1",
        "Gold Ring",
        {"CombinedDPS": 1.0},
        compute=lambda spec: {"CombinedDPS": 100.0},
        render_with_pob=False,
    )
    assert "Rarity of Items found" in out.spec_text, "정본 implicit이 명세에 들어가야 한다"
    assert "Implicits: 1" in out.spec_text
    # ⚠ 롤은 **우리가 풀지 않는다**(#34) — `{range:R}`를 붙여 PoB가 풀게 한다.
    # 우리가 풀면 `+12.5 to Dexterity` 같은 인게임에 없는 값이 나온다(실측 2026-08-09).
    # 사용자 정본도 `{tags:attribute}{range:1}+(10-15) to Intelligence` 꼴이다.
    implicit = next(ln for ln in out.spec_text.splitlines() if "Rarity of Items" in ln)
    assert implicit.startswith("{range:"), implicit
    assert "(" in implicit, "범위를 그대로 둔다 — 해소는 PoB 몫"


def test_unmeasurable_affixes_are_reported_not_silently_dropped() -> None:
    """PoB가 못 읽는 접사는 델타 0이라 **그리디가 절대 안 고른다** (백로그 #22).

    그러면 조립 결과는 그 축을 뺀 **바닥값**인데, 말하지 않으면 "이 베이스의 고점"으로
    읽힌다. 실측 2026-08-09: `Amber Amulet` 접사 풀 82건 중 **32건(39%)**이 여기 해당한다 —
    사용자가 "이번 0.5 시즌 대표 크래프팅"이라 짚은 퀄리티 축이 그중 하나다.

    표기는 이미 KB에 있었다(`pob_modeling.supported: false`, PR #48이 붙임) —
    **`optimize_rare`가 그걸 안 읽은 것**이 이 결함의 알맹이다.
    """

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        return {"CombinedDPS": 100.0}

    pool = enumerate_base_affixes("Amber Amulet")
    flagged = [o for o in pool if o.pob_unmeasurable]
    assert flagged, "KB 표기를 풀이 읽어야 한다 — 안 읽으면 이 결함이 그대로다"

    out = optimize_rare(
        SPEC, "Amulet", "Amber Amulet", {"CombinedDPS": 1.0}, compute=compute, render_with_pob=False
    )
    assert {o.label for o in out.unmeasurable} == {o.label for o in flagged}
    assert any("PoB가 문구를 못 읽는다" in n for n in out.notes), (
        "조용히 빠지면 안 된다 — 바닥값을 고점으로 읽게 된다"
    )


def test_measurable_pool_reports_nothing() -> None:
    """표기가 없는 풀에서는 경고를 만들지 않는다 — 없는 근거를 지어내지 않는다."""

    from pok.engine.rares import AffixOption

    plain = AffixOption(
        label="mod.x", affix_type="prefix", text="+10 to maximum Life", group="g", ilvl=1
    )
    assert plain.pob_unmeasurable is False


def test_assembly_is_legal_by_construction() -> None:
    """조립 결과가 **그대로 쓸 수 있어야** 한다 (백로그 #23).

    사후 검사만 하면 `legal: false`가 나와도 반환 `text`를 못 쓰고 매번 손으로
    재조립해야 한다 — 실측 2026-08-09(투구 `Spiritbone Crown`): 접두 초과·group 중복.

    ⚠ 개수를 맞추는 방식으로는 못 고친다: 그리디는 **후보 단위**로 세는데 검사기는
    **매칭된 모드 id 단위**로 센다. 하이브리드 한 후보가 두 줄이면 검사기가 서로 다른
    모드 둘로 매칭할 수 있어 3개를 골랐는데 5개로 세졌다(실측). 그래서 조립하면서
    **검사기에게 직접 묻는다** — 판정 주체를 하나로 만든다.
    """

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        # 줄이 많을수록 좋다고 말해 한도를 시험한다
        text = "\n".join(str(i.get("text", "")) for i in spec.get("items") or [])
        return {"CombinedDPS": 100.0 + len(text.splitlines())}

    for slot, base in (("Helmet", "Spiritbone Crown"), ("Amulet", "Amber Amulet")):
        out = optimize_rare(
            SPEC, slot, base, {"CombinedDPS": 1.0}, compute=compute, render_with_pob=False
        )
        assert out.legal, f"{base}: {out.legality_errors}"
        assert out.chosen, f"{base}: 합법성을 지키느라 아무것도 못 고르면 그것도 결함이다"


def test_trial_and_final_use_the_same_yardstick() -> None:
    """시험 검사와 최종 판정이 다른 기준이면 "통과시켜 놓고 실격"이 난다.

    훼손 모드는 접사 칸 밖(바알 오브 1회)이라 최종 판정에서 빠지는데, 시험에만
    넣으면 멀쩡한 접사가 훼손 때문에 걸러진다.
    """
    import inspect

    from pok.engine.rares import optimize_rare as fn

    source = inspect.getsource(fn)
    assert source.count("include_corrupted=False") == 2, "시험·최종이 같은 기준이어야 한다"


def test_jewel_cap_follows_the_season_override() -> None:
    """0.5 주얼은 **총 5모드**다 — 생성기가 2/2로 자르고 있었다 (#34 E).

    검사기(`legality._affix_limits`)는 이미 알고 있었으므로 **둘이 어긋나 있었다**
    (§0 ④ 판정 주체가 둘이면 어긋난다). 실사용 주얼(`Maelstrom Shine`)이 5줄인데
    도구는 4줄까지만 냈다.
    """
    from pok.engine.rares import _affix_caps

    pre, suf, total, label = _affix_caps("Emerald", None)
    assert (pre, suf, total) == (3, 3, 5), (pre, suf, total)
    assert "season_override" in label
    # 장비는 그대로 3/3·총 6 — 시즌 규칙을 남에게 흘리지 않는다
    assert _affix_caps("Lapis Amulet", None)[:3] == (3, 3, 6)


def test_greedy_stops_at_the_total_not_at_each_cap() -> None:
    """각 한도는 3인데 **총합은 5**다 — 3/3(총 6)은 인게임에서 못 만든다."""

    def compute(spec: dict[str, Any]) -> dict[str, float]:
        text = "\n".join(str(i.get("text", "")) for i in spec.get("items") or [])
        return {"CombinedDPS": 100.0 + len(text.splitlines())}

    out = optimize_rare(
        SPEC,
        "Weapon 2",
        "Sacred Focus",
        {"CombinedDPS": 1.0},
        compute=compute,
        render_with_pob=False,
    )
    affixes = [r for r in out.chosen if r.option.affix_type != "corrupted"]
    assert len(affixes) <= 6, "장비 총한도"


def test_radius_jewel_declares_or_says_it_will_read_zero() -> None:
    """반경 선언이 없으면 **조용히 0**이다 — 엔진이 고르지 않되 **말은 한다**(제안 B).

    실측: 선언 없이는 반경 내 노터블 6개에도 Δ0, `Radius: Very Large`면 10.44 → 15.84.
    """
    import pytest

    quiet = optimize_rare(
        SPEC, "Jewel", "Time-Lost Sapphire", {"CombinedDPS": 1.0},
        compute=lambda s: {"CombinedDPS": 100.0}, render_with_pob=False,
    )  # fmt: skip
    assert any("반경 주얼인데" in n for n in quiet.notes), quiet.notes
    assert not any(ln.startswith("Radius:") for ln in quiet.spec_text.splitlines())

    declared = optimize_rare(
        SPEC, "Jewel", "Time-Lost Sapphire", {"CombinedDPS": 1.0},
        compute=lambda s: {"CombinedDPS": 100.0}, render_with_pob=False, radius="Very Large",
    )  # fmt: skip
    assert "Radius: Very Large" in declared.spec_text
    assert not any("반경 주얼인데" in n for n in declared.notes)

    # 모르는 라벨은 **거부** — 지어내면 반경이 조용히 틀린다
    with pytest.raises(ValueError, match="반경 라벨"):
        optimize_rare(
            SPEC, "Jewel", "Time-Lost Sapphire", {"CombinedDPS": 1.0},
            compute=lambda s: {"CombinedDPS": 100.0}, render_with_pob=False, radius="아주 큼",
        )  # fmt: skip
