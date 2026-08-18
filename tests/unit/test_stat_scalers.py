"""주 배율기 자동 감지 — 축을 모르면 노력량이 결과에 반영되지 않는다 (철칙 5).

실측 2026-08-18: 「100 생명력당」 줄을 셋 가진 빌드에서 생명력 2.53배가 DPS 3.38배가
됐는데, 같은 자리에서 「주문 피해 +100%」는 1.14배였다. 한 세션이 그 사실을 알아내는
데 하루를 쓰고 트리를 다섯 번 갈아엎었다. 그래서 묻지 않아도 반환값에 나오게 한다.
"""

from __future__ import annotations

from pok.mcp.tools.build import _stat_scalers

RATHPITH = (
    "Rarity: UNIQUE\nRathpith Globe\nSacred Focus\nImplicits: 0\n"
    "Non-Channelling Spells deal 7% increased Damage per 100 maximum Life\n"
    "Non-Channelling Spells have 4% increased Critical Hit Chance per 100 maximum Life\n"
    "Non-Channelling Spells have 3% increased Magnitude of Ailments per 100 maximum Life\n"
)
PLAIN = "Rarity: RARE\nSome Ring\nGold Ring\nImplicits: 0\n+161 to maximum Life\n"


def test_detects_the_axis_and_counts_the_lines() -> None:
    out = _stat_scalers({"items": [{"slot": "Weapon 2", "text": RATHPITH}]})
    assert out["primary"] == "Life"
    assert len(out["axes"]["Life"]) == 3
    assert all(h["per"] == 100 for h in out["axes"]["Life"])
    assert "주 배율기" in out["note"]


def test_flat_life_is_not_a_scaler() -> None:
    """+161 생명력은 스택 요소지 **배율기**가 아니다 — 섞으면 신호가 죽는다."""
    assert _stat_scalers({"items": [{"slot": "Ring 1", "text": PLAIN}]}) == {}


def test_reads_jewels_too() -> None:
    out = _stat_scalers({"jewels": [{"socket_node_id": 123, "text": RATHPITH}]})
    assert out["primary"] == "Life"
    assert out["axes"]["Life"][0]["slot"] == "Jewel@123"


def test_attribute_axes_are_named_as_pob_stats() -> None:
    txt = "Rarity: RARE\nX\nY\nImplicits: 0\n1% increased Damage per 15 Strength\n"
    out = _stat_scalers({"items": [{"slot": "Ring 1", "text": txt}]})
    assert out["primary"] == "Str"  # PoB 스탯 키와 맞춰야 evaluate_delta로 바로 잰다
