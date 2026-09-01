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
                                # 스파크는 모드가 둘("Base"/"Cold-Infused")이라
                                # 선언이 필요하다 — 안 주면 조용히 1번(#52)
                                "stat_set_index": 1,
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


def test_compute_pob_reports_item_legality_every_call() -> None:
    """`compute_pob`이 **장비 실재 여부를 매번** 말한다 (백로그 #27).

    검사기는 `assemble()`에만 걸려 있었는데 설계 반복은 `compute_pob`으로 한다 —
    즉 **검사가 걸린 도구를 정작 설계 중에는 안 썼다.** 실측 2026-08-09: 그렇게
    20여 회 측정한 빌드를 `assemble()`에 넘기자 **10슬롯 중 4개가 실격**이었고,
    그 위에서 나온 수치가 설계 근거로 쓰였다.

    아래 두 가짜는 그 사고에서 실제로 나온 것이다 — 존재하지 않는 베이스와
    실재하지 않는 문구.
    """
    from pok.mcp.tools.build import _items_legal

    spec = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "items": [
            {
                "slot": "Gloves",
                "text": "Rarity: RARE\nFake\nSilk Gloves\nItem Level: 80\n+40% to Fire Resistance",
            },
        ],
    }
    out = _items_legal(spec)
    assert out["items_legal"] is False
    assert out["illegal_items"][0]["slot"] == "Gloves"
    assert any("Silk Gloves" in r for r in out["illegal_items"][0]["reasons"])


def test_legal_gear_is_not_flagged() -> None:
    """정상 장비를 실격으로 말하면 그게 새 오도다 — 게이트는 양방향으로 정확해야 한다."""
    from pok.mcp.tools.build import _items_legal

    spec = {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "items": [{"slot": "Amulet", "text": "Rarity: RARE\nOK\nAmber Amulet\nItem Level: 80"}],
    }
    assert _items_legal(spec) == {"items_legal": True, "illegal_items": []}


def test_req_shortfall_rides_on_every_return() -> None:
    """요구 속성 미달은 **1회성 경고여선 안 된다** (백로그 #29).

    실측 2026-08-09: 경고가 한 번만 나와 20여 회 측정 동안 사라졌다. 한 번만 말하는
    경고는 문서와 동급이다(철칙 5).
    """
    from types import SimpleNamespace

    from pok.mcp.tools.build import _pick

    result = SimpleNamespace(
        stats={"CombinedDPS": 100.0, "ReqStr": 120.0, "Str": 20.0},
        is_tree_legal=True,
        pruned_nodes=(),
        meta={},
        is_item_sockets_legal=True,
        item_socket_problems=(),
        item_socket_warnings=(),
        items=(),
        dropped_items=(),  # #135 — 반환이 이 축도 싣는다
    )
    out = _pick(result, ["CombinedDPS"])  # type: ignore[arg-type]
    assert out["req_shortfall"] == {"str": 100.0}
    # 이름이 축을 정직하게 말해야 한다 — 옛 `tree_legal`은 장비 실격을 가렸다
    assert "tree_connected" in out and "tree_legal" not in out
    # 룬 소켓 한도도 **매 반환에** 실린다 (#120) — `items_legal`은 소켓 수를 안 본다
    assert out["item_sockets_legal"] is True
    assert "item_socket_problems" not in out, "정상일 땐 안 싣는다(소음 방지)"
