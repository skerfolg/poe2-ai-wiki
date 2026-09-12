"""#164 — `find_carriers`가 다중 효과 스킬의 **첫 효과만** 평가하던 자리.

한 젬이 `pob.effects`를 여러 개 갖는다(내장 트리거·부산 스킬 — KB에 70종). 반발은
저주 효과(`CurseOfRepulsionPlayer`)와 충격파 효과(`CurseOfRepulsionShockwavePlayer`,
`Attack`)를 갖는데, 첫 효과만 보고 「요구 타입 미충족: Attack」으로 살아있는 번개를
거짓 거부했다 — 실측 2026-09-11: 세션이 그 반환을 근거로 사용자가 인게임에서 쓰는
구성을 "불가능"으로 판정했다.

합집합만 내면 반대 오독이 생긴다(「저주에 근접 보조가 붙는다」). 그래서 담체마다
**어느 효과에 붙는지**를 낸다.
"""

from __future__ import annotations

from typing import Any

import pytest

from pok.engine import hosting
from pok.kb.skill_facts import SkillGate


def _gate(
    skill_id: str,
    *,
    name: str,
    record_id: str,
    types: tuple[str, ...] = (),
    require: tuple[str, ...] = (),
    exclude: tuple[str, ...] = (),
    is_support: bool = False,
) -> SkillGate:
    return SkillGate(
        skill_id=skill_id,
        name=name,
        types=frozenset(types),
        require=require,
        exclude=exclude,
        adds=(),
        minion_types=frozenset(),
        ignore_minion_types=False,
        from_item=False,
        cannot_be_supported=False,
        support_gems_only=False,
        is_support=is_support,
        record_id=record_id,
        catalog_source="gem",
    )


@pytest.fixture
def two_effect_gates(monkeypatch: pytest.MonkeyPatch) -> dict[str, SkillGate]:
    """저주 효과 + 충격파 효과를 가진 스킬 하나와 보조 넷 — KB 없이 규칙만 잠근다."""
    gates = {
        "CursePlayer": _gate(
            "CursePlayer", name="반발", record_id="skill.x", types=("Spell", "AppliesCurse")
        ),
        "ShockwavePlayer": _gate(
            "ShockwavePlayer", name="반발", record_id="skill.x", types=("Attack", "Triggered")
        ),
        "SupMelee": _gate(
            "SupMelee",
            name="근접 보조",
            record_id="support.a",
            require=("Attack",),
            is_support=True,
        ),
        "SupCurse": _gate(
            "SupCurse",
            name="저주 보조",
            record_id="support.b",
            require=("AppliesCurse",),
            is_support=True,
        ),
        "SupAny": _gate("SupAny", name="아무 보조", record_id="support.c", is_support=True),
        "SupMinion": _gate(
            "SupMinion",
            name="소환 보조",
            record_id="support.d",
            require=("Minion",),
            is_support=True,
        ),
    }
    monkeypatch.setattr(hosting, "skill_gates", lambda root=None: gates)
    return gates


def _by_carrier(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["carrier"]: r for r in rows}


def test_모든_효과를_평가하고_어느_효과에_붙는지_낸다(
    two_effect_gates: dict[str, SkillGate],
) -> None:
    out = hosting.find_carriers("반발", include_blocked=True)
    assert out["ok"], out
    # `types`는 합집합 — 첫 효과만 보던 때는 Attack이 없었다
    assert {"Spell", "AppliesCurse", "Attack", "Triggered"} <= set(out["types"])
    assert [e["id"] for e in out["effects"]] == ["CursePlayer", "ShockwavePlayer"]

    hosts = _by_carrier(out["carriers"])
    assert hosts["근접 보조"]["effects"] == ["ShockwavePlayer"], "충격파에 붙는다 — 저주가 아니다"
    assert hosts["저주 보조"]["effects"] == ["CursePlayer"], "저주에 붙는다 — 충격파가 아니다"
    assert hosts["아무 보조"]["effects"] == ["CursePlayer", "ShockwavePlayer"]
    assert out["count"] == 3

    blocked = _by_carrier(out["blocked"])
    assert set(blocked) == {"소환 보조"}
    # 막힌 것은 효과마다 사유를 낸다 — 하나만 내면 「왜 안 되는가」가 반쪽이다
    assert set(blocked["소환 보조"]["reasons"]) == {"CursePlayer", "ShockwavePlayer"}
    assert (
        "CursePlayer" in blocked["소환 보조"]["why"]
        and "ShockwavePlayer" in blocked["소환 보조"]["why"]
    )


def test_효과가_하나인_스킬의_반환은_종전과_같다(monkeypatch: pytest.MonkeyPatch) -> None:
    """효과 꼬리표는 **효과가 둘 이상일 때만** 붙는다 — 단일 효과 소비자는 아무것도 안 바뀐다."""
    gates = {
        "OnlyPlayer": _gate("OnlyPlayer", name="단일", record_id="skill.y", types=("Spell",)),
        "SupSpell": _gate(
            "SupSpell", name="주문 보조", record_id="support.e", require=("Spell",), is_support=True
        ),
        "SupAttack": _gate(
            "SupAttack",
            name="공격 보조",
            record_id="support.f",
            require=("Attack",),
            is_support=True,
        ),
    }
    monkeypatch.setattr(hosting, "skill_gates", lambda root=None: gates)
    out = hosting.find_carriers("단일", include_blocked=True)
    assert out["skill_id"] == "OnlyPlayer" and out["types"] == ["Spell"]
    assert "effects" not in out
    assert out["carriers"] == [{"carrier": "주문 보조", "skill_id": "SupSpell"}]
    assert out["blocked"] == [
        {"carrier": "공격 보조", "skill_id": "SupAttack", "why": "요구 타입 미충족: Attack"}
    ]


def test_반발의_충격파에_살아있는_번개가_붙는다() -> None:
    """실측 2026-09-11의 사례 — KB 정본으로 대조한다.

    살아있는 번개(`Attack, Damage` — 연산자 없음 = 둘 중 하나)는 충격파 효과에 붙는다.
    ⭑ 가루칸의 결의는 **여전히 막힌다** — 다만 사유가 바뀐다: 저주엔 Attack이 없고
    충격파는 `Cooldown`·`Triggered`가 배제 타입이다(PoB `excludeSkillTypes` 그대로).
    보고서는 이것도 거짓 거부로 적었지만 PoB 규칙상 참 거부다 — 효과별 사유가 그것을 보인다.
    """
    out = hosting.find_carriers("Repulsion", include_blocked=True)
    assert out["ok"], out
    assert out["skill_id"] == "CurseOfRepulsionPlayer"
    assert "Attack" in out["types"], "합집합에 충격파의 Attack이 있어야 한다"
    assert [e["id"] for e in out["effects"]] == [
        "CurseOfRepulsionPlayer",
        "CurseOfRepulsionShockwavePlayer",
    ]

    hosts = _by_carrier(out["carriers"])
    assert hosts["Living Lightning"]["effects"] == ["CurseOfRepulsionShockwavePlayer"]

    blocked = _by_carrier(out["blocked"])
    garukhan = blocked["Garukhan's Resolve"]
    assert garukhan["reasons"]["CurseOfRepulsionPlayer"] == "요구 타입 미충족: Attack"
    assert "배제 타입에 걸린다" in garukhan["reasons"]["CurseOfRepulsionShockwavePlayer"]
