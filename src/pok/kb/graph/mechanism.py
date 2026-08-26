"""메커니즘 상태 그래프 — 「무엇이 무엇을 만들고 무엇이 그것을 먹나」 (#92, #91 자매).

`supply.py`가 **스탯→스탯** 비례 엣지를 다뤘다면 여기는 **상태→상태** 전이를 다룬다.
빌드의 연쇄(동결→소비→주입 생성→주입 페이오프 같은 사슬)는 어느 레코드 문구
하나에도 없고 **여러 담체의 생산·소비를 그래프로 엮어야** 나온다.

## 왜 기존 도구로 안 되나 (실측 2026-08-20)

- `scan_synergies`는 **쌍만** 낸다 — 다단 순회가 없어 사슬이 안 나온다.
- `discover_mechanics`는 사전 매칭이라 문구에 키워드가 없으면 못 찾는다(자기 고백).
- 정본 typed edge는 **사실상 비어 있다** — 관계 448건 중 Mechanic은 3건뿐(전부 한
  레코드). AGENTS.md는 "시너지는 관계 그래프로 판단"이라 적혀 있는데 그 그래프가 없다.

## 두 소스를 융합한다 (어느 한쪽도 절반만 안다)

  · **구조화 타입** (`data.pob.effects[].types`) — `GeneratesInfusion`·
    `SkillConsumesFreeze` 같은 토큰 33종. 소비/생산 **의미론이 정확**하지만
    상태이상 *생산*은 여기 없다(냉기 스킬이 얼린다는 건 타입이 아니다).
  · **텍스트 술어** (`predicates.py`) — 상태이상 생산·페이오프를 읽는다. 대신
    통제 어휘(KD-2) 안에서만 본다.

실측: 타입만 쓰면 20축 중 2축만 생산·소비가 둘 다 있고, 융합하면 18종 전이가 나온다.

## 소비(consume)와 페이오프(payoff)는 다른 엣지다

동결을 **소비**하는 스킬은 그 동결을 없애고(다음 소비자가 못 먹는다), 동결에
**페이오프**하는 효과는 상태를 남긴다. 사슬을 이을 때 이 구분이 없으면 같은 상태를
두 번 먹는 불가능한 연쇄가 나온다. 그래서 엣지 종류를 싣는다.

## 판단 없음 (AD-3)

전이를 열거하고 근거를 달 뿐, 어느 연쇄가 좋은지는 답하지 않는다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, replace

from pok.kb.graph.predicates import canon_status, extract_predicates, record_texts
from pok.kb.store import Record, Store

# ── 구조화 타입 토큰 → 상태 축 ──────────────────────────────────────────
# PoB `data.pob.effects[].types`의 토큰이다. 문구가 아니라 **타입 시스템**이라
# 표기 흔들림이 없다(#62 hosting과 같은 재료).
PRODUCE_TYPES: dict[str, str] = {
    "GeneratesCharges": "charge",
    "GeneratesRemnants": "remnant",
    "GeneratesEnergy": "meta_energy",
    "GeneratesInfusion": "infusion",
    "CreatesGroundEffect": "ground_effect",
    "CreatesFissure": "fissure",
    "CreatesGroundRune": "hazard",
    "CreatesMinion": "minion",
    "CreatesSkeletonMinion": "minion",
    "CreatesUndeadMinion": "minion",
    "CreatesDemonMinion": "minion",
    "CanCreateStoneElementals": "minion",
    "CreatesCompanion": "companion",
    "GainsStages": "stage",
    "HasSeals": "seal",
    "ComboStacking": "combo",
}
CONSUME_TYPES: dict[str, str] = {
    # ⚠ 토큰이 **종류를 말하면 종류로** 쓴다 — `power_charge` 소비자와 `frenzy_charge`
    # 생산자를 같은 축으로 뭉치면 성립하지 않는 사슬이 나온다. 종류를 안 말하는
    # 일반 토큰(`ConsumesCharges`)만 `charge`로 남긴다(#95 어휘 통일).
    "ConsumesCharges": "charge",
    "SkillConsumesPowerChargesOnUse": "power_charge",
    "SkillConsumesFrenzyChargesOnUse": "frenzy_charge",
    "SkillConsumesEnduranceChargesOnUse": "endurance_charge",
    "SkillConsumesFreeze": "freeze",
    "SkillConsumesShock": "shock",
    "SkillConsumesIgnite": "ignite",
    "SkillConsumesBleeding": "bleeding",
    "SkillConsumesParried": "parried",
    "ConsumesRage": "rage",
    "ConsumesFullyBrokenArmour": "broken_armour",
}
# 텍스트 술어의 subject → 상태 축. 두 소스가 **같은 축 이름**을 써야 융합된다.
_STATUS_AXIS: dict[str, str] = {
    "shocked": "shock",
    "ignited": "ignite",
    "chilled": "chill",
    "frozen": "freeze",
    "electrocuted": "electrocute",
    "poisoned": "poison",
    "bleeding": "bleeding",
    "stunned": "stun",
    "cursed": "curse",
    "blinded": "blind",
    "immobilised": "immobilise",
    "pinned": "pin",
    "dazed": "daze",
    "hindered": "hinder",
    "burning": "burning",
    "marked": "marked",
    "maimed": "maim",
}
_SUBJECT_AXIS: dict[str, str] = {
    "self.charge.power": "power_charge",
    "self.charge.frenzy": "frenzy_charge",
    "self.charge.endurance": "endurance_charge",
    "self.infusion.count": "infusion",
    "self.combo.count": "combo",
    "self.ward.pct": "ward",
    "self.seal.count": "seal",
    "env.remnant.available": "remnant",
    "env.fissure.count": "fissure",
    "env.ground-effect": "ground_effect",
    "self.rage.count": "rage",
}

# ── 월드 객체 축 (#95) ──────────────────────────────────────────────────
# 「스킬 A가 만든 **객체**를 스킬 B가 대상·조건으로 쓴다」는 연쇄. 상태(상태이상·자원)와
# 생산/소비 의미론이 같아서 **같은 그래프에 얹는다** — 세 번째 평행 그래프를 만들면
# 축 어휘 분열만 깊어진다(실측: #91 28축 vs #92 32축인데 공유가 2종뿐이었다).
#
# 사용자 지적 2026-08-21: "번개 차원 이동은 구형 번개를 대상으로 사용할 수 있다" —
# 이런 **대상 객체** 연쇄가 상태 그래프에도 호스팅 도구에도 안 잡혔다. 실측: 축 17종.
#
# ⚠ **자기 서술을 걸러야 한다.** `Fissure duration is 8 seconds`·`Shockwave radius is
# 2 metres`는 그 스킬이 **자기 객체의 속성**을 말하는 것이지 연쇄가 아니다. 이걸 안
# 거르면 이론 쌍이 872 → 3,455로 4배 부풀려진다(실측 2026-08-21).
_OBJECT_AXES: tuple[tuple[str, str], ...] = (
    # (축 이름, 문구 표면형 정규식) — 긴 표현을 먼저 둔다("Ice Crystal" ⊃ "Crystal")
    ("ball_lightning", r"Ball Lightning"),
    ("ice_crystal", r"Ice Crystals?"),
    ("ice_fragment", r"Ice Fragments?"),
    ("solar_orb", r"Solar Orbs?"),
    ("frostbolt", r"Frostbolts?"),
    ("corpse", r"[Cc]orpses?"),
    ("aftershock", r"Aftershocks?"),
    ("shockwave", r"Shockwaves?"),
    ("volcano", r"Volcanoes|Volcanos?"),
    ("totem", r"Totems?"),
    ("banner", r"Banners?"),
    ("bell", r"Bells?"),
    ("wall", r"Walls?"),
    ("pillar", r"Pillars?"),
    ("crystal", r"Crystals?"),
)
_OBJ_CREATE = re.compile(
    r"\b(?:create|creates|creating|summon|summons|leaves? behind|drops?|places?|forms?"
    r"|spawns?|transform(?:s|ing)?\s+.{0,20}\binto)\b",
    re.I,
)
_OBJ_CONSUME = re.compile(
    r"\b(?:consume|consumes|consuming|detonat\w+|target(?:s|ing)?|activat\w+|destroy\w*"
    r"|shatter\w*|reanimat\w+|that hits? an?|impacts? on|cast on|used? on)\b",
    re.I,
)
# 자기 객체의 속성을 말하는 문장 — 연쇄가 아니다.
_OBJ_SELF_DESC = re.compile(
    r"\b(?:duration|radius|limit|maximum Life|number of|Fires?|branch(?:es)?|expires?)\b",
    re.I,
)
# 부정문은 관계가 아니라 **반대**다 (#93에서 얻은 교훈 — 극성 검사 없이 AND 매칭하면
# `Cannot inflict …`가 관련으로 잡힌다).
_OBJ_NEGATION = re.compile(r"\bcannot\b|\bdoes not\b|\bcan't\b", re.I)


@dataclass(frozen=True)
class StateEdge:
    """상태 축 하나에 대한 담체의 관계 1건. 근거 문구가 판정의 전부다(AD-8)."""

    axis: str
    kind: str  # "produce" | "consume" | "payoff"
    carrier_id: str
    carrier_name: str
    carrier_type: str  # Skill | Support | Passive | Item | Modifier | Mechanic
    # "type"(구조화 토큰) | "text"(술어) | "object"(월드 객체) | "umbrella"(상위 상태
    # 전파) — 신뢰도 구분. `umbrella`는 **유도된** 엣지라 근거가 두 줄로 붙는다.
    source: str
    evidence: str
    # ⛔ **회전수 제약** (#124). 전이의 *유무*만 내면 「8초마다 다시 깔아야 하는 사슬」과
    #    「상시 사슬」이 **같아 보인다** — 「연결된다」가 「쓸 수 있다」가 아니다.
    #    실측 2026-08-25: 상태 엣지 1,208건 중 담체가 `cooldown_s`를 가진 것이 **207건**,
    #    근거 문구에 지속이 명시된 것이 **11건**이다. 둘은 다른 것을 뜻한다 —
    #    쿨다운은 **얼마나 자주 걸 수 있나**, 지속은 **한 번 걸면 얼마나 가나**.
    #    ⚠ `None`은 「제약 없음」이 아니라 **모른다**다. 0으로 읽지 말 것(#109 계열).
    cooldown_s: float | None = None
    duration_s: float | None = None
    # ⛔ **동시 보유 한도** (#124). 「연결된다」가 「쓸 수 있다」가 아니다 — 와류는 원소
    #    지면을 **하나만** 흡수하므로(사용자 인게임 판정 2026-08-25,
    #    `insight.whirlwind-absorbs-one-ground-only`) 지면 축 둘을 잇는 사슬은
    #    「둘 다 켜진다」가 아니라 **「둘 중 하나」**다. 먼저 붙은 것이 자리를 차지하고,
    #    맵의 잡 지면이 선점하면 강한 지면으로 **덮어쓰지 못한다**.
    #    ⚠ 정본 문구는 이걸 **명시하지 않는다**("takes on **that** element"가 단수를
    #    함의할 뿐) — 그래서 사용자 판정이 근거다(AD-3).
    #    `None`은 「한도 없음」이 아니라 **모른다**다(#109 계열).
    concurrent_cap: int | None = None


@dataclass(frozen=True)
class AxisSummary:
    axis: str
    producers: int
    consumers: int
    payoffs: int


@dataclass(frozen=True)
class StateScan:
    edges: tuple[StateEdge, ...]
    axes: tuple[AxisSummary, ...]
    # 소비·페이오프는 있는데 **생산자가 없는** 축. 수집 갭이거나 어휘 갭이다 —
    # 조용히 두면 "이 축은 못 쓴다"로 오독된다(#21·B-11과 같은 형태).
    unproduced_axes: tuple[str, ...] = ()


def object_edges_of(texts: list[str]) -> tuple[tuple[str, str, str], ...]:
    """문구에서 (축, kind, 근거문장) 객체 엣지를 뽑는다 (#95).

    **문장 단위**로 본다 — 부정어·자기 서술이 그 문장에만 걸리기 때문이다.
    한 문장이 생성과 소비를 동시에 말할 수 있다("Consume a Corpse **to create** a
    Zombie") — 그때는 둘 다 낸다.
    """
    out: list[tuple[str, str, str]] = []
    for text in texts:
        for sentence in re.split(r"(?<=[.;])\s+|\n", str(text)):
            sentence = sentence.strip()
            if not sentence or _OBJ_NEGATION.search(sentence) or _OBJ_SELF_DESC.search(sentence):
                continue
            for axis, pattern in _OBJECT_AXES:
                if not re.search(rf"\b{pattern}\b", sentence, re.I):
                    continue
                if _OBJ_CREATE.search(sentence):
                    out.append((axis, "produce", sentence))
                if _OBJ_CONSUME.search(sentence):
                    out.append((axis, "consume", sentence))
                break  # 축 어휘는 앞의 것이 이긴다(긴 표현 우선)
    return tuple(out)


# ── 우산 상태 (#96) ─────────────────────────────────────────────────────
# 어떤 상태는 **다른 상태들의 상위 개념**이다. 정본이 그걸 문장으로 말해 준다:
#   "Pinned targets count as Immobilised."
#   "While an enemy is Heavy Stunned, they … count as Immobilised."
#   "A target is immobilised if it cannot move, for example due to being
#    Frozen, Pinned, Heavy Stunned, or Electrocuted."
# 이 관계가 없으면 상위 축은 **생산자가 없는 것처럼 보인다**. 실측 2026-08-21:
# 속박은 페이오프 18건인데 생산 3건(그나마 1건은 부정문 오독)이라 "공급이 마름"으로
# 판정됐다 — 실제로는 동결 14·기절 6·전기충격 2가 전부 속박을 만든다.
#
# ⚠ 관계를 **손으로 적지 않는다**. 시즌마다 새 규칙이 생기면 수동 표는 못 따라간다
# (사용자 지적 2026-08-20: "새로운 규칙을 찾을 때마다 수동으로 추가하라고 할 수도 없고").
# 정본 Mechanic 문구에서 읽는다.
_UMB_COUNTS_AS = re.compile(
    r"(?:(?P<src>[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?)\s+(?:targets?|enemies)\s+)?"
    r"count(?:s)? as\s+(?P<dst>[A-Z][A-Za-z]+)",
)
_UMB_DUE_TO = re.compile(r"due to being\s+(?P<list>[^.]+)", re.I)
# "Enemies taking Fire damage over time are Burning. Usually this occurs **because
# the enemy is Ignited**." — 같은 우산 관계인데 표현이 다르다. 이 형태를 안 읽으면
# 연소가 「생산자 0」으로 남는다(실측 2026-08-21: 페이오프 5건인데 공급 0).
_UMB_BECAUSE = re.compile(
    r"because\s+(?:the\s+)?(?:enemy|enemies|target|they)\s+(?:is|are)\s+(?P<src>[A-Z][A-Za-z]+)",
    re.I,
)
_UMB_NEGATION = re.compile(r"\b(?:do(?:es)? not|cannot|can't|never)\b[^.;]{0,20}$", re.I)


@dataclass(frozen=True)
class UmbrellaRelation:
    """`source_axis` 상태가 걸리면 `target_axis` 상태로도 친다 (정본 문구 유래)."""

    source_axis: str
    target_axis: str
    evidence: str


def _axis_of_state_name(word: str) -> str | None:
    """ "Frozen"·"Heavy Stunned"·"Pinned" 같은 상태 이름 → 축.

    `Heavy Stunned`는 `Stunned`의 강도 구분이라 같은 축으로 접는다 — 우리 어휘에
    강도 축이 없고, 페이오프 문구도 강도를 가리지 않는다.
    """
    # 목록 분리 잔여물("or Electrocuted")과 강도 수식어를 함께 턴다 — 안 털면
    # "Frozen, Pinned, Heavy Stunned, or Electrocuted"의 **마지막 항목만** 조용히
    # 빠진다(실측 2026-08-21: 전기충격 → 속박 경로가 사라졌다).
    cleaned = re.sub(r"^(?:or|and|the|a|an)\s+", "", word.strip(), flags=re.I)
    cleaned = re.sub(r"^(?:Heavy|Light)\s+", "", cleaned, flags=re.I)
    value = canon_status(cleaned)
    return _STATUS_AXIS.get(value) if value else None


def umbrella_relations(store: Store) -> tuple[UmbrellaRelation, ...]:
    """정본 Mechanic 문구에서 「A는 B로도 친다」 관계를 읽는다 (결정적, 판단 없음)."""
    out: dict[tuple[str, str], UmbrellaRelation] = {}
    for record in store.records.values():
        if record.type != "Mechanic":
            continue
        data = record.raw.get("data", {}) or {}
        own_axis = _axis_of_state_name(record.name_en)
        for stat in data.get("keyword_stats") or data.get("stats") or ():
            for sentence in re.split(r"(?<=[.;])\s+|\n", str(stat)):
                sentence = sentence.strip()
                if not sentence:
                    continue
                # ① "X count as Y" — X가 없으면 이 레코드 자신이 X다
                for m in _UMB_COUNTS_AS.finditer(sentence):
                    if _UMB_NEGATION.search(sentence[: m.start()]):
                        continue  # "do not count as"는 반대다
                    src = _axis_of_state_name(m.group("src") or "") or own_axis
                    dst = _axis_of_state_name(m.group("dst") or "")
                    if src and dst and src != dst:
                        out.setdefault((src, dst), UmbrellaRelation(src, dst, sentence))
                # ② "… due to being A, B, C, or D" — 이 레코드가 상위 축이다
                due = _UMB_DUE_TO.search(sentence)
                if due and own_axis:
                    for word in re.split(r",\s*|\s+or\s+|\s+and\s+", due.group("list")):
                        src = _axis_of_state_name(word)
                        if src and src != own_axis:
                            out.setdefault(
                                (src, own_axis), UmbrellaRelation(src, own_axis, sentence)
                            )
                # ③ "… because the enemy is Ignited" — 같은 관계의 다른 표현형
                because = _UMB_BECAUSE.search(sentence)
                if because and own_axis and not _UMB_NEGATION.search(sentence[: because.start()]):
                    src = _axis_of_state_name(because.group("src"))
                    if src and src != own_axis:
                        out.setdefault((src, own_axis), UmbrellaRelation(src, own_axis, sentence))
    return tuple(out.values())


def _carrier_types(record: Record) -> set[str]:
    out: set[str] = set()
    for effect in record.raw.get("data", {}).get("pob", {}).get("effects", []) or ():
        out.update(str(t) for t in effect.get("types", []) or ())
        out.update(str(t) for t in effect.get("adds", []) or ())
    return out


#: 축별 **동시 보유 한도** (#124). 문구에 없어 **사용자 인게임 판정**이 근거다(AD-3) —
#: `insight.whirlwind-absorbs-one-ground-only`. 없는 축은 `None`(모름)이지 「무제한」이 아니다.
#:
#: ⚠ **와류끼리의 규칙과 헷갈리지 말 것**: 같은 레코드가 *"…grants it a stage, making it
#: larger and more damaging"* 라고도 적는데 그건 **와류 간 병합·강화**이고, 여기 한도는
#: **지면 흡수**의 것이다. 정반대 성질이라 한 문단으로 읽으면 오판한다.
_CONCURRENT_CAP: dict[str, int] = {
    "ground_effect": 1,
    "ground_chilled": 1,
    "ground_ignited": 1,
    "ground_shocked": 1,
}

_DURATION = re.compile(r"(?:for|lasts?)\s+(\d+(?:\.\d+)?)\s+second", re.I)


def _with_rate_limits(edge: StateEdge, store: Store) -> StateEdge:
    """엣지에 **회전수 제약**을 붙인다 (#124).

    - `cooldown_s` — 담체 레코드의 구조화 필드(실측 207건). **얼마나 자주 걸 수 있나.**
    - `duration_s` — 근거 문구의 `for N seconds`/`lasts N seconds`(실측 11건).
      **한 번 걸면 얼마나 가나.**

    ⚠ 둘은 다른 것이다. 쿨다운 4초·지속 8초면 상시 유지되지만, 쿨다운 8초·지속 4초면
    절반은 꺼져 있다. 하나로 뭉치면 그 구분이 사라진다.

    ⛔ **`None`은 「제약 없음」이 아니라 「모른다」다** — 0으로 읽으면 「상시」로 오독된다
    (#109 계열: 없는 것을 0으로 읽지 않는다).
    """
    record = store.records.get(edge.carrier_id)
    cooldown = (record.raw.get("data") or {}).get("cooldown_s") if record else None
    found = _DURATION.search(edge.evidence or "")
    return replace(
        edge,
        cooldown_s=float(cooldown) if isinstance(cooldown, int | float) else None,
        duration_s=float(found.group(1)) if found else None,
        concurrent_cap=_CONCURRENT_CAP.get(edge.axis),
    )


def scan_state_edges(store: Store) -> StateScan:
    """정본 전수에서 상태 생산·소비·페이오프 엣지를 뽑는다 (구조화 타입 + 텍스트 융합)."""
    edges: list[StateEdge] = []

    for record in store.records.values():
        name, rtype = record.name_en, record.type
        # ① 구조화 타입 — 의미론이 정확한 쪽
        for token in _carrier_types(record):
            if token in PRODUCE_TYPES:
                edges.append(
                    StateEdge(
                        axis=PRODUCE_TYPES[token],
                        kind="produce",
                        carrier_id=record.id,
                        carrier_name=name,
                        carrier_type=rtype,
                        source="type",
                        evidence=f"PoB 타입 토큰 `{token}`",
                    )
                )
            if token in CONSUME_TYPES:
                edges.append(
                    StateEdge(
                        axis=CONSUME_TYPES[token],
                        kind="consume",
                        carrier_id=record.id,
                        carrier_name=name,
                        carrier_type=rtype,
                        source="type",
                        evidence=f"PoB 타입 토큰 `{token}`",
                    )
                )
        # ② 월드 객체 (#95) — 「A가 만든 객체를 B가 대상으로 쓴다」. 구조화 타입에도
        #    통제 어휘에도 없어서 지금까지 어느 도구에도 안 잡혔다.
        if record.type in ("Skill", "Support"):
            data = record.raw.get("data", {})
            obj_texts = [str(data.get("description") or "")]
            obj_texts += [str(x) for x in (data.get("stats") or ())]
            for obj_axis, obj_kind, sentence in object_edges_of(obj_texts):
                edges.append(
                    StateEdge(
                        axis=obj_axis,
                        kind=obj_kind,
                        carrier_id=record.id,
                        carrier_name=name,
                        carrier_type=rtype,
                        source="object",
                        evidence=sentence,
                    )
                )
        # ③ 텍스트 술어 — 상태이상 생산·페이오프를 읽는 쪽
        texts = record_texts(record.raw)
        if not texts:
            continue
        for predicate in extract_predicates(texts, store.subjects):
            if predicate.subject == "enemy.status":
                axis = _STATUS_AXIS.get(predicate.value or "")
            elif predicate.subject == "env.ground-effect" and predicate.value:
                # 지면은 **종류가 페이오프를 가른다** — 점화 지대 생산자와 냉각 지대
                # 소비자를 한 축으로 뭉치면 성립하지 않는 사슬이 나온다(#95 남은 것 ③).
                axis = f"ground_{predicate.value}"
            else:
                axis = _SUBJECT_AXIS.get(predicate.subject)
            if axis is None:
                continue
            edges.append(
                StateEdge(
                    axis=axis,
                    # 텍스트는 「없앤다」를 구분하지 못한다 — 요구는 payoff로 싣고,
                    # 소비 판정은 구조화 타입에만 맡긴다(잘못 이으면 불가능한 연쇄가 난다).
                    kind="produce" if predicate.direction == "supply" else "payoff",
                    carrier_id=record.id,
                    carrier_name=name,
                    carrier_type=rtype,
                    source="text",
                    evidence=predicate.evidence,
                )
            )

    # ④ 우산 상태 전파 (#96) — 하위 상태를 만드는 담체는 **상위 상태도 만든다**.
    #    이걸 안 하면 상위 축이 "생산자 없음"으로 보여 거짓 갭 판정이 난다.
    umbrellas = umbrella_relations(store)
    by_source: dict[str, list[UmbrellaRelation]] = defaultdict(list)
    for relation in umbrellas:
        by_source[relation.source_axis].append(relation)
    derived: list[StateEdge] = []
    seen: set[tuple[str, str]] = set()
    for edge in edges:
        if edge.kind != "produce":
            continue
        for relation in by_source.get(edge.axis, ()):
            key = (relation.target_axis, edge.carrier_id)
            if key in seen:
                continue
            seen.add(key)
            derived.append(
                StateEdge(
                    axis=relation.target_axis,
                    kind="produce",
                    carrier_id=edge.carrier_id,
                    carrier_name=edge.carrier_name,
                    carrier_type=edge.carrier_type,
                    source="umbrella",
                    # 근거는 두 줄이다 — 담체가 하위 상태를 만든다는 문구 + 하위가
                    # 상위로 친다는 정본 규칙. 둘 다 있어야 사람이 판정할 수 있다(AD-8).
                    evidence=f"{edge.evidence} ⟶ {relation.evidence}",
                )
            )
    edges.extend(derived)

    # ⛔ **회전수는 여기 한 곳에서 붙인다** (#124). 엣지 생성부가 5곳이라 생성부마다
    #    달면 **안 단 곳이 뚫린다**(§0 ⑦ — 관문을 패턴마다 달면 안 단 패턴이 뚫린다).
    edges = [_with_rate_limits(e, store) for e in edges]

    by_axis: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for edge in edges:
        idx = {"produce": 0, "consume": 1, "payoff": 2}[edge.kind]
        by_axis[edge.axis][idx] += 1
    axes = tuple(
        AxisSummary(axis=a, producers=v[0], consumers=v[1], payoffs=v[2])
        for a, v in sorted(by_axis.items(), key=lambda kv: -sum(kv[1]))
    )
    return StateScan(
        edges=tuple(edges),
        axes=axes,
        unproduced_axes=tuple(
            a.axis for a in axes if a.producers == 0 and (a.consumers or a.payoffs)
        ),
    )


# ── 전이·사슬 ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Transition:
    """상태 A를 먹고 상태 B를 내놓는 담체 — 사슬의 마디."""

    from_axis: str
    to_axis: str
    carrier_id: str
    carrier_name: str
    carrier_type: str
    in_kind: str  # 들어오는 쪽이 consume인가 payoff인가 (소비면 상태가 사라진다)
    evidence_in: str
    evidence_out: str


@dataclass(frozen=True)
class MechanismChain:
    axes: tuple[str, ...]
    # 마디마다 **쓸 수 있는 담체 전부**. 같은 축 경로를 담체 수만큼 복제하면
    # 출력이 중복으로 뒤덮인다(실측 2026-08-20: 사슬 200건 중 대부분이 같은 경로).
    transitions: tuple[Transition, ...]  # 마디당 대표 1개
    hop_options: tuple[tuple[str, ...], ...] = ()  # 마디당 담체 이름 전량
    # 사슬 끝 축의 페이오프 수 — 「여기까지 오면 무엇을 먹나」
    terminal_payoffs: int = 0
    # 사슬 안에서 같은 상태를 두 번 소비하려 드는지 등 발견된 문제
    warnings: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class ChainTrace:
    transitions: tuple[Transition, ...]
    chains: tuple[MechanismChain, ...]
    truncated: bool = False


def find_transitions(scan: StateScan) -> tuple[Transition, ...]:
    """한 담체가 A를 먹고(consume/payoff) B를 만들면(produce) A→B 전이다."""
    ins: dict[str, list[StateEdge]] = defaultdict(list)
    outs: dict[str, list[StateEdge]] = defaultdict(list)
    for edge in scan.edges:
        if edge.kind == "produce":
            outs[edge.carrier_id].append(edge)
        else:
            ins[edge.carrier_id].append(edge)
    transitions: list[Transition] = []
    for carrier_id, in_edges in ins.items():
        for in_edge in in_edges:
            for out_edge in outs.get(carrier_id, ()):
                if in_edge.axis == out_edge.axis:
                    continue  # 자기 자신을 먹고 만드는 것은 전이가 아니다(재생)
                transitions.append(
                    Transition(
                        from_axis=in_edge.axis,
                        to_axis=out_edge.axis,
                        carrier_id=carrier_id,
                        carrier_name=in_edge.carrier_name,
                        carrier_type=in_edge.carrier_type,
                        in_kind=in_edge.kind,
                        evidence_in=in_edge.evidence,
                        evidence_out=out_edge.evidence,
                    )
                )
    return tuple(transitions)


def trace_mechanism_chains(
    store: Store,
    from_axis: str | None = None,
    depth: int = 4,
    max_chains: int = 60,
) -> ChainTrace:
    """상태 전이를 이어 다단 사슬을 편다.

    `from_axis`를 주면 그 축에서 출발하는 사슬만, 생략하면 전이가 있는 모든 축에서
    출발한다. 사슬 끝 축의 페이오프 수를 함께 내 「어디까지 가면 보상이 있나」를
    보인다 — 어느 사슬이 좋은지는 답하지 않는다(AD-3).
    """
    scan = scan_state_edges(store)
    transitions = find_transitions(scan)
    payoffs = {a.axis: a.payoffs for a in scan.axes}
    # 같은 (A→B)를 여러 담체가 하면 **한 마디에 선택지가 여럿**인 것이지 사슬이
    # 여럿인 게 아니다. 축 쌍으로 묶어 대표 1개 + 담체 목록을 들고 다닌다.
    by_pair: dict[tuple[str, str], list[Transition]] = defaultdict(list)
    for transition in transitions:
        by_pair[(transition.from_axis, transition.to_axis)].append(transition)
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for pair in by_pair:
        adjacency[pair[0]].append(pair)

    chains: list[MechanismChain] = []
    truncated = False

    def walk(axes: tuple[str, ...], path: tuple[tuple[str, str], ...]) -> None:
        nonlocal truncated
        if len(chains) >= max_chains:
            truncated = True
            return
        if path:
            hops = [by_pair[p] for p in path]
            consumed = [h[0].from_axis for h in hops if any(t.in_kind == "consume" for t in h)]
            chains.append(
                MechanismChain(
                    axes=axes,
                    transitions=tuple(h[0] for h in hops),
                    hop_options=tuple(tuple(sorted({t.carrier_name for t in h})) for h in hops),
                    terminal_payoffs=payoffs.get(axes[-1], 0),
                    warnings=tuple(
                        f"같은 상태를 두 번 소비한다: {axis}"
                        for axis in {a for a in consumed if consumed.count(a) > 1}
                    ),
                )
            )
        if len(axes) > depth:
            return
        for pair in sorted(adjacency.get(axes[-1], ()), key=lambda p: p[1]):
            if pair[1] in axes:
                continue  # 순환은 사슬로 펴지 않는다(무한 확장 방지)
            walk((*axes, pair[1]), (*path, pair))

    starts = [from_axis] if from_axis else sorted({t.from_axis for t in transitions})
    for start in starts:
        walk((start,), ())
    return ChainTrace(transitions=transitions, chains=tuple(chains), truncated=truncated)
