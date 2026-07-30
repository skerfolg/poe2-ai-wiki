"""mcp/tools/build — dict 변환·선별 반환·적법성 어댑터 (PoB 호출 없는 부분)."""

from __future__ import annotations

import pytest

from pok.mcp.tools.build import check_item_legality
from pok.pob.buildxml import spec_from_dict


class TestSpecFromDict:
    def test_전체_필드_왕복(self) -> None:
        spec = spec_from_dict(
            {
                "class_name": "Sorceress",
                "ascendancy": "Sorceress1",
                "level": 92,
                "tree_nodes": [4739, "22419"],
                "skills": [
                    {
                        "gems": [
                            {
                                "gem_id": "Metadata/Items/Gems/SkillGemSpark",
                                "name": "Spark",
                                "level": 20,
                            }
                        ]
                    }
                ],
                "items": [{"slot": "Ring 1", "text": "Rarity: RARE\nA\nIron Ring"}],
                "config": {"enemyIsBoss": True},
            }
        )
        assert spec.level == 92
        assert spec.tree_nodes == (4739, 22419)
        assert spec.skills[0].gems[0].name == "Spark"
        assert spec.items[0].slot == "Ring 1"
        assert spec.config == (("enemyIsBoss", True),)

    def test_모르는_키는_거부(self) -> None:
        with pytest.raises(ValueError, match="모르는 키"):
            spec_from_dict({"class_name": "Sorceress", "ascendancy": "Sorceress1", "oops": 1})

    def test_기본값(self) -> None:
        spec = spec_from_dict({"class_name": "Witch", "ascendancy": "Witch1"})
        assert spec.level == 90
        assert spec.tree_nodes == ()


def test_check_item_legality_어댑터() -> None:
    out = check_item_legality(
        "Rarity: RARE\nPok Ring\nIron Ring\nItem Level: 80\nAdds 1 to 3 Cold damage to Attacks"
    )
    assert out["legal"] is True
    assert out["lines"][0]["status"] in ("LEGAL", "CONDITIONAL")
