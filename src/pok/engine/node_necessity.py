"""왜 「측정 0」인데 채택되나 — 조건부 필요성 판정 큐 (사용자 지시 2026-08-20).

## 전제를 뒤집는다

옛 도구는 「DPS·EHP가 안 움직임」을 **「가치 없음」**으로 뒤집어 habit 도장을 찍었다.
실측 사고: `Vitality Siphon`(주문 피해 20% 생명력 흡수, 블러드 메이지 채택 67%)이
그렇게 찍혀 「갈아탈 예산」 제안이 나갔다 — 블러드 메이지는 `Sanguimancy`로 **생명력을
내고 시전**하므로 흡수를 빼면 유지가 무너진다.

**패시브 노드에 가치 없는 노드는 없다**(사용자 정리) — 중요도가 낮은 노드는 있어도.
그러니 「측정 0 + 채택됨」은 결함 신호가 아니라 **축을 못 잡았다는 신호**다.

## 형태 — 조건부 필요성

    노드      Vitality Siphon (채택 67% · DPS·EHP 무변동)
    제공      생명력 흡수
    요구 기재  Sanguimancy — "Skills gain a Base Life Cost equal to Base Mana Cost"
    판정      생명력으로 시전하는 빌드는 흡수 없이 유지가 안 된다 → 필수
    반대      생명력 비용 기재가 없는 빌드는 채용 불필요

앞의 셋은 결정적으로 나온다(이 모듈). **판정·반대는 에이전트가 근거를 찾아 쓴다** —
KB 원문·PoB 소스·웹. ⛔ 근거 경로 없는 판정은 받지 않는다(제안 계약의 `route`와 같은
사상): 「그럴 것 같다」가 정본에 들어가면 그게 오염이다.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── 제공 축 — 노드가 **무엇을 주나** ────────────────────────────────────
#
# 앞의 것이 이긴다(긴/특수 표현 먼저). 측정 축(CombinedDPS·Life·TotalEHP)에 안 잡히는
# 것만 실린다 — 잡히는 것은 애초에 이 큐에 안 온다.
SUPPLY_AXES: tuple[tuple[str, str], ...] = (
    ("생명력 흡수", r"Life Leech|Leeched as Life"),
    ("마나 흡수", r"Mana Leech|Leeched as Mana"),
    ("흡수 일반", r"\bLeech"),
    ("생명력 재생", r"Life Regenerat"),
    ("마나 재생", r"Mana Regenerat"),
    ("에너지 실드 재충전", r"Energy Shield Recharge"),
    ("재생 일반", r"Regenerat"),
    ("회수", r"Recoup"),
    ("회복", r"Recover|Recovery"),
    ("자원 비용", r"Cost Efficiency|\bCost of Skills|\bMana Cost|\bLife Cost"),
    ("점유", r"Reserv"),
    ("정신력", r"\bSpirit\b"),
    ("충전 생성", r"gain .* Charge|Charge on|additional .* Charge"),
    ("충전 유지", r"Charge"),
    ("이동", r"Movement Speed"),
    ("기절·경직", r"\bStun\b|\bDaze\b"),
    ("상태이상 임계", r"Ailment Threshold|Buildup"),
    ("저항", r"Resistance"),
    ("플라스크", r"Flask"),
    ("호신부", r"Charm"),
    ("발현", r"Presence"),
    ("소환수", r"Minion|Allies"),
    ("범위", r"Area of Effect"),
    ("투사체", r"Projectile"),
    ("명중", r"Accuracy"),
    ("차단", r"\bBlock\b"),
    ("회피 판정", r"Evade|Dodge"),
)
_SUPPLY = tuple((name, re.compile(p, re.I)) for name, p in SUPPLY_AXES)

# ── 요구 — 그 축을 **필요하게 만드는** 문구 ─────────────────────────────
#
# 요구는 「이 축을 소모한다」거나 「이 축이 없으면 성립 안 한다」는 선언이다.
# 축마다 어떤 문구가 요구인지는 게임 규칙이라 여기 표로 든다 — ⛔ 추측하지 않는다.
DEMAND_PATTERNS: dict[str, tuple[str, ...]] = {
    "생명력 흡수": (r"Life Cost", r"Reserves? .*Life", r"Pay .*Life", r"lose .*Life"),
    "흡수 일반": (r"Life Cost", r"Mana Cost"),
    "마나 흡수": (r"Mana Cost", r"Reserves? .*Mana"),
    "생명력 재생": (r"Life Cost", r"degeneration", r"Reserves? .*Life"),
    "마나 재생": (r"Mana Cost", r"Reserves? .*Mana"),
    "자원 비용": (r"Life Cost", r"Mana Cost"),
    "점유": (r"Reserv",),
    "정신력": (r"Reserves? .*Spirit", r"Spirit Cost"),
    "충전 생성": (r"consume .*Charge", r"remove .*Charge", r"per .*Charge"),
    "충전 유지": (r"per .*Charge", r"consume .*Charge"),
    "상태이상 임계": (r"Stun", r"Ailment"),
    "플라스크": (r"Flask",),
    "호신부": (r"Charm",),
    "발현": (r"Presence",),
    "소환수": (r"Minion",),
}


@dataclass(frozen=True)
class NecessityCase:
    """판정 대기 1건 — 앞의 셋은 결정적, 판정·반대는 에이전트 몫이다."""

    node_id: int
    name_en: str
    kind: str
    adoption_ci_low: float
    stats_en: tuple[str, ...]
    supply_axis: str | None  # 무엇을 주나 (None = 분류 실패 — 어휘 갭이다)
    demand_carriers: tuple[dict[str, str], ...] = field(default=())
    measured: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        """에이전트에게 넘길 수 있나 — 축을 못 잡았으면 어휘부터 고쳐야 한다."""
        return self.supply_axis is not None


def classify_supply(stats_en: Sequence[str]) -> str | None:
    """이 노드가 **무엇을 공급하나**. 모르면 None — 지어내지 않는다."""
    for line in stats_en:
        for name, pattern in _SUPPLY:
            if pattern.search(line):
                return name
    return None


def demand_carriers(
    axis: str, records: Any, *, limit: int = 6, for_ascendancy: str | None = None
) -> list[dict[str, str]]:
    """그 축을 **요구하는** 기재 후보. 근거 문구를 함께 낸다(AD-8).

    ⛔ 여기서 「이 노드가 필요하다」고 결론내지 않는다 — 후보와 근거까지다.

    `for_ascendancy`를 주면 **같은 전직 기재를 먼저** 낸다. 전직 노드의 요구원은
    보통 그 전직 자신이다 — 실측 2026-08-20: `Vitality Siphon`(Witch2)의 요구원인
    `Sanguimancy`(Witch2, "Skills gain a Base Life Cost equal to Base Mana Cost")가
    전 KB 사전순 정렬에서 유니크들에 밀려 후보에 안 들어왔다.
    """
    patterns = [re.compile(p, re.I) for p in DEMAND_PATTERNS.get(axis, ())]
    if not patterns:
        return []
    scored: list[tuple[int, dict[str, str]]] = []
    for rid, record in records.items():
        if record.type not in {"Passive", "Item", "Mechanic", "Skill"}:
            continue
        data = record.raw.get("data") or {}
        lines = [
            *(data.get("stats_en") or []),
            *(data.get("explicits") or []),
            *(data.get("stats") or []),
        ]
        for line in lines:
            hits = sum(1 for p in patterns if p.search(str(line)))
            if hits:
                # 여러 패턴에 걸릴수록 그 축의 **핵심 요구원**일 확률이 높다.
                # ⛔ 사전 순으로 자르면 Sanguimancy 같은 전직 핵심이 밀려난다
                #    (실측 2026-08-20: 첫 구현이 그랬다).
                same_asc = bool(for_ascendancy and (data.get("ascendancy") or "") == for_ascendancy)
                scored.append(
                    (
                        hits + (10 if same_asc else 0),
                        {
                            "id": rid,
                            "name": str((record.raw.get("name") or {}).get("en") or rid),
                            "type": record.type,
                            "evidence": str(line)[:120],
                        },
                    )
                )
                break
    scored.sort(key=lambda kv: (-kv[0], kv[1]["id"]))
    return [row for _score, row in scored[:limit]]


def build_queue(
    *, min_adoption: float = 20.0, min_n: int = 15, limit: int | None = None
) -> list[NecessityCase]:
    """판정 큐 — **채택되는데 측정 0인 노드** 전량.

    ⚠ 「측정 0」은 결함이 아니라 **축을 못 잡았다는 신호**다. 채택률 문턱을 두는
    이유는 「아무도 안 찍는 노드」까지 판정할 필요는 없어서이지, 낮으면 가치가
    없어서가 아니다.
    """
    import glob
    import json

    from pok.common.paths import knowledge_dir
    from pok.engine.tree.graph import TreeGraph
    from pok.kb.store import load

    kb = knowledge_dir()
    graph = TreeGraph(kb)
    records = load().records

    values: dict[int, dict[str, Any]] = {}
    for path in glob.glob(str(kb / "game-data" / "tree" / "node-values-*.ndjson")):
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if line.strip():
                data = json.loads(line)["data"]
                values[int(data["node"]["node_id"])] = data

    node_of = {
        rid: int(r.raw["data"]["node_id"])
        for rid, r in records.items()
        if r.type == "Passive" and (r.raw.get("data") or {}).get("node_id") is not None
    }
    adoption: dict[int, float] = {}
    for path in glob.glob(str(kb / "game-data" / "usage-profiles" / "*.json")):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        for key in ("passives", "keystones"):
            for entry in doc["data"]["observed"].get(key, []):
                nid = node_of.get(entry["ref"])
                if nid and entry.get("ci_low", 0) > adoption.get(nid, 0):
                    adoption[nid] = float(entry["ci_low"])

    out: list[NecessityCase] = []
    for nid, value in sorted(values.items()):
        ci_low = adoption.get(nid, 0.0)
        if ci_low < min_adoption:
            continue
        axes = value.get("axes") or {}
        dps, ehp = axes.get("CombinedDPS") or {}, axes.get("TotalEHP") or {}
        if int(dps.get("n") or 0) < min_n:
            continue
        # 둘 중 하나라도 움직였으면 측정 축 안이다 — 이 큐의 대상이 아니다
        if dps.get("active_share") or ehp.get("active_share"):
            continue
        node = graph.nodes.get(nid)
        if node is None:
            continue
        axis = classify_supply(node.stats_en)
        out.append(
            NecessityCase(
                node_id=nid,
                name_en=node.name_en,
                kind=node.kind,
                adoption_ci_low=ci_low,
                stats_en=tuple(node.stats_en),
                supply_axis=axis,
                demand_carriers=tuple(
                    demand_carriers(axis, records, for_ascendancy=node.ascendancy)
                )
                if axis
                else (),
                measured={
                    "CombinedDPS_n": int(dps.get("n") or 0),
                    "note": "DPS·EHP 어느 빌드에서도 안 움직였다 — 축을 못 잡은 것이다",
                },
            )
        )
    out.sort(key=lambda c: -c.adoption_ci_low)
    return out[:limit] if limit else out
