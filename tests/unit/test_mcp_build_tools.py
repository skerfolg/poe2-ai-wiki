"""mcp/tools/build — dict 변환·선별 반환·적법성 어댑터 (PoB 호출 없는 부분)."""

from __future__ import annotations

from typing import Any

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

    def test_아이템의_derived_from은_스펙_전용_키다(self) -> None:
        """#152 — 희귀 슬롯의 출처 도장은 **받되 PoB로는 안 보낸다**.

        훅 게이트와 자동 채움이 읽는 유일한 신호인데 스키마가 거부해, 자동 채움이 첫 칸에
        찍은 도장으로 둘째 칸부터 죽었고 거부문이 안내한 탈출구도 막혀 있었다. 최상위
        `derived_from`과 같은 규약을 아이템에도 둔다 — **모르는 키는 여전히 거부**하되,
        허용 목록이 이 키를 말해야 거부문과 스키마가 어긋나지 않는다.
        """
        item = {
            "slot": "Ring 1",
            "text": "Rarity: RARE\nA\nIron Ring",
            "derived_from": {"tool": "x"},
        }
        spec = spec_from_dict({"class_name": "Witch", "ascendancy": "Witch1", "items": [item]})
        assert spec.items[0].slot == "Ring 1" and not hasattr(spec.items[0], "derived_from")
        with pytest.raises(ValueError, match=r"모르는 키: \['oops'\].*derived_from"):
            spec_from_dict(
                {"class_name": "Witch", "ascendancy": "Witch1", "items": [{**item, "oops": 1}]}
            )


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


def test_illegal_jewel_is_flagged_by_compute_pob() -> None:
    """**주얼도 `items_legal`에 실린다** (#162) — #27이 `items[]`만 고친 자리의 구멍.

    `assemble()`의 검사 대상은 `items + jewels`인데 `_items_legal`은 `items[]`만 돌았다.
    그래서 설계 반복(`compute_pob`) 내내 주얼이 **무검사로** 지나가고 출고에서야 잡힌다 —
    #27이 장비에 대해 고친 것과 **정확히 같은 형태**가 주얼에 남아 있었다.

    실측 2026-09-10: `compute_pob`이 `items_legal: True`를 낸 빌드가 출고에서
    `[Jewel@61419] 24% increased Critical Hit Chance for Attacks → ILLEGAL`로 거부됐다
    (주얼의 그 접사는 6~16만 적법하다). 그 사이 수치가 설계 판단의 근거로 쓰였다.

    ⚠ 슬롯 이름은 `assemble()`과 같은 `Jewel@<소켓 node_id>`여야 한다 — 두 도구가
    다른 이름을 내면 세션이 같은 것을 가리키는지 모른다.
    """
    from pok.mcp.tools.build import _items_legal

    spec = {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "items": [{"slot": "Amulet", "text": "Rarity: RARE\nOK\nAmber Amulet\nItem Level: 80"}],
        "jewels": [
            {
                "socket_node_id": 61419,
                "text": (
                    "Rarity: RARE\nMaelstrom Heart\nEmerald\nItem Level: 82\n"
                    "24% increased Critical Hit Chance for Attacks"
                ),
            }
        ],
    }
    out = _items_legal(spec)
    assert out["items_legal"] is False
    assert out["illegal_items"][0]["slot"] == "Jewel@61419"


def test_legal_jewel_is_not_flagged() -> None:
    """적법한 주얼을 실격으로 말하면 그게 새 오도다 — 양방향으로 정확해야 한다."""
    from pok.mcp.tools.build import _items_legal

    spec = {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "jewels": [
            {
                "socket_node_id": 61419,
                "text": (
                    "Rarity: RARE\nMaelstrom Heart\nEmerald\nItem Level: 82\n"
                    "16% increased Critical Hit Chance for Attacks"
                ),
            }
        ],
    }
    assert _items_legal(spec) == {"items_legal": True, "illegal_items": []}


def test_jewel_spec_accepts_derived_from_stamp() -> None:
    """주얼도 출처 도장을 받는다 (#162) — #152가 `items[]`에만 준 규약의 대칭.

    `optimize_rare(slot="Jewel@<소켓 node_id>")`가 내는 결과에는 `derived_from`이 붙어
    있고, 그것을 스펙의 주얼 항목에 옮겨 적는 것이 정상 사용인데
    `모르는 키: ['derived_from']`로 죽었다(실측 2026-09-10).
    """
    from pok.pob.buildxml import spec_from_dict

    spec = spec_from_dict(
        {
            "class_name": "Mercenary",
            "ascendancy": "Mercenary3",
            "tree_nodes": [61419],
            "jewels": [
                {
                    "socket_node_id": 61419,
                    "derived_from": {"tool": "optimize_rare", "reason": "테스트"},
                    "text": "Rarity: RARE\nOK\nEmerald\nItem Level: 82",
                }
            ],
        },
        validate_catalog=False,
    )
    # 도장은 계보이지 아이템 속성이 아니다 — 받아서 벗겨 낸다(PoB로 안 간다)
    assert len(spec.jewels) == 1
    assert not hasattr(spec.jewels[0], "derived_from")


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


# ── #155 — assemble_pob이 30분을 조용히 태우고 결과를 잃던 자리 ───────────────────


def test_차단될_스펙에는_자동_채움을_돌리지_않는다(monkeypatch: pytest.MonkeyPatch) -> None:
    """#155 — 정적 검사(0.2초)가 자동 채움(슬롯당 수 분) **앞**에 온다.

    순서가 반대라서 어차피 차단될 스펙에 30분을 태운 뒤 거부했고(실측 2026-09-09:
    31분 57초), 클라이언트는 1800초에 포기해 그 결과를 버렸다.
    """
    import pok.engine.rares as rares
    from pok.mcp.tools.build import assemble_pob

    calls: list[str] = []

    def spy(spec: dict[str, Any], slot: str, base: str, weights: dict[str, float]) -> Any:
        calls.append(slot)
        raise RuntimeError("PoB 없음")

    monkeypatch.setattr(rares, "optimize_rare", spy)
    spec = {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "tree_nodes": [],
        "config": {"multiplierRage": 44},  # 공급원 없음 → 차단
        "derived_from": {"items": {"weights": {"TotalDPS": 1.0}}},
        "items": [{"slot": "Ring 1", "text": "Rarity: RARE\nR\nGold Ring\n+10 to Strength"}],
    }
    out = assemble_pob(spec, "test-155")
    assert out["ok"] is False and "실현 불가능" in out["reason"]
    assert calls == [], "차단될 스펙에 optimize_rare를 돌렸다 — 30분이 버려진다"


def test_MCP_경유_자동_채움이_진행을_알린다(monkeypatch: pytest.MonkeyPatch) -> None:
    """#155 — 진행 알림이 없으면 클라이언트는 「no response or progress」로 포기한다.

    서버 래퍼를 실제로 지나는 경로(인메모리 클라이언트)에서 알림이 나오는지 본다 —
    `Context` 주입·스레드→루프 브리지·텔레메트리(비JSON 인자)가 전부 이 길에 있다.
    """
    import asyncio
    import json

    from fastmcp import Client

    import pok.engine.rares as rares
    from pok.mcp.server import mcp

    class _R:
        def __init__(self, text: str) -> None:
            self.text, self.delta = text, {}

    def fake(spec: dict[str, Any], slot: str, base: str, weights: dict[str, float]) -> Any:
        if slot == "Ring 2":
            raise RuntimeError("둘째는 실패 — PoB 전에 거부로 끝나게")
        return _R(f"Rarity: RARE\n산출물\n{base}\n+30 to Strength")

    monkeypatch.setattr(rares, "optimize_rare", fake)
    spec = {
        "class_name": "Mercenary",
        "ascendancy": "Mercenary3",
        "tree_nodes": [],
        "derived_from": {"items": {"weights": {"TotalDPS": 1.0}}},
        "items": [
            {"slot": "Ring 1", "text": "Rarity: RARE\nR\nGold Ring\n+10 to Strength"},
            {"slot": "Ring 2", "text": "Rarity: RARE\nR\nIron Ring\n+10 to Strength"},
        ],
    }
    seen: list[tuple[float, float | None, str | None]] = []

    async def on_progress(progress: float, total: float | None, message: str | None) -> None:
        seen.append((progress, total, message))

    async def main() -> Any:
        async with Client(mcp) as client:
            return await client.call_tool(
                "assemble_pob",
                {"build_spec": spec, "slug": "test-155"},
                progress_handler=on_progress,
                raise_on_error=False,
            )

    result = asyncio.run(main())
    data = result.data if isinstance(result.data, dict) else json.loads(result.content[0].text)
    assert data.get("ok") is False and "autofill_failed" in data, data
    assert seen and any("Ring 1" in (m or "") for _, _, m in seen), seen
