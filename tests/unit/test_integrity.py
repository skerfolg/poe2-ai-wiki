"""스펙 자체의 설계 무결성 — 적법한데 **애초에 빌드가 아닌 것** (백로그 #58 ①).

한 세션이 같은 실패를 3연속했고 **세 번 다 도구가 통과시켰다**. 지금까지의 강제
지점은 전부 "지금 적법한가"를 봤기 때문이다. 실측 2026-08-11: 주력기가 스펙에 없는
채로 3회차가 돌았고 `CombinedDPS` 2,562 → 주력기 투입 시 **24,436**.
"""

from __future__ import annotations

import pytest

from pok.engine.integrity import _record_kind, spec_integrity

COEA = {
    "gem_id": "Metadata/Items/Gems/SkillGemCastOnElementalAilment",
    "name": "Cast on Elemental Ailment",
}
SPARK = {"gem_id": "Metadata/Items/Gems/SkillGemSpark", "name": "Spark", "stat_set_index": 1}
UNLEASH = {"gem_id": "Metadata/Items/Gems/SkillGemUnleashSupport", "name": "Unleash"}


def test_main_group_without_a_damage_skill_is_reported() -> None:
    problems = spec_integrity({"skills": [{"gems": [COEA, UNLEASH]}]})
    assert any("딜을 낼 스킬이 없다" in p for p in problems)
    assert any("24,436" in p for p in problems), "실측을 함께 줘야 크기를 안다"


def test_unconnected_trigger_group_is_reported() -> None:
    """트리거 젬만 든 그룹은 정신력만 점유하고 아무것도 하지 않는다."""
    problems = spec_integrity(
        {"skills": [{"gems": [SPARK]}, {"gems": [COEA]}], "main_socket_group": 1}
    )
    assert any("skills[1]" in p and "발동될 스킬이 없다" in p for p in problems)
    assert not any("skills[0]" in p for p in problems), "정상 그룹까지 짚으면 안 읽힌다"


def test_main_active_skill_pointing_at_a_meta_gem_is_reported() -> None:
    """The verdict follows native effect identity, not a guessed gem slot."""
    native = {
        "format": "pok.native-selection.v1",
        "status": "observed",
        "actual": {
            "selected": True,
            "group_index": 1,
            "active_index": 1,
            "gem_index": 1,
            "effect_id": "MetaCastOnElementalAilmentPlayer",
            "meta_container": True,
        },
    }
    problems = spec_integrity(
        {"skills": [{"gems": [COEA, SPARK], "main_active_skill": 1}]}, native_selection=native
    )
    assert any("메타 컨테이너" in p and "MetaCastOnElementalAilmentPlayer" in p for p in problems)


def test_leading_support_never_becomes_a_false_selected_gem_verdict():
    spec = {"skills": [{"gems": [UNLEASH, SPARK], "main_active_skill": 1}]}
    assert spec_integrity(spec) == ()  # No observation is not permission to guess.
    native = {
        "format": "pok.native-selection.v1",
        "status": "observed",
        "actual": {
            "selected": True,
            "group_index": 1,
            "active_index": 1,
            "gem_index": 2,
            "effect_id": "SparkPlayer",
            "meta_container": False,
        },
    }
    assert spec_integrity(spec, native_selection=native) == ()
    native["actual"]["active_index"] = 2
    problems = spec_integrity(spec, native_selection=native)
    assert any("요청과 PoB 실제" in row for row in problems)


def test_unobserved_or_untrusted_format_does_not_invent_an_ordinal_diagnosis():
    spec = {"skills": [{"gems": [UNLEASH, SPARK], "main_active_skill": 1}]}
    assert spec_integrity(spec, native_selection={"actual": {"meta_container": True}}) == ()


def test_out_of_range_main_socket_group_is_reported() -> None:
    problems = spec_integrity({"skills": [{"gems": [SPARK]}], "main_socket_group": 3})
    assert any("main_socket_group=3" in p for p in problems)


def test_a_normal_build_is_silent() -> None:
    """게이트가 정상을 막으면 신호가 죽는다 (§0 ⑤) — 경고도 마찬가지다."""
    assert spec_integrity({"skills": [{"gems": [SPARK, UNLEASH]}]}) == ()
    # 트리거 그룹이라도 **발동될 스킬이 함께 있으면** 조용하다
    assert not any(
        "발동될 스킬이 없다" in p
        for p in spec_integrity({"skills": [{"gems": [COEA, SPARK], "main_active_skill": 2}]})
    )


def test_empty_spec_is_reported() -> None:
    assert spec_integrity({"skills": []})[0].startswith("스킬 그룹이 하나도 없다")


@pytest.mark.parametrize(
    "name,gem_id",
    [
        ("Wind Dancer", "Metadata/Items/Gems/SkillGemWindDancer"),
        ("Escape Shot", "Metadata/Items/Gems/SkillGemEscapeShot"),
    ],
)
def test_inbuilt_trigger_does_not_need_an_external_payload(name, gem_id):
    gem = {"name": name, "gem_id": gem_id}
    assert spec_integrity({"skills": [{"gems": [SPARK]}, {"gems": [gem]}]}) == ()
    assert spec_integrity({"skills": [{"gems": [gem]}]}) == ()
    # Native identity wins over a stale/translated display name.
    assert spec_integrity({"skills": [{"gems": [{**gem, "name": "renamed"}]}]}) == ()


def test_explicit_meta_marker_wins_over_an_ancillary_inbuilt_effect():
    assert (
        _record_kind(
            frozenset({"meta", "trigger"}),
            [
                {"types": ["Meta"]},
                {"types": ["InbuiltTrigger", "Attack"]},
            ],
        )
        == "meta"
    )
    assert _record_kind(frozenset({"trigger"}), [{"types": ["Meta"]}]) == "meta"
    assert (
        _record_kind(
            frozenset({"trigger"}),
            [
                {"support": True, "types": ["InbuiltTrigger"]},
            ],
        )
        == "meta"
    )
    assert _record_kind(frozenset({"attack"}), [{"types": ["Attack", "Triggerable"]}]) == "active"


def test_public_calculation_boundary_preserves_real_empty_meta_warning(monkeypatch, tmp_path):
    """Stub native arithmetic only; keep the actual result diagnostic path."""
    import asyncio

    from fastmcp import Client, FastMCP

    from pok.artifacts import tool_results
    from pok.mcp import server
    from pok.mcp.tools import build
    from pok.pob.runner import PobResult

    api = FastMCP("inbuilt-trigger-diagnostic-test")
    monkeypatch.setattr(server, "mcp", api)
    monkeypatch.setattr(server, "_TOOL_PARAMS", {})
    monkeypatch.setattr(server, "observe_sources", lambda: {})
    monkeypatch.setattr(tool_results, "artifacts_dir", lambda root=None: tmp_path / "artifacts")
    monkeypatch.setattr(build, "_compute", lambda spec: PobResult({"Life": 100}, {}, (), (), False))
    monkeypatch.setattr(build, "_procedure_refusal", lambda spec: None)
    server.tool(build.compute_pob)

    async def exercise():
        async with Client(api) as client:
            for gem in (
                {"name": "Wind Dancer", "gem_id": "Metadata/Items/Gems/SkillGemWindDancer"},
                {"name": "Escape Shot", "gem_id": "Metadata/Items/Gems/SkillGemEscapeShot"},
                COEA,
            ):
                response = await client.call_tool(
                    "compute_pob",
                    {
                        "build_spec": {
                            "class_name": "Monk",
                            "ascendancy": "Monk1",
                            "level": 90,
                            "skills": [{"gems": [SPARK]}, {"gems": [gem]}],
                        },
                        "stats": ["Life"],
                    },
                )
                warnings = response.data.get("design_warnings", [])
                assert any("발동될 스킬이 없다" in row for row in warnings) == (gem == COEA)
                assert response.data["stats"]["Life"] == 100

    asyncio.run(exercise())
