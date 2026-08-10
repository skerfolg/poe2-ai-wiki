"""한 스킬의 **모드(statSet)** 선택 — 안 주면 조용히 1번이다 (백로그 #52, 2026-08-10).

구형 번개는 `[1] Ball Lightning` · `[2] Fire-Infused` · `[3] Ignited Ground` 셋이고
셋이 사실상 다른 스킬이다. 지정하지 않으면 PoB가 1번으로 재는데 조립은 정상으로
보인다 — 보고자의 장비 갖춘 빌드에서 `WithIgniteDPS` 2,387 vs **47,329**(20배).

⚠ 이 파일이 지키는 두 번째 것: **속성 형식은 PoB 쪽 죽은 코드다.**
`SkillsTab.lua:354-355`가 `statSetIndex` 속성을 파싱하지만 370-371행이 즉시 `{}`로
덮어쓴다. 자식 원소로 내지 않으면 조용히 무시되고 파트 1·2·3이 같은 값이 된다.
"""

from __future__ import annotations

import pytest

from pok.pob.buildxml import spec_from_dict, to_xml
from pok.pob.catalog import stat_sets
from pok.pob.versions import resolve_snapshot

BALL_LIGHTNING = "Metadata/Items/Gems/SkillGemBallLightning"
BASE = {"class_name": "Sorceress", "ascendancy": "Sorceress1", "level": 90}


def _pob_ready() -> bool:
    try:
        resolve_snapshot()
    except (FileNotFoundError, RuntimeError):
        return False
    return True


needs_pob_snapshot = pytest.mark.skipif(not _pob_ready(), reason="external/pob 스냅샷 없음")


@needs_pob_snapshot
def test_stat_sets_are_read_from_pob_source() -> None:
    effect, labels = stat_sets(BALL_LIGHTNING)
    assert effect == "BallLightningPlayer", "선택 XML의 키는 grantedEffectId다"
    assert labels == ("Ball Lightning", "Fire-Infused", "Ignited Ground")


@needs_pob_snapshot
def test_single_mode_skill_has_one_label() -> None:
    """모드가 하나면 게이트가 걸리면 안 된다 — 111개 젬만 해당한다(§0 ⑤)."""
    _, labels = stat_sets("Metadata/Items/Gems/SkillGemFlameblast")
    assert labels == ("Flameblast",)


@needs_pob_snapshot
def test_multi_mode_gem_without_a_choice_is_rejected() -> None:
    with pytest.raises(ValueError) as err:
        spec_from_dict(
            {**BASE, "skills": [{"gems": [{"gem_id": BALL_LIGHTNING, "name": "Ball Lightning"}]}]}
        )
    msg = str(err.value)
    assert "모드가 3개" in msg and "1번으로 계산" in msg
    assert "Ignited Ground" in msg, "어느 모드가 있는지 안 알려주면 고를 수 없다"


@needs_pob_snapshot
def test_choice_is_emitted_as_child_elements_not_attributes() -> None:
    """속성으로 내면 PoB가 조용히 무시한다 — 자식 원소인지까지 잠근다."""
    spec = spec_from_dict(
        {
            **BASE,
            "skills": [
                {
                    "gems": [
                        {"gem_id": BALL_LIGHTNING, "name": "Ball Lightning", "stat_set_index": 3}
                    ]
                }
            ],
        }
    )
    xml = to_xml(spec)
    assert '<StatSetIndex grantedEffect="BallLightningPlayer" index="3"/>' in xml
    assert '<StatSetCalcsIndex grantedEffect="BallLightningPlayer" index="3"/>' in xml
    assert "statSetIndex=" not in xml, "속성 형식은 PoB의 죽은 코드다"


@needs_pob_snapshot
def test_unspecified_gem_stays_self_closing() -> None:
    """모드가 하나인 젬은 XML이 그대로여야 한다 — 회귀 폭을 좁힌다."""
    spec = spec_from_dict(
        {
            **BASE,
            "skills": [
                {
                    "gems": [
                        {
                            "gem_id": "Metadata/Items/Gems/SkillGemFlameblast",
                            "name": "Flameblast",
                            "stages": 10,
                        }
                    ]
                }
            ],
        }
    )
    assert "<StatSetIndex" not in to_xml(spec)
