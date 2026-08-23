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
# 축마다 **어떻게 재나** — 이게 판정의 절반이다.
#   "config"   PoB가 계산할 수 있는데 **토글이 꺼져** 0으로 보인다 → 켜고 다시 재면 된다
#   "trigger"  발동률 모델이 따로 있다(`compute_trigger_rate`)
#   None       측정 경로가 아예 없다 → 에이전트 판정 + 갭 라벨
#
# ⚠ 「못 재는 것」과 「안 켠 것」을 가르는 것이 요점이다. 실측 2026-08-20:
#    `Predatory Instinct`("50% more damage against Rare and Unique")는 PoB가 계산할
#    수 있는데 config가 꺼져 0으로 나왔다 — 이걸 「측정 밖」으로 묶으면 켜서 잴 수
#    있는 것을 영영 안 잰다(#44의 반대 실수).
# ⚠ **실측으로 검증한 목록이다**(2026-08-22). 14건에 프로파일을 켜 보고 실제로 값이
#    난 축만 남겼다 — 6/14만 움직였고, 나머지는 「config를 켜면 잰다」가 **내 추측**
#    이었다. 켜도 0인 것은 config 문제가 아니라 PoB 모델 갭이다(#101 계열).
#    실측 결과: 상태이상 계열(감전·빙결·약점)만 config로 열린다.
MEASURABLE_VIA: dict[str, str] = {
    "조건부 배율": "config",
    "추가 피해 변환": "config",
    "상태이상 강도·지속": "config",
    "상태이상 중첩": "config",
    "발동 자원 환급": "trigger",
    "상태이상 임계": "config",
    "발동 주기": "trigger",
    # 감속이 config에 안 켜져 있어 0으로 보인다 — Predatory Instinct와 동형(배치 B)
    "이동 제약 무효": "config",
}

SUPPLY_AXES: tuple[tuple[str, str], ...] = (
    # ── 메커니즘 부여·구조 변경 (문구가 특수하므로 먼저) ──
    ("스킬 부여", r"Grants Skill|Grants Sands|Can tattoo"),
    ("발동 주기", r"instead Trigger|Trigger .* every"),
    ("쿨다운", r"Cooldown Uses|Cooldown Recovery"),
    ("자원 대체", r"is replaced by|Costs? Converted"),
    ("소켓 변형", r"Rune-only sockets|Base Type transformed"),
    ("추가 투사체", r"additional Arrow|additional Projectile"),
    ("배치", r"Placement (?:speed|range)"),
    ("이동 제약 무효", r"unaffected by Slows|cannot be Slowed"),
    ("조건부 배율", r"if you've|against Rare and Unique|Recently, up to|more damage against"),
    ("버프 스택", r"Tailwind|Combo\b|Infusion|Remnants?\b|stack of|minimum of \d+ Power"),
    ("추가 피해 변환", r"Gain \d+% of .* as Extra"),
    ("연쇄 폭발", r"to Explode|create an additional"),
    ("반복 시전", r"chance to Echo|Repeatable Spells"),
    ("상태이상 강도·지속", r"Magnitude of|Shock Duration|Ailment Duration"),
    ("상태이상 중첩", r"affected by two of your"),
    # ⚠ `Cannot be X`(면역 = **이득**)와 `Cannot X`(제약 = **대가**)는 구문으로 갈린다 —
    #    수동태면 면역이다. 실측: `Unwavering Stance`의 "Cannot be Light Stunned"가
    #    이득인데 "Cannot Dodge Roll"과 같이 대가로 묶여 축을 놓쳤다(판정 배치 B).
    ("면역", r"\bImmune to|\bCannot be \w+"),
    ("발동 자원 환급", r"refund .* Energy"),
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
    # ⚠ `Reserv`는 "**Un**reserved"에도 걸린다 — 플라스크 노드가 점유로 오분류됐다
    ("점유", r"(?<!Un)(?<!un)Reserv"),
    ("정신력", r"\bSpirit\b"),
    ("충전 생성", r"gain .* Charge|Charge on|additional .* Charge"),
    ("충전 유지", r"Charge"),
    ("이동", r"Movement Speed"),
    # ⚠ `\bStun\b`는 "Stunned"·"Stunning"에 안 걸린다 — 배치 C가 잡았다
    ("기절·경직", r"\bStun\w*\b|\bDaze\w*\b"),
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
    # 어떻게 재나 — "config"(토글 켜면 잰다) · "trigger"(발동률 모델) · None(경로 없음)
    measurable_via: str | None = None
    demand_carriers: tuple[dict[str, str], ...] = field(default=())
    measured: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        """에이전트에게 넘길 수 있나 — 축을 못 잡았으면 어휘부터 고쳐야 한다."""
        return self.supply_axis is not None


# 「대가」 줄 — 이 줄에서 축을 뽑으면 **비용을 공급으로 오독**한다.
# 실측(판정 배치 B): `Unwavering Stance`의 2줄 "Cannot Dodge Roll or Sprint"에서
# "Dodge"를 잡아 `회피 판정`으로 분류했는데, 실제 공급은 1줄의 기절 면역이고
# 2줄은 대가다. 키스톤은 「이득 + 대가」 구조라 이 오독이 구조적으로 반복된다.
# ⚠ `Cannot be …`는 **제외한다** — 그건 면역이라 이득이다(위 축 표 참조).
_COST_LINE = re.compile(r"^\s*(?:Cannot(?! be)|You cannot(?! be)|-\d|\d+% (?:less|reduced))", re.I)


def classify_supply(stats_en: Sequence[str]) -> str | None:
    """이 노드가 **무엇을 공급하나**. 모르면 None — 지어내지 않는다.

    ⛔ 대가 줄(`Cannot …`·`N% less …`)은 건너뛴다 — 거기서 축을 뽑으면 비용이
    공급으로 둔갑한다. 대가 줄밖에 없으면 마지막에 그것으로라도 분류한다(무분류보다 낫다).
    """
    for line in stats_en:
        if _COST_LINE.search(line):
            continue
        for name, pattern in _SUPPLY:
            if pattern.search(line):
                return name
    for line in stats_en:  # 대가 줄뿐인 노드 — 없는 것보다 낫다
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
    # ⛔ **자기 자신을 질의로 삼은 프로파일은 세지 않는다** (판정 배치 B가 잡았다).
    #    `keypassives-<노드>` 프로파일 27종은 **그 노드를 가진 빌드만** 뽑은 표본이라
    #    자기 채택률 100%는 정의상 참이다 — 동어반복이다. 이걸 「채택 92.9」로 읽으면
    #    「전원이 찍는 필수」로 오독하고, 실제로 그렇게 오독해 큐를 만들었다.
    #    실측: Unwavering Stance는 그 표본에서도 **트리 배정 42%**(58%는 룬·장비)다.
    adoption: dict[int, float] = {}
    for path in glob.glob(str(kb / "game-data" / "usage-profiles" / "*.json")):
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        anchor_ref = str((doc["data"].get("anchor") or {}).get("ref") or "")
        for key in ("passives", "keystones"):
            for entry in doc["data"]["observed"].get(key, []):
                if entry["ref"] == anchor_ref:
                    continue  # 앵커 자신 — 이 표본은 그 노드로 걸러 뽑았다
                nid = node_of.get(entry["ref"])
                if nid and entry.get("ci_low", 0) > adoption.get(nid, 0):
                    adoption[nid] = float(entry["ci_low"])

    out: list[NecessityCase] = []
    for nid, value in sorted(values.items()):
        ci_low = adoption.get(nid, 0.0)
        if ci_low < min_adoption:
            continue
        axes = value.get("axes") or {}
        dps = axes.get("CombinedDPS") or {}
        if int(dps.get("n") or 0) < min_n:
            continue
        # ⛔ **어느 축에서든 움직였으면 잰 것이다 — 전 축을 본다.**
        #    DPS·EHP만 보면 축 확장(#100)의 이득이 큐에 반영되지 않는다. 실측
        #    2026-08-22: 축을 13개로 넓혀 `Vitality Siphon`이 `LifeLeechGainRate`
        #    55벌 전부 100% 손실로 잡혔는데도, 필터가 DPS·EHP만 봐서 「측정 0」 큐에
        #    그대로 남았다 — 6시간 재측정의 이득이 큐에서 증발할 뻔했다.
        # ⛔ **오염 포함본까지 본다**(#99) — 제외본의 0이 「표본을 버린 뒤의 0」인
        #    경우가 39건 있었다(Invigorating Archon: 잔존 7.4%인데 포함하면 92.0%).
        if any(
            axis.get("active_share") or (axis.get("with_tainted") or {}).get("active_share", 0) > 0
            for axis in axes.values()
        ):
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
                measurable_via=MEASURABLE_VIA.get(axis or ""),
                demand_carriers=tuple(
                    demand_carriers(axis, records, for_ascendancy=node.ascendancy)
                )
                if axis
                else (),
                measured={
                    "CombinedDPS_n": int(dps.get("n") or 0),
                    # 오염 제외로 표본이 얼마나 줄었나 — 낮으면 결론을 약하게 낼 것
                    "kept_pct": (dps.get("with_tainted") or {}).get("kept_pct"),
                    "note": "DPS·EHP가 **오염 포함본에서도** 안 움직였다 — "
                    "축을 못 잡은 것이다(#99 반영)",
                },
            )
        )
    out.sort(key=lambda c: -c.adoption_ci_low)
    return out[:limit] if limit else out


# ── 판정 계약 — 에이전트가 쓰고, 근거 없으면 거부한다 ──────────────────
#
# 「기계적으로 안 되는 것은 LLM이 판단한다」(사용자 지시 2026-08-20). 다만 판단에는
# **출처**가 붙어야 한다 — 「그럴 것 같다」가 정본에 들어가면 그게 오염이다.
# M5 제안 계약의 `route`와 같은 사상이고, 여기서는 `evidence`가 그 자리다.
EVIDENCE_SOURCES: dict[str, str] = {
    "kb": "KB 정본 레코드 — id와 문구를 인용",
    "pob-source": "PoB 소스(ModParser·Calcs 등) — 파일:줄",
    "wiki": "커뮤니티 위키·공식 패치노트 — URL",
    "measured": "PoB 실측 — config 토글 전후 수치",
}


class NecessityError(ValueError):
    """판정이 계약을 못 지켰을 때 — 무엇이 왜 빠졌는지 문장으로."""


def validate_verdict(doc: dict[str, Any]) -> dict[str, Any]:
    """에이전트 판정 1건을 검증한다.

    필수 넷: `node_id` · `verdict`(필요한 이유) · `counter`(불필요한 조건) ·
    `evidence`(출처 목록). ⛔ `evidence`가 비면 거부한다 — 근거 없는 판정은
    「측정된 것」으로 굳어 정본을 오염시킨다(M5 함정 ②와 같은 형태).
    """
    missing = [k for k in ("node_id", "verdict", "counter", "evidence") if not doc.get(k)]
    if missing:
        raise NecessityError(
            f"판정에 {missing}이 없다 — 「무엇을 주는가」는 도구가 이미 냈고, "
            "에이전트가 낼 것은 **필요한 이유**(verdict)·**불필요한 조건**(counter)·"
            "**출처**(evidence)다. 사용자 지시 2026-08-20: 근거 경로 없는 판정은 안 받는다"
        )
    rows = []
    for item in doc["evidence"]:
        source = str(item.get("source") or "")
        if source not in EVIDENCE_SOURCES:
            raise NecessityError(
                f"모르는 출처 {source!r} — 허용: {sorted(EVIDENCE_SOURCES)}. "
                "출처를 못 대면 그건 판정이 아니라 추측이다"
            )
        if not str(item.get("ref") or "").strip():
            raise NecessityError(
                f"출처 {source}에 ref가 없다 — 되짚을 수 없는 근거는 근거가 아니다"
            )
        rows.append(
            {"source": source, "ref": str(item["ref"]), "quote": str(item.get("quote") or "")}
        )
    return {
        "node_id": int(doc["node_id"]),
        "verdict": str(doc["verdict"]),
        "counter": str(doc["counter"]),
        "evidence": rows,
        # 판정 주체 — 재현·교차 검증에 필요하다(M5 함정 ③과 같은 이유)
        "judged_by": dict(doc.get("judged_by") or {}),
    }
