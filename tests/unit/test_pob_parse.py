"""pob/parse — PoB 공유 코드 → 구조 요약 (D30 앵커 수집의 해석기)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from pok.artifacts.store import new_anchor_id, record_anchor
from pok.pob.buildxml import BuildSpec, GemSpec, ItemSpec, SkillGroupSpec, to_xml
from pok.pob.codec import encode
from pok.pob.parse import parse_pob, parse_pob_xml

_SPEC = BuildSpec(
    class_name="Witch",
    ascendancy="Witch1",
    level=91,
    tree_nodes=(46644, 13174),
    skills=(
        SkillGroupSpec(
            gems=(
                GemSpec(
                    gem_id="Metadata/Items/Gems/SkillGemEmberFusillade", name="Ember Fusillade"
                ),
                GemSpec(gem_id="Metadata/Items/Gems/SupportGemExecute", name="Execute III"),
            ),
            slot="Weapon 1",
        ),
    ),
    items=(ItemSpec(slot="Amulet", text="Rarity: RARE\nPok Amulet\nGold Amulet\nItem Level: 80"),),
)


def test_요약_라운드트립_spec_to_xml_to_summary() -> None:
    summary = parse_pob_xml(to_xml(_SPEC))
    assert summary.class_name == "Witch" and summary.level == 91
    assert summary.tree_nodes == (46644, 13174)
    assert summary.skill_groups[0].gems == ("Ember Fusillade", "Execute III")
    assert summary.main_skill_gems == ("Ember Fusillade", "Execute III")
    assert summary.items == tuple([summary.items[0]])
    assert (summary.items[0].rarity, summary.items[0].base) == ("rare", "Gold Amulet")


def test_공유_코드_경유_파싱() -> None:
    summary = parse_pob(encode(to_xml(_SPEC)))
    assert summary.class_name == "Witch" and summary.tree_nodes == (46644, 13174)


def test_손상_코드는_ValueError() -> None:
    with pytest.raises(ValueError):
        parse_pob("not-a-build-code!!!")


def test_앵커_기록은_계보_필수(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "artifacts").mkdir(parents=True)
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="계보"):
        record_anchor("20260802-x", {"pob-code.txt": "abc"}, {}, root=root)
    manifest = {
        "kind": "external-anchor-build",
        "source": {"url": "https://poe.ninja/poe2/pob/26a2b", "site": "poe.ninja"},
    }
    out = record_anchor("20260802-x", {"pob-code.txt": "abc"}, manifest, root=root)
    assert (out / "pob-code.txt").read_text(encoding="utf-8") == "abc"
    assert (out / "manifest.json").exists()
    # id 충돌 회피: 같은 슬러그 재발급 시 -2 접미
    now = datetime(2026, 8, 2, tzinfo=UTC)
    assert new_anchor_id("x", root=root, now=now) == "20260802-x-2"
