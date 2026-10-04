"""#129 — Claude 훅 없이 실제 MCP 호출 경로에서도 필수 절차를 거부한다.

기존 Node 훅 시험만으로는 Codex의 무검사 경로가 보이지 않았다. FastMCP Client를
사용하고 KB·PoB 경계만 대체한다. 절차 판정, 스펙 변환, 자동 채움은 실제 코드다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastmcp import Client

from pok.engine.procedures import check_procedures
from pok.mcp.server import mcp

_RARE = "Rarity: RARE\nTest Ring\nGold Ring\n+10 to Strength"


def _spec(**over: Any) -> dict[str, Any]:
    return {
        "class_name": "Sorceress",
        "ascendancy": "Sorceress1",
        "level": 90,
        "tree_nodes": [10100],
        "attribute_choices": [[10100, "str"]],
        "items": [],
        **over,
    }


def _call(tool: str, spec: dict[str, Any]) -> dict[str, Any]:
    async def run() -> dict[str, Any]:
        async with Client(mcp) as client:
            args: dict[str, Any] = {"build_spec": spec}
            if tool == "assemble_pob":
                args["slug"] = "test-procedure-gate"
            result = await asyncio.wait_for(client.call_tool(tool, args), timeout=20)
            assert not result.is_error, result
            return (
                dict(result.data)
                if isinstance(result.data, dict)
                else dict(json.loads(result.content[0].text))
            )

    return asyncio.run(run())


@pytest.fixture
def boundaries(monkeypatch: pytest.MonkeyPatch) -> dict[str, list[Any]]:
    from pok.common import telemetry
    from pok.engine import rares
    from pok.engine.constraints import assumptions, axes
    from pok.engine.tree import corpus
    from pok.kb import store
    from pok.kb.graph import antagonists
    from pok.mcp.tools import build
    from pok.pob import buildxml

    calls: dict[str, list[Any]] = {"compute": [], "assemble": [], "optimize": []}
    records = {
        str(node): SimpleNamespace(
            type="Passive", raw={"data": {"node_id": node, "attribute_choice": {"value": 5}}}
        )
        for node in (10100, 20200)
    }
    monkeypatch.setattr(store, "load", lambda: SimpleNamespace(records=records))
    monkeypatch.setattr(telemetry, "record", lambda *a, **kw: None)
    monkeypatch.setattr(buildxml, "_validate_catalog", lambda spec: None)
    monkeypatch.setattr(build, "_get_checker", lambda: object())
    monkeypatch.setattr(build, "_pick", lambda *a: {"stats": {"Life": 100}})
    monkeypatch.setattr(build, "_points", lambda *a: {})
    monkeypatch.setattr(build, "_stat_scalers", lambda *a: {})
    monkeypatch.setattr(build, "_unset_config", lambda *a: {})
    monkeypatch.setattr(build, "_config_upkeep", lambda *a: {})
    monkeypatch.setattr(
        assumptions, "check_assumptions", lambda spec: assumptions.AssumptionReport(())
    )
    monkeypatch.setattr(
        axes,
        "check_axes",
        lambda spec: SimpleNamespace(empty_axes=(), unmeasured_axes=(), notes=()),
    )
    monkeypatch.setattr(corpus, "compare_build_spec", lambda spec: {})
    monkeypatch.setattr(antagonists, "report_for_spec", lambda *a: [])

    def compute(spec: Any) -> object:
        calls["compute"].append(spec)
        return object()

    def assemble(spec: Any, slug: str, **kwargs: Any) -> SimpleNamespace:
        calls["assemble"].append(kwargs["spec_data"])
        return SimpleNamespace(
            build_id=slug,
            path=Path("unused"),
            build_code="test-code",
            duplicates=(),
            result=object(),
        )

    def optimize(spec: Any, slot: str, base: str, weights: Any) -> SimpleNamespace:
        calls["optimize"].append((slot, weights))
        return SimpleNamespace(text=_RARE.replace("Test Ring", "Optimized Ring"), delta={"Life": 1})

    monkeypatch.setattr(build, "_compute", compute)
    monkeypatch.setattr(build, "assemble", assemble)
    monkeypatch.setattr(rares, "optimize_rare", optimize)
    return calls


@pytest.mark.parametrize("tool", ["compute_pob", "assemble_pob"])
def test_능력치_선택_누락을_훅_없이_거부한다(tool: str, boundaries: dict[str, list[Any]]) -> None:
    out = _call(tool, _spec(attribute_choices=[]))
    assert out["ok"] is False and "10100" in " ".join(out["blocking"])
    assert not any(boundaries.values()), "검사 전에 계산·자동 채움·출고하면 안 된다"


@pytest.mark.parametrize("tool", ["compute_pob", "assemble_pob"])
def test_가중치와_출처_없는_희귀를_훅_없이_거부한다(
    tool: str, boundaries: dict[str, list[Any]]
) -> None:
    # tree_nodes를 생략해도 희귀 검사는 적용된다.
    spec = _spec(items=[{"slot": "Ring 1", "text": _RARE}])
    del spec["tree_nodes"]
    out = _call(tool, spec)
    assert out["ok"] is False
    assert "derived_from" in " ".join(out["blocking"])
    assert not any(boundaries.values())


@pytest.mark.parametrize("tool", ["compute_pob", "assemble_pob"])
def test_복원본은_그대로_읽는다(tool: str, boundaries: dict[str, list[Any]]) -> None:
    spec = _spec(
        restored_from="pob-code", attribute_choices=[], items=[{"slot": "Ring 1", "text": _RARE}]
    )
    out = _call(tool, spec)
    assert out.get("ok", True) and out["stats"]["Life"] == 100
    assert len(boundaries["assemble" if tool == "assemble_pob" else "compute"]) == 1
    assert not boundaries["optimize"]


@pytest.mark.parametrize("tool", ["compute_pob", "assemble_pob"])
def test_명시한_수동_장비와_사전형_능력치_선택을_허용한다(
    tool: str, boundaries: dict[str, list[Any]]
) -> None:
    spec = _spec(
        attribute_choices={"10100": "str"},
        items=[
            {"slot": "Ring 1", "text": _RARE, "derived_from": {"tool": "manual", "why": "test"}}
        ],
    )
    out = _call(tool, spec)
    assert out.get("ok", True) and out["stats"]["Life"] == 100
    assert not boundaries["optimize"]


@pytest.mark.parametrize("choices", [{"20200": "str"}, [[20200, "str"], [20200, "dex"]]])
def test_다른_노드나_중복_선택으로_개수만_맞출_수_없다(
    choices: Any, boundaries: dict[str, list[Any]]
) -> None:
    assert "10100" in " ".join(check_procedures(_spec(attribute_choices=choices)))


def test_선언한_가중치는_실제_자동_채움으로_넘긴다(boundaries: dict[str, list[Any]]) -> None:
    out = _call(
        "assemble_pob",
        _spec(
            items=[{"slot": "Ring 1", "text": _RARE}],
            derived_from={"items": {"weights": {"Life": 1.0}}},
        ),
    )
    assert out["ok"] is True and out["autofilled"]["replaced"]
    assert boundaries["optimize"] == [("Ring 1", {"Life": 1.0})]
    item = boundaries["assemble"][0]["items"][0]
    assert "Optimized Ring" in item["text"] and item["derived_from"]["tool"] == "optimize_rare"


def test_자동_채움이_실패하면_출고하지_않는다(
    boundaries: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pok.engine import rares

    def unavailable(*a: Any) -> Any:
        raise RuntimeError("PoB unavailable")

    monkeypatch.setattr(rares, "optimize_rare", unavailable)
    out = _call(
        "assemble_pob",
        _spec(
            items=[{"slot": "Ring 1", "text": _RARE}],
            derived_from={"items": {"weights": {"Life": 1.0}}},
        ),
    )
    assert out["ok"] is False and out["autofill_failed"][0]["slot"] == "Ring 1"
    assert not boundaries["assemble"]


def test_검사_입력_오류도_MCP_오류_대신_수정_사유를_준다(
    boundaries: dict[str, list[Any]],
) -> None:
    out = _call("compute_pob", _spec(attribute_choices=["invalid-pair"]))
    assert out["ok"] is False and "스펙" in " ".join(out["blocking"])
    assert not any(boundaries.values())


def test_KB_검증_실패를_침묵으로_통과시키지_않는다(
    boundaries: dict[str, list[Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pok.kb import store

    def broken() -> Any:
        raise store.KBValidationError(["fixture schema error"])

    monkeypatch.setattr(store, "load", broken)
    out = _call("compute_pob", _spec())
    assert out["ok"] is False and "fixture schema error" in " ".join(out["blocking"])
    assert not any(boundaries.values())


def test_가중치_오류도_실행_전_수정_사유를_준다(boundaries: dict[str, list[Any]]) -> None:
    out = _call(
        "assemble_pob",
        _spec(
            items=[{"slot": "Ring 1", "text": _RARE}],
            derived_from={"items": {"weights": {"Life": "not-a-number"}}},
        ),
    )
    assert out["ok"] is False and "weights" in " ".join(out["blocking"])
    assert not any(boundaries.values())
