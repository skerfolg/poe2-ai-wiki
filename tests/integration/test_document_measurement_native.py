"""Exact XML native observations cannot be applied to an edited document."""

import pytest

from pok.artifacts.store import record_immutable_build
from pok.engine.document_selection import select_effect
from pok.engine.pob_documents import (
    edit_document,
    inspect_document,
    load_document_measurement,
    measure_document,
)
from pok.pob.buildxml import BuildSpec, GemSpec, SkillGroupSpec, to_xml
from pok.pob.versions import find_luajit, resolve_snapshot


def ready():
    try:
        find_luajit()
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


pytestmark = pytest.mark.skipif(not ready(), reason="LuaJIT or pinned PoB unavailable")


def test_measure_edit_remeasure_keeps_each_observation_on_its_document(tmp_path):
    xml = to_xml(
        BuildSpec(
            class_name="Sorceress",
            ascendancy="Sorceress1",
            level=90,
            skills=(
                SkillGroupSpec(
                    gems=(
                        GemSpec(
                            gem_id="Metadata/Items/Gems/SkillGemSpark",
                            name="Spark",
                            stat_set_index=1,
                        ),
                    )
                ),
            ),
        )
    )
    stored = record_immutable_build(
        "original-doc", {"source.xml": xml.encode()}, {"kind": "pob-document"}, root=tmp_path
    )
    reference = {
        "artifact_id": stored["artifact_id"],
        "name": "source.xml",
        "sha256": stored["files"]["source.xml"]["sha256"],
    }
    before = measure_document(reference, stats=[], use_cache=False, root=tmp_path)
    assert before["meta"]["nativeSelection"]["actual"]["stat_set_index"] == 1
    inspected = inspect_document(reference, tag="StatSetIndex", root=tmp_path)
    target = inspected["nodes"][0]
    child = edit_document(
        reference,
        inspected["xml_revision"],
        [
            {
                "path": target["path"],
                "tag": "StatSetIndex",
                "attribute": "index",
                "expected_raw_value": "1",
                "value": "2",
            }
        ],
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="another XML"):
        load_document_measurement(
            before["document_measurement_ref"], child["xml_ref"], root=tmp_path
        )
    after = measure_document(child["xml_ref"], stats=[], use_cache=False, root=tmp_path)
    assert after["meta"]["nativeSelection"]["actual"]["stat_set_index"] == 2
    assert (
        load_document_measurement(
            after["document_measurement_ref"], child["xml_ref"], root=tmp_path
        )["binding"]
        == "verified_exact_xml_subject"
    )
    assert (
        load_document_measurement(before["document_measurement_ref"], reference, root=tmp_path)[
            "measurement"
        ]["meta"]["nativeSelection"]["actual"]["stat_set_index"]
        == 1
    )


@pytest.mark.parametrize("inbuilt", [False, True])
def test_observed_effect_and_mode_selection_is_verified_after_native_remeasurement(
    tmp_path, inbuilt
):
    if inbuilt:
        gems = (
            GemSpec(
                gem_id="Metadata/Items/Gems/SkillGemWindDancer",
                name="Wind Dancer",
                stat_set_index=1,
                stages=3,
            ),
        )
        active, mode, effect = 2, 1, "TriggeredWindDancerPlayer"
        character, ascendancy = "Monk", "Monk1"
    else:
        gems = (
            GemSpec(gem_id="Metadata/Items/Gems/SkillGemUnleashSupport", name="Unleash", level=1),
            GemSpec(gem_id="Metadata/Items/Gems/SkillGemSpark", name="Spark", stat_set_index=1),
        )
        active, mode, effect = 1, 2, "SparkPlayer"
        character, ascendancy = "Sorceress", "Sorceress1"
    xml = to_xml(
        BuildSpec(
            class_name=character,
            ascendancy=ascendancy,
            level=90,
            skills=(SkillGroupSpec(gems=gems),),
        )
    )
    stored = record_immutable_build(
        "select-doc", {"source.xml": xml.encode()}, {"kind": "pob-document"}, root=tmp_path
    )
    reference = {
        "artifact_id": stored["artifact_id"],
        "name": "source.xml",
        "sha256": stored["files"]["source.xml"]["sha256"],
    }
    before = measure_document(reference, stats=[], use_cache=False, root=tmp_path)
    result = select_effect(
        reference,
        before["xml_revision"],
        before["document_measurement_ref"],
        active,
        mode,
        use_cache=False,
        root=tmp_path,
    )
    assert result["status"] == "native_selection_matched", result
    actual = result["measurement"]["meta"]["nativeSelection"]["actual"]
    assert actual["effect_id"] == effect
    assert actual["stat_set_index"] == mode
    assert actual["gem_index"] == (1 if inbuilt else 2)
    assert result["execution_identity"] == "not_verified"
    assert result["game_feasibility"] == "not_checked"
