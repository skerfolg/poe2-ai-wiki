"""#63 P1 — 스킬 타입·모드 수집기의 파싱 규칙을 **데이터 없이** 잠근다.

CI엔 `Data/Skills/sup_dex.lua` 하나뿐이라 실데이터 대조는 로컬에서만 돈다(#62와
같은 구조). 여기서는 손으로 만든 Lua 조각으로 파서의 의미론을 고정한다 —
특히 **RPN 식의 순서 보존**과 **메타 젬 반쪽 둘**은 틀리면 조용히 틀린다.
"""

from __future__ import annotations

from pathlib import Path

from pok.kb.ingest.skill_types import (
    _fold,
    _pob_block,
    parse_gems,
    parse_skill_effects,
)

_SKILLS_LUA = """\
skills["BallPlayer"] = {
	name = "Ball",
	skillTypes = { [SkillType.Spell] = true, [SkillType.Totemable] = true, },
	statSets = {
		[1] = { label = "One", },
		[2] = { label = "Two", },
	},
}
skills["SummonMetaPlayer"] = {
	name = "Meta Totem",
	skillTypes = { [SkillType.Meta] = true, },
}
skills["SupportMetaPlayer"] = {
	name = "SupportMetaInternal",
	support = true,
	ignoreMinionTypes = true,
	requireSkillTypes = { SkillType.Spell, SkillType.Totemable, SkillType.AND, },
	excludeSkillTypes = { SkillType.Triggered, SkillType.NOT, },
	addSkillTypes = { SkillType.UsedByTotem, },
}
skills["GrantedPlayer"] = {
	name = "Granted Thing",
	fromItem = true,
	cannotBeSupported = true,
	skillTypes = { [SkillType.Attack] = true, },
}
skills["StaffOnlyPlayer"] = {
	name = "Staff Only",
	weaponTypes = { ["Staff"] = true, },
	skillTypes = { [SkillType.Attack] = true, },
}
skills["UnarmedOkPlayer"] = {
	name = "Unarmed Ok",
	weaponTypes = { ["None"] = true, ["One Hand Mace"] = true, },
}
skills["NoWeaponRulePlayer"] = {
	name = "No Weapon Rule",
	skillTypes = { [SkillType.Spell] = true, },
}
"""

_GEMS_LUA = """\
	["Metadata/Items/Gems/SkillGemBall"] = {
		name = "Ball",
		grantedEffectId = "BallPlayer",
	},
	["Metadata/Items/Gems/SkillGemMeta"] = {
		name = "Meta Totem",
		grantedEffectId = "SummonMetaPlayer",
		additionalGrantedEffectId1 = "SupportMetaPlayer",
	},
"""


def _src(tmp_path: Path) -> Path:
    (tmp_path / "Data" / "Skills").mkdir(parents=True)
    (tmp_path / "Data" / "Skills" / "act_int.lua").write_text(_SKILLS_LUA, encoding="utf-8")
    (tmp_path / "Data" / "Gems.lua").write_text(_GEMS_LUA, encoding="utf-8")
    return tmp_path


def test_rpn_order_is_preserved(tmp_path: Path) -> None:
    """require/exclude는 후위 식이다 — 정렬하면 의미가 바뀐다(`{A,B,AND}` ≠ `{AND,A,B}`)."""
    effects = parse_skill_effects(_src(tmp_path))
    gate = effects["SupportMetaPlayer"]
    assert gate["require"] == ["Spell", "Totemable", "AND"]
    assert gate["exclude"] == ["Triggered", "NOT"]
    assert gate["adds"] == ["UsedByTotem"]
    assert gate["support"] is True
    assert gate["ignore_minion_types"] is True


def test_stat_set_labels_in_declared_order(tmp_path: Path) -> None:
    """statSet 라벨은 1번부터 선언 순서다 — 색인이 곧 XML의 index다(#52)."""
    effects = parse_skill_effects(_src(tmp_path))
    assert effects["BallPlayer"]["stat_sets"] == ["One", "Two"]
    assert sorted(effects["BallPlayer"]["types"]) == ["Spell", "Totemable"]


def test_flags_only_present_when_true(tmp_path: Path) -> None:
    """빈 값·거짓 플래그는 생략한다 — 레코드가 938건이라 지면이 비용이다."""
    effects = parse_skill_effects(_src(tmp_path))
    granted = effects["GrantedPlayer"]
    assert granted["from_item"] is True and granted["cannot_be_supported"] is True
    assert "require" not in granted and "stat_sets" not in granted
    assert "from_item" not in effects["BallPlayer"]


def test_meta_gem_keeps_both_halves(tmp_path: Path) -> None:
    """메타 젬은 소환 반쪽 + 보조 반쪽 — 주 id만 남기면 담체 판정이 통째로 빠진다."""
    src = _src(tmp_path)
    gems = parse_gems(src)
    assert gems["Metadata/Items/Gems/SkillGemMeta"]["effects"] == [
        "SummonMetaPlayer",
        "SupportMetaPlayer",
    ]
    effects = parse_skill_effects(src)
    by_name = {"meta totem": ["Metadata/Items/Gems/SkillGemMeta"]}
    block = _pob_block("Skill", "Meta Totem", by_name, gems, effects, {})
    assert block is not None and len(block["effects"]) == 2
    assert block["effects"][1]["support"] is True


def test_fold_bridges_diacritics() -> None:
    """poe2db는 `Mórrigan's`, PoB는 `Morrigan's` — 뭉개지 않으면 실존 젬이 고아가 된다."""
    assert _fold("Mórrigan's Insight") == _fold("Morrigan's Insight")
    assert _fold("Oisín’s Oath") == _fold("Oisin's Oath")  # noqa: RUF001


def test_무기_계열_제약을_수집한다(tmp_path: Path) -> None:
    """`weaponTypes`는 `SkillType.X`가 아니라 `["Staff"] = true` 형태다 (#103).

    ⛔ **무기 제약은 빌드의 첫 전제다.** 여기서 틀리면 스킬·전직·아이템이 전부 무효가
    된다 — 실측 2026-08-22: `Crushing Fear`(실제로는 `['Staff']`)를 철퇴 빌드의 핵심으로
    설계했다가 컨셉을 두 번 다시 짰다. `pob_gap`처럼 **조용한 0**이 아니라 **조용한
    거짓 성립**이라 더 나쁘다(§0 ⑩).
    """
    skills = parse_skill_effects(_src(tmp_path))
    assert skills["StaffOnlyPlayer"]["weapon_types"] == ["Staff"]


def test_맨손_허용도_값으로_싣는다(tmp_path: Path) -> None:
    """⚠ `"None"`을 거르면 **맨손 성립 여부를 표현할 수 없다** — 의미 있는 값이다.

    집합 의미라 정렬한다(안정 diff).
    """
    skills = parse_skill_effects(_src(tmp_path))
    assert skills["UnarmedOkPlayer"]["weapon_types"] == ["None", "One Hand Mace"]


def test_제약_없는_스킬은_키를_안_만든다(tmp_path: Path) -> None:
    """⛔ 빈 배열을 넣으면 「제약 없음」과 「PoB가 안 적음」이 섞인다.

    키 자체의 유무로 구별되게 둔다 — 없는 것을 0으로 읽지 않는다는 이 저장소의
    반복 규율과 같은 자리다(#109 계열).
    """
    skills = parse_skill_effects(_src(tmp_path))
    assert "weapon_types" not in skills["NoWeaponRulePlayer"]
