"""후보가 마르면 **넓혀 보고** 멈춘다 (#67 6차, 사용자 지적 2026-08-12).

그리디는 반경 안의 가까운 후보만 본다. 시작점 주변이 빌드와 무관한 권역이면
한 수도 못 두고 끝나는데, **예산은 그대로 남는다** — 「노드를 중간까지만 찍은」
트리가 정상 산출물로 나간다.

독스트링에 "반경·후보 수를 늘려라"라고 적어 두는 방식은 이 레포에서 실패가
증명됐다(문서에만 있는 규율은 안 지켜진다). 그래서 도구가 스스로 넓힌다.

실측 A/B (앵커 46포인트 + 예산 30 · 반경 7):
- 확장 없음: 스텝 **0** · 예산 30 전량 미사용 · rejected=1
- 자동 확장: 스텝 **11** · 예산 30 전량 사용 (반경 7 → 14 → 24)

⚠ `point_budget`이 76 → 72로 내려간 것은 시험을 통과시키려는 조정이 아니라 **회계가
바뀌었기 때문**이다(#68). 이 앵커 11개는 일반 42 + 전직 4로 갈리는데, 예전엔 46을
전부 일반 예산에서 뺐다(76-46=30). 이제 전직 4는 별도 풀이라 안 뺀다(76-42=34).
그리디에 남는 몫을 이 시험이 재던 **30 그대로** 두려면 72가 맞다(72-42=30).
"""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree import optimize as opt
from pok.engine.tree.corpus import suggest_anchors
from pok.engine.tree.graph import TreeGraph
from pok.pob.buildxml import spec_from_dict
from pok.pob.versions import find_luajit, resolve_snapshot


def _env_ready() -> bool:
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


# 후보 하나가 PoB 계산 1회다 — 오라클 없이는 돌 수 없다(형제 통합 테스트와 같은 관문).
pytestmark = pytest.mark.skipif(not _env_ready(), reason="LuaJIT 또는 external/pob 스냅샷 없음")


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
        "point_budget": 72,  # 일반 42 + 그리디 몫 30 (#68 회계 — 독스트링 참조)
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


def test_시간_상한을_넘기면_멈추고_밝힌다(graph: TreeGraph) -> None:
    """후보 하나가 PoB 계산 1회(실측 0.16초)다. 예산·후보 수에 비례해 늘어나
    **예산 156·후보 40이 40분을 넘겼다**(실측 2026-08-12: 진행 표시도 없이 45분째
    돌던 실행을 죽였다). 상한이 없으면 세션이 통째로 멈춘다.

    ⚠ 중단한 트리는 **덜 최적화된 것이지 완성된 것이 아니다** — 그 사실이 반환값에
    없으면 정상 산출물로 읽힌다.
    """
    out = opt.optimize_tree(
        spec_from_dict({"class_name": "Monk", "ascendancy": "Monk1", "level": 90}),
        graph,
        opt.Objective(weights={"TotalEHP": 1.0}),
        point_budget=60,
        candidate_radius=8,
        max_candidates_per_round=30,
        time_budget_s=5,
    )
    assert any("시간 상한" in n and "남았다" in n for n in out.notes), (
        "시간으로 잘린 트리를 완성본과 구별할 수 없다"
    )


def test_주얼_소켓을_0으로_쟀으면_말한다(graph: TreeGraph) -> None:
    """빈 소켓은 델타 0이라 그리디가 **영영 안 찍는다**. 래더 표본은 중앙 5개를 찍는데
    우리 산출물은 앵커로 받은 것뿐이었다(실측 2026-08-12).

    ⛔ 예전처럼 **고정 가중치를 가정하지 않는다**(AD-8 반프록시): 같은 소켓이 매직
    주얼 +10.16 DPS, 레어 +21.07로 **2배 넘게 갈린다** — 상수로는 표현할 수 없다.
    재려면 템플릿이 필요하고, 안 줬으면 **0으로 쟀다고 말한다**.
    """
    out = opt.optimize_tree(
        spec_from_dict({"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90}),
        graph,
        opt.Objective(weights={"TotalEHP": 1.0}),
        point_budget=6,
        candidate_radius=6,
        max_candidates_per_round=10,
        time_budget_s=60,
    )
    assert any("0으로 쟀다" in n for n in out.notes), "소켓을 0으로 재고도 조용하다"


def test_반경_선언_없는_주얼_템플릿을_잡는다(graph: TreeGraph) -> None:
    """반경 주얼(Time-Lost 계열)은 `Radius:` 선언이 없으면 **어느 소켓에서든 델타 0**
    이다(실측 2026-08-09: 선언하면 CritChance 10.44 → 15.84). 오류가 아니라 조용한
    과소 계상이라 소켓을 하나도 안 찍었어도 알려야 한다 — 안 그러면 다음 실행에서
    같은 템플릿으로 또 0을 잰다.
    """
    bad = (
        "Rarity: RARE\nFoo\nTime-Lost Diamond\nItem Level: 82\n"
        "Notable Passive Skills in Radius also grant 10% increased Critical Hit Chance"
    )
    out = opt.optimize_tree(
        spec_from_dict({"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90}),
        graph,
        opt.Objective(weights={"TotalEHP": 1.0}),
        point_budget=4,
        candidate_radius=5,
        max_candidates_per_round=8,
        jewel_templates=(bad,),
        time_budget_s=60,
    )
    assert any("반경 선언" in n for n in out.notes), "반경 누락을 놓쳤다"
