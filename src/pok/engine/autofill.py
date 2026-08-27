"""조립 직전 **빠진 절차를 그 자리에서 돌린다** — 거부 대신 실행 (#129).

거부는 구멍이 난다. 사용자 지적(2026-08-27): *"감지를 해서 리젝하는 방식은 지금까지도
계속 시도했는데 매번 구멍이 발생한다"*. 이유가 있다 — 거부는 **할 일을 호출자에게
되돌려주고**, 되돌려받은 쪽이 안 하면 그대로다. 실측: `skipped_procedures` 경고를
세션이 **보고서에 옮겨 적고 실행은 안 했다**.

→ **건너뛸 것 자체를 없앤다.** `derived_from`이 없는 희귀 슬롯을 만나면 그 자리에서
`optimize_rare`를 돌려 채운다.

⛔ **판단은 만들지 않는다 (철칙 3).** `optimize_rare`는 `weights`를 받는데 그것은
**빌드 판단**이라 엔진이 지어낼 수 없다. 대신 **이 빌드가 이미 선언한 가중치**를
재사용한다 — 다른 슬롯의 `derived_from[...]["weights"]`가 곧 호출자가 밝힌 판단이다.
선언이 하나도 없으면 **재사용할 판단이 없으므로 안 돌린다**(그때는 게이트가 거부한다).
즉 여기서 하는 일은 *판단*이 아니라 **선언된 판단의 적용**이다.

⚠ **손으로 쓴 아이템을 갈아 끼운다** — 조용히 하면 안 된다. 무엇을 무엇으로 바꿨는지
`replaced`에 전부 남기고, 호출자가 원치 않으면 그 슬롯에 `derived_from`을 명시해
의도를 밝히면 된다(그러면 여기 안 걸린다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

#: 희귀 등급 줄 — `derived_from` 검사 대상은 희귀뿐이다. 유니크는 고정 아이템이라
#: 최적화할 접사가 없고, 매직·일반은 애초에 조립 산출물이 아니다.
_RARE = re.compile(r"^\s*Rarity:\s*Rare\s*$", re.I | re.M)

#: 주얼 슬롯 — 자동 실행에서 **뺀다**.
#:
#: ⛔ `optimize_rare`는 주얼을 `slot="Jewel@<소켓 node_id>"`로 받는다. 스펙에 있는
#: 이름(`Gloves Jewel Socket 1`)을 그대로 넘기면 PoB가 그 주얼을 반영하지 못해
#: **델타가 전부 0**으로 나오고, 그리디는 0끼리 비교해 아무거나 고른다 — 실측
#: 2026-08-06: 그 경로로 주얼이 **저스펙으로 출고**됐다.
#: 소켓 node_id를 여기서 되짚을 수는 있지만 그건 추측이 섞인다. 대신 `skipped`로 내고
#: 호출자가 올바른 형식으로 직접 돌리게 한다 — **모르면 건드리지 않는다.**
_JEWEL = re.compile(r"\bJewel\b", re.I)


def _base_type(text: str) -> str | None:
    """아이템 텍스트에서 베이스 이름 — 희귀는 **3번째 줄**이다.

    `Rarity: RARE` / 이름 / 베이스 순서다(`legality._parse_item`과 같은 규약).
    형식이 어긋나면 None을 낸다 — **모르면 건드리지 않는다**.
    """
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    return lines[2] if len(lines) >= 3 else None


def declared_weights(spec: dict[str, Any]) -> dict[str, float] | None:
    """이 빌드가 **이미 선언한** 가중치. 없으면 None.

    ⛔ 엔진이 지어내지 않는다(철칙 3). 도장에 남은 것을 되읽을 뿐이다 — 어느 슬롯을
    최적화하며 호출자가 밝힌 판단이 그것이고, 같은 빌드의 다른 슬롯에 그대로 쓰는 것은
    **새 판단이 아니다**.

    ⚠ 우선순위는 `rares` > `items` > 나머지다. 희귀 슬롯을 채우는 것이므로 같은
    도구가 쓰던 축이 가장 가깝다.
    """
    stamps = spec.get("derived_from") or {}
    if not isinstance(stamps, dict):
        return None
    for key in ("rares", "items", *sorted(stamps)):
        entry = stamps.get(key)
        if isinstance(entry, dict):
            weights = entry.get("weights")
            if isinstance(weights, dict) and weights:
                return {str(k): float(v) for k, v in weights.items()}
    return None


def unstamped_rares(spec: dict[str, Any]) -> list[dict[str, str]]:
    """`derived_from`이 없는 희귀 슬롯 — 손으로 지었을 가능성이 있는 것들.

    ⛔ **복원본은 세지 않는다.** `restore_pob_spec`으로 남의 빌드를 읽으면 도장이
    있을 수 없다 — 거기서 갈아 끼우면 **읽어 온 빌드가 다른 빌드가 된다**(§0 ⑪).
    """
    if spec.get("restored_from"):
        return []
    out: list[dict[str, str]] = []
    for item in spec.get("items") or ():
        if not isinstance(item, dict) or item.get("derived_from"):
            continue
        text = str(item.get("text") or "")
        if not _RARE.search(text):
            continue
        slot, base = str(item.get("slot") or ""), _base_type(text)
        if not slot or not base:
            continue
        if _JEWEL.search(slot):
            out.append({"slot": slot, "base_type": base, "jewel": "1"})
            continue
        out.append({"slot": slot, "base_type": base})
    return out


class _Optimizer(Protocol):
    def __call__(
        self, spec: dict[str, Any], slot: str, base_type: str, weights: dict[str, float]
    ) -> Any: ...


@dataclass
class AutofillReport:
    """무엇을 돌렸고 무엇을 못 돌렸나 — **양쪽 다** 낸다."""

    #: 갈아 끼운 슬롯. `{slot, base_type, before, after, delta}`
    replaced: list[dict[str, Any]] = field(default_factory=list)
    #: 돌려야 했는데 못 돌린 슬롯과 사유 — 침묵하면 「다 했다」로 읽힌다
    skipped: list[dict[str, str]] = field(default_factory=list)
    #: 재사용한 가중치(호출자가 선언한 것). None이면 아무것도 안 돌렸다
    weights: dict[str, float] | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ran(self) -> bool:
        return bool(self.replaced)


def autofill_rares(
    spec: dict[str, Any], optimize: _Optimizer, *, limit: int = 6
) -> tuple[dict[str, Any], AutofillReport]:
    """도장 없는 희귀 슬롯을 `optimize_rare`로 채운 **새 스펙**과 보고를 낸다.

    `optimize`는 주입받는다 — 엔진이 PoB 실행 경로를 직접 잡으면 시험이 PoB에 묶인다.

    `limit`은 폭주 방지다. 슬롯당 1~2분이라 한 번에 여러 칸이 걸리면 조립이 통째로
    길어진다 — 넘치면 **자른 사실을 `skipped`에 남긴다**(조용히 자르면 「다 했다」로 읽힌다).
    """
    report = AutofillReport()
    targets = unstamped_rares(spec)
    if not targets:
        return spec, report

    weights = declared_weights(spec)
    if weights is None:
        # ⛔ 재사용할 선언이 없다 — 여기서 가중치를 **지어내면** 엔진이 빌드 판단을
        # 하는 것이다(철칙 3). 안 돌리고 사유를 낸다. 게이트가 그때 거부한다.
        report.skipped = [
            {
                **t,
                "why": "선언된 weights가 없다 — optimize_rare를 한 번 돌려 판단을 밝힐 것",
            }
            for t in targets
        ]
        report.notes.append(
            "가중치 선언이 없어 자동 실행을 건너뛰었다 — 엔진은 빌드 판단을 지어내지 않는다(철칙 3)"
        )
        return spec, report

    report.weights = weights
    if len(targets) > limit:
        report.skipped = [
            {**t, "why": f"한 번에 {limit}칸까지만 자동 실행한다 — 이 슬롯은 직접 돌릴 것"}
            for t in targets[limit:]
        ]
        targets = targets[:limit]

    out = spec
    for target in targets:
        slot, base = target["slot"], target["base_type"]
        if target.get("jewel"):
            report.skipped.append(
                {
                    "slot": slot,
                    "base_type": base,
                    "why": (
                        '주얼은 optimize_rare(slot="Jewel@<소켓 node_id>")로 직접 '
                        "돌릴 것 — 슬롯 이름을 그대로 넘기면 PoB가 반영하지 못해 "
                        "델타가 전부 0이 되고 저스펙이 나간다(실측 2026-08-06)"
                    ),
                }
            )
            continue
        before = next(
            (str(i.get("text") or "") for i in (out.get("items") or ()) if i.get("slot") == slot),
            "",
        )
        try:
            result = optimize(out, slot, base, weights)
        # 한 칸이 실패해도 나머지는 채운다 — 하나 때문에 전부 멈추면 거부와 같아진다
        except Exception as exc:
            report.skipped.append({**target, "why": f"optimize_rare 실패: {exc}"})
            continue
        text = getattr(result, "text", None)
        if not text:
            report.skipped.append({**target, "why": "optimize_rare가 텍스트를 못 냈다"})
            continue
        items = [dict(i) for i in (out.get("items") or ()) if str(i.get("slot")) != slot]
        items.append({"slot": slot, "text": text, "derived_from": {"tool": "optimize_rare"}})
        out = {**out, "items": items}
        report.replaced.append(
            {
                "slot": slot,
                "base_type": base,
                "before": before,
                "after": text,
                "delta": getattr(result, "delta", None),
            }
        )
    return out, report
