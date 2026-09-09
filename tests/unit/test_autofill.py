"""#129 2차 — 빠진 절차를 **거부 대신 그 자리에서 돌린다**.

거부는 구멍이 난다. 사용자 지적(2026-08-27): *"감지를 해서 리젝하는 방식은 지금까지도
계속 시도했는데 매번 구멍이 발생한다"*. 이유가 있다 — 거부는 할 일을 호출자에게
**되돌려주고**, 되돌려받은 쪽이 안 하면 그대로다.

⛔ 다만 엔진은 **빌드 판단을 지어내지 않는다**(철칙 3). `optimize_rare`의 `weights`는
판단이라, 이 빌드가 **이미 선언한 것**만 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import pytest

from pok.engine.autofill import autofill_rares, declared_weights, unstamped_rares

_RARE = "Rarity: RARE\n손으로 지은 반지\nGold Ring\n+10 to Strength"


def _spec(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "tree_nodes": [1],
        "items": [{"slot": "Ring 1", "text": _RARE}],
    }
    base.update(over)
    return base


@dataclass
class _Result:
    text: str
    delta: dict[str, float]


def _fake_optimizer(calls: list[tuple[str, str, dict[str, float]]]) -> Any:
    def run(spec: dict[str, Any], slot: str, base_type: str, weights: dict[str, float]) -> _Result:
        calls.append((slot, base_type, dict(weights)))
        return _Result(
            text=f"Rarity: RARE\n도구 산출물\n{base_type}\n+30 to Strength",
            delta={"TotalDPS": 1000.0},
        )

    return run


def test_선언된_가중치를_재사용해_채운다() -> None:
    """호출자가 다른 슬롯에서 밝힌 판단을 **그대로** 쓴다 — 새 판단이 아니다."""
    spec = _spec(derived_from={"items": {"weights": {"TotalDPS": 1.0, "Life": 0.3}}})
    calls: list[tuple[str, str, dict[str, float]]] = []
    out, report = autofill_rares(spec, _fake_optimizer(calls))

    assert report.ran and not report.skipped
    assert calls == [("Ring 1", "Gold Ring", {"TotalDPS": 1.0, "Life": 0.3})]
    assert report.weights == {"TotalDPS": 1.0, "Life": 0.3}
    ring = next(i for i in out["items"] if i["slot"] == "Ring 1")
    assert "도구 산출물" in ring["text"] and ring["derived_from"]


def test_가중치_선언이_없으면_지어내지_않는다() -> None:
    """⛔ **철칙 3** — 엔진에 빌드 판단을 넣지 않는다.

    재사용할 선언이 없으면 **안 돌리고 사유를 낸다**. 여기서 기본 가중치를 지어내면
    그건 엔진이 「무엇이 좋은 빌드인가」를 정하는 것이다.
    """
    calls: list[tuple[str, str, dict[str, float]]] = []
    out, report = autofill_rares(_spec(), _fake_optimizer(calls))

    assert calls == [], "가중치가 없는데 최적화를 돌렸다"
    assert out == _spec() and not report.ran
    assert report.skipped and "weights" in report.skipped[0]["why"]


def test_복원본은_건드리지_않는다() -> None:
    """⛔ 남의 빌드를 읽어 왔는데 갈아 끼우면 **다른 빌드가 된다**(§0 ⑪ 거짓 거부).

    복원본에 `derived_from`이 있을 리 없다 — 그것을 「손으로 지었다」로 읽으면
    읽기 자체가 불가능해진다.
    """
    spec = _spec(restored_from="pob-code", derived_from={"items": {"weights": {"TotalDPS": 1.0}}})
    calls: list[tuple[str, str, dict[str, float]]] = []
    out, report = autofill_rares(spec, _fake_optimizer(calls))
    assert calls == [] and out == spec and not report.ran and unstamped_rares(spec) == []


def test_도장이_있으면_0초다() -> None:
    """정상 절차를 밟은 조립에는 **아무 비용도 없다** — 자동 실행이 상시 세금이 아니다."""
    spec = _spec(
        items=[{"slot": "Ring 1", "text": _RARE, "derived_from": {"tool": "optimize_rare"}}]
    )
    calls: list[tuple[str, str, dict[str, float]]] = []
    _, report = autofill_rares(spec, _fake_optimizer(calls))
    assert calls == [] and not report.ran and not report.skipped


def test_유니크는_대상이_아니다() -> None:
    """유니크는 고정 아이템이라 최적화할 접사가 없다 — 걸면 통과 불가능한 게이트가 된다."""
    spec = _spec(items=[{"slot": "Ring 1", "text": "Rarity: UNIQUE\n마법사의 피\nGold Ring"}])
    assert unstamped_rares(spec) == []


def test_한_칸이_실패해도_나머지는_채운다() -> None:
    """하나 때문에 전부 멈추면 **거부와 같아진다** — 그래서 고치려던 문제로 돌아간다."""
    spec = _spec(
        derived_from={"items": {"weights": {"TotalDPS": 1.0}}},
        items=[
            {"slot": "Ring 1", "text": _RARE},
            {"slot": "Ring 2", "text": _RARE.replace("Gold Ring", "Iron Ring")},
        ],
    )

    def flaky(s: dict[str, Any], slot: str, base: str, w: dict[str, float]) -> _Result:
        if slot == "Ring 1":
            raise RuntimeError("PoB 부팅 실패")
        return _Result(text=f"Rarity: RARE\n산출물\n{base}", delta={})

    _, report = autofill_rares(spec, flaky)
    assert len(report.replaced) == 1 and report.replaced[0]["slot"] == "Ring 2"
    assert len(report.skipped) == 1 and "PoB 부팅 실패" in report.skipped[0]["why"]


def test_자른_것을_조용히_넘기지_않는다() -> None:
    """⚠ 상한으로 자르면 **자른 사실을 낸다** — 침묵하면 「다 했다」로 읽힌다(형태 ⑭)."""
    spec = _spec(
        derived_from={"items": {"weights": {"TotalDPS": 1.0}}},
        items=[{"slot": f"Ring {i}", "text": _RARE} for i in range(4)],
    )
    calls: list[tuple[str, str, dict[str, float]]] = []
    _, report = autofill_rares(spec, _fake_optimizer(calls), limit=2)
    assert len(report.replaced) == 2 and len(report.skipped) == 2
    assert all("2칸까지만" in s["why"] for s in report.skipped)


def test_가중치_우선순위는_rares가_먼저다() -> None:
    """희귀 슬롯을 채우므로 **같은 도구가 쓰던 축**이 가장 가깝다."""
    spec = _spec(
        derived_from={
            "tree": {"weights": {"Life": 9.0}},
            "rares": {"weights": {"TotalDPS": 1.0}},
            "items": {"weights": {"EHP": 2.0}},
        }
    )
    assert declared_weights(spec) == {"TotalDPS": 1.0}


def test_베이스를_못_읽으면_건드리지_않는다() -> None:
    """⛔ **모르면 그대로 둔다** — 형식이 어긋난 텍스트를 추측으로 최적화하면 더 나쁘다."""
    assert unstamped_rares(_spec(items=[{"slot": "Ring 1", "text": "Rarity: RARE"}])) == []


def test_주얼은_자동으로_안_채운다() -> None:
    """⛔ 실물 빌드에서 드러난 갭(형태 ⑭ — 지어낸 스펙에는 주얼 슬롯이 없었다).

    `optimize_rare`는 주얼을 `slot="Jewel@<소켓 node_id>"`로 받는다. 스펙의 슬롯 이름
    (`Gloves Jewel Socket 1`)을 그대로 넘기면 PoB가 반영하지 못해 **델타가 전부 0**이
    되고, 그리디는 0끼리 비교해 아무거나 고른다 — 실측 2026-08-06: 그 경로로 주얼이
    **저스펙으로 출고**됐다. 채우는 것보다 **안 채우고 말하는 것**이 낫다.
    """
    spec = _spec(
        derived_from={"items": {"weights": {"TotalDPS": 1.0}}},
        items=[{"slot": "Gloves Jewel Socket 1", "text": _RARE.replace("Gold Ring", "Emerald")}],
    )
    calls: list[tuple[str, str, dict[str, float]]] = []
    out, report = autofill_rares(spec, _fake_optimizer(calls))
    assert calls == [], "주얼을 잘못된 슬롯 형식으로 최적화했다"
    assert out == spec and not report.replaced
    assert len(report.skipped) == 1 and "Jewel@" in report.skipped[0]["why"]


def test_실물_빌드에서_희귀_슬롯을_찾아낸다() -> None:
    """⚠ **실물 입력으로 「울린다」를 잰다**(형태 ⑭) — 지어낸 스펙은 갭을 못 드러낸다.

    주얼 슬롯 문제가 여기서 드러났다: 손으로 만든 시험 스펙에는 주얼이 없어 전부
    통과했지만, 실제 빌드에는 `Gloves Jewel Socket 1`이 있었다.
    """
    code = Path("artifacts/builds/negres-martial-artist/build-pob-code.txt")
    if not code.exists():  # 실물 빌드가 없는 환경 — 이 시험은 의미가 없다
        pytest.skip("실물 빌드 없음")
    from pok.pob.restore import spec_from_pob

    spec = spec_from_pob(code.read_text(encoding="utf-8").strip()).spec
    assert unstamped_rares(spec) == [], "복원본을 손으로 지은 것으로 읽었다"

    handmade = {k: v for k, v in spec.items() if k != "restored_from"}
    found = unstamped_rares(handmade)
    assert {f["slot"] for f in found} >= {"Weapon 1", "Amulet", "Gloves"}
    assert any(f["base_type"] == "Massive Greathammer" for f in found)
    # 주얼은 찾되 **자동으로는 안 채운다**
    assert any(f.get("jewel") for f in found)


# ── #152 — 자동 채움이 자기 스펙을 오염시키던 자리 ─────────────────────────────
#
# 첫 칸에 찍은 `derived_from` 도장이 둘째 칸의 `optimize_rare`와 조립의 `spec_from_dict`로
# 그대로 가는데, 스키마가 그 키를 거부해 **첫 칸만 성공하고 나머지는 전부 실패**했다.
# 위의 가짜 최적화기는 받은 스펙을 **읽지 않아** 이 오염을 볼 수 없었다 — 아래 가짜는
# 실제 도구가 하는 것과 같이 받은 스펙을 스키마에 태운다.

_FULL = {"class_name": "Witch", "ascendancy": "Witch1"}


def _strict_optimizer(calls: list[dict[str, Any]]) -> Any:
    """받은 스펙을 **실제 도구처럼** 스키마에 태우는 가짜 — 오염이 있으면 여기서 죽는다."""
    from pok.pob.buildxml import spec_from_dict

    def run(spec: dict[str, Any], slot: str, base_type: str, weights: dict[str, float]) -> _Result:
        spec_from_dict(spec, validate_catalog=False)  # 실제 optimize_rare가 밟는 첫 관문
        calls.append({"slot": slot, "items": [dict(i) for i in spec["items"]]})
        return _Result(text=f"Rarity: RARE\n산출물\n{base_type}\n+30 to Strength", delta={})

    return run


def test_둘째_칸부터_자기_스펙을_넘겨도_스키마를_통과한다() -> None:
    """#152 — **2칸 이상**이어야 보인다. 1칸 시험은 첫 칸이 언제나 성공해 구조적으로 못 본다."""
    spec = _spec(
        **_FULL,
        derived_from={"items": {"weights": {"TotalDPS": 1.0}}},
        items=[
            {"slot": "Ring 1", "text": _RARE},
            {"slot": "Ring 2", "text": _RARE.replace("Gold Ring", "Iron Ring")},
        ],
    )
    calls: list[dict[str, Any]] = []
    _, report = autofill_rares(spec, _strict_optimizer(calls))

    assert not report.skipped, report.skipped
    assert [r["slot"] for r in report.replaced] == ["Ring 1", "Ring 2"]
    # 둘째 호출은 첫 칸의 **도장 찍힌** 아이템을 이미 들고 있었다 — 그 스펙이 통과했다
    carried = next(i for i in calls[1]["items"] if i["slot"] == "Ring 1")
    assert carried["derived_from"] == {"tool": "optimize_rare", "via": "autofill"}


def test_자동_채움_산출_스펙은_조립_입력_스키마를_통과한다() -> None:
    """채운 스펙은 그대로 `assemble(spec_from_dict(…))`로 간다 — 거기서 죽으면 1칸도 못 나간다.

    도장은 아이템의 속성이 아니라 계보라 **PoB로는 안 간다**: 스키마가 받되 벗겨 낸다.
    `ItemSpec` 자체에는 그 필드가 없어야 한다 — PoB 직렬화 형식은 그대로다.
    """
    from pok.pob.buildxml import ItemSpec, spec_from_dict

    spec = _spec(**_FULL, derived_from={"items": {"weights": {"TotalDPS": 1.0}}})
    out, report = autofill_rares(spec, _fake_optimizer([]))
    assert report.ran

    built = spec_from_dict(out, validate_catalog=False)
    ring = next(i for i in built.items if i.slot == "Ring 1")
    assert "도구 산출물" in ring.text
    assert "derived_from" not in {f.name for f in fields(ItemSpec)}


def test_거부문이_안내한_탈출구가_실제로_열려_있다(monkeypatch: pytest.MonkeyPatch) -> None:
    """#152 얼굴 ② — 거부문은 「그 슬롯에 derived_from을 명시할 것」을 안내한다.

    금지하려면 대안 경로가 먼저 있어야 한다(철칙 5 따름정리). 안내를 **그대로 따른** 스펙이
    훅 게이트·자동 채움·스키마를 다 지나야 탈출구다 — 실측 2026-09-09: 스키마가 막았다.
    거부문을 실제 경로(`assemble_pob`)에서 받아 온다 — 문구를 베껴 적으면 둘이 따로 논다.
    """
    import pok.engine.rares as rares
    from pok.mcp.tools.build import assemble_pob
    from pok.pob.buildxml import spec_from_dict

    def unavailable(*_: Any, **__: Any) -> Any:
        raise RuntimeError("PoB 없음")

    monkeypatch.setattr(rares, "optimize_rare", unavailable)
    spec = _spec(
        **_FULL,
        derived_from={"items": {"weights": {"TotalDPS": 1.0}}},
        items=[
            {"slot": "Ring 1", "text": _RARE},
            {"slot": "Ring 2", "text": _RARE.replace("Gold Ring", "Iron Ring")},
        ],
    )
    refused = assemble_pob(spec, "test-152")
    assert refused["ok"] is False and "derived_from" in refused["reason"]
    assert {s["slot"] for s in refused["autofill_failed"]} == {"Ring 1", "Ring 2"}

    # 안내대로 — 실패한 슬롯마다 도장을 명시한다
    escaped = {
        **spec,
        "items": [{**i, "derived_from": {"tool": "manual", "why": "시험"}} for i in spec["items"]],
    }
    assert unstamped_rares(escaped) == []  # 자동 채움 대상에서 빠진다
    _, report = autofill_rares(escaped, unavailable)  # 최적화기를 부르지 않는다
    assert not report.skipped and not report.ran
    built = spec_from_dict(escaped, validate_catalog=False)  # 스키마가 받는다
    assert {i.slot for i in built.items} == {"Ring 1", "Ring 2"}


def test_날린_대리_측정_줄을_보고에_남긴다() -> None:
    """갈아 끼우면 `substitutes`가 함께 빠진다 — 옮기지도, 조용히 버리지도 않는다 (#153).

    옮기면 사라진 룬의 대리 줄이 추산을 실측으로 둔갑시키고, 조용히 버리면 트리 문구를
    얹어 두던 측정이 말없이 준다. 엔진은 어느 쪽인지 모른다 — 빠진 사실을 낸다.
    """
    spec = _spec(
        derived_from={"items": {"weights": {"TotalDPS": 1.0}}},
        items=[{"slot": "Ring 1", "text": _RARE, "substitutes": ["10% increased Cast Speed"]}],
    )
    out, report = autofill_rares(spec, _fake_optimizer([]))
    assert report.replaced[0]["before_substitutes"] == ["10% increased Cast Speed"]
    ring = next(i for i in out["items"] if i["slot"] == "Ring 1")
    assert "substitutes" not in ring, "대리 줄을 새 아이템으로 옮기면 추산이 실측으로 둔갑한다"
