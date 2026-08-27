"""#129 — 조립 게이트가 **경고가 아니라 거부**인지 잠근다.

MCP 반환 경고는 세션이 읽고 무시할 수 있다. 실측 2026-08-27: `skipped_procedures`에
실린 경고를 세션이 **보고서에 옮겨 적고 실행은 안 했다** — 손으로 지은 희귀 3슬롯 +
룬 9칸 공란 + 트리 42포인트 미배분 상태에서 `assemble_pob`이 `ok: true`를 냈다.

`PreToolUse` 훅은 **하버스가 실행**하므로 세션이 우회할 수 없다(§0 ⑫).
⚠ `compute_pob`도 막는다 — 안 그러면 조립을 피하고 계산 수치만 보고하는 경로로 샌다.
**이번 사고가 정확히 그 경로였다.**
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_HOOK = Path("scripts/workflow-pretooluse.mjs")


def _run(payload: dict) -> int:
    node = shutil.which("node")
    if node is None:  # CI 환경 가드 — node 없으면 이 시험은 의미가 없다
        pytest.skip("node 없음")
    proc = subprocess.run(
        [node, str(_HOOK)],
        input=json.dumps(payload, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.returncode


def _spec(**over: object) -> dict:
    base = {"tree_nodes": [10100], "attribute_choices": [], "items": []}
    base.update(over)
    return base


def test_손으로_지은_조립을_거부한다() -> None:
    """능력치 택1 미지정 → 거부. PoB가 전부 기본값으로 계산해 **능력치가 통째로 샌다**.

    실측 2026-08-27: 배정 85노드 중 33개가 택1인데 선택 0건 → 능력치 165점 소실,
    `req_shortfall`이 허수가 됐다.
    """
    assert _run({"tool_name": "mcp__pok__assemble_pob", "tool_input": {"build_spec": _spec()}}) == 2


def test_계산_경로도_막는다() -> None:
    """⚠ `compute_pob`만 열어 두면 **조립을 피하고 수치만 보고하는 경로**로 샌다."""
    assert _run({"tool_name": "mcp__pok__compute_pob", "tool_input": {"build_spec": _spec()}}) == 2


def test_복원본은_막지_않는다() -> None:
    """⛔ **거짓 거부 방지** — 복원본에는 `derived_from`도, 코드에 없는 택1 선택도 없다.

    막으면 **남의 빌드를 읽는 것 자체가 불가능**해진다(§0 ⑪ — 통과 불가능한 게이트는
    우회 경로를 학습시킨다). 실측 2026-08-27: 이 예외가 없을 때 복원한 실물 빌드가
    그대로 막혔다. 읽기는 열고 **쓰기(조립)에서는 그대로 막는다.**
    """
    spec = _spec(restored_from="pob-code", items=[{"slot": "Amulet", "text": "Rarity: Rare\nX\n"}])
    assert _run({"tool_name": "mcp__pok__compute_pob", "tool_input": {"build_spec": spec}}) == 0


def test_절차를_갖춘_스펙은_통과한다() -> None:
    """⛔ 반대 방향 — 게이트가 정상 조립을 막으면 그게 새 사고다."""
    spec = _spec(attribute_choices=[[10100, "str"]])
    assert _run({"tool_name": "mcp__pok__assemble_pob", "tool_input": {"build_spec": spec}}) == 0


def test_빌드_스펙이_아니면_안_건드린다() -> None:
    """검사 대상이 `build_spec`이라 빌드 작업이 아니면 애초에 안 걸린다.

    키워드로 켜고 끄지 않는 이유가 이것이다 — **키워드 목록은 항상 사고보다 뒤처진다.**
    """
    assert _run({"tool_name": "mcp__pok__compute_pob", "tool_input": {}}) == 0
    assert _run({"tool_name": "Read", "tool_input": {"file_path": "x"}}) == 0


def test_가중치를_선언하면_훅이_비켜_준다() -> None:
    """#129 2차 — 조립이 **자동으로 채우므로** 막을 이유가 없다.

    ⚠ 막으면 자동 실행에 **도달조차 못 한다**. 훅과 조립이 서로 미루면 두 겹이 다 있는데
    구멍이 남으므로, 인계 지점을 여기서 잠근다:
    훅이 비켜 준 경우 → `assemble_pob`이 채우거나 **거부한다**(`test_autofill.py` 참조).
    """
    spec = _spec(
        attribute_choices=[],
        items=[{"slot": "Ring 1", "text": "Rarity: RARE\nX\nGold Ring"}],
        derived_from={"items": {"weights": {"TotalDPS": 1.0}}},
        tree_nodes=[],
    )
    assert _run({"tool_name": "mcp__pok__assemble_pob", "tool_input": {"build_spec": spec}}) == 0


def test_가중치_선언이_없으면_여전히_거부한다() -> None:
    """⛔ 재사용할 판단이 없으면 조립도 못 채운다 — 그때는 훅이 막아야 한다.

    엔진이 기본 가중치를 지어내면 「무엇이 좋은 빌드인가」를 엔진이 정하는 것이다(철칙 3).
    """
    spec = _spec(
        attribute_choices=[],
        items=[{"slot": "Ring 1", "text": "Rarity: RARE\nX\nGold Ring"}],
        tree_nodes=[],
    )
    assert _run({"tool_name": "mcp__pok__assemble_pob", "tool_input": {"build_spec": spec}}) == 2
