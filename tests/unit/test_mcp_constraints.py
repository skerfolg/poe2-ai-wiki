"""mcp/tools/constraints — 설계 루프 도구 3종 (dict 입출력, v6 수치)."""

from __future__ import annotations

import pytest

from pok.common.paths import project_root
from pok.mcp.tools.constraints import check_constraints, evaluate_objective, parse_design_doc

_V6_SKILLS = [
    {
        "skill": "불씨 일제 사격",
        "supports": [
            ["처형 III", "red"],
            ["화염 조율", "red"],
            ["조프의 장작", "red"],
            ["신중한 시전", "blue"],
            ["라키아타의 흐름", "green"],
        ],
    },
    {
        "skill": "CoEA 구형 번개",
        "supports": [
            ["앗지리의 성찬식", "blue"],
            ["묵직함", "red"],
            ["울네톨의 포옹", "red"],
            ["방어구 파괴 III", "red"],
        ],
    },
    {"skill": "일반 CoC 혜성", "supports": [["냉기 숙련", "blue"]]},
]


def test_check_constraints_v6_통합() -> None:
    out = check_constraints(
        point_budget={
            "bundles": [
                {"name": "화염술사의 계약", "points": 2, "required": True},
                {"name": "변화된 살점→베이다트의 의지", "points": 4, "required": True},
                {"name": "웃는 번제", "points": 2},
                {"name": "불꽃을 가져오는 자", "points": 2},
            ]
        },
        color_ledger={"skills": _V6_SKILLS, "color": "red"},
        reservation={
            "entries": [
                {"name": "CoEA+앗지리의 성찬식", "base_pct": 66.0},
                {"name": "베이다트의 의지", "base_pct": 25.0, "fixed": True},
            ],
            "efficiency_pct": 57.0,
        },
        exhaustion={
            "skills": _V6_SKILLS,
            "anoints": [{"item": "목걸이", "existing": "기존 성유", "planned": None}],
        },
    )
    pb = out["point_budget"]
    assert pb["budget"] == 8 and pb["total_points"] == 10  # 예산은 KB에서 (미지정)
    assert sorted(pb["branches"]) == [("불꽃을 가져오는 자",), ("웃는 번제",)]
    cl = out["color_ledger"]
    assert cl["total"] == 10 and cl["satisfied"] and cl["headroom_additions"] == 1
    rv = out["reservation"]
    assert rv["remaining_pct"] == 32.96 and rv["low_life"]
    assert rv["low_life_threshold_pct"] == 35.0  # 임계는 KB에서 (미지정)
    assert out["exhaustion"]["violations"] == ()


def test_check_constraints_빈_입력_거부() -> None:
    assert check_constraints()["ok"] is False


def test_evaluate_objective_사전식() -> None:
    out = evaluate_objective(
        targets=[
            {"metric": "remaining_life_pct", "op": "<=", "value": 35.0, "label": "로우라이프"},
            {"metric": "CritChance", "op": ">=", "value": 60.0},
        ],
        measured={"remaining_life_pct": 32.96},
    )
    assert not out["satisfied"]
    assert out["next_bottleneck"]["metric"] == "CritChance"
    assert out["unmeasured"] == ("CritChance",)


def test_parse_design_doc_v6() -> None:
    build_id = "20260731-ember-fusillade-설계v6"
    if not (project_root() / "artifacts" / "builds" / build_id / "design.md").exists():
        pytest.skip("v6 설계 문서 없음 (artifacts는 로컬 산출물)")
    out = parse_design_doc(build_id)
    assert out["ok"] and out["version"] == "v6"
    assert len(out["queue"]) == 16 and out["counts"]["formulas"] == 20
    assert "formulas" not in out  # full=False — 토큰 예산
    full = parse_design_doc(build_id, full=True)
    assert any("66" in f["text"] for f in full["formulas"])


def test_parse_design_doc_부재는_사유_반환() -> None:
    out = parse_design_doc("없는-빌드-id")
    assert out["ok"] is False and "설계 문서 없음" in out["reason"]
