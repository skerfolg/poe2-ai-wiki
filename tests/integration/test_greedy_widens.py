"""후보가 마르면 **넓혀 보고** 멈춘다 (#67 6차, 사용자 지적 2026-08-12).

그리디는 반경 안의 가까운 후보만 본다. 시작점 주변이 빌드와 무관한 권역이면
한 수도 못 두고 끝나는데, **예산은 그대로 남는다** — 「노드를 중간까지만 찍은」
트리가 정상 산출물로 나간다.

독스트링에 "반경·후보 수를 늘려라"라고 적어 두는 방식은 이 레포에서 실패가
증명됐다(문서에만 있는 규율은 안 지켜진다). 그래서 도구가 스스로 넓힌다.

실측 A/B (앵커 46포인트 + 예산 30 · 반경 7):
- 확장 없음: 스텝 **0** · 예산 30 전량 미사용 · rejected=1
- 자동 확장: 스텝 **11** · 예산 30 전량 사용 (반경 7 → 14 → 24)
"""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree import optimize as opt
from pok.engine.tree.corpus import suggest_anchors
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import spec_from_dict


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(knowledge_dir())


def _spec():
    return spec_from_dict(
        {
            "class_name": "Monk",
            "ascendancy": "Monk1",
            "level": 90,
            "skills": [
                {
                    "gems": [
                        {
                            "gem_id": "Metadata/Items/Gems/SkillGemTempestFlurry",
                            "name": "Tempest Flurry",
                            "stat_set_index": 1,
                        }
                    ]
                }
            ],
            "tree_nodes": [],
        }
    )


def test_마른_라운드에_멈추지_않고_넓힌다(graph: TreeGraph, monkeypatch) -> None:
    anchors = tuple(r["node"] for r in suggest_anchors(graph, "Martial Artist")["required"])
    objective = opt.Objective(weights={"CombinedDPS": 1.0, "TotalEHP": 0.6})
    common = {
        "point_budget": 76,
        "candidate_radius": 7,
        "max_candidates_per_round": 14,
        "required_anchors": anchors,
    }

    # 상한을 시작값으로 막으면 **확장 이전 동작**이 그대로 재현된다
    monkeypatch.setattr(opt, "_MAX_REACH", 7)
    monkeypatch.setattr(opt, "_MAX_SLICE", 14)
    before = opt.optimize_tree(_spec(), graph, objective, **common)
    assert not before.steps, "이 구성은 원래 한 수도 못 두고 멈춘다(전제가 깨졌다)"
    assert any("쓰지 못하고 끝났다" in n for n in before.notes), (
        "예산을 남기고 끝났는데 조용하다 — 미사용 예산은 반드시 신호가 돼야 한다"
    )

    monkeypatch.setattr(opt, "_MAX_REACH", 24)
    monkeypatch.setattr(opt, "_MAX_SLICE", 160)
    after = opt.optimize_tree(_spec(), graph, objective, **common)
    assert after.steps, "넓히고도 한 수도 못 뒀다"
    assert any("넓혔다" in n for n in after.notes), "넓힌 사실을 안 밝혔다"
    assert not any("쓰지 못하고 끝났다" in n for n in after.notes), "예산이 남았다"
