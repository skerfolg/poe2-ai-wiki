"""아이템 최적화 루프 — 슬롯별 후보 열거·실측·그리디 채택 (사용자 지시 2026-08-06).

트리에는 `optimize_tree`(후보 열거 → PoB 델타 그리디 → 가지치기)가 있는데 아이템에는
**루프가 없었다** — 측정 도구(`evaluate_delta`)만 있고, 열거·비교·채택이 전부 세션
절차에 맡겨져 있어 호출을 건너뛰면 유니크·주얼 미고려가 그대로 재발했다(실측
2026-08-06). 트리와 같은 경계로 엔진에 넣는다:

    기계(여기): 슬롯별 유니크 열거(KB) · 텍스트 렌더링 · PoB 델타 실측 · 그리디 채택
    판단(스킬): 희귀 템플릿 구성 · 컨셉 적합 · 조건부 고점을 실제로 추구할지

## 2판 측정 — 단판 스냅샷 비교의 함정 (사용자 지적 2026-08-06)

래스피스의 구체는 생명력 세팅 **전** 문맥에서 희귀 집중구보다 낮게 나오지만, 생명력을
채우면 고점이다(`per 100 maximum Life` 스케일). 현재 문맥 델타 한 장으로 비교하면
이런 유니크가 **구조적으로 탈락**한다 — 실측 2회: 눈알왕관+래스피스 각각 델타 0,
함께 1.44배 / 뒤틀린 천공인 무투자 0.985 동률 → 마나 투자 시 역전.

그래서 효과 문구에서 스케일 축(`per N maximum Life` 등)을 읽으면 **그 축을 탐침으로
올린 문맥에서 한 번 더 잰다.** 2판이 우세하면 `conditional_peak`으로 낸다.

## 착용 가능성 (사용자 사고 2·3, 2026-08-06)

PoB는 요구 속성 미달이어도 스탯을 계산해 준다 — 즉 1판 델타는 **착용 불가인
아이템에도 낙관적으로 나온다.** 그래서 변형 문맥의 `ReqStr/Dex/Int`를 보유
`Str/Dex/Int`와 대조해 미달(`req_shortfall`)을 기록하고, 미달 후보는 **채택하지
않는다.** 대신 부족분을 속성 탐침으로 채운 문맥에서 한 번 더 재서(2판) "제약을
지불하면 얼마가 나오는가"를 수치로 낸다 — 감수할지는 설계 판단이다.

## 축 수요-공급 연쇄 (사용자 사고 6·8, N개 확장 지시 2026-08-06)

조건부 고점의 수요 축(래스피스=생명력, 요구 미달=속성)이 확인되면, **다른 슬롯
후보 중 그 축을 공급하는 것**을 골라 연쇄로 실측한다 — 쌍에서 멈추지 않고 개선이
계속되는 한 3개·4개까지 늘린다(사용자: "쌍만으로는 고차원 빌드를 구성할 수 없다").
확장 축은 매 단계 갱신된다: 연쇄가 아직 착용 불가면 그 속성으로, 아니면 같은
스케일 축으로. 시드·공급자 모두 유니크와 희귀 템플릿을 가리지 않는다 — 고유+희귀·
희귀+희귀 연쇄가 같은 경로로 나온다(신성모독엔 `per 100 maximum Mana` 같은 스케일
접사가 있어 희귀도 수요 시드가 된다).

사전 정의 묶음이 아니라 축이 짝을 고른다 — 검사 조합은 수요·공급이 만나는 곳뿐이라
조합 폭발이 없다. 연쇄는 탐침이 아닌 **실제 문맥** 측정이므로, 점수가 단독 최선을
이기면 전 구성원을 채택한다. 축으로 안 잡히는 창발 조합은 이 경로 밖이다 — 그건
`evaluate_change_bundle`(가설 묶음 실측)과 라운드 재측정 그리디가 맡는 층이다.
"""

from __future__ import annotations

import functools
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pok.engine.valuation import UnscoredAxis, axis_gain, unscored_axes

# PoB 슬롯 → KB 유니크 `category`. 실측 0.5.4b: 유니크의 (class_group, category)
# 조합 38종이 이 매핑으로 깨끗이 갈린다.
SLOT_CATEGORIES: dict[str, frozenset[str]] = {
    "Helmet": frozenset({"helmet"}),
    "Body Armour": frozenset({"body"}),
    "Gloves": frozenset({"gloves"}),
    "Boots": frozenset({"boots"}),
    "Amulet": frozenset({"amulet"}),
    "Ring 1": frozenset({"ring"}),
    "Ring 2": frozenset({"ring"}),
    "Belt": frozenset({"belt"}),
    "Weapon 1": frozenset(
        {"mace", "bow", "spear", "staff", "warstaff", "wand", "sceptre", "talisman",
         "sword", "axe", "dagger", "claw", "crossbow", "flail"}
    ),
    "Weapon 2": frozenset({"shield", "focus", "buckler", "quiver"}),
}  # fmt: skip
# KB category "flask"는 호신부(base에 Charm)와 플라스크(base에 Flask)가 섞여 있다 —
# PoB 슬롯이 다르므로 base_type으로 가른다. 주얼은 슬롯이 아니라 트리 소켓이다.
_CHARM_BASE = re.compile(r"charm", re.I)
_FLASK_BASE = re.compile(r"flask", re.I)

_RANGE = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")
# 스케일 조건 문구 — 이 축을 채워야 값이 나오는 유니크의 표식
_SCALING = re.compile(
    r"per\s+\d*\s*(?:maximum\s+)?(Life|Mana|Energy Shield|Spirit)"
    r"|%\s+of\s+(?:your\s+)?maximum\s+(Life|Mana|Energy Shield)",
    re.I,
)
# 축별 표준 탐침 — 2판 측정에서 기준·후보 양쪽에 같은 양을 얹는다(공정 비교).
# 값은 "그 축을 진지하게 세팅한" 규모의 근사이고, 결과에 그대로 기록된다.
PROBES: dict[str, str] = {
    "life": "+1000 to maximum Life",
    "mana": "+1000 to maximum Mana",
    "energy shield": "+1000 to maximum Energy Shield",
    "spirit": "+100 to Spirit",
}
_PROBE_HOSTS = ("Ring 2", "Ring 1", "Belt", "Amulet")
_ATTR_NAMES = {"str": "Strength", "dex": "Dexterity", "int": "Intelligence"}
# 축의 공급 문구 — 페어링에서 공급자 후보를 고르는 표식. 크기 순위는 문구의 첫
# 수치로 매긴다(플랫·%가 섞이면 부정확하지만 **순위용**이고, 최종 판정은 실측이다).
_SUPPLY: dict[str, re.Pattern[str]] = {
    "life": re.compile(r"\+(\d+) to maximum Life|(\d+)% increased maximum Life", re.I),
    "mana": re.compile(r"\+(\d+) to maximum Mana|(\d+)% increased maximum Mana", re.I),
    "energy shield": re.compile(
        r"\+(\d+) to maximum Energy Shield|(\d+)% increased maximum Energy Shield", re.I
    ),
    "spirit": re.compile(r"\+(\d+) to Spirit", re.I),
    "str": re.compile(r"\+(\d+) to (?:Strength|all Attributes)", re.I),
    "dex": re.compile(r"\+(\d+) to (?:Dexterity|all Attributes)", re.I),
    "int": re.compile(r"\+(\d+) to (?:Intelligence|all Attributes)", re.I),
}


@dataclass(frozen=True)
class ItemCandidate:
    label: str  # KB id 또는 호출자 라벨
    slot: str
    text: str  # PoB 파스 가능한 아이템 텍스트
    source: str  # "unique-kb" | "rare-template"


@dataclass(frozen=True)
class CandidateResult:
    candidate: ItemCandidate
    delta_now: dict[str, float]  # 현재 문맥 (1판)
    scaling_axes: tuple[str, ...]
    delta_probed: dict[str, float] | None  # 요구 축 탐침 문맥 (2판, 축 있을 때만)
    probe: str | None
    floor_violations: tuple[str, ...]
    # 요구 속성 미달 {"str": 부족분, …} — PoB는 미달이어도 계산해 주므로 1판 델타가
    # 낙관이다. 미달 후보는 채택 금지, 2판(속성 탐침)으로 "지불 시 이득"만 낸다.
    req_shortfall: dict[str, float] = field(default_factory=dict)

    def score(self, weights: Mapping[str, float], base: Mapping[str, float] | None = None) -> float:
        """정책 점수. `base`(현재 스펙의 실측)를 주면 **비선형 축에 곡선을 건다**.

        이동속도가 그 축이다 — 0 → 20%p와 60 → 80%p는 같은 20이 아니다(#25).
        `base`를 안 주면 **0에서 더하는 것으로 친다** — 곡선은 그대로 걸리되 이미
        가진 이동속도를 모르므로 값이 낙관적으로 나온다. 실제 값을 원하면 기준 실측을
        넘길 것(`optimize_items`는 넘긴다).
        """
        return sum(
            w * axis_gain(k, self.delta_now.get(k, 0.0), (base or {}).get(k, 0.0))
            for k, w in weights.items()
        )

    def probed_score(
        self, weights: Mapping[str, float], base: Mapping[str, float] | None = None
    ) -> float:
        if self.delta_probed is None:
            return self.score(weights, base)
        return sum(
            w * axis_gain(k, self.delta_probed.get(k, 0.0), (base or {}).get(k, 0.0))
            for k, w in weights.items()
        )

    @property
    def blocked(self) -> bool:
        """지금 이대로는 채택 불가 — 바닥선 위반이거나 착용 불가."""
        return bool(self.floor_violations) or bool(self.req_shortfall)

    @property
    def conditional_peak(self) -> bool:
        """1판에서는 밀리지만 조건(축·속성)을 채우면 열리는가 — 래스피스형의 표식."""
        return self.delta_probed is not None


# 딜 가중만 준 호출에서도 **항상 재는** 방어·유틸 축 (백로그 #18).
#
# 왜 필요한가: `weights={"CombinedDPS":1}`이면 순수 방어 유니크의 점수가 **정확히 0**이고
# 그리디는 양수만 채택하므로 **후보에 올라도 절대 안 뽑힌다.** 딜 가중이 기본 사용
# 패턴이라, 그 패턴에서 한 부류가 통째로 안 보이는 것이 결함이다. 실측 2026-08-09
# (허리띠 20종·딜 가중): 채택 가능 후보 **0건**인데 그중 12종이 EHP를 올렸다
# (뷔르나바스 +55 · 아홉 꼬리 고양이 +123 · 메긴노드의 허리띠 +90…).
#
# 축을 더 담는 비용은 **0**이다 — PoB 1회 실행이 619개 스탯을 한꺼번에 준다.
_DEFENSIVE_AXES: tuple[str, ...] = (
    "TotalEHP",
    "Life",
    "EnergyShield",
    "Armour",
    "Evasion",
    # ⚠ `MovementSpeed`가 아니라 **`MovementSpeedMod`**다. 없는 키를 넣으면 델타가
    # 늘 0으로 나오고 — 이 결함이 고치려던 바로 그 「조용한 0」이다. 실측 2026-08-09:
    # 처음에 `MovementSpeed`로 적었고 후보 20종이 전부 0.000으로 찍혔는데도 넘어갔다.
    # 그래서 축 이름이 실재하는지는 `tests/integration/`이 PoB 실측으로 잠근다.
    "MovementSpeedMod",
)
# `TotalEHP`가 방어 축을 대부분 흡수하므로 그것을 대표값으로 쓴다 — 나머지는 왜 올랐는지
# 읽기 위한 내역이다(저항·회피는 EHP로 합산돼 들어온다).
_DEFENSIVE_HEADLINE = "TotalEHP"
_DEFENSIVE_REPORT_LIMIT = 8


def _defensive_gain(result: CandidateResult) -> float:
    """방어 개선 대표값 — 없으면 0. 음수는 개선이 아니므로 0으로 깎는다."""
    return max(result.delta_now.get(_DEFENSIVE_HEADLINE, 0.0), 0.0)


@dataclass(frozen=True)
class ChainResult:
    """수요-공급 연쇄(2개 이상)의 실측 — 탐침이 아닌 실제 문맥이므로 채택 근거가 된다.

    members[0]이 수요 시드(조건부 고점), 이후가 공급자 순서다. 유니크·희귀 템플릿을
    가리지 않는다 — 고유+희귀·희귀+희귀 연쇄가 같은 형태로 나온다."""

    members: tuple[tuple[str, str], ...]  # (label, slot) 연쇄 순서
    axis_path: tuple[str, ...]  # 각 확장이 겨냥한 축 (길이 = len(members) - 1)
    delta_chain: dict[str, float]
    delta_members_alone: tuple[dict[str, float], ...]
    floor_violations: tuple[str, ...]
    req_shortfall: dict[str, float]

    def score(self, weights: Mapping[str, float], base: Mapping[str, float] | None = None) -> float:
        return sum(
            w * axis_gain(k, self.delta_chain.get(k, 0.0), (base or {}).get(k, 0.0))
            for k, w in weights.items()
        )

    @property
    def synergy(self) -> dict[str, float]:
        """연쇄 - 단독합 — 양수면 합보다 크다(곱연산 맞물림의 표식)."""
        return {
            k: round(v - sum(d.get(k, 0.0) for d in self.delta_members_alone), 4)
            for k, v in self.delta_chain.items()
        }

    @property
    def blocked(self) -> bool:
        return bool(self.floor_violations) or bool(self.req_shortfall)


@dataclass(frozen=True)
class ItemStep:
    slot: str
    adopted: str
    deltas: dict[str, float]
    replaced: str


@dataclass(frozen=True)
class ItemOptimizeResult:
    spec: dict[str, Any]  # 채택 반영 후
    steps: tuple[ItemStep, ...]
    # 채택되지 않았지만 요구 축을 채우면 고점인 후보 — **판단은 호출자 몫**(AD-3).
    # 추구하려면 그 축을 빌드 성립 조건으로 장부화하고 문맥 확정 후 재측정할 것.
    conditional_peaks: tuple[CandidateResult, ...]
    notes: tuple[str, ...]
    chains: tuple[ChainResult, ...] = ()  # 수요-공급 연쇄 실측 전량 (채택 여부와 무관)
    # 가중 축은 전부 0인데 **방어 축은 양수**인 후보 — 점수가 0이라 그리디가 절대
    # 채택하지 않는다. 채택하지 않되 **보이게는 한다**(백로그 #18, 자동 보고).
    defensive_only: tuple[CandidateResult, ...] = ()
    # 후보가 **실제로 움직였는데** 가중치에 없는 축 — #18·#22·#25가 전부 이 형태였고
    # 셋 다 사용자가 지적해줘야 발견됐다. 채택은 호출자가 정하되 **안 보이는 채로
    # 배제되는 일은 없어진다**(AD-3). 압축 근거는 `engine.valuation.unscored_axes`.
    unscored_axes: tuple[UnscoredAxis, ...] = ()


def resolve_rolls(text: str, roll: str = "mid") -> str:
    """`(60-100)` 범위를 정책대로 수치화한다 — PoB에 보낼 때 필요.

    정책은 결과에 기록된다: 만점 롤 가정으로 비교했다가 결론이 뒤집힌 실측이 있다
    (뒤틀린 천공인 0.985 "동률" — 만점 가정에서만 동률이었다).
    """

    def _pick(m: re.Match[str]) -> str:
        lo, hi = float(m.group(1)), float(m.group(2))
        value = {"min": lo, "max": hi, "mid": (lo + hi) / 2}[roll]
        return str(int(value)) if value == int(value) else f"{value:g}"

    return _RANGE.sub(_pick, text)


def render_unique(record: Mapping[str, Any], roll: str = "mid") -> str:
    """KB 유니크 레코드 → PoB 파스 가능한 아이템 텍스트."""
    data = record.get("data") or {}
    name = (record.get("name") or {}).get("en") or record.get("id", "?")
    implicits = [resolve_rolls(str(t), roll) for t in data.get("implicits") or []]
    explicits = [resolve_rolls(str(t), roll) for t in data.get("explicits") or []]
    lines = [
        "Rarity: UNIQUE",
        str(name),
        str(data.get("base_type") or ""),
        f"Implicits: {len(implicits)}",
        *implicits,
        *explicits,
    ]
    return "\n".join(lines)


def scaling_axes(texts: Sequence[str]) -> tuple[str, ...]:
    """효과 문구에서 스케일 축을 읽는다 — 있으면 2판 측정 대상이다."""
    found: list[str] = []
    for line in texts:
        for m in _SCALING.finditer(line):
            axis = (m.group(1) or m.group(2) or "").lower()
            if axis and axis in PROBES and axis not in found:
                found.append(axis)
    return tuple(found)


@functools.lru_cache(maxsize=4)
def _kb_records(root: Path | None) -> dict[str, Any]:
    """KB 로드 메모이즈 — `store.load`는 캐시가 없어(16k 레코드 재검증) 라운드x슬롯마다
    부르면 측정보다 로드가 비싸진다. 읽기 전용이므로 프로세스 수명 캐시가 안전하다."""
    from pok.kb.store import load as store_load

    return dict(store_load(root).records)


def _slot_filter(slot: str) -> tuple[frozenset[str], re.Pattern[str] | None] | None:
    """슬롯 → (category 집합, base_type 추가 필터). 매핑 밖이면 None."""
    if slot.startswith("Charm"):
        return frozenset({"flask"}), _CHARM_BASE
    if slot.startswith("Flask"):
        return frozenset({"flask"}), _FLASK_BASE
    if slot == "Jewel" or slot.startswith("Jewel@"):
        return frozenset({"jewel"}), None
    categories = SLOT_CATEGORIES.get(slot)
    return (categories, None) if categories else None


def enumerate_slot_uniques(
    slot: str, root: Path | None = None, *, limit: int | None = None
) -> list[ItemCandidate]:
    """슬롯의 유니크 후보 **전량** — KB에서 결정적으로 열거한다 (기본 무절단).

    이 열거가 절차로만 있던 것이 카옴 누락(61배 격차 성분)의 원인이었다 — 세션이
    건너뛰면 후보에 오를 방법 자체가 없었다. limit을 주면 자르되, **잘랐다는 사실은
    호출자(optimize_items)가 노트로 남긴다** — 조용한 절단이 곧 조용한 카옴 누락이다.
    `pob_computable: false`는 계산 불가라 뺀다(대체 조립 경로는 B-3).
    """
    picked = _slot_filter(slot)
    if picked is None:
        return []
    categories, base_filter = picked
    out: list[ItemCandidate] = []
    for record_id, record in _kb_records(root).items():
        data = record.raw.get("data") or {}
        if record.type != "Item" or data.get("rarity") != "unique":
            continue
        if data.get("category") not in categories:
            continue
        if base_filter and not base_filter.search(str(data.get("base_type") or "")):
            continue
        if data.get("pob_computable") is False:
            continue
        if record_id.endswith("-cultivated"):
            continue  # 같은 이름의 재배판 — 원판만 열거 (중복 측정 방지)
        out.append(
            ItemCandidate(
                label=record_id,
                slot=slot,
                text=render_unique(record.raw),
                source="unique-kb",
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def _replace_slot(spec: dict[str, Any], slot: str, text: str) -> dict[str, Any]:
    if slot.startswith("Jewel@"):
        node = int(slot.split("@", 1)[1])
        jewels = [dict(j) for j in spec.get("jewels") or [] if j.get("socket_node_id") != node]
        return {**spec, "jewels": [*jewels, {"socket_node_id": node, "text": text}]}
    items = [dict(i) for i in spec.get("items") or []]
    kept = [i for i in items if i.get("slot") != slot]
    return {**spec, "items": [*kept, {"slot": slot, "text": text}]}


def _with_probe_lines(spec: dict[str, Any], lines: Sequence[str]) -> dict[str, Any]:
    """탐침을 얹은 문맥 — 빈 장신구 슬롯에 넣거나, 없으면 기존 아이템에 덧붙인다."""
    joined = "\n".join(lines)
    items = [dict(i) for i in spec.get("items") or []]
    used = {i.get("slot") for i in items}
    for host in _PROBE_HOSTS:
        if host not in used:
            probe_item = {
                "slot": host,
                "text": f"Rarity: MAGIC\nProbe\nGold Ring\nImplicits: 0\n{joined}",
            }
            return {**spec, "items": [*items, probe_item]}
    for item in items:
        if item.get("slot") == "Belt":
            item["text"] = str(item.get("text", "")) + f"\n{joined}"
            return {**spec, "items": items}
    items[0]["text"] = str(items[0].get("text", "")) + f"\n{joined}"
    return {**spec, "items": items}


def req_shortfall(
    measured: Mapping[str, float], base: Mapping[str, float] | None = None
) -> dict[str, float]:
    """`_req_shortfall`의 공개 이름 — 조회·계산 도구가 상시 부착에 쓴다 (#29).

    경고가 **1회성**이라 20여 회 측정 동안 사라진 사고가 있었다. 한 번만 말하는
    경고는 문서와 동급이다(철칙 5) — 그래서 매 반환에 싣는다.
    """
    return _req_shortfall(measured, base)


def _req_shortfall(
    measured: Mapping[str, float], base: Mapping[str, float] | None = None
) -> dict[str, float]:
    """요구 속성 미달 — PoB의 ReqStr/Dex/Int vs 보유 Str/Dex/Int (실측 2026-08-06:
    Glorious Plate가 Sorceress에 ReqStr 121 vs Str 7로 나온다).

    `base`를 주면 **후보가 새로 유발/악화시킨 미달만** 낸다 — 기반 스펙 자체의 미달
    (예: 스킬 젬의 Int 요구)로 모든 후보를 차단하면 최적화가 통째로 멎는다(실측
    2026-08-06: 스파크 20레벨의 Int 요구가 전 후보를 blocked로 만들어 채택 0건).
    기반 미달은 호출자가 따로 보고한다. 값은 **착용에 필요한 전량**이다(증가분이
    아니라 — 지불해야 하는 건 전체 부족분이다)."""
    out: dict[str, float] = {}
    for key, req_key in (("Str", "ReqStr"), ("Dex", "ReqDex"), ("Int", "ReqInt")):
        need = measured.get(req_key, 0.0) - measured.get(key, 0.0)
        if need <= 0:
            continue
        if base is not None:
            base_need = base.get(req_key, 0.0) - base.get(key, 0.0)
            if need <= base_need + 1e-6:
                continue  # 기반이 이미 그만큼 미달 — 이 후보 탓이 아니다
        out[key.lower()] = round(need, 1)
    return out


def _attr_probe_lines(shortfall: Mapping[str, float]) -> list[str]:
    """부족분을 채우는 속성 탐침 — 50 단위로 올림해 탐침 기준(probed_base) 캐시가 살게."""
    return [
        f"+{math.ceil((need + 10) / 50) * 50} to {_ATTR_NAMES[attr]}"
        for attr, need in sorted(shortfall.items())
    ]


def _supply_magnitude(text: str, axis: str) -> float:
    """공급 크기 — 순위용 근사(첫 수치 합). 최종 판정은 쌍 실측이 한다."""
    pattern = _SUPPLY.get(axis)
    if pattern is None:
        return 0.0
    total = 0.0
    for m in pattern.finditer(text):
        first = next((g for g in m.groups() if g), None)
        if first:
            total += float(first)
    return total


ComputeFn = Callable[[dict[str, Any]], dict[str, float]]


def _default_compute() -> ComputeFn:
    from pok.engine.compute import compute_pob as _compute
    from pok.pob.buildxml import spec_from_dict

    def run(spec: dict[str, Any]) -> dict[str, float]:
        return dict(_compute(spec_from_dict(spec)).stats)

    return run


def evaluate_slot(
    spec: dict[str, Any],
    slot: str,
    candidates: Sequence[ItemCandidate],
    *,
    stats: tuple[str, ...] = ("CombinedDPS", "Life", "TotalEHP"),
    floors: Mapping[str, float] | None = None,
    compute: ComputeFn | None = None,
    base_stats: Mapping[str, float] | None = None,
) -> list[CandidateResult]:
    """슬롯 후보들을 실측한다 — 1판(현재 문맥) + 조건 보유 시 2판(탐침 문맥).

    2판을 여는 조건은 둘이다: 스케일 축 문구(래스피스형) 또는 요구 속성 미달
    (착용하려면 속성 투자가 필요한 후보). 둘 다 "조건을 지불하면 얼마인가"를 잰다.
    """
    run = compute or _default_compute()
    base = dict(base_stats) if base_stats is not None else run(spec)
    results: list[CandidateResult] = []
    probed_base: dict[str, dict[str, float]] = {}
    for cand in candidates:
        variant = _replace_slot(spec, slot, cand.text)
        measured = run(variant)
        delta_now = {k: round(measured.get(k, 0.0) - base.get(k, 0.0), 4) for k in stats}
        violations = tuple(
            f"{k} {measured.get(k, 0.0):g} < 바닥선 {v:g}"
            for k, v in (floors or {}).items()
            if measured.get(k, 0.0) < v
        )
        shortfall = _req_shortfall(measured, base)
        axes = scaling_axes(cand.text.splitlines())
        probe_lines: list[str] = []
        if axes:
            probe_lines = [PROBES[axes[0]]]  # 첫 축 기준 — 복수 축은 scaling_axes로 드러난다
        elif shortfall:
            probe_lines = _attr_probe_lines(shortfall)
        delta_probed = None
        probe_used = None
        if probe_lines:
            probe_key = "\n".join(probe_lines)
            if probe_key not in probed_base:
                probed_base[probe_key] = run(_with_probe_lines(spec, probe_lines))
            probed_variant = run(_with_probe_lines(variant, probe_lines))
            base_p = probed_base[probe_key]
            delta_probed = {
                k: round(probed_variant.get(k, 0.0) - base_p.get(k, 0.0), 4) for k in stats
            }
            probe_used = probe_key
        results.append(
            CandidateResult(
                candidate=cand,
                delta_now=delta_now,
                scaling_axes=axes,
                delta_probed=delta_probed,
                probe=probe_used,
                floor_violations=violations,
                req_shortfall=shortfall,
            )
        )
    return results


def _measure_chain(
    spec: dict[str, Any],
    base: Mapping[str, float],
    members: Sequence[CandidateResult],
    axis_path: Sequence[str],
    *,
    stats: tuple[str, ...],
    floors: Mapping[str, float] | None,
    run: ComputeFn,
) -> ChainResult:
    variant = dict(spec)
    for member in members:
        variant = _replace_slot(variant, member.candidate.slot, member.candidate.text)
    measured = run(variant)
    delta = {k: round(measured.get(k, 0.0) - base.get(k, 0.0), 4) for k in stats}
    violations = tuple(
        f"{k} {measured.get(k, 0.0):g} < 바닥선 {v:g}"
        for k, v in (floors or {}).items()
        if measured.get(k, 0.0) < v
    )
    return ChainResult(
        members=tuple((m.candidate.label, m.candidate.slot) for m in members),
        axis_path=tuple(axis_path),
        delta_chain=delta,
        delta_members_alone=tuple(m.delta_now for m in members),
        floor_violations=violations,
        req_shortfall=_req_shortfall(measured, base),
    )


def optimize_items(
    spec: dict[str, Any],
    slots: Sequence[str],
    weights: Mapping[str, float],
    *,
    rare_templates: Mapping[str, Sequence[str]] | None = None,
    floors: Mapping[str, float] | None = None,
    stats: tuple[str, ...] | None = None,
    max_rounds: int = 3,
    max_candidates_per_slot: int | None = None,
    jewel_sockets: Sequence[int] = (),
    max_chain: int = 4,
    max_chain_measures_per_round: int = 10,
    root: Path | None = None,
    compute: ComputeFn | None = None,
) -> ItemOptimizeResult:
    """슬롯들을 그리디로 개선한다 — `optimize_tree`의 아이템판.

    라운드마다 각 슬롯의 후보(KB 유니크 **전수** 열거 + 호출자 희귀 템플릿)를 현재
    문맥에서 실측하고, 정책 점수(`weights`, RC3 다축) 최고의 양수 채택을 반영한 뒤
    다음 라운드를 돈다 — 채택이 문맥을 바꾸므로(저항·생명력) 재측정이 필수다.

    - **전수가 기본**: `max_candidates_per_slot`을 주면 자르되 노트로 알린다 —
      조용한 절단은 조용한 카옴 누락과 같은 결함이다(사용자 승인 2026-08-06: 전수).
    - **착용 불가는 채택하지 않는다**: `req_shortfall`이 있는 후보는 1판 델타가
      낙관(미달이어도 PoB는 계산)이므로 채택 금지 — 속성 탐침 2판으로만 낸다.
    - **탐침 기반 조건부 고점은 채택하지 않고 드러낸다**: 1판에서 밀려도 2판(요구 축
      탐침)에서 우세한 후보는 `conditional_peaks`로 나온다. 단 **실제 공급자와의
      연쇄 실측**(`chains`)이 단독 최선을 이기면 채택한다 — 가정이 아니라 측정이다.
    - **연쇄는 쌍에서 멈추지 않는다**(사용자 지시 2026-08-06): 개선이 계속되는 한
      `max_chain`까지 공급자를 이어 붙이며 실측한다. 확장 축은 매 단계 갱신 —
      연쇄가 아직 착용 불가면 그 속성, 아니면 같은 스케일 축. 시드·공급자 모두
      유니크·희귀 템플릿을 가리지 않는다(고유+희귀·희귀+희귀 연쇄 동일 경로).
    - `slots`에 `"Jewel"`을 넣으면 `jewel_sockets`(트리에 **할당된** 소켓 node_id)의
      빈 칸에 유니크 주얼을 실측한다. 소켓을 안 주면 후보가 있어도 **미측정으로
      보고**한다 — 없다고 단정하지 않는다.
    """
    # 방어 축은 **가중치와 무관하게 항상 잰다.** PoB 1회 실행이 619개 스탯을 한꺼번에
    # 주므로 축을 더 담는 비용은 0이고, 안 담으면 "딜 0 · 방어 양수"를 판정할 근거
    # 자체가 없다(#18: 딜 위주 weights에서 방어 유니크가 통째로 안 보인 원인).
    measure = tuple(dict.fromkeys((*(stats or tuple(weights)), *_DEFENSIVE_AXES)))
    run = compute or _default_compute()
    current = dict(spec)
    steps: list[ItemStep] = []
    peaks: dict[str, CandidateResult] = {}
    chains: list[ChainResult] = []
    defensive: dict[str, CandidateResult] = {}
    notes: list[str] = []
    seen_notes: set[str] = set()

    def note(msg: str) -> None:
        if msg not in seen_notes:
            seen_notes.add(msg)
            notes.append(msg)

    if not any(axis in weights for axis in _DEFENSIVE_AXES):
        note(
            "⚠ weights에 방어 축이 없다 — **방어만 개선하는 후보는 점수가 0이라 절대 "
            "채택되지 않는다.** 그리디는 양수만 채택하므로 후보에 올라도 결과에 안 나온다. "
            f"그 후보들은 `defensive_only`로 실어 보낸다(판단은 호출자 몫). "
            f"방어 축 예: {', '.join(_DEFENSIVE_AXES[:3])}"
        )

    for _ in range(max_rounds):
        base_now = run(current)
        base_short = _req_shortfall(base_now)
        if base_short:
            note(
                f"⚠ 기반 스펙 자체가 요구 속성 미달: {base_short} — 후보 차단 사유로는 "
                f"쓰지 않지만(후보 탓이 아니다), 트리·장비로 채워야 실제 착용이 성립한다"
            )
        best: tuple[float, str, CandidateResult] | None = None
        round_results: list[CandidateResult] = []
        for slot in slots:
            eval_slot = slot
            if slot == "Jewel":
                used = {j.get("socket_node_id") for j in current.get("jewels") or []}
                free = [s for s in jewel_sockets if s not in used]
                pool = enumerate_slot_uniques("Jewel", root)
                if not free:
                    note(
                        f"Jewel: 유니크 주얼 후보 {len(pool)}건 **미측정** — "
                        f"jewel_sockets(트리에 할당된 소켓 node_id)가 없거나 다 찼다. "
                        f"'없다'가 아니라 '안 쟀다'이다"
                    )
                    continue
                eval_slot = f"Jewel@{free[0]}"
            candidates = enumerate_slot_uniques(eval_slot, root)
            if max_candidates_per_slot is not None and len(candidates) > max_candidates_per_slot:
                note(
                    f"{slot}: 후보 {len(candidates)}건 중 {max_candidates_per_slot}건만 측정 — "
                    f"절단됨. 전수 측정은 max_candidates_per_slot을 빼면 된다"
                )
                candidates = candidates[:max_candidates_per_slot]
            for i, text in enumerate((rare_templates or {}).get(slot, [])):
                candidates.append(
                    ItemCandidate(f"rare:{slot}#{i}", eval_slot, text, "rare-template")
                )
            if not candidates:
                note(f"{slot}: 후보 0건 — 슬롯 매핑 밖이거나 KB에 유니크가 없다")
                continue
            for result in evaluate_slot(
                current, eval_slot, candidates,
                stats=measure, floors=floors, compute=run, base_stats=base_now,
            ):  # fmt: skip
                round_results.append(result)
                score = result.score(weights, base_now)
                if not result.blocked and score > 0 and (best is None or score > best[0]):
                    best = (score, eval_slot, result)
                # 점수로는 절대 못 올라오는 방어 개선분을 따로 붙잡는다 (#18).
                # `best`와 경쟁시키지 않는다 — 채택은 여전히 가중치가 정한다(AD-3).
                if score <= 0 and not result.blocked and _defensive_gain(result) > 0:
                    prev = defensive.get(result.candidate.label)
                    if prev is None or _defensive_gain(result) > _defensive_gain(prev):
                        defensive[result.candidate.label] = result
                if (
                    result.conditional_peak
                    and result.probed_score(weights, base_now) > max(score, 0.0)
                    and result.candidate.label not in peaks
                ):
                    peaks[result.candidate.label] = result

        # 축 수요-공급 연쇄: 조건부 고점의 수요 축을 실제로 공급하는 다른 슬롯
        # 후보를 이어 붙이며 실측한다 — 개선이 계속되는 한 max_chain까지(쌍에서
        # 멈추면 고차원 조합이 닫힌다, 사용자 지시). 탐침(가정)을 실측으로 바꾸는 단계.
        best_chain: tuple[float, ChainResult, list[CandidateResult]] | None = None
        demand = sorted(
            (r for r in round_results if r.conditional_peak),
            key=lambda r: r.probed_score(weights, base_now),
            reverse=True,
        )[:3]
        budget = max_chain_measures_per_round
        for seed in demand:
            members = [seed]
            axis_path: list[str] = []
            used_slots = {seed.candidate.slot}
            cur_score = seed.score(weights, base_now)
            axis = seed.scaling_axes[0] if seed.scaling_axes else next(iter(seed.req_shortfall), "")
            while axis and len(members) < max_chain and budget > 0:
                suppliers = sorted(
                    (
                        r for r in round_results
                        if r.candidate.slot not in used_slots
                        and not r.blocked
                        and _supply_magnitude(r.candidate.text, axis) > 0
                    ),
                    key=lambda r: _supply_magnitude(r.candidate.text, axis),
                    reverse=True,
                )[:2]  # fmt: skip
                extended: tuple[float, ChainResult, CandidateResult] | None = None
                for supplier in suppliers:
                    if budget <= 0:
                        break
                    budget -= 1
                    chain = _measure_chain(
                        current, base_now, [*members, supplier], [*axis_path, axis],
                        stats=measure, floors=floors, run=run,
                    )  # fmt: skip
                    chains.append(chain)
                    c_score = chain.score(weights, base_now)
                    if (
                        not chain.blocked
                        and c_score > 0
                        and (best_chain is None or c_score > best_chain[0])
                    ):
                        best_chain = (c_score, chain, [*members, supplier])
                    if extended is None or c_score > extended[0]:
                        extended = (c_score, chain, supplier)
                # 이번 확장이 현 연쇄 점수를 못 넘으면 이 시드는 여기까지다
                if extended is None or extended[0] <= cur_score + 1e-9:
                    break
                cur_score, chain, supplier = extended
                members.append(supplier)
                used_slots.add(supplier.candidate.slot)
                axis_path.append(axis)
                # 다음 축: 연쇄가 아직 착용 불가면 그 속성부터, 아니면 같은 축을 계속
                axis = next(iter(chain.req_shortfall), axis)

        if best_chain is not None and (best is None or best_chain[0] > best[0]):
            _, chain, parts = best_chain
            for i, part in enumerate(parts):
                current = _replace_slot(current, part.candidate.slot, part.candidate.text)
                steps.append(
                    ItemStep(
                        slot=part.candidate.slot,
                        adopted=part.candidate.label,
                        # 연쇄 전체 델타는 시드 걸음에, 공급자 걸음엔 단독 델타를 적는다
                        deltas=chain.delta_chain if i == 0 else part.delta_now,
                        replaced=_slot_holder(spec, part.candidate.slot),
                    )
                )
            note(
                f"연쇄 채택({len(parts)}개): {' + '.join(m[0] for m in chain.members)} "
                f"(축 경로={list(chain.axis_path)}) — 연쇄 실측이 단독 최선을 이겼다. "
                f"시너지 성분은 chains의 synergy 참조"
            )
            continue
        if best is None:
            break
        _, slot, chosen = best
        current = _replace_slot(current, slot, chosen.candidate.text)
        steps.append(
            ItemStep(
                slot=slot,
                adopted=chosen.candidate.label,
                deltas=chosen.delta_now,
                replaced=_slot_holder(spec, slot),
            )
        )

    if peaks:
        note(
            f"조건부 고점 {len(peaks)}건 — 1판(현재 문맥)에서는 밀리지만 요구 조건(축·"
            f"속성)을 채우면 우세하다. 추구하려면 성립 조건으로 장부화하고 재측정할 것"
        )
    ranked = sorted(defensive.values(), key=_defensive_gain, reverse=True)
    if len(ranked) > _DEFENSIVE_REPORT_LIMIT:
        note(
            f"방어 전용 후보 {len(ranked)}건 중 상위 {_DEFENSIVE_REPORT_LIMIT}건만 실어 보낸다 "
            f"— 절단됐다는 사실을 남긴다(조용한 절단 금지)"
        )
        ranked = ranked[:_DEFENSIVE_REPORT_LIMIT]
    # 채택된 마지막 후보가 건드린 축 중 **점수에 안 들어간 것**을 낸다. 채택분이
    # 없으면 라운드에서 가장 점수가 높았던 후보를 쓴다 — "이걸 골랐는데 저건 안 봤다"가
    # 보여야 한다. 방어 축은 이미 `defensive_only`로 따로 보고하므로 중복하지 않는다.
    probe = steps[-1].deltas if steps else (round_results[0].delta_now if round_results else None)
    axes: tuple[UnscoredAxis, ...] = ()
    if probe:
        axes, truncated = unscored_axes(probe, base_now, weights, already_reported=_DEFENSIVE_AXES)
        if truncated:
            note(truncated)
    return ItemOptimizeResult(
        spec=current,
        steps=tuple(steps),
        conditional_peaks=tuple(peaks.values()),
        notes=tuple(notes),
        chains=tuple(chains),
        defensive_only=tuple(ranked),
        unscored_axes=axes,
    )


def _slot_holder(spec: dict[str, Any], slot: str) -> str:
    """교체 전 그 슬롯에 있던 아이템의 이름 줄 — 없으면 (빈 슬롯)."""
    for item in spec.get("items") or []:
        if item.get("slot") == slot:
            lines = str(item.get("text", "")).splitlines()
            return lines[1] if len(lines) > 1 else "(?)"
    return "(빈 슬롯)"
