"""#129 — 계산·조립 전 필수 절차. 클라이언트 훅 없이 같은 규칙을 적용한다.

선택 누락과 희귀 출처만 판정한다. 어떤 능력치를 고르거나 어떤 가중치를 쓸지는
호출자의 판단이다. 복원본은 읽어 온 구성을 보존하고, 선언된 가중치는 조립의
자동 채움으로 넘긴다.
"""

from __future__ import annotations

import re
from typing import Any

from pok.engine.autofill import declared_weights
from pok.kb import store

_RARE = re.compile(r"^\s*Rarity:\s*Rare\s*$", re.I | re.M)


def attribute_choice_nodes() -> frozenset[int]:
    """검증된 KB에서 능력치 택1 노드를 읽는다 (정본 변경은 store가 감지한다)."""
    return frozenset(
        int(data["node_id"])
        for record in store.load().records.values()
        if record.type == "Passive"
        and (data := record.raw.get("data", {})).get("attribute_choice")
        and "node_id" in data
    )


def check_procedures(build_spec: dict[str, Any]) -> tuple[str, ...]:
    """빠진 절차와 수정 경로. 복원본·명시한 수동 출처는 기존 예외를 유지한다."""
    if build_spec.get("restored_from"):
        return ()

    problems: list[str] = []
    tree = build_spec.get("tree_nodes") or []
    if tree:
        try:
            required = {int(node) for node in tree} & attribute_choice_nodes()
            choices = build_spec.get("attribute_choices") or {}
            pairs = choices.items() if isinstance(choices, dict) else choices
            selected = {int(node) for node, _ in pairs}
        except (OSError, ValueError, TypeError, store.KBValidationError) as exc:
            problems.append(f"능력치 선택을 확인하지 못했다 — KB·스펙을 확인할 것: {exc}")
        else:
            missing = sorted(required - selected)
            if missing:
                problems.append(
                    f"능력치 택1 노드 {len(required)}개 중 {len(missing)}개 미지정: {missing} — "
                    "PoB 기본값으로 계산되므로 능력치가 샌다. build_spec.attribute_choices에 "
                    '{"<node_id>": "str"|"dex"|"int"} 또는 [[node_id, "str"], ...]를 채울 것'
                )

    handmade = [
        str(item["slot"])
        for item in build_spec.get("items") or []
        if isinstance(item, dict)
        and item.get("slot")
        and _RARE.search(str(item.get("text") or ""))
        and not item.get("derived_from")
    ]
    if handmade:
        try:
            weights = declared_weights(build_spec)
        except (TypeError, ValueError) as exc:
            problems.append(f"선언된 weights가 유효하지 않다 — 숫자 가중치를 지정할 것: {exc}")
        else:
            if weights is None:
                problems.append(
                    f"희귀 슬롯 {len(handmade)}개에 derived_from이 없다 ({', '.join(handmade)}) — "
                    "선언된 weights도 없어 자동으로 채울 수 없다. optimize_rare의 text와 "
                    "derived_from을 옮기거나, 이미 정한 weights를 build_spec.derived_from에 "
                    "선언하면 조립이 나머지를 채운다. 의도한 수동 장비라면 해당 슬롯에 "
                    'derived_from = {"tool": "manual", "why": "<사유>"}를 명시할 것'
                )
    return tuple(problems)
