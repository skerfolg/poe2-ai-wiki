"""`exclude_nodes` — 설계 판단으로 뺀 노드를 그리디가 다시 뽑지 않게 (제안 A 일부).

그리디는 배타 관계를 모른다. 실측 2026-08-09: 원소 집정관 축을 위해 「검은화염 계약」
(집정관의 `Cannot deal Non-Elemental Damage with Spells`와 정면 충돌)을 손으로 뺐는데,
재실행하자 남은 8포인트로 **그것과 「피의 제물」을 그대로 재채택**했다. PoB가 집정관을
모델링하지 않아(#3) 충돌이 점수에 안 보이기 때문이다.

배타 **감지**는 어렵지만 배타 **지정**은 호출자가 할 수 있다(AD-3: 판단은 호출자).
"""

from __future__ import annotations

import inspect

from pok.engine.tree.optimize import optimize_tree


def test_exclude_nodes_seeds_the_banned_set() -> None:
    """제외 노드는 후보 필터가 이미 쓰는 `banned`에 그대로 들어간다.

    별도 경로를 만들지 않은 것이 요점이다 — 재채택 금지 로직이 하나뿐이라
    "여기선 막고 저기선 안 막힌다"가 생기지 않는다.
    """
    source = inspect.getsource(optimize_tree)
    assert "banned: set[int] = set(exclude_nodes)" in source
    signature = inspect.signature(optimize_tree)
    assert signature.parameters["exclude_nodes"].default == ()


def test_mcp_adapter_passes_exclusions_through() -> None:
    from pok.mcp.tools.tree import optimize_tree as mcp_optimize

    signature = inspect.signature(mcp_optimize)
    assert "exclude_nodes" in signature.parameters
    assert "검은화염 계약" in (mcp_optimize.__doc__ or ""), "왜 필요한지가 도구 설명에 있어야 한다"
