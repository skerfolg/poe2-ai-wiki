"""스킬 세트 충전율 — 빈 역할 칸을 드러낸다 (이관 4 D5).

사용자 지적: 타 유저 앵커는 스킬 그룹 13~28개인데 우리 산출물은 1개였고 정신력
100 중 0을 썼다. `BUILD_DESIGN §2-3-d`가 이미 규율로 있는데 **두 빌드 연속 어겼다.**
같은 세션이 룬은 안 빠뜨렸다 — `exhaustion.sockets`가 보여줬기 때문이다.
"""

from __future__ import annotations

from pok.engine.constraints.skillset import SkillEntry, check_skillset


def test_main_skill_only_build_is_flagged() -> None:
    """이관 노트의 실제 상황 — 주력기 1개, 정신력 100 중 0 사용."""
    report = check_skillset(
        [SkillEntry("Bone Blast", "Deals physical damage")],
        spirit_pool=100.0,
        main_skill="Bone Blast",
    )
    assert report.total_skills == 1
    assert len(report.empty_roles) == 6, "주력기 외 6칸이 비었다"
    assert report.spirit_remaining == 100.0
    joined = " ".join(report.notes)
    assert "한 점도 쓰지 않았다" in joined
    assert "13~28개" in joined, "실측 대비를 함께 보여야 판단이 선다"


def test_filled_build_stops_warning() -> None:
    """채우면 신호가 꺼져야 한다 — 안 꺼지면 경고가 소음이 된다."""
    report = check_skillset(
        [
            SkillEntry("Bone Blast", "physical damage"),
            SkillEntry("Herald of Blood", "Herald buff", reservation=30),
            SkillEntry("Despair", "curse the enemy", reservation=25),
            SkillEntry("Cast on Critical", "trigger socketed spells"),
            SkillEntry("Blink", "dash to location"),
            SkillEntry("Skeletal Warrior", "summon minion", reservation=20),
            SkillEntry("Molten Shield", "guard skill grants immunity"),
        ],
        spirit_pool=100.0,
        main_skill="Bone Blast",
    )
    assert report.fill_pct == 100.0 and not report.empty_roles
    assert report.spirit_remaining == 25.0
    assert not any("한 점도" in n for n in report.notes)


def test_unclassified_is_not_forced_into_a_role() -> None:
    """못 맞히면 `unclassified`로 낸다 — 억지 배정은 "채웠다"는 거짓 신호다."""
    report = check_skillset([SkillEntry("Mystery Skill", "does something")])
    assert report.unclassified == ("Mystery Skill",)


def test_explicit_role_overrides_keyword_guess() -> None:
    report = check_skillset([SkillEntry("Odd Name", "", role="curse")])
    assert not report.unclassified
    assert any(r.key == "curse" and r.filled for r in report.roles)


def test_remaining_spirit_points_to_the_lookup_tool() -> None:
    """잔여를 알려주는 데서 멈추지 않고 **후보를 물을 경로**까지 준다."""
    report = check_skillset(
        [SkillEntry("A", "buff", reservation=60)], spirit_pool=100.0, main_skill="X"
    )
    assert any("find_by_value" in n for n in report.notes)
