"""축 완전성 보고 + 탐침 게이트 (회차 종결 R1·R2·R3).

사용자 교정 2판이 세션 생성본과 61배 차이를 실증했다. 격차 성분 대부분이
"어려운 것"이 아니라 **열거조차 안 한 축**이었다 — 젬 레벨 +5(1.28x)·카옴(1.26x)·
성유·부여 스킬·호신부/플라스크.
"""

from __future__ import annotations

from pok.engine.constraints.axes import check_axes
from pok.pob.buildxml import find_probe_lines, spec_from_dict, strip_probe_tags, to_xml

SESSION_BUILD = {
    # 세션 생성본의 실제 상태: 젬 전부 20, 목걸이에 성유 없음, 호신부/플라스크 없음
    "class_name": "Witch",
    "ascendancy": "Witch2",
    "skills": [{"gems": [{"name": "Stampede", "level": 20}]}],
    "items": [
        {"slot": "Amulet", "text": "Rarity: RARE\nT\nBase"},
        {"slot": "Weapon 1", "text": "Rarity: UNIQUE\nT\nBase"},
    ],
}


def test_session_build_state_is_fully_surfaced() -> None:
    """세션 생성본을 넣으면 61배 격차의 성분들이 전부 드러나야 한다."""
    report = check_axes(SESSION_BUILD)
    states = {a.key: a.state for a in report.axes}
    assert states["gem_level"] == "empty", "전부 20레벨 = +레벨 축 미사용"
    assert states["anoint"] == "empty", "목걸이가 있는데 성유가 없다"
    assert states["charm"] == "empty" and states["flask"] == "empty"
    assert states["quality"] == "unmeasured" and states["slot_attack"] == "unmeasured"
    assert any("61배" in n for n in report.notes)


def test_covered_axes_stop_warning() -> None:
    """축을 채우면 신호가 꺼져야 한다 — 안 꺼지면 소음이 된다."""
    corrected = {
        **SESSION_BUILD,
        "skills": [{"gems": [{"name": "Stampede", "level": 25}]}],
        "items": [
            {"slot": "Amulet", "text": "Rarity: RARE\nT\nBase\nAllocates 12345"},
            {"slot": "Charm 1", "text": "Rarity: MAGIC\nT\nBase"},
            {"slot": "Flask 1", "text": "Rarity: MAGIC\nT\nBase"},
        ],
    }
    report = check_axes(corrected, quality_checked=True, slot_attack_deltas={"Amulet": 120.0})
    states = {a.key: a.state for a in report.axes}
    for key in ("gem_level", "anoint", "charm", "flask", "quality", "slot_attack"):
        assert states[key] == "covered", f"{key}가 covered여야 한다"


def test_unmeasured_is_not_empty() -> None:
    """'없다'와 '안 쟀다'를 가른다 — 없다고 단정하면 그게 또 조용한 거짓이다."""
    report = check_axes(SESSION_BUILD)
    slot_attack = next(a for a in report.axes if a.key == "slot_attack")
    assert slot_attack.state == "unmeasured"
    assert "evaluate_delta" in slot_attack.detail, "재는 방법까지 알려준다"
    # 실측을 주면 empty/covered로 갈린다
    with_deltas = check_axes(SESSION_BUILD, slot_attack_deltas={"Amulet": 0.0})
    assert next(a for a in with_deltas.axes if a.key == "slot_attack").state == "empty"


def test_probe_lines_block_assembly_but_not_measurement() -> None:
    """탐침 게이트 (R1) — 천장 측정은 통과, 출고는 거부.

    실증: `+16650 생명력` 탐침이 빠진 뒤 주 엔진(생명력)을 실물로 재건하지 않은 채
    출고됐다. 태그가 없어서 "재건해야 할 것" 목록에 오르지 못했다.
    """
    spec = {
        "class_name": "Witch",
        "ascendancy": "Witch2",
        "items": [
            {
                "slot": "Body Armour",
                "text": "Rarity: RARE\nT\nBase\n--------\n+16650 to maximum Life [탐침]",
            }
        ],
    }
    probes = find_probe_lines(spec)
    assert probes == ["Body Armour: +16650 to maximum Life [탐침]"]
    # 측정 경로: XML에서 태그만 벗고 수치는 유지
    xml = to_xml(spec_from_dict(spec))
    assert "[탐침]" not in xml and "+16650" in xml


def test_probe_tag_variants() -> None:
    assert strip_probe_tags("+100 Life [PROBE]") == "+100 Life "
    assert find_probe_lines({"jewels": [{"socket_node_id": 7, "text": "x [probe]"}]})
    assert not find_probe_lines({"items": [{"slot": "A", "text": "clean line"}]})
