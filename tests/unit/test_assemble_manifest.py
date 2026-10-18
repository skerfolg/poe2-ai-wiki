"""조립 manifest — 대리 측정 주입의 계보와 함정 경고 (#3)."""

from __future__ import annotations

import json
from dataclasses import replace
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest

from pok.artifacts import store
from pok.engine.assemble import assemble
from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec, spec_from_dict
from pok.pob.runner import PobResult


@pytest.fixture
def recorded_assembly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Mock:
    """PoB 대신 고정 측정값을 쓰되 산출물은 실제 저장 경로로 기록한다."""
    import pok.engine.assemble as module

    run = Mock(return_value=PobResult({}, {}, (), (), False))
    checker = Mock()
    checker.check.return_value = SimpleNamespace(is_legal=True, errors=(), verdicts=())
    monkeypatch.setattr(module, "run_build", run)
    monkeypatch.setattr(module, "ItemLegalityChecker", lambda _: checker)
    monkeypatch.setattr(module, "to_xml", lambda _: "<PathOfBuilding2/>")
    monkeypatch.setattr(module, "pinned_commit", lambda: "test-pob")
    monkeypatch.setattr(module, "spec_integrity", lambda _: ())
    monkeypatch.setattr(module, "find_design_doc", lambda _: None)
    monkeypatch.setattr(module, "record_build", partial(store.record_build, root=tmp_path))
    monkeypatch.setattr(module, "new_build_id", partial(store.new_build_id, root=tmp_path))
    monkeypatch.setattr(module, "find_by_hash", partial(store.find_by_hash, root=tmp_path))
    return run


def test_saved_spec_preserves_choices_settings_and_provenance(recorded_assembly: Mock) -> None:
    source: dict[str, Any] = {
        "class_name": "Witch",
        "ascendancy": "Witch1",
        "level": "92",
        "tree_nodes": ["4739", 22419],
        "attribute_choices": {4739: "int", "22419": "힘"},
        "main_socket_group": 2,
        "config": {"conditionLowLife": True, "customMods": "+10 to Strength\n+20 to Dexterity"},
        "skills": [
            {"gems": [{"gem_id": "test-disabled", "name": "보조", "enabled": False}]},
            {
                "slot": "Helmet",
                "gems": [
                    {
                        "gem_id": "test-main",
                        "name": "주력",
                        "level": 17,
                        "quality": 12,
                        "stages": 3,
                        "stat_set_index": 2,
                        "corrupted": True,
                        "corrupt_level": 1,
                    }
                ],
            },
        ],
        "items": [
            {
                "slot": "Ring 1",
                "text": "Rarity: RARE\n산출물\nIron Ring",
                "substitutes": ("+30 to maximum Life",),
                "derived_from": {"tool": "optimize_rare", "why": "선택 보존"},
            }
        ],
        "jewels": [
            {
                "socket_node_id": 61419,
                "text": "Rarity: RARE\n주얼\nEmerald",
                "allocates": [42],
                "derived_from": {"tool": "optimize_rare"},
            }
        ],
        "derived_from": {"items": {"tool": "optimize_items", "weights": {"Life": 1.0}}},
        "restored_from": {"build_id": "original"},
    }
    spec = spec_from_dict(source, validate_catalog=False)
    built = assemble(spec, "resume", spec_data=source)
    saved = json.loads((built.path / "spec.json").read_text(encoding="utf-8"))
    restored = spec_from_dict(saved, validate_catalog=False)
    assert recorded_assembly.call_args.args[0] == spec
    assert restored.config == spec.config and restored.attribute_choices == spec.attribute_choices
    assert restored.skills == spec.skills
    assert saved["level"] == 92 and saved["tree_nodes"] == [4739, 22419]
    assert saved["skills"][0]["gems"][0]["level"] == 20, "생략된 런타임 기본값도 보존"
    assert saved["items"][0]["substitutes"] == ["+30 to maximum Life"]
    assert saved["items"][0]["derived_from"] == source["items"][0]["derived_from"]
    assert saved["jewels"][0]["derived_from"] == source["jewels"][0]["derived_from"]
    assert saved["derived_from"] == source["derived_from"]
    assert saved["restored_from"] == source["restored_from"]
    assert source["level"] == "92" and "level" not in source["skills"][0]["gems"][0]


def test_saved_spec_without_source_is_reusable(recorded_assembly: Mock) -> None:
    spec = BuildSpec(
        class_name="Sorceress",
        ascendancy="Sorceress1",
        tree_nodes=(4739,),
        attribute_choices=((4739, "int"),),
        config=(("conditionLowLife", True),),
        skills=(SkillGroupSpec(gems=(GemSpec("test-gem", "테스트", level=16),)),),
    )
    built = assemble(spec, "resume-defaults")
    saved = json.loads((built.path / "spec.json").read_text(encoding="utf-8"))
    assert spec_from_dict(saved, validate_catalog=False) == spec
    assert saved["level"] == 90 and saved["main_socket_group"] == 1
    assert saved["config"] == {"conditionLowLife": True}
    assert saved["attribute_choices"] == {"4739": "int"}


def test_exploration_keeps_legality_separate_from_readiness(recorded_assembly: Mock) -> None:
    built = assemble(BuildSpec(class_name="Mercenary", ascendancy="Mercenary3"), "exploration")
    manifest = json.loads((built.path / "manifest.json").read_text(encoding="utf-8"))
    validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
    assert built.is_legal and manifest["legal"] is True
    assert manifest["purpose"] == validation["purpose"] == "exploration"
    assert built.optimization_readiness == manifest["optimization_readiness"]
    assert validation["optimization_readiness"]["status"] == "not_ready"
    assert validation["optimization_readiness"]["recommendation_ready"] is False


def test_final_without_contract_is_refused_before_calculation(recorded_assembly: Mock) -> None:
    from pok.engine.optimization_readiness import OptimizationNotReadyError

    with pytest.raises(OptimizationNotReadyError) as caught:
        assemble(
            BuildSpec(class_name="Mercenary", ascendancy="Mercenary3"),
            "final",
            purpose="recommendation",
        )
    assert caught.value.report["blockers"][0]["code"] == "contract_missing"
    recorded_assembly.assert_not_called()


def test_prior_partial_search_history_does_not_pass_larger_recommendation(
    recorded_assembly: Mock,
) -> None:
    from copy import deepcopy

    from pok.engine.assemble import _runtime_spec_data
    from pok.engine.optimization_readiness import (
        OptimizationNotReadyError,
        measured_review_receipt,
    )
    from pok.engine.provenance import missing_procedures, stamp

    spec = BuildSpec(
        class_name="Mercenary",
        ascendancy="Mercenary3",
        items=(ItemSpec(slot="Ring 1", text="Original"),),
    )
    source = _runtime_spec_data(spec)
    source["derived_from"] = {
        "items": stamp(
            source,
            "items",
            tool="optimize_items",
            search_evidence={
                "scope": {"slots": ["Ring 1", "Ring 2", "Amulet"]},
                "settings": {"max_rounds": 3},
                "termination": {"reason": "no_positive_candidate", "converged": True},
                "unresolved": [],
            },
        )
    }
    variant = deepcopy(source)
    variant["items"][0]["text"] = "Measured alternative"
    source["derived_from"]["items"] = measured_review_receipt(
        source,
        {"ring": variant},
        {"ring": {"Life": 110}},
        component="items",
        stats=["Life"],
        baseline_stats={"Life": 100},
        unresolved=[],
    )
    source["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "items": {
                "scope": {
                    "slots": [
                        "Weapon 1",
                        "Helmet",
                        "Gloves",
                        "Boots",
                        "Belt",
                        "Amulet",
                        "Ring 1",
                        "Ring 2",
                        "Body Armour",
                    ]
                },
                "allowed_termination_reasons": ["variants_evaluated"],
            },
        },
    }
    assert missing_procedures(source) == []
    with pytest.raises(OptimizationNotReadyError) as caught:
        assemble(spec, "old-three-is-not-nine", spec_data=source, purpose="recommendation")
    assert "scope_missing" in {row["code"] for row in caught.value.report["blockers"]}
    recorded_assembly.assert_not_called()
    source["optimization_contract"]["required_components"]["items"]["scope"]["slots"] = ["Ring 1"]
    built = assemble(spec, "current-one-reviewed", spec_data=source, purpose="recommendation")
    saved = json.loads((built.path / "spec.json").read_text(encoding="utf-8"))
    manifest = json.loads((built.path / "manifest.json").read_text(encoding="utf-8"))
    assert saved["derived_from"] == source["derived_from"]
    assert manifest["optimization_readiness"]["status"] == "ready"
    assert not manifest.get("skipped_procedures")


@pytest.mark.parametrize("with_exception", [False, True])
def test_ready_recommendation_persists_its_contract_and_machine_status(
    recorded_assembly: Mock,
    with_exception: bool,
) -> None:
    from pok.engine.assemble import _runtime_spec_data
    from pok.engine.optimization_readiness import optimization_readiness
    from pok.engine.provenance import stamp

    spec = BuildSpec(class_name="Mercenary", ascendancy="Mercenary3")
    source = _runtime_spec_data(spec)
    source["optimization_contract"] = {
        "version": 1,
        "required_components": {
            "tree": {
                "scope": {"candidate_nodes": [1, 2]},
                "allowed_termination_reasons": ["no_improvement"],
            }
        },
    }
    source["derived_from"] = {
        "tree": stamp(
            source,
            "tree",
            tool="evaluate_tree",
            search_evidence={
                "scope": {"candidate_nodes": [1, 2]},
                "settings": {},
                "termination": {"reason": "no_improvement", "converged": True},
                "unresolved": [],
            },
        )
    }
    if with_exception:
        source["optimization_contract"]["required_components"]["tree"]["scope"][
            "candidate_nodes"
        ].append(3)
        issue = optimization_readiness(source)["blockers"][0]
        source["optimization_contract"]["exceptions"] = [
            {"issue_id": issue["issue_id"], "reason": "This specific candidate is excluded."}
        ]
    built = assemble(spec, "ready-final", spec_data=source, purpose="recommendation")
    saved = json.loads((built.path / "spec.json").read_text(encoding="utf-8"))
    validation = json.loads((built.path / "validation.json").read_text(encoding="utf-8"))
    manifest = json.loads((built.path / "manifest.json").read_text(encoding="utf-8"))
    assert saved["optimization_contract"] == source["optimization_contract"]
    status = "ready_with_exceptions" if with_exception else "ready"
    assert validation["optimization_readiness"]["status"] == status
    if with_exception:
        limitation = built.optimization_readiness["qualification"]["known_limitations"][0]
        assert limitation["expected"] == [3]
    assert manifest["optimization_readiness"] == built.optimization_readiness
    assert manifest["purpose"] == "recommendation"
    with pytest.raises(ValueError, match="strict=True"):
        assemble(spec, "invalid-final", spec_data=source, purpose="recommendation", strict=False)


@pytest.mark.parametrize("changed", ["level", "items", "config"])
def test_stale_source_is_rejected_before_measurement(recorded_assembly: Mock, changed: str) -> None:
    source = {"class_name": "Witch", "ascendancy": "Witch1"}
    spec = spec_from_dict(source, validate_catalog=False)
    replacements = {
        "level": 95,
        "items": (ItemSpec("Ring 1", "Rarity: RARE\nNew\nIron Ring"),),
        "config": (("conditionLowLife", True),),
    }
    with pytest.raises(ValueError, match=f"spec_data.*{changed}"):
        assemble(replace(spec, **{changed: replacements[changed]}), "stale", spec_data=source)
    recorded_assembly.assert_not_called()


def test_saved_spec_contains_auto_filled_item(recorded_assembly: Mock) -> None:
    from pok.engine.autofill import autofill_rares

    source = {
        "class_name": "Witch",
        "ascendancy": "Witch1",
        "items": [{"slot": "Ring 1", "text": "Rarity: RARE\nBefore\nIron Ring"}],
        "derived_from": {"items": {"weights": {"Life": 1.0}}},
    }
    replacement = "Rarity: RARE\nAfter\nIron Ring\n+30 to maximum Life"
    filled, report = autofill_rares(source, Mock(return_value=SimpleNamespace(text=replacement)))
    assert report.ran
    spec = spec_from_dict(filled, validate_catalog=False)
    built = assemble(spec, "resume-autofill", spec_data=filled)
    saved = json.loads((built.path / "spec.json").read_text(encoding="utf-8"))
    assert saved["items"][0]["text"] == recorded_assembly.call_args.args[0].items[0].text
    assert saved["items"][0]["text"] == replacement
    assert saved["items"][0]["derived_from"] == {"tool": "optimize_rare", "via": "autofill"}
    assert source["items"][0]["text"] != replacement


def test_rune_substitution_warns_about_lost_amplification() -> None:
    """주입 줄은 룬으로 인식되지 않아 증폭이 **안 곱해진다** (#3 확장).

    실측 2026-08-09(`Greater Body Rune` 2개 · 룬 효과 +200%):
    정본 표기 ES **+300** vs `substitutes` 주입 **+100** — 3배 과소다.
    문서 규율로 두면 안 지켜지므로 조립이 자동으로 붙인다(철칙 5).
    """
    from pok.engine.assemble import _rune_amplification_warning
    from pok.pob.buildxml import BuildSpec, ItemSpec

    runed = ItemSpec(
        slot="Weapon 1",
        text="Rarity: RARE\nProbe\nAttuned Wand\n200% increased effect of Socketed Runes",
        substitutes=("+50 to maximum Energy Shield",),
    )
    warning = _rune_amplification_warning(
        BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(runed,))
    )
    assert "안 곱해진다" in warning and "Weapon 1(+200%)" in warning

    # 게이트는 양방향 — 룬 효과가 없거나 주입이 없으면 아무 말도 하지 않는다
    plain = ItemSpec(slot="Weapon 1", text="Rarity: RARE\nProbe\nAttuned Wand",
                     substitutes=("+50 to maximum Energy Shield",))  # fmt: skip
    assert not _rune_amplification_warning(
        BuildSpec(class_name="Sorceress", ascendancy="Sorceress1", items=(plain,))
    )
    assert not _rune_amplification_warning(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            items=(ItemSpec(slot="Weapon 1", text=runed.text),),
        )
    )
