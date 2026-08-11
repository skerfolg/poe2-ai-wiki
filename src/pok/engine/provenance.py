"""산출 출처와 **낡음(stale)** 판정 — 백로그 #58 ③ (2026-08-11).

세션을 건너오는 것은 **스펙 파일**이고 결정은 문서에 쌓이는데, 스펙은 언제나
「적법」하므로 이어받은 세션은 그 위에 얹는다. 그래서 낡은 산출물이 계승된다.

실측(이관 5차): 선행 문서가 「트리 3·4·5차 전부 무효」라고 적어 뒀는데
(`conditionLowLife` 없이 산출했으므로) **그 트리가 그대로 계승돼** 다음 세션이 그
위에 25포인트를 더 얹었다. 「무효」라는 말을 읽고도 계승한 이유는 **무엇이 달라서
무효인지 몰랐기 때문**이다 — 그래서 해시 불일치만 알리면 소용없고, 사람이 읽을
문장이 나와야 한다.

## 설계 (보고자 제안 그대로)

- **축별(per-component)**: 트리만 낡고 장비는 멀쩡한 경우가 실제로 있었다. 스펙 전체
  해시 하나면 매번 전부 빨개져서 무시하게 된다.
- **`config`는 값 그대로, 구성은 해시 + 짧은 설명**: 작은 것은 값을 두면 diff가 바로
  문장이 된다. 큰 것만 해시로 하고 **설명을 함께 저장해** 불일치 시 풀어 쓴다.
- **자기 축은 안 본다**: 트리 도장은 트리를 안 본다. 자기가 만든 것과 자기를 비교하면
  항상 같거나(무의미) 손대는 순간 항상 빨개진다.
- **거부하지 않는다**: 낡은 트리로 일부러 A/B를 재는 것이 정상 작업이다(§0 ⑤).
  대신 매 반환에 싣고 정본 출고물(manifest)에 각인한다.
- **사람이 쓰는 자리는 없다**: 생산자(`optimize_*`)가 박고 조립이 옮긴다.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# 도장에 담기는 축들. 각 축은 (키, 만드는 함수)이고 `_OWN_AXIS`로 자기 축을 뺀다.
_AXES = ("config", "skills", "items", "tree")
# 컴포넌트 → 그 산출물 자신에 해당하는 축 (그 축은 비교에서 뺀다).
#
# ⚠ 룬·희귀는 여기 없다. 둘 다 결과가 **아이템 텍스트**로 들어가므로, 도장을
# **적용 후 스펙**에 찍으면 그 순간엔 일치하고 나중에 장비가 바뀌면 낡는다 —
# 그게 맞는 동작이다. 여기 넣으면 "무기를 바꿨는데 룬 계획은 멀쩡"이 된다.
_OWN_AXIS = {"tree": "tree", "items": "items"}


def _digest(payload: Any) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha1:" + hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _skills_view(spec: dict[str, Any]) -> tuple[Any, str]:
    """스킬 구성 → (해시 대상, 사람이 읽을 요약).

    무엇이 목적함수를 바꾸는가만 담는다: 어떤 젬을 어느 **모드**로, 어느 그룹을
    주력으로. 레벨·품질은 축을 바꾸지 않으므로 뺀다(바뀔 때마다 빨개지면 안 읽힌다).
    """
    groups = list(spec.get("skills") or [])
    payload = [
        {
            "main_active_skill": g.get("main_active_skill", 1),
            "gems": [
                {"id": gem.get("gem_id", ""), "stat_set_index": gem.get("stat_set_index")}
                for gem in (g.get("gems") or [])
            ],
        }
        for g in groups
    ]
    main_index = int(spec.get("main_socket_group") or 1)
    payload_with_main = {"main_socket_group": main_index, "groups": payload}
    desc = "(스킬 없음)"
    if 1 <= main_index <= len(groups):
        main = groups[main_index - 1]
        gems = main.get("gems") or []
        pointer = int(main.get("main_active_skill") or 1)
        if 1 <= pointer <= len(gems):
            gem = gems[pointer - 1]
            mode = gem.get("stat_set_index")
            desc = f"{main_index}({gem.get('name', '?')}" + (f"[모드 {mode}]" if mode else "") + ")"
        else:
            desc = f"{main_index}(주력 젬 지정 밖)"
    return payload_with_main, desc


def _items_view(spec: dict[str, Any]) -> tuple[Any, str]:
    items = sorted(
        (str(i.get("slot", "")), str(i.get("text", ""))) for i in (spec.get("items") or [])
    )
    return items, f"{len(items)}슬롯"


def _tree_view(spec: dict[str, Any]) -> tuple[Any, str]:
    nodes = sorted(int(n) for n in (spec.get("tree_nodes") or []))
    return nodes, f"{len(nodes)}노드"


def derivation_context(spec: dict[str, Any]) -> dict[str, Any]:
    """지금 이 스펙의 문맥 — 도장을 찍을 때도, 낡음을 판정할 때도 같은 함수를 쓴다."""
    skills_payload, skills_desc = _skills_view(spec)
    items_payload, items_desc = _items_view(spec)
    tree_payload, tree_desc = _tree_view(spec)
    return {
        # 작은 것은 **값 그대로** — diff가 바로 문장이 된다
        "config": dict(spec.get("config") or {}),
        "skills_sig": _digest(skills_payload),
        "skills_desc": skills_desc,
        "items_sig": _digest(items_payload),
        "items_desc": items_desc,
        "tree_sig": _digest(tree_payload),
        "tree_desc": tree_desc,
    }


def stamp(
    spec: dict[str, Any],
    component: str,
    *,
    tool: str,
    weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """산출 직후의 문맥을 도장으로 만든다 — 생산자가 부른다(사람이 쓰지 않는다).

    `spec`은 **산출을 반영한 뒤**의 스펙이어야 한다. 그래야 자기 축이 자기와 같다.
    """
    out = dict(derivation_context(spec))
    out["tool"] = tool
    if weights is not None:
        # weights는 스펙에 없으므로 비교 대상이 아니다 — **무엇을 상대로 최적화했나**를
        # 남기는 것이 목적이다(점화 빌드에서 `CombinedDPS` 단독은 함정이었다).
        out["weights"] = dict(weights)
    return out


def _config_diffs(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [
        f"config.{k}: {before.get(k, '(없음)')} → {after.get(k, '(없음)')}"
        for k in keys
        if before.get(k) != after.get(k)
    ]


def stale_components(spec: dict[str, Any]) -> list[dict[str, str]]:
    """스펙에 박힌 도장들과 지금 문맥을 대조 — 낡은 축을 **문장으로** 낸다.

    해시 불일치만 알리면 무용하다(보고자 지적): 「무효」라는 말을 읽고도 계승한
    이유가 **무엇이 달라서 무효인지 몰랐기 때문**이었다.
    """
    stamps = spec.get("derived_from") or {}
    if not isinstance(stamps, dict):
        return []
    now = derivation_context(spec)
    out: list[dict[str, str]] = []
    for component, mark in sorted(stamps.items()):
        if not isinstance(mark, dict):
            continue
        own = _OWN_AXIS.get(str(component))
        whys = _config_diffs(dict(mark.get("config") or {}), dict(now["config"]))
        for axis in _AXES:
            if axis == "config" or axis == own:
                continue
            key = f"{axis}_sig"
            if key in mark and mark[key] != now[key]:
                whys.append(f"{axis}: {mark.get(f'{axis}_desc', '?')} → {now[f'{axis}_desc']}")
        for why in whys:
            entry = {"component": str(component), "why": why}
            tool = str(mark.get("tool") or "")
            if tool:
                entry["advice"] = f"{tool} 재실행"
            out.append(entry)
    return out
