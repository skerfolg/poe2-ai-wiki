"""산출 출처와 낡음 판정 — 백로그 #58 ③ (2026-08-11).

선행 문서가 「트리 3·4·5차 전부 무효」라고 적어 뒀는데(`conditionLowLife` 없이
산출했으므로) **그 트리가 그대로 계승돼** 다음 세션이 25포인트를 더 얹었다.
「무효」를 읽고도 계승한 이유는 **무엇이 달라서 무효인지 몰랐기 때문**이다 —
그래서 이 파일이 지키는 것은 "감지한다"가 아니라 **"문장으로 말한다"**이다.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from pok.engine.provenance import derivation_context, missing_procedures, stale_components, stamp

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


@pytest.mark.parametrize(
    "collection,identity,value",
    [
        ("items", "slot", "Weapon 1"),
        ("jewels", "socket_node_id", 4739),
    ],
)
def test_nested_context_change_reports_owner_path(
    collection: str,
    identity: str,
    value: Any,
) -> None:
    spec = _spec()
    spec[collection] = [{identity: value, "text": "an item"}]
    owner = spec[collection][0]
    owner["derived_from"] = {"rares": stamp(spec, "rares", tool="optimize_rare")}
    assert stale_components(spec) == []
    spec["tree_nodes"].append(55555)
    (found,) = stale_components(spec)
    assert found["path"] == f"{collection}[0].derived_from.rares"
    assert found[identity] == str(value)
    assert found["component"] == "rares" and found["status"] == "stale"
    assert found["why"] == "tree: 2노드 → 3노드"


def test_nested_tree_stamp_still_ignores_own_axis() -> None:
    spec = _spec(jewels=[{"socket_node_id": 4739, "text": "jewel"}])
    spec["jewels"][0]["derived_from"] = {"tree": stamp(spec, "tree", tool="optimize_tree")}
    spec["tree_nodes"].append(55555)
    assert stale_components(spec) == []


def test_items_stamp_still_ignores_its_own_item_axis() -> None:
    spec = _stamped("items", "optimize_items")
    spec["items"][0]["text"] = "a changed item"
    spec["items"][0]["substitutes"] = ["+10 to maximum Life"]
    spec["items"][0]["active"] = False
    assert stale_components(spec) == []


def test_item_activity_change_is_part_of_context() -> None:
    spec = _stamped()
    spec["items"][0]["active"] = True
    assert stale_components(spec) == []
    spec["items"][0]["active"] = False
    (found,) = stale_components(spec)
    assert found["why"].startswith("item_activity:")


@pytest.mark.parametrize(
    "field,value",
    [
        ("level", 21),
        ("quality", 20),
        ("enabled", False),
        ("stages", 4),
        ("corrupted", True),
        ("corrupt_level", 1),
    ],
)
def test_gem_calculation_inputs_are_part_of_context(field: str, value: Any) -> None:
    spec = _stamped()
    spec["skills"][0]["gems"][0][field] = value
    (found,) = stale_components(spec)
    assert found["why"].startswith("skills_details:")


@pytest.mark.parametrize("field,value", [("enabled", False), ("slot", "Helmet")])
def test_skill_group_calculation_inputs_are_part_of_context(field: str, value: Any) -> None:
    spec = _stamped()
    spec["skills"][0][field] = value
    assert any(row["why"].startswith("skills_details:") for row in stale_components(spec))


@pytest.mark.parametrize(
    "field,value",
    [
        ("level", 100),
        ("class_name", "Witch"),
        ("ascendancy", "Sorceress2"),
    ],
)
def test_character_changes_invalidate_other_context(field: str, value: Any) -> None:
    spec = _stamped()
    spec[field] = value
    (found,) = stale_components(spec)
    assert found["why"].startswith("character:")


@pytest.mark.parametrize(
    "field,value",
    [
        ("text", "different jewel"),
        ("socket_node_id", 22419),
        ("allocates", [55555]),
    ],
)
def test_jewel_contents_location_and_grants_are_context(field: str, value: Any) -> None:
    spec = _spec(jewels=[{"socket_node_id": 4739, "text": "jewel"}])
    spec["derived_from"] = {"tree": stamp(spec, "tree", tool="optimize_tree")}
    spec["jewels"][0][field] = value
    (found,) = stale_components(spec)
    assert found["why"].startswith("jewels:")


def test_attribute_choices_and_substitutes_are_calculation_context() -> None:
    spec = _stamped()
    spec["attribute_choices"] = {"4739": "dex"}
    spec["items"][0]["substitutes"] = ["+10 to maximum Life"]
    assert {row["why"].split(":")[0] for row in stale_components(spec)} == {
        "attribute_choices",
        "item_substitutes",
    }


def test_defaults_metadata_and_order_do_not_make_fresh_context_stale() -> None:
    spec = _spec(
        jewels=[{"socket_node_id": 4739, "text": "jewel"}],
        attribute_choices={4739: "dex"},
    )
    spec["derived_from"] = {"tree": stamp(spec, "tree", tool="optimize_tree")}
    spec["skills"][0].update(slot="Weapon 1", enabled=True, main_active_skill=1)
    spec["skills"][0]["gems"][0].update(
        level=20,
        quality=0,
        enabled=True,
        stages=None,
        corrupted=False,
        corrupt_level=0,
    )
    spec["items"][0]["substitutes"] = []
    spec["jewels"][0]["allocates"] = []
    spec["jewels"][0]["derived_from"] = {}
    spec["attribute_choices"] = {"4739": "dex"}
    spec["tree_nodes"].reverse()
    assert stale_components(spec) == []


def _legacy_mark(spec: dict[str, Any]) -> dict[str, Any]:
    mark = stamp(spec, "tree", tool="optimize_tree")
    return {
        key: value
        for key, value in mark.items()
        if key
        in {
            "config",
            "skills_sig",
            "skills_desc",
            "items_sig",
            "items_desc",
            "tree_sig",
            "tree_desc",
            "tool",
        }
    }


def test_legacy_stamp_is_unverified_without_false_hash_changes() -> None:
    spec = _spec()
    spec["derived_from"] = {"tree": _legacy_mark(spec)}
    (found,) = stale_components(spec)
    assert found["status"] == "unverified"
    spec["skills"][0]["gems"][0]["quality"] = 20
    (found,) = stale_components(spec)
    assert found["status"] == "unverified", "구도장에 없는 입력은 변경됐다고 단정할 수 없다"


def test_legacy_stamp_still_reports_provable_changes() -> None:
    spec = _spec()
    spec["derived_from"] = {"tree": _legacy_mark(spec)}
    spec["config"] = {"conditionLowLife": True}
    changes = [row for row in stale_components(spec) if row["status"] == "stale"]
    assert [row["why"] for row in changes] == ["config.conditionLowLife: False → True"]


def test_incomplete_v2_stamp_reports_missing_coverage() -> None:
    spec = _stamped()
    del spec["derived_from"]["tree"]["jewels_sig"]
    (found,) = stale_components(spec)
    assert found["status"] == "unverified" and "jewels" in found["why"]


def test_invalid_top_level_stamps_do_not_hide_nested_stamps() -> None:
    spec = _spec(derived_from="unusable")
    spec["items"][0]["derived_from"] = {"rares": stamp(spec, "rares", tool="optimize_rare")}
    spec["config"]["conditionLowLife"] = True
    assert stale_components(spec)[0]["path"] == "items[0].derived_from.rares"


def test_direct_legacy_item_receipt_is_not_silently_skipped() -> None:
    spec = _spec()
    spec["items"][0]["derived_from"] = _legacy_mark(spec)
    spec["config"]["conditionLowLife"] = True
    found = stale_components(spec)
    assert {row["status"] for row in found} == {"stale", "unverified"}
    assert {row["path"] for row in found} == {"items[0].derived_from"}


def test_direct_tree_receipt_preserves_own_axis_semantics() -> None:
    spec = _spec()
    spec["items"][0]["derived_from"] = stamp(spec, "tree", tool="optimize_tree")
    spec["tree_nodes"].append(55555)
    assert stale_components(spec) == []


def test_search_evidence_is_snapshotted_without_a_sufficiency_verdict() -> None:
    evidence = {
        "scope": {"slots": ["Weapon 1"]},
        "settings": {"max_rounds": 1},
        "termination": {"reason": "max_rounds", "converged": False},
        "unresolved": [{"code": "limited_scope", "detail": "one slot"}],
    }
    expected = deepcopy(evidence)
    mark = stamp(_spec(), "items", tool="optimize_items", search_evidence=evidence)
    evidence["scope"]["slots"].append("Helmet")
    assert mark["search_evidence"] == expected
    spec = _spec(derived_from={"items": mark})
    assert stale_components(spec) == [], "범위 충분성은 문맥 변경 판정과 별개다"


def test_missing_procedure_means_missing_evidence_not_no_session_call() -> None:
    for marks in ({}, {"items": {}}, {"items": {"tool": "optimize_rare"}}):
        (found,) = missing_procedures(_spec(derived_from=marks))
        assert found["status"] == "unverified"
        assert "한 번도 안 돌렸다" not in found["why"]
        assert "전체 세션의 미실행을 뜻하지" in found["why"]


def test_gemling_20261012_nested_provenance_regression() -> None:
    """실제 perfect-strike/spec.json에서 계산 없이 축소한 휴대 가능한 출처 fixture.

    실제 최종 노드·config와 Weapon/Helmet/Ruby의 config/tree 도장을 보존한다.
    게임 아이템 문구·젬·다른 도장 축은 이 재현에 필요 없어 제외했다. 플레이용 스펙이 아니다.
    """
    config = {
        "enemyLevel": 82,
        "enemyIsBoss": "Pinnacle",
        "enemyFireResist": 50,
        "enemyColdResist": 50,
        "enemyLightningResist": 50,
        "enemyChaosResist": 30,
        "enemyFirePen": 0,
        "enemyColdPen": 0,
        "enemyLightningPen": 0,
    }
    spec = {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "level": 100,
        "tree_nodes": [
            1200,
            1433,
            1442,
            2617,
            3601,
            4140,
            5710,
            6015,
            6529,
            7721,
            7960,
            8554,
            11525,
            11641,
            13326,
            14429,
            14654,
            16168,
            18448,
            22616,
            23382,
            23930,
            24430,
            25374,
            27726,
            28510,
            28982,
            29611,
            30141,
            31238,
            31326,
            32416,
            32474,
            33722,
            34882,
            35426,
            36822,
            38300,
            38323,
            39594,
            39716,
            41768,
            42350,
            44733,
            45248,
            45969,
            47191,
            47263,
            47931,
            48552,
            48631,
            50629,
            51248,
            52669,
            53030,
            53108,
            53294,
            53329,
            54232,
            55188,
            55190,
            57373,
            58295,
            58591,
            59093,
            59779,
            61438,
            64724,
            56910,
            14926,
            50609,
            48530,
            4623,
            48524,
            16311,
            32600,
            31290,
            37609,
            21213,
            20303,
            8406,
            48305,
            6898,
            30704,
            22045,
            13505,
            63209,
            36602,
            18465,
            17655,
            19873,
            28950,
            43893,
            55101,
            58016,
            58528,
            45363,
            55478,
            48006,
            26739,
            7777,
            47150,
            44836,
            38779,
            44605,
            32549,
            29098,
            3218,
            53443,
            5088,
            16596,
            38535,
            61835,
            55888,
            50216,
            1170,
            41126,
            64443,
            9884,
            38696,
            54868,
            14265,
            32845,
            31746,
            41012,
            11392,
            9918,
            21017,
            55789,
            41665,
            50562,
        ],
        "config": config,
        "items": [
            {
                "slot": "Weapon 1",
                "derived_from": {
                    "rares": {
                        "config": {},
                        "tree_sig": "sha1:a0eb037b6316",
                        "tree_desc": "68노드",
                        "tool": "optimize_rare",
                    }
                },
            },
            {
                "slot": "Helmet",
                "derived_from": {
                    "rares": {
                        "config": {},
                        "tree_sig": "sha1:93b5932647e7",
                        "tree_desc": "8노드",
                        "tool": "optimize_rare",
                    }
                },
            },
        ],
        "jewels": [
            {
                "socket_node_id": 55190,
                "derived_from": {
                    "rares": {
                        "config": config,
                        "tree_sig": "sha1:6c3c1efec49b",
                        "tree_desc": "114노드",
                        "tool": "optimize_rare",
                    }
                },
            }
        ],
    }
    assert derivation_context(spec)["tree_sig"] == "sha1:7e70cbeb437a"
    found = stale_components(spec)
    assert {(row["path"], row["why"]) for row in found if row["why"].startswith("tree:")} == {
        ("items[0].derived_from.rares", "tree: 68노드 → 131노드"),
        ("items[1].derived_from.rares", "tree: 8노드 → 131노드"),
        ("jewels[0].derived_from.rares", "tree: 114노드 → 131노드"),
    }
    assert sum(row["status"] == "unverified" for row in found) == 3
