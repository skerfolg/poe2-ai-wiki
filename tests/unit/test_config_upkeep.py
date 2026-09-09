"""켜 둔 config의 유지 비용 — 「이 표기가 팩에서도 서나」 (#145).

실측 2026-09-04(레퍼런스 힘스태킹 젬링): 조건 13종을 전부 참으로 둔 빌드가 세팅
없이 팩에 들어가면 표기의 **52.6%**였다. 딜을 만드는 둘(전쟁 깃발·격노)은 영광 200
축적 + 반경 6m 유지를 요구하고, 마크 2종은 `Limit 1 Marked targets`라 한 마리에만
걸린다. 그 대가를 **아무 반환값도 말하지 않았다.**
"""

from __future__ import annotations

from pok.engine.constraints.upkeep import UpkeepCost, find_upkeep_costs, truthy_conditions

# 전부 KB 정본의 실제 문구다(`skill.war-banner`·`skill.snipers-mark`·
# `skill.ice-tipped-arrows`·`skill.ancestral-cry`). 지어낸 문구로 시험하면
# 파서가 게임 표기와 어긋나도 초록불이 뜬다.
WAR_BANNER = [
    "Generates 100% of Monster Power as Glory for this Skill on Hitting with an Attack",
    "Requires 200 Glory to use",
    "Banner Aura radius is 6 metres",
    "Aura grants 25% more Attack damage",
]
SNIPERS_MARK = [
    "Limit 1 Marked targets",
    "Maximum Mark duration is 8 seconds",
    "Next Critical Hit against Marked Enemy has (20 — 77)% increased Critical Damage Bonus",
]
ICE_TIPPED = [
    "Maximum Buff duration is 20 seconds",
    "Empowers 4 Attacks",
    "Converts 100% of Physical damage to Cold damage",
]


def _kinds(costs: tuple[UpkeepCost, ...], source: str) -> set[str]:
    return {c.kind for c in costs if c.source == source}


def test_hard_per_pack_costs_are_reported_without_any_config_link() -> None:
    """자원 관문·대상 한계·횟수·반경은 **config 연동과 무관하게** 낸다.

    ⭑ 이게 이 검사기의 존재 이유다. `bannerPlanted`는 PoB `ConfigOptions.lua`에
    관련성 조건이 **아예 없어서**(`conds=()`) config를 축으로 삼는 매처로는 통째로
    누락된다 — 그런데 실측에서 이 빌드 딜의 **20.3%**가 거기 걸려 있었다. 즉 가장
    큰 대가가 가장 조용했다.
    """
    costs = find_upkeep_costs({"skill.war-banner": WAR_BANNER}, {})
    assert _kinds(costs, "skill.war-banner") == {"resource_gate", "positional"}, costs
    gate = next(c for c in costs if c.kind == "resource_gate")
    # 근거는 **원문 그대로** 남아야 반박할 수 있다
    assert gate.evidence == "Requires 200 Glory to use", gate
    assert "6" in next(c for c in costs if c.kind == "positional").note


def test_mark_single_target_limit_is_read_from_game_text() -> None:
    """`Limit 1 Marked targets` — PoB는 대상 하나를 재므로 「상시 걸림」으로 계산된다.

    팩에서는 N마리 중 1마리에만 걸린다. 이 한 줄이 「보스 딜」과 「클리어 딜」을
    가르는데 어느 반환값에도 없었다.
    """
    costs = find_upkeep_costs({"skill.snipers-mark": SNIPERS_MARK}, {})
    single = [c for c in costs if c.kind == "single_target"]
    assert len(single) == 1, costs
    assert "1마리" in single[0].note, single[0]


def test_limited_uses_is_reported() -> None:
    """「Empowers 4 Attacks」 — 횟수를 쓰면 다시 걸어야 한다(노출 공급원이 이것이었다)."""
    costs = find_upkeep_costs({"skill.ice-tipped-arrows": ICE_TIPPED}, {})
    assert "limited_uses" in _kinds(costs, "skill.ice-tipped-arrows"), costs
    # 20초 지속은 `_LONG_DURATION_S`(60초) 밑이지만 config 연동이 없으므로 안 낸다 —
    # 흔한 표시를 무조건 내면 빌드의 모든 스킬이 신고돼 신호가 묻힌다
    assert "recast" not in _kinds(costs, "skill.ice-tipped-arrows"), costs


def test_cooldown_needs_a_config_link_to_be_reported() -> None:
    """쿨다운·지속은 **그 출처가 켜 둔 조건에 걸릴 때만** 낸다.

    쿨다운은 거의 모든 스킬에 있다. 무조건 내면 20그룹짜리 빌드가 20건을 뱉고
    진짜 신호(자원 관문·대상 한계)가 묻힌다.
    """
    texts = {"skill.ancestral-cry": ["Warcry duration is 8 seconds", "Warcry radius is 4 metres"]}
    quiet = find_upkeep_costs(texts, {}, cooldowns={"skill.ancestral-cry": 0.4})
    assert _kinds(quiet, "skill.ancestral-cry") == {"positional"}, quiet

    loud = find_upkeep_costs(
        texts, {"conditionUsedWarcryRecently": True}, cooldowns={"skill.ancestral-cry": 0.4}
    )
    assert "recast" in _kinds(loud, "skill.ancestral-cry"), loud
    linked = [c for c in loud if c.kind == "recast"]
    assert all("conditionUsedWarcryRecently" in c.config_vars for c in linked), linked


def test_only_truthy_conditions_count() -> None:
    """퀘스트 보상 문자열·0·False는 「켠 조건」이 아니다."""
    got = truthy_conditions(
        {
            "conditionMoving": True,
            "conditionStationary": False,
            "multiplierRage": 30,
            "multiplierNearbyEnemies": 0,
            "questAct 4Halls Of The DeadTasalio's Test": "+5% to Cold Resistance",
        }
    )
    assert got == {"conditionMoving": True, "multiplierRage": 30}, got


def test_no_unsupplied_verdict_is_emitted() -> None:
    """⛔ 「공급원이 없다」는 내지 않는다 — 첫 판이 11건 중 6건 오탐이었다.

    재의 전령은 점화를 거는데 문구가 `Ignite surrounding enemies`라 키워드
    `Ignited`에 안 걸렸고, `bannerValour`의 PoB 조건은 `ifSkill "Unbound Avatar"`라
    전쟁 깃발과 무관하다. 두 방향 다 틀린 매처로 「없음」을 선언하면 **없는 결함을
    조사하게 만든다**. 그 판정은 `audit_config_upkeep(measure=True)`의 실측 몫이다.
    """
    costs = find_upkeep_costs(
        {"skill.herald-of-ash": ["Ignite surrounding enemies if Overkill damage is at least 20%"]},
        {"conditionEnemyIgnited": True, "conditionEnemyLightningExposure": True},
    )
    assert all(c.kind != "unsupplied" for c in costs), costs
