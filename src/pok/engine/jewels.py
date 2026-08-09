"""반경 주얼 표기 — `Radius:` 선언이 없으면 **조용히 0**이 된다 (백로그 제안 B).

## 발의의 진단은 틀렸다

제안 B는 *"PoB `ModParser`에 패턴이 없어 파싱되지 않는다"*로 봤다. **패턴은 있다** —
`Modules/ModParser.lua:7041`의 `^(%w+) Passive Skills in Radius also grant (.*)$`가
부여 문구를 재귀 파싱하고 `CalcSetup.lua`의 `runRadiusJewelFunc`이 반경 안 노드에 돌린다.

진짜 원인은 **우리가 반경을 선언하지 않은 것**이다. 실측 2026-08-09
(`Time-Lost Diamond`, 반경 내 할당 노터블 6개, 「노터블당 주문 치명타 10%」):

    주얼 없음                     CritChance 10.44
    반경 선언 없음                        10.44   ← Δ0, 조용히 빠진다
    Radius: Small                        12.24
    Radius: Medium / Large               13.14
    Radius: Very Large                   15.84

반경이 커질수록 값이 오른다 — PoB는 **정상적으로 계산한다.** 선언이 없으면 반경이
정해지지 않아 아무 노드도 안 걸릴 뿐이다. 그래서 "서로 다른 소켓의 델타가 동일"이라는
증상이 나왔다 — 어느 소켓이든 0이었던 것이다.

룬(#33)과 **같은 계열**이다: 선언이 없으면 오류가 아니라 **조용한 과소 계상**이 된다.

## 반경을 우리가 정하지 않는다

어느 반경인지는 아이템이 정하는 값이라 **추측하면 안 된다.** 그래서 이 모듈은
`Radius:` 누락을 **감지해 알리고**, 넣는 것은 호출자가 라벨을 골라 `render_radius_jewel`
로 한다. 모르는 것을 지어내지 않는다.
"""

from __future__ import annotations

import re

# PoB가 읽는 반경 라벨. 실효 반경은 `tree.clusters.JEWEL_RADII` 참고(표기의 1.2배).
RADIUS_LABELS: tuple[str, ...] = ("Small", "Medium", "Large", "Very Large")

# `Notable Passive Skills in Radius also grant …` 꼴 — 반경이 있어야 의미가 있는 줄
_RADIUS_GRANT = re.compile(r"\bPassive Skills in Radius\b", re.I)
_RADIUS_DECL = re.compile(r"^\s*Radius:\s*(.+?)\s*$", re.I | re.M)


def declared_radius(item_text: str) -> str | None:
    """아이템 텍스트가 선언한 반경 라벨 (없으면 None)."""
    match = _RADIUS_DECL.search(item_text)
    return match.group(1) if match else None


def needs_radius_declaration(item_text: str) -> bool:
    """반경 부여 줄이 있는데 `Radius:` 선언이 없는가 — **조용한 0**의 조건."""
    return bool(_RADIUS_GRANT.search(item_text)) and declared_radius(item_text) is None


def render_radius_jewel(item_text: str, radius: str) -> str:
    """반경 선언을 붙인다(이미 있으면 갈아 끼운다).

    ⛔ 반경을 엔진이 고르지 않는다 — 호출자가 그 주얼의 실제 반경을 준다.
    """
    if radius not in RADIUS_LABELS:
        raise ValueError(f"모르는 반경 라벨 {radius!r} — 허용: {list(RADIUS_LABELS)}")
    lines = [ln for ln in item_text.splitlines() if not ln.lower().startswith("radius:")]
    # 베이스 줄 바로 뒤가 PoB 관례다(스펙 줄 구역).
    head, rest = lines[:3], lines[3:]
    return "\n".join([*head, f"Radius: {radius}", *rest])
