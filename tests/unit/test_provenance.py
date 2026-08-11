"""산출 출처와 낡음 판정 — 백로그 #58 ③ (2026-08-11).

선행 문서가 「트리 3·4·5차 전부 무효」라고 적어 뒀는데(`conditionLowLife` 없이
산출했으므로) **그 트리가 그대로 계승돼** 다음 세션이 25포인트를 더 얹었다.
「무효」를 읽고도 계승한 이유는 **무엇이 달라서 무효인지 몰랐기 때문**이다 —
그래서 이 파일이 지키는 것은 "감지한다"가 아니라 **"문장으로 말한다"**이다.
"""

from __future__ import annotations

from typing import Any

from pok.engine.provenance import stale_components, stamp

BALL = "Metadata/Items/Gems/SkillGemBallLightning"


def _spec(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 90,
        "config": {"conditionLowLife": False},
        "skills": [{"gems": [{"gem_id": BALL, "name": "Ball Lightning", "stat_set_index": 1}]}],
        "items": [{"slot": "Weapon 1", "text": "Rarity: NORMAL\nA\nAttuned Wand\n"}],
        "tree_nodes": [4739, 22419],
    }
    return {**base, **over}


def _stamped(component: str = "tree", tool: str = "optimize_tree") -> dict[str, Any]:
    spec = _spec()
    spec["derived_from"] = {component: stamp(spec, component, tool=tool)}
    return spec


def test_a_fresh_stamp_is_silent() -> None:
    """산출 직후에는 아무것도 낡지 않았다 — 매번 빨개지면 아무도 안 읽는다(§0 ⑤)."""
    assert stale_components(_stamped()) == []


def test_config_change_is_reported_as_a_sentence() -> None:
    """실제 사고 그대로: `conditionLowLife` off→on이 트리를 무효로 만들었다."""
    spec = _stamped()
    spec["config"] = {"conditionLowLife": True}
    (found,) = stale_components(spec)
    assert found["component"] == "tree"
    assert found["why"] == "config.conditionLowLife: False → True", found
    assert found["advice"] == "optimize_tree 재실행"


def test_main_skill_mode_change_is_reported() -> None:
    """`stat_set_index` 1 → 3은 같은 젬인데 20배 다른 축이다(#52)."""
    spec = _stamped()
    spec["skills"] = [{"gems": [{"gem_id": BALL, "name": "Ball Lightning", "stat_set_index": 3}]}]
    (found,) = stale_components(spec)
    assert "모드 1" in found["why"] and "모드 3" in found["why"], found


def test_tree_stamp_ignores_its_own_axis() -> None:
    """트리 도장이 트리를 보면 손대는 순간 항상 빨개진다 — 자기 축은 뺀다."""
    spec = _stamped()
    spec["tree_nodes"] = [4739, 22419, 55555]
    assert stale_components(spec) == []


def test_rune_stamp_does_not_ignore_items() -> None:
    """룬은 결과가 **아이템 텍스트**로 들어간다 — 장비가 바뀌면 낡아야 한다.

    자기 축으로 빼면 "무기를 바꿨는데 룬 계획은 멀쩡"이 된다.
    """
    spec = _stamped("runes", "optimize_runes")
    spec["items"] = [{"slot": "Weapon 1", "text": "Rarity: RARE\nB\nSiphoning Wand\n"}]
    (found,) = stale_components(spec)
    assert found["component"] == "runes" and found["why"].startswith("items:")


def test_each_component_is_judged_apart() -> None:
    """트리만 낡고 장비는 멀쩡한 경우가 실제로 있었다 — 전체 해시 하나면 못 가른다."""
    spec = _spec()
    spec["derived_from"] = {
        "tree": stamp(spec, "tree", tool="optimize_tree"),
        "items": stamp(spec, "items", tool="optimize_items"),
    }
    spec["tree_nodes"] = [1, 2, 3]  # 트리만 손댄다
    reported = {s["component"] for s in stale_components(spec)}
    assert reported == {"items"}, "장비 도장만 트리 변경을 본다(트리는 자기 축)"


def test_weights_are_recorded_but_not_compared() -> None:
    """무엇을 상대로 최적화했나는 남겨야 한다 — 스펙에 없으니 비교는 못 한다."""
    spec = _spec()
    mark = stamp(spec, "tree", tool="optimize_tree", weights={"CombinedDPS": 1.0})
    assert mark["weights"] == {"CombinedDPS": 1.0}
    spec["derived_from"] = {"tree": mark}
    assert stale_components(spec) == []


def test_a_spec_without_stamps_is_silent() -> None:
    """도장이 없는 옛 스펙이 갑자기 경고 더미가 되면 안 된다."""
    assert stale_components(_spec()) == []
    assert stale_components({"derived_from": None}) == []


# ── 필수 절차 미이행 (백로그 #58 ④) ──


def test_missing_unique_enumeration_is_reported() -> None:
    """규율은 이미 `skills/`에 있었고 **감지 수단만** 없었다.

    실측 2026-08-11: 한 회차가 유니크 전수를 끝까지 안 돌려 검은화염을 포함한
    유니크가 후보에 오른 적이 없었다. 나중에 돌려 보니 `defensive_only`로
    EHP +1,032짜리 후보가 근거와 함께 나왔다 — **호출을 안 했으면 그 근거도 없다.**
    """
    from pok.engine.provenance import missing_procedures

    (found,) = missing_procedures(_spec())
    assert found["procedure"] == "optimize_items"
    assert "전수" in found["why"]
    assert "derived_from" in found["advice"], "무엇을 해야 사라지는지 말해야 한다"


def test_a_stamped_spec_is_silent() -> None:
    """돌린 흔적이 있으면 조용하다 — 출고마다 뜨면 아무도 안 읽는다(§0 ⑤)."""
    from pok.engine.provenance import missing_procedures

    spec = _spec()
    spec["derived_from"] = {"items": stamp(spec, "items", tool="optimize_items")}
    assert missing_procedures(spec) == []


def test_other_stamps_do_not_satisfy_it() -> None:
    """트리를 돌렸다고 유니크를 본 것이 아니다 — 축이 다르다."""
    from pok.engine.provenance import missing_procedures

    spec = _spec()
    spec["derived_from"] = {"tree": stamp(spec, "tree", tool="optimize_tree")}
    assert [m["procedure"] for m in missing_procedures(spec)] == ["optimize_items"]
