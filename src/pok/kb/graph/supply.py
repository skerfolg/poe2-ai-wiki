"""스택 축 공급 엣지 스캔 — 「이 스탯은 어디로 흘러가나」 (#91, #62 계열).

빌드의 고점은 스택 축 하나를 밀 때 **몇 갈래가 동시에 자라는가**로 갈린다
(예: 힘→생명(고유 보너스)→래스피스 구체의 치명타·주문 피해). 이 사슬은 어느
레코드 문구 하나에도 없고 **여러 담체의 비례 문구를 그래프로 엮어야** 나온다.
2026-08-19 세션이 이 조사를 손으로 했고, 도구 경로가 없어 `external/pob` 파일
탐색으로 도피했다(B-11 형태 재현). 이 모듈이 그 갭을 닫는다.

## 정본만 읽는다 (철칙 2 — #63 P2와 같은 이유)

유니크 explicits·트리 노드 stats·메커니즘 정의는 전부 KB 정본에 있다.
`external/pob`를 런타임에 직독하면 파생물에 판정이 걸리고 CI에서 통째로 깨진다
(hosting.py 1차 구현이 실제로 그랬다). 시즌 갱신은 ingest가 정본을 갈면 따라온다.

## 판단 없음 (AD-3)

비례 문구(`per N X` / `for every N X` / `equal to N% of X`)의 결정적 매칭과
그래프 조립까지만 한다. 「어느 사슬이 유망한가」는 여기서 답하지 않는다 —
점수도 순위도 없고, 엣지·근거 문구·배타 재료(슬롯·전직 잠금·대가)만 낸다.

## 수동 조사에서 확인된 함정 4건 (BACKLOG #91)

① **변형**: KB Item explicits는 현행 변형이지만 Modifier 레코드는 구변형을
   구분 없이 담는다(Prism Guardian 생→정 변환이 0.2.1에서 삭제됐는데
   `modifier.uniquespiritpermaximumlife1`이 남아 세션이 오판). → **Modifier는
   스캔하지 않는다.** 담체 실물이 보장되는 Item·Passive·Mechanic만.
② **정적/전역**: `Item X on Equipped ...`는 장비에 박힌 수치의 정적 판독이라
   전역 스탯과 합치면 가짜 순환이 생긴다. → `scope` 필드로 가른다.
③ **잡음**: `per second`류(비율), 처치/적중/소모 시 획득(플로우)은 스택 사슬이
   아니다. → 비율은 무시, 플로우는 `scope="flow"`로 표시(조용히 빼지 않는다).
④ **배타**: 전직 잠금·점유 대가 없이 엣지를 이으면 공존 불가 사슬이 나온다
   (Beidat x Crimson Power는 전직이 달라 애초에 배타). → 엣지에 싣는다.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass

from pok.kb.store import Record, Store

# ── 축 어휘 ──────────────────────────────────────────────────────────────
# (축 키, 표면형 정규식). **앞의 것이 이긴다** — 긴/특수 표현을 먼저 둔다
# ("Life Cost"가 "Life"보다, "Item Armour"가 "Armour"보다 먼저).
# ⚠ 축 이름은 `graph/mechanism.py`(상태·객체 그래프)와 **같은 어휘를 쓴다** —
# 두 그래프를 교차 순회하려면 이름이 같아야 한다(#95). `curse_count`·
# `minion_count`가 저쪽의 `curse`·`minion`과 갈려 있어 잇지 못했다.
AXIS_VOCAB: tuple[tuple[str, str], ...] = (
    ("item_energy_shield", r"Item Energy Shield"),
    ("item_armour", r"Item Armour"),
    ("item_evasion", r"Item Evasion(?: Rating)?"),
    ("life_cost", r"Life Cost"),
    ("mana_cost", r"Mana Cost"),
    ("spirit_charge", r"Spirit Charges?"),
    ("power_charge", r"Power Charges?"),
    ("frenzy_charge", r"Frenzy Charges?"),
    ("endurance_charge", r"Endurance Charges?"),
    ("all_attributes", r"all Attributes"),
    ("strength", r"Strength"),
    ("dexterity", r"Dexterity"),
    ("intelligence", r"Intelligence"),
    ("grand_spectrum", r"(?:socketed )?Grand Spectrums?"),
    ("socket_count", r"Sockets? filled"),
    ("life", r"(?:[Mm]aximum )?Life"),
    ("mana", r"(?:[Mm]aximum )?Mana"),
    ("energy_shield", r"(?:[Mm]aximum )?Energy Shield"),
    ("spirit", r"(?:[Mm]aximum )?Spirit"),
    ("accuracy", r"Accuracy(?: Rating)?"),
    ("deflection", r"Deflection(?: Rating)?"),
    ("armour", r"Armour"),
    ("evasion", r"Evasion(?: Rating)?"),
    ("rage", r"(?:[Mm]aximum )?Rage"),
    ("curse", r"Curses?"),
    ("minion", r"(?:Undead )?Minions?|Companions?"),
    ("combo", r"Combo"),
    ("devotion", r"Devotion"),
    ("quality", r"Quality"),
    ("level", r"(?:player )?[Ll]evel"),
    ("darkness", r"Darkness"),
    ("volatility", r"Volatility"),
    ("tribute", r"Tribute"),
)

_AXIS_RES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (key, re.compile(rf"(?<![A-Za-z-]){pat}\b")) for key, pat in AXIS_VOCAB
)

# 비례 마커. "per second/minute"는 비율 표기라 소스가 아니다(마커 탐색에서 건너뜀).
_PER_RE = re.compile(r"\b(?:per|for every)\s+(?:(?P<num>\d+(?:\.\d+)?)%?\s+)?")
_RATE_RE = re.compile(r"^(?:second|minute|Second|Minute)\b")
_EQUAL_RE = re.compile(
    r"^(?P<target>.+?)\s+(?:is |are )?equal to\s+"
    r"(?:(?P<num>[\d().%\-]+(?:%| percent)?)\s+of\s+)?(?:your\s+|their\s+|the\s+)?"
    r"(?P<src>.+)$"
)
# "Gain (4-6)% of maximum Mana as Extra maximum Energy Shield" 형 전환.
_AS_EXTRA_RE = re.compile(
    r"[Gg]ain\s+(?P<num>[\d().\-]+)%\s+of\s+(?:your\s+|their\s+)?(?P<src>.+?)\s+"
    r"as\s+(?:[Ee]xtra\s+)?(?P<target>[^,.]+)"
)

# 소스 창의 플로우 단서 — 스택 사슬이 아니라 순환 기관(획득/소모 이벤트)이다.
_FLOW_RE = re.compile(
    r"\b(?:consumed|expended|spent|killed|kill\b|Hit with|hit by|used|Recently|"
    r"exploded|Culled|gained|you Suppress)",
    re.IGNORECASE,
)
# 소스 창의 정적 판독 단서 — 장비/할당에 박힌 수치를 읽는다(전역 스탯 아님).
_STATIC_RE = re.compile(r"\bon (?:Equipped|your)\b|\bEquipped\b|\bsocketed\b|\bSocket filled\b")
_RADIUS_RE = re.compile(r"\b(?:Allocated )?in Radius\b|\bAllocated\b")

# 좌변(대상) 판독 가드 — 축 단어가 나와도 「그 축의 총량을 준다」가 아니면 payoff다.
#   ① 파생 수치: Life **Regeneration** Rate / Spirit **Reservation** Efficiency …
_DERIVED_AFTER = re.compile(
    r"^\s*(?:Regeneration|Regen\b|Recharge|Recovery|Reservation|Leech|Flask|Cost\b|"
    r"Duration|loss\b|Penetration|Resistance)"
)
#   ② 수령 주체: **Minions have** +10% … — Minion 수를 주는 게 아니다.
_RECIPIENT_AFTER = re.compile(r"^\s*(?:deal|deals|have|has|gain|gains|take|are|Regenerate)\b")
#   ③ 회복/상실 문장: Regenerate 2 Life … / Lose 5% of maximum Mana …
_RECOVERY_HEAD = re.compile(r"^\s*(?:Regenerate|Recover|Lose|Sacrifice|Removes?)\b")
#   ⑤ 수령 주체가 남이면 플레이어 축 공급이 아니다: **Minions gain** … Life as ES
_ALLY_HEAD = re.compile(r"^\s*(?:Minions?|Companions?|(?:Nearby )?Allies|Summoned|Totems?)\b")
#   ④ 크기/효과 수식: Duration of Curses / effect of Non-Curse Auras
_MODIFIED_BEFORE = re.compile(r"(?:Duration|[Ee]ffect|Magnitude|number)\s+of\s*$")

# 담체의 대가 줄 — 엣지에 실어 배타·비용 판단 재료로 낸다.
_COST_RE = re.compile(
    r"Reserves? \d+% of|cost an additional|Costs? an extra|Lose \d+% of|"
    r"you cannot|instead of"
)

# 고유 보너스(Mechanic 정의문) — "provides an inherent bonus of +2 to maximum
# Life per 1 Strength" 형태라 일반 파서가 그대로 읽는다. 별도 상수 없음.
_INHERENT_IDS = ("mechanic.strength", "mechanic.dexterity", "mechanic.intelligence")

# ── 파생 다리 (구조화 필드에서 계산) ────────────────────────────────────
# 비례 **문구**가 없는 게임 규칙 엣지(예: 정신력→소환수 수)는 문구 파서로
# 구조적으로 못 찾는다. 1차 구현은 큐레이션 코드 표였는데 사용자 판정
# (2026-08-19)으로 기각됐다 — "새 규칙마다 수동 추가는 운영이 안 된다".
# #62(hosting)·#63과 같은 답: 규칙은 산문이 아니라 **구조화 필드**에 있다.
# Skill.data.reservation[].resource(어느 자원을 예약하나) x tags(무엇을 주나)를
# 읽으면 다리가 **매 스캔 파생**된다 — 새 시즌 스킬이 정본에 들어오는 순간
# 다리도 따라온다. 수동 목록은 「태그→축」 대응 하나뿐이고, 그건 새 규칙이
# 아니라 새 **규칙 범주**(스키마 변화)가 생길 때만 는다.
_RESERVER_TAG_AXIS: tuple[tuple[str, str], ...] = (
    ("minion", "minion"),
    ("companion", "minion"),
)


@dataclass(frozen=True)
class SupplyEdge:
    """비례 엣지 1건. 근거 문구(evidence)가 판정의 전부다(AD-8)."""

    source_axis: str
    kind: str  # "supply"(축→축) | "payoff"(축→피해·효과)
    target_axis: str | None  # supply일 때만
    target_text: str  # 좌변 원문 — payoff 내용이자 supply의 재확인 근거
    carrier_id: str
    carrier_name: str
    carrier_kind: str  # "item" | "passive" | "mechanic" | "derived"(구조화 필드 파생)
    slot: str | None  # 아이템 장착 부위 — 슬롯 배타 판단 재료
    ascendancy: str | None  # 전직 잠금 — 다르면 공존 불가
    scope: str  # "global" | "item_static" | "allocated_radius" | "flow"
    per: str | None  # 비율 분모 원문 ("100", "20%" 등)
    evidence: str  # 원문 줄 전체
    costs: tuple[str, ...]  # 담체의 대가 줄들 (점유·추가 코스트)
    # 노드 획득 경로 — "anointable"이면 성유로 전직·트리 위치 무관하게 얻는다.
    acquisition: str | None = None


@dataclass(frozen=True)
class AxisSummary:
    """축 하나의 수급 현황 — 허브(진입·진출·보상 수)를 보여주는 지도."""

    axis: str
    supply_in: int  # 이 축으로 들어오는 supply 엣지 수
    supply_out: int  # 이 축에서 다른 축으로 나가는 supply 엣지 수
    payoffs: int  # 이 축을 소스로 삼는 payoff 엣지 수


@dataclass(frozen=True)
class SupplyScan:
    edges: tuple[SupplyEdge, ...]
    axes: tuple[AxisSummary, ...]
    # 걸러낸 것의 사유별 수 — 조용한 절단 금지(#21).
    skipped: tuple[tuple[str, int], ...]
    # 보상은 있는데 **들어오는 비례 공급이 하나도 없는** 축. 셋 중 하나다:
    # 플랫으로만 큰다(속성) / 행동으로 얻는다(충전·저주) / **다리 누락**.
    # 다리 갭이 침묵하지 않도록 항상 노출한다 — 사용자 판정 2026-08-19
    # ("새 규칙마다 수동 추가는 운영이 안 된다")의 가시성 절반.
    unsourced_axes: tuple[str, ...] = ()


def _match_axis(text: str) -> tuple[str, re.Match[str]] | None:
    """어휘 순서대로 첫 매치를 낸다. "Non-Curse"처럼 접두 부정은 매치하지 않는다."""
    for key, rx in _AXIS_RES:
        m = rx.search(text)
        if m:
            return key, m
    return None


def _match_axis_last(text: str) -> tuple[str, re.Match[str]] | None:
    """좌변(부여 대상)용 — **끝점이 가장 뒤인** 매치를 낸다.

    부여되는 명사는 마커 직전에 온다: "Strength provides an inherent bonus of
    +2 to maximum Life ⟨per 1 Strength⟩"에서 대상은 Strength가 아니라 Life다.
    끝점이 같으면(겹침: "Item Energy Shield" ⊃ "Energy Shield") 어휘 우선순위가
    이긴다.
    """
    best: tuple[int, int, str, re.Match[str]] | None = None
    for idx, (key, rx) in enumerate(_AXIS_RES):
        for m in rx.finditer(text):
            candidate = (m.end(), -idx, key, m)
            if best is None or candidate[:2] > best[:2]:
                best = candidate
    if best is None:
        return None
    return best[2], best[3]


def _classify_target(segment: str) -> tuple[str, str | None]:
    """좌변을 supply(축 총량 부여)인지 payoff(그 외 전부)인지 가른다."""
    if _RECOVERY_HEAD.search(segment) or _ALLY_HEAD.search(segment):
        return "payoff", None
    found = _match_axis_last(segment)
    if found is None:
        return "payoff", None
    axis, m = found
    after = segment[m.end() :]
    before = segment[: m.start()]
    if _DERIVED_AFTER.search(after) or _RECIPIENT_AFTER.search(after):
        return "payoff", None
    if _MODIFIED_BEFORE.search(before):
        return "payoff", None
    return "supply", axis


def _source_scope(window: str) -> str:
    if _FLOW_RE.search(window):
        return "flow"
    if _STATIC_RE.search(window):
        return "item_static"
    if _RADIUS_RE.search(window):
        return "allocated_radius"
    return "global"


def _parse_line(line: str) -> Iterator[tuple[str, str, str | None, str, str, str | None]]:
    """줄 하나에서 (source_axis, kind, target_axis, target_text, scope, per)를 낸다.

    한 줄에 마커가 여럿이면(예: "Regenerate 0.05 Life per second per Maximum
    Energy Shield") 비율 표기(per second)는 건너뛰고 나머지를 각각 낸다.
    """
    as_extra = _AS_EXTRA_RE.search(line) if not _ALLY_HEAD.search(line) else None
    if as_extra is not None:
        src_found = _match_axis(as_extra.group("src"))
        # 대상이 축이어야 전환 supply다 — "Cold Damage as Extra Chaos" 같은
        # 피해 전환은 여기 소관이 아니다(아래 per-마커가 payoff로 처리).
        target_found = _match_axis_last(as_extra.group("target"))
        if src_found is not None and target_found is not None:
            yield (
                src_found[0],
                "supply",
                target_found[0],
                as_extra.group("target").strip(),
                _source_scope(as_extra.group("src")),
                f"{as_extra.group('num')}%",
            )
            return

    eq = _EQUAL_RE.match(line)
    if eq is not None:
        window = eq.group("src")
        found = _match_axis(window)
        if found is not None:
            src_axis, _ = found
            kind, target_axis = _classify_target(eq.group("target"))
            yield (
                src_axis,
                kind,
                target_axis,
                eq.group("target").strip(),
                _source_scope(window),
                eq.group("num"),
            )
        return

    for m in _PER_RE.finditer(line):
        window = line[m.end() :]
        if _RATE_RE.match(window):
            continue  # per second/minute — 비율이지 소스가 아니다
        found = _match_axis(window[:60])
        if found is None:
            continue
        src_axis, sm = found
        if sm.start() > 40:  # 마커에서 먼 매치는 이 마커의 소스가 아니다
            continue
        target_text = line[: m.start()].strip().rstrip(",")
        kind, target_axis = _classify_target(target_text)
        yield (
            src_axis,
            kind,
            target_axis,
            target_text,
            _source_scope(window[:80]),
            m.group("num"),
        )


def _join_continuations(lines: tuple[str, ...]) -> tuple[str, ...]:
    """개행으로 잘린 문장을 잇는다 — **소문자로 시작하는 줄은 앞줄의 연속**이다.

    KB 트리 노드 stats가 게임 툴팁의 줄바꿈을 보존한다: Penetrate는
    "… Added Physical Damage equal" / "to 25% of the Accuracy Rating …" 두 줄이라
    `equal to` 마커가 잘려 파서가 못 봤다(실측 2026-08-19, 사용자 테스트).
    """
    joined: list[str] = []
    for line in lines:
        if joined and line[:1].islower():
            joined[-1] = f"{joined[-1]} {line}"
        else:
            joined.append(line)
    return tuple(joined)


def _carrier_lines(record: Record) -> tuple[str, ...]:
    data = record.raw.get("data", {})
    if record.type == "Item":
        raw = tuple(str(x) for x in data.get("explicits") or ())
    elif record.type == "Passive":
        raw = tuple(str(x) for x in data.get("stats_en") or ())
    elif record.type == "Mechanic":
        raw = tuple(str(x) for x in data.get("stats") or ())
    else:
        raw = ()
    return _join_continuations(raw)


def _ascendancy(record: Record) -> str | None:
    data = record.raw.get("data", {})
    code = data.get("ascendancy")
    if not code:
        return None
    name = (data.get("ascendancy_name") or {}).get("en")
    return f"{name}({code})" if name else str(code)


def scan_supply_edges(store: Store) -> SupplyScan:
    """정본 전수(Item·Passive·Mechanic)에서 비례 엣지를 뽑는다.

    Modifier는 **일부러 안 본다** — 접사 레코드는 구변형을 구분 없이 담아
    삭제된 엣지를 되살린다(#91 함정 ①). 아이템 explicits가 현행 변형이다.
    """
    edges: list[SupplyEdge] = []
    skipped: dict[str, int] = defaultdict(int)

    def scan_record(record: Record, carrier_kind: str, slot: str | None) -> None:
        lines = _carrier_lines(record)
        costs = tuple(line for line in lines if _COST_RE.search(line))
        lock = _ascendancy(record)
        acquisition = record.raw.get("data", {}).get("acquisition")
        for line in lines:
            for src_axis, kind, target_axis, target_text, scope, per in _parse_line(line):
                if kind == "supply" and target_axis == src_axis:
                    skipped["self_edge(증가율 자기참조)"] += 1
                    continue
                edges.append(
                    SupplyEdge(
                        source_axis=src_axis,
                        kind=kind,
                        target_axis=target_axis,
                        target_text=target_text,
                        carrier_id=record.id,
                        carrier_name=record.name_en,
                        carrier_kind=carrier_kind,
                        slot=slot,
                        ascendancy=lock,
                        scope=scope,
                        per=per,
                        evidence=line,
                        costs=costs,
                        acquisition=acquisition,
                    )
                )

    for record in store.records.values():
        if record.type == "Item":
            data = record.raw.get("data", {})
            if not data.get("explicits"):
                continue
            if data.get("class_group") == "cultivated" or record.id.endswith("-cultivated"):
                # 함양 사본은 원본과 동일해(#66) 담체를 이중 계상한다.
                skipped["cultivated_duplicate(#66)"] += 1
                continue
            scan_record(record, "item", data.get("category"))
        elif record.type == "Passive":
            scan_record(record, "passive", None)
        elif record.type == "Mechanic" and record.id in _INHERENT_IDS:
            scan_record(record, "mechanic", None)
        else:
            continue

    # 파생 다리 — 예약 자원 축 → 예약 스킬이 주는 축. 구조화 필드에서 매 스캔
    # 계산한다(새 시즌 스킬이 정본에 들어오면 자동 반영). 예약 자원이 축 어휘
    # 밖이면 사유 카운터로 남긴다.
    reservers: dict[tuple[str, str], list[str]] = defaultdict(list)
    for record in store.records.values():
        if record.type != "Skill":
            continue
        tags = set(record.tags)
        target_axes = {axis for tag, axis in _RESERVER_TAG_AXIS if tag in tags}
        if not target_axes:
            continue
        for entry in record.raw.get("data", {}).get("reservation") or ():
            resource = str(entry.get("resource", "")).lower()
            source_found = _match_axis(str(entry.get("resource", "")))
            if source_found is None:
                skipped[f"reserver_resource_unmapped({resource})"] += 1
                continue
            for target_axis in target_axes:
                reservers[(source_found[0], target_axis)].append(record.name_en)
    for (src_axis, target_axis), skill_names in sorted(reservers.items()):
        sample = ", ".join(sorted(skill_names)[:3])
        edges.append(
            SupplyEdge(
                source_axis=src_axis,
                kind="supply",
                target_axis=target_axis,
                target_text=f"예약 스킬 {len(skill_names)}건이 이 자원으로 산다",
                carrier_id="kb:skill.reservation",
                carrier_name=f"예약 스킬 {len(skill_names)}건 (예: {sample})",
                carrier_kind="derived",
                slot=None,
                ascendancy=None,
                scope="global",
                per=None,
                evidence=(
                    f"Skill.data.reservation에서 파생 — {len(skill_names)}건이 "
                    f"{src_axis}를 예약해 {target_axis}를 공급한다 (예: {sample})"
                ),
                costs=(),
            )
        )

    by_axis: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # in, out, payoff
    for e in edges:
        if e.kind == "supply" and e.target_axis is not None:
            by_axis[e.target_axis][0] += 1
            by_axis[e.source_axis][1] += 1
        else:
            by_axis[e.source_axis][2] += 1
    axes = tuple(
        AxisSummary(axis=a, supply_in=v[0], supply_out=v[1], payoffs=v[2])
        for a, v in sorted(by_axis.items(), key=lambda kv: -(kv[1][0] + kv[1][1] + kv[1][2]))
    )
    return SupplyScan(
        edges=tuple(edges),
        axes=axes,
        skipped=tuple(sorted(skipped.items())),
        unsourced_axes=tuple(a.axis for a in axes if a.payoffs > 0 and a.supply_in == 0),
    )


# ── 사슬 순회 ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Chain:
    """다단 사슬 1개 — axes[0]을 밀면 axes[1:]가 따라 자란다."""

    axes: tuple[str, ...]
    edges: tuple[SupplyEdge, ...]  # axes를 잇는 supply 엣지 (단계당 1개 대표)
    # 공존 진단 — 잇는 것과 함께 챙길 수 있는지. 빈 튜플이면 발견된 충돌 없음.
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class CycleCandidate:
    """순환 후보 — viable=False면 sources가 왜 못 도는지 말한다."""

    axes: tuple[str, ...]
    viable: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ChainTrace:
    chains: tuple[Chain, ...]
    cycles: tuple[CycleCandidate, ...]
    # 각 도달 축의 payoff 수(사슬의 「이 축까지 오면 무엇을 먹나」)
    payoff_counts: tuple[tuple[str, int], ...]
    truncated: bool


def _coexistence_conflicts(edges: tuple[SupplyEdge, ...]) -> tuple[str, ...]:
    """사슬을 이루는 엣지들이 한 캐릭터에 공존 가능한지 — 결정적 검사만.

    전직 잠금이 서로 다르면 배타. 같은 슬롯을 서로 다른 아이템이 요구해도 배타.
    (성립 판정이 아니다 — 여기 없는 충돌이 없다는 보장은 못 한다, 철칙 4.)
    """
    conflicts: list[str] = []
    locks = {e.ascendancy for e in edges if e.ascendancy}
    if len(locks) > 1:
        conflicts.append(f"전직 잠금 충돌: {sorted(locks)}")
    slot_users: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        if e.slot:
            slot_users[e.slot].add(e.carrier_name)
    for slot, users in sorted(slot_users.items()):
        if len(users) > 1:
            conflicts.append(f"슬롯 충돌({slot}): {sorted(users)}")
    return tuple(conflicts)


def trace_chains(
    store: Store,
    from_axis: str,
    depth: int = 3,
    max_chains: int = 40,
) -> ChainTrace:
    """from_axis에서 시작하는 supply 사슬을 깊이우선으로 편다.

    **scope="global" 엣지만 잇는다** — item_static(장비 정적 판독)·flow(이벤트)·
    allocated_radius는 전역 스탯을 되먹이지 못해 사슬이 안 된다(#91 함정 ②③).
    순환 후보는 잘라내지 않고 사유와 함께 낸다.
    """
    scan = scan_supply_edges(store)
    adjacency: dict[str, dict[str, list[SupplyEdge]]] = defaultdict(lambda: defaultdict(list))
    payoffs: dict[str, int] = defaultdict(int)
    for e in scan.edges:
        if e.kind == "supply" and e.target_axis is not None and e.scope == "global":
            adjacency[e.source_axis][e.target_axis].append(e)
        elif e.kind == "payoff":
            payoffs[e.source_axis] += 1

    chains: list[Chain] = []
    cycles: list[CycleCandidate] = []
    truncated = False

    def walk(path_axes: tuple[str, ...], path_edges: tuple[SupplyEdge, ...]) -> None:
        nonlocal truncated
        if len(chains) >= max_chains:
            truncated = True
            return
        current = path_axes[-1]
        if len(path_axes) > 1:
            chains.append(
                Chain(
                    axes=path_axes,
                    edges=path_edges,
                    conflicts=_coexistence_conflicts(path_edges),
                )
            )
        if len(path_axes) > depth:
            return
        for target, target_edges in sorted(adjacency[current].items()):
            representative = target_edges[0]
            if target in path_axes:
                cycle_axes = (*path_axes[path_axes.index(target) :], target)
                cycle_edges = (*path_edges[path_axes.index(target) :], representative)
                reasons = list(_coexistence_conflicts(cycle_edges))
                cycles.append(
                    CycleCandidate(
                        axes=cycle_axes,
                        viable=not reasons,
                        reasons=tuple(reasons),
                    )
                )
                continue
            walk((*path_axes, target), (*path_edges, representative))

    walk((from_axis,), ())
    reached = {a for c in chains for a in c.axes} | {from_axis}
    return ChainTrace(
        chains=tuple(chains),
        cycles=tuple(cycles),
        payoff_counts=tuple(sorted(((a, payoffs[a]) for a in reached), key=lambda kv: -kv[1])),
        truncated=truncated,
    )
