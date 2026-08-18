"""주 배율기 자동 감지 — 축을 모르면 노력량이 결과에 반영되지 않는다 (철칙 5).

실측 2026-08-18: 「100 생명력당」 줄을 셋 가진 빌드에서 생명력 2.53배가 DPS 3.38배가
됐는데, 같은 자리에서 「주문 피해 +100%」는 1.14배였다. 한 세션이 그 사실을 알아내는
데 하루를 쓰고 트리를 다섯 번 갈아엎었다. 그래서 묻지 않아도 반환값에 나오게 한다.

⛔ **이 파일의 핵심은 일반성이다.** 처음엔 스탯 12종 허용목록으로 짰다가 KB 전량
대조에서 **포착률 10%**가 나왔다 — 스태킹 축의 종류는 열려 있다. 아래 원형 표가
한 빌드에 맞춘 구현으로 되돌아가는 것을 막는다.
"""

from __future__ import annotations

import pytest

from pok.mcp.tools.build import _stat_scalers


def _spec(*lines: str) -> dict:
    body = "Rarity: RARE\nProbe\nBase\nImplicits: 0\n" + "\n".join(lines) + "\n"
    return {"items": [{"slot": "Test", "text": body}]}


# (라벨, 줄, 기대 축키, 기대 pob_stat) — 서로 다른 스태킹 원형을 한 줄씩
ARCHETYPES = [
    (
        "생명력",
        "Non-Channelling Spells deal 7% increased Damage per 100 maximum Life",
        "Life",
        "Life",
    ),
    ("힘(어법 변형)", "1% increased Damage per 15 of your Strength", "Str", "Str"),
    ("지능", "2% increased Spell Damage per 10 Intelligence", "Int", "Int"),
    (
        "에너지 보호막",
        "Gain 5 Armour per 10 Item Energy Shield on Equipped Armour",
        "EnergyShield",
        "EnergyShield",
    ),
    (
        "저주 수",
        "Spell Hits Gain 31% of Damage as Extra Chaos Damage per Curse on Enemy",
        "curse on enemy",
        None,
    ),
    (
        "소켓된 유니크 수",
        "2% increased Maximum Life per socketed Grand Spectrum",
        "socketed grand spectrum",
        None,
    ),
    ("충전", "8% increased Damage per Power Charge", "power charge", None),
    ("단계", "20% increased Area of Effect per Stage", "stage", None),
]


@pytest.mark.parametrize("label,line,axis,pob", ARCHETYPES, ids=[a[0] for a in ARCHETYPES])
def test_each_stacking_archetype_is_detected(
    label: str, line: str, axis: str, pob: str | None
) -> None:
    out = _stat_scalers(_spec(line))
    assert out, f"{label}: 축을 못 찾았다 — 허용목록으로 좁아졌는지 볼 것"
    assert axis in out["axes"], f"{label}: 축키가 {list(out['axes'])}로 나왔다"
    assert out["axes"][axis][0]["pob_stat"] == pob


def test_unknown_axes_are_surfaced_not_dropped() -> None:
    """PoB 키로 못 옮겨도 **버리지 않는다** — 조용한 제외가 이 프로젝트가 데인 형태다."""
    out = _stat_scalers(_spec("8% increased Damage per Power Charge"))
    assert "unclassified" in out
    assert "power charge" in out["unclassified"]["axes"]
    assert "축이 아니라는 뜻이 아니다" in out["unclassified"]["why"]


@pytest.mark.parametrize(
    "line",
    [
        "Regenerate 2% of maximum Life per second",
        "Gain 5 Life per enemy killed",
        "20% increased Damage per Combo expended",
        "+5 to Level per Quality",
    ],
)
def test_rate_and_event_phrases_are_not_axes(line: str) -> None:
    """「~당」이어도 시간·사건은 축이 아니다 — 섞으면 신호가 죽는다."""
    assert _stat_scalers(_spec(line)) == {}


def test_flat_stat_is_not_a_scaler() -> None:
    """+161 생명력은 스택 요소지 **배율기**가 아니다."""
    assert _stat_scalers(_spec("+161 to maximum Life")) == {}


def test_ranks_by_distinct_effects_not_copies() -> None:
    """같은 줄 여러 벌(장대한 파장 3개)이 **서로 다른 3줄**을 이기면 안 된다.

    실측 2026-08-18: 줄 수로 세니 「소켓된 장대한 파장」이 래스피스의 생명력 3줄을 눌렀다.
    """
    same = "2% increased Maximum Life per socketed Grand Spectrum"
    spec = {
        "items": [
            {
                "slot": "Weapon 2",
                "text": "Rarity: UNIQUE\nRathpith\nFocus\n"
                "7% increased Damage per 100 maximum Life\n"
                "4% increased Critical Hit Chance per 100 maximum Life\n"
                "3% increased Magnitude of Ailments per 100 maximum Life\n",
            }
        ],
        "jewels": [
            {"socket_node_id": i, "text": f"Rarity: UNIQUE\nGrand Spectrum\nRuby\n{same}\n"}
            for i in (1, 2, 3)
        ],
    }
    out = _stat_scalers(spec)
    assert out["distinct_effects"]["Life"] == 3
    assert out["distinct_effects"]["socketed grand spectrum"] == 1
    assert out["top_candidate"] == "Life"
    assert out["ranked"][0] == "Life"


def test_it_reports_a_candidate_not_a_verdict() -> None:
    """어느 축이 실제로 큰지는 판정하지 않는다 (철칙 3)."""
    out = _stat_scalers(_spec("7% increased Damage per 100 maximum Life"))
    assert "top_candidate" in out and "primary" not in out
    assert "센 것이지 잰 것이 아니다" in out["note"]


def test_reads_jewels_too() -> None:
    out = _stat_scalers(
        {
            "jewels": [
                {
                    "socket_node_id": 123,
                    "text": "Rarity: UNIQUE\nJ\nB\n7% increased Damage per 100 maximum Life\n",
                }
            ]
        }
    )
    assert out["axes"]["Life"][0]["slot"] == "Jewel@123"


def test_damage_scaling_axes_outrank_defensive_ones() -> None:
    """딜을 곱하는 축인지는 판정이 아니라 **사실**이라 표시한다.

    실측 2026-08-18: 경계 감개 빌드에서 「소켓당 저항 +11%」(서로 다른 3줄)가
    「저주당 추가 카오스 피해」(2줄)를 줄 수로 눌렀다. 방어 스케일러가 위에 오면
    세션이 딜 축을 못 집는다.
    """
    out = _stat_scalers(
        _spec(
            "+11% to Chaos Resistance per Socket filled",
            "+11% to Fire Resistance per Socket filled",
            "+11% to Cold Resistance per Socket filled",
            "Spell Hits Gain 31% of Damage as Extra Chaos Damage per Curse on Enemy",
            "Spell Hits Gain 30% of Damage as Extra Physical Damage per Curse on Enemy",
        )
    )
    assert out["scales_damage"]["curse on enemy"] is True
    assert out["scales_damage"]["socket filled"] is False
    assert out["top_candidate"] == "curse on enemy"
    assert out["ranked"][0] == "curse on enemy"
