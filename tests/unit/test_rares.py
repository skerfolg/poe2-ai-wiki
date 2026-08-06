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

    out = optimize_rare(SPEC, "Weapon 2", "Sacred Focus", {"CombinedDPS": 1.0}, compute=compute)
    chosen_texts = "\n".join(r.option.text for r in out.chosen)
    assert "increased Spell Damage" in chosen_texts
    assert "Mana Regeneration" not in chosen_texts
    assert sum(r.option.affix_type == "prefix" for r in out.chosen) <= 3
    assert sum(r.option.affix_type == "suffix" for r in out.chosen) <= 3
    assert "Item Level:" in out.text, "ilvl 없으면 legality가 기본 1로 파싱해 전부 스폰 불가가 된다"
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

    out = optimize_rare(SPEC, "Weapon 2", "Sacred Focus", {"CombinedDPS": 1.0}, compute=compute)
    corrupted = [r for r in out.chosen if r.option.affix_type == "corrupted"]
    assert len(corrupted) == 1, "바알 오브는 1회 — 훼손 모드 캡 1"
    assert out.text.splitlines()[-1] == "Corrupted"
    assert any("도박" in n for n in out.notes), "훼손 조달의 도박성이 명시돼야 한다"
