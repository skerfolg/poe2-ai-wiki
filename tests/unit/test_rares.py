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
    groups = [a.group for a in pool]
    assert len(groups) == len(set(groups)), "그룹별 최고 티어 1건만 — 티어 중복 금지"
    assert all(a.affix_type in ("prefix", "suffix") for a in pool)
    assert all("(" not in a.text for a in pool), "범위는 롤 정책으로 해소돼 있어야 한다"


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
