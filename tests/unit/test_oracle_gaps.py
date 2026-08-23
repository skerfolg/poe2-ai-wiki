"""오라클이 **보고도 안 센 것**을 스스로 신고하는가 (#110).

PoB 0.23.1은 플레이어의 트리거·미라주 계산을 통째로 꺼 뒀다
(`Modules/CalcPerform.lua:3433` "TURNING OFF CALC TRIGGERS AND MIRAGES FOR TIME BEING").
되살려 보니 **둘 다 크래시한다** — `CalcTriggers.lua:396`·`CalcMirages.lua:59`이 같은
`skillFlags`(nil)에서 죽는다(실측 2026-08-23). 정책이 아니라 **PoE2 이식 미완성**이고,
우리 스냅샷이 이미 상류 `dev` HEAD라 올라갈 곳도 없다.

⛔ 그래서 이건 「고칠 결함」이 아니라 **선언해야 할 갭**이다. 선언이 없으면 조용한 0이
된다(BACKLOG 형태 ①) — 실측: 래더 표본 120벌 중 **110벌(92%)**이 발동 스킬을 갖는다.
"""

from __future__ import annotations

from pok.pob.runner import PobResult


def _result(**meta: object) -> PobResult:
    return PobResult(stats={}, meta=meta, allocated_nodes=(), pruned_nodes=(), cached=False)


def test_발동_스킬을_본_만큼_신고한다() -> None:
    got = _result(gapTriggeredSkills=3, gapMirageSkills=0, gapMainSkillTriggered=0)
    assert got.oracle_gaps["triggered_skills"] == 3
    assert not got.measures_all_damage, "발동 스킬이 있으면 딜 수치를 그대로 믿으면 안 된다"


def test_갭이_없으면_딜을_그대로_믿어도_된다() -> None:
    got = _result(gapTriggeredSkills=0, gapMirageSkills=0, gapMainSkillTriggered=0)
    assert got.measures_all_damage
    assert got.oracle_gaps == {
        "triggered_skills": 0,
        "mirage_skills": 0,
        "main_skill_triggered": 0,
    }


def test_주력기_발동은_따로_센다() -> None:
    """오차의 **방향이 다르다** — 뭉치면 어느 쪽인지 말할 수 없다.

    주력기가 아닌 발동 스킬은 기여가 0으로 빠져 **과소평가**지만, 주력기 자신이
    발동이면 발동률이 안 걸려 시전 속도대로 계산되므로 **과대평가** 쪽이다.
    실측(래더 120벌): 발동 보유 92% 중 주력기가 발동인 것은 **17%**다.
    """
    side = _result(gapTriggeredSkills=2, gapMainSkillTriggered=0)
    main = _result(gapTriggeredSkills=2, gapMainSkillTriggered=1)
    assert side.oracle_gaps["main_skill_triggered"] == 0
    assert main.oracle_gaps["main_skill_triggered"] == 1
    assert not side.measures_all_damage and not main.measures_all_damage


def test_옛_스냅샷의_meta에도_안_깨진다() -> None:
    """갭 키가 없던 시절의 결과를 읽어도 0으로 읽힌다 — 없는 것과 0은 같다."""
    assert _result(**{"class": "Warrior"}).measures_all_damage
