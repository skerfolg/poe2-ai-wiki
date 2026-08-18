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
# 타임리스 주얼 — 반경 안 패시브를 **다른 것으로 바꾼다**(Conquered). 옵션을 얹는
# 반경 주얼과 종류가 다르다: 노드의 **의미 자체**가 달라져, 그 주얼을 뺀 상태에서
# 잰 노드 델타는 그 노드의 값이 아니다.
_TIMELESS = re.compile(r"\bTimeless Jewel\b", re.I)


def declared_radius(item_text: str) -> str | None:
    """아이템 텍스트가 선언한 반경 라벨 (없으면 None)."""
    match = _RADIUS_DECL.search(item_text)
    return match.group(1) if match else None


def needs_radius_declaration(item_text: str) -> bool:
    """반경 부여 줄이 있는데 `Radius:` 선언이 없는가 — **조용한 0**의 조건."""
    return bool(_RADIUS_GRANT.search(item_text)) and declared_radius(item_text) is None


# ── 어느 링인가 (BACKLOG #71) ────────────────────────────────────────────────
#
# `Radius:` 라벨만으로는 부족하다. PoB에서 실제 반경을 정하는 것은 **모드 문구**다
# (`ModParser.lua:5512-5524`) — 아이템이 "only affects passives in massive ring"처럼
# 링을 **지목**하고, 그 번호가 `Data.lua`의 12개 표를 가리킨다.
_FIXED_INDEX: dict[str, int] = {"small": 1, "medium": 2, "large": 3, "very large": 4}
# 링 이름 → PoB radiusIndex. **긴 이름을 먼저** 봐야 한다("very small"이 "small"에
# 먹히면 안 된다).
_RING_INDEX: tuple[tuple[str, int], ...] = (
    ("medium-small", 7),
    ("medium-large", 9),
    ("very small", 5),
    ("very large", 11),
    ("massive", 12),
    ("medium", 8),
    ("small", 6),
    ("large", 10),
)
_RING_DECL = re.compile(r"(?:only )?affects passives in ([a-z -]+?) ring", re.I)
# Time-Lost 계열의 반경 승급 — 부여 문구가 `Radius:` 라벨을 덮어쓴다
_UPGRADE = re.compile(r"upgrades radius to (medium|large|very large)", re.I)


def radius_index(item_text: str) -> int | None:
    """이 주얼이 실제로 쓰는 PoB `radiusIndex` (모르면 None).

    우선순위는 PoB를 따른다: **링 지목 문구 > 반경 승급 > `Radius:` 라벨**.
    링 지목이 있으면 라벨은 표시용이라 무시된다 — `Controlled Metamorphosis`가
    `Radius: Variable`이라고만 적고 "Only affects Passives in Massive Ring"으로
    실제 링을 말하는 것이 그 예다.
    """
    ring = _RING_DECL.search(item_text)
    if ring:
        want = " ".join(ring.group(1).split()).lower()
        for name, idx in _RING_INDEX:
            if want == name or want.endswith(name):
                return idx
    upgrade = _UPGRADE.search(item_text)
    if upgrade:
        return _FIXED_INDEX[upgrade.group(1).strip().lower()]
    label = (declared_radius(item_text) or "").strip().lower()
    return _FIXED_INDEX.get(label)


def effective_radius(item_text: str) -> tuple[float, float] | None:
    """실효 (inner, outer) — **도넛이면 inner 안쪽은 안 덮는다**.

    ⛔ inner를 버리고 원으로 재면 덮는 노드를 과대평가한다(BACKLOG #71). Variable
    링 8개는 전부 도넛이고, 가장 작은 것(5번)은 780~1140이라 소켓 바로 옆 노드가
    **안 걸린다**.
    """
    from pok.engine.tree.clusters import JEWEL_RADIUS_BY_INDEX

    idx = radius_index(item_text)
    return JEWEL_RADIUS_BY_INDEX.get(idx) if idx is not None else None


# 「반경 안 패시브를 **길 없이** 찍을 수 있다」 — PoB `ModParser.lua:5511`의
# intuitiveLeapLike 꼴(From Nothing · Controlled Metamorphosis).
_NOCONN = re.compile(r"can be Allocated\s+without being connected", re.I)


def allocates_without_path(item_text: str) -> bool:
    """이 주얼이 반경 안 노드의 **연결 요건을 없애는가**.

    이런 주얼이 있으면 그래프 연결성으로 「성립하는 트리」를 판정하면 안 된다 —
    반경 안 노드는 길이 안 닿아도 인게임에서 찍힌다. 코퍼스의 48.8%가 보유
    (From Nothing 1,193벌 · Controlled Metamorphosis 275벌, BACKLOG #87).
    """
    return bool(_NOCONN.search(item_text))


def is_timeless(item_text: str) -> bool:
    """타임리스 주얼인가 — **트리를 바꾸는** 주얼이라 따로 다뤄야 한다.

    반경 주얼은 반경 안 노드에 옵션을 **얹는다**. 타임리스는 반경 안 패시브를
    **다른 것으로 바꾼다**("Passives in radius are Conquered by …"). 그래서 이 주얼을
    뗀 채로 잰 노드 델타는 그 노드의 값이 아니다 — 같은 노드가 다른 것이 된다.

    실측 2026-08-18(래더 타이탄): `Undying Hate` 하나를 빼자 EHP 16,507 → 1,093
    (6.6%)로 무너졌다. 반경 안 할당 노드는 겨우 몇 개인데도 그렇다. 코퍼스 1,175벌
    중 106벌(9.0%)이 타임리스를 들고 있어 예외로 넘길 비율이 아니다.
    """
    return bool(_TIMELESS.search(item_text))


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
