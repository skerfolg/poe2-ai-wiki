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
올린 문맥에서 한 번 더 잰다.** 2판이 우세하면 `conditional_peak`으로 낸다 — 채택은
하지 않는다(그 축을 채울지는 설계 판단이고, 채택하면 성립 조건으로 장부화해야 한다).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    def score(self, weights: Mapping[str, float]) -> float:
        return sum(w * self.delta_now.get(k, 0.0) for k, w in weights.items())

    def probed_score(self, weights: Mapping[str, float]) -> float:
        if self.delta_probed is None:
            return self.score(weights)
        return sum(w * self.delta_probed.get(k, 0.0) for k, w in weights.items())

    @property
    def conditional_peak(self) -> bool:
        """1판에서는 밀리지만 2판에서 열리는가 — 래스피스형의 표식."""
        return self.delta_probed is not None


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


def enumerate_slot_uniques(
    slot: str, root: Path | None = None, *, limit: int = 40
) -> list[ItemCandidate]:
    """슬롯의 유니크 후보 전량 — KB에서 결정적으로 열거한다.

    이 열거가 절차로만 있던 것이 카옴 누락(61배 격차 성분)의 원인이었다 — 세션이
    건너뛰면 후보에 오를 방법 자체가 없었다. `pob_computable: false`는 계산 불가라
    빼되, 뺐다는 사실을 호출자가 알 수 있게 개수를 남긴다.
    """
    from pok.kb.store import load as store_load

    categories = SLOT_CATEGORIES.get(slot)
    if not categories:
        return []
    out: list[ItemCandidate] = []
    for record in store_load(root).records.values():
        data = record.raw.get("data") or {}
        if record.type != "Item" or data.get("rarity") != "unique":
            continue
        if data.get("category") not in categories:
            continue
        if data.get("pob_computable") is False:
            continue
        if record.id.endswith("-cultivated"):
            continue  # 같은 이름의 재배판 — 원판만 열거 (중복 측정 방지)
        out.append(
            ItemCandidate(
                label=record.id,
                slot=slot,
                text=render_unique(record.raw),
                source="unique-kb",
            )
        )
        if len(out) >= limit:
            break
    return out


def _replace_slot(spec: dict[str, Any], slot: str, text: str) -> dict[str, Any]:
    items = [dict(i) for i in spec.get("items") or []]
    kept = [i for i in items if i.get("slot") != slot]
    return {**spec, "items": [*kept, {"slot": slot, "text": text}]}


def _with_probe(spec: dict[str, Any], axis: str) -> dict[str, Any]:
    """탐침을 얹은 문맥 — 빈 장신구 슬롯에 넣거나, 없으면 허리띠 텍스트에 덧붙인다."""
    probe_line = PROBES[axis]
    items = [dict(i) for i in spec.get("items") or []]
    used = {i.get("slot") for i in items}
    for host in _PROBE_HOSTS:
        if host not in used:
            probe_item = {
                "slot": host,
                "text": f"Rarity: MAGIC\nProbe\nGold Ring\nImplicits: 0\n{probe_line}",
            }
            return {**spec, "items": [*items, probe_item]}
    for item in items:
        if item.get("slot") == "Belt":
            item["text"] = str(item.get("text", "")) + f"\n{probe_line}"
            return {**spec, "items": items}
    items[0]["text"] = str(items[0].get("text", "")) + f"\n{probe_line}"
    return {**spec, "items": items}


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
) -> list[CandidateResult]:
    """슬롯 후보들을 실측한다 — 1판(현재 문맥) + 스케일 축 보유 시 2판(탐침 문맥)."""
    run = compute or _default_compute()
    base = run(spec)
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
        axes = scaling_axes(cand.text.splitlines())
        delta_probed = None
        probe_used = None
        if axes:
            axis = axes[0]  # 첫 축 기준 — 복수 축은 결과의 scaling_axes로 드러난다
            if axis not in probed_base:
                probed_base[axis] = run(_with_probe(spec, axis))
            probed_variant = run(_with_probe(variant, axis))
            base_p = probed_base[axis]
            delta_probed = {
                k: round(probed_variant.get(k, 0.0) - base_p.get(k, 0.0), 4) for k in stats
            }
            probe_used = PROBES[axis]
        results.append(
            CandidateResult(
                candidate=cand,
                delta_now=delta_now,
                scaling_axes=axes,
                delta_probed=delta_probed,
                probe=probe_used,
                floor_violations=violations,
            )
        )
    return results


def optimize_items(
    spec: dict[str, Any],
    slots: Sequence[str],
    weights: Mapping[str, float],
    *,
    rare_templates: Mapping[str, Sequence[str]] | None = None,
    floors: Mapping[str, float] | None = None,
    stats: tuple[str, ...] | None = None,
    max_rounds: int = 3,
    max_candidates_per_slot: int = 40,
    root: Path | None = None,
    compute: ComputeFn | None = None,
) -> ItemOptimizeResult:
    """슬롯들을 그리디로 개선한다 — `optimize_tree`의 아이템판.

    라운드마다 각 슬롯의 후보(KB 유니크 자동 열거 + 호출자 희귀 템플릿)를 현재
    문맥에서 실측하고, 정책 점수(`weights`, RC3 다축) 최고의 양수 채택을 반영한 뒤
    다음 라운드를 돈다 — 채택이 문맥을 바꾸므로(저항·생명력) 재측정이 필수다.

    **조건부 고점은 채택하지 않고 드러낸다**: 1판에서 밀려도 2판(요구 축 탐침)에서
    우세한 후보는 `conditional_peaks`로 나온다. 그 축을 채울지는 설계 판단이고,
    추구하면 성립 조건 장부화 + 문맥 확정 후 재측정이 따른다(재검토 큐).
    """
    measure = stats or tuple(weights)
    run = compute or _default_compute()
    current = dict(spec)
    steps: list[ItemStep] = []
    peaks: dict[str, CandidateResult] = {}
    notes: list[str] = []

    for _ in range(max_rounds):
        best: tuple[float, str, CandidateResult] | None = None
        for slot in slots:
            candidates = enumerate_slot_uniques(slot, root, limit=max_candidates_per_slot)
            for i, text in enumerate((rare_templates or {}).get(slot, [])):
                candidates.append(ItemCandidate(f"rare:{slot}#{i}", slot, text, "rare-template"))
            if not candidates:
                notes.append(f"{slot}: 후보 0건 — 슬롯 매핑 밖이거나 KB에 유니크가 없다")
                continue
            for result in evaluate_slot(
                current, slot, candidates, stats=measure, floors=floors, compute=run
            ):
                if result.floor_violations:
                    continue  # 바닥선을 깨는 채택은 하지 않는다 — 사유는 결과로 남는다
                score = result.score(weights)
                if score > 0 and (best is None or score > best[0]):
                    best = (score, slot, result)
                if (
                    result.conditional_peak
                    and result.probed_score(weights) > max(score, 0.0)
                    and result.candidate.label not in peaks
                ):
                    peaks[result.candidate.label] = result
        if best is None:
            break
        _, slot, chosen = best
        replaced = next(
            (str(i.get("text", "")).splitlines()[1:2] or ["(빈 슬롯)"])[0]
            for i in [*(current.get("items") or []), {"slot": slot, "text": "\n(빈 슬롯)"}]
            if i.get("slot") == slot
        )
        current = _replace_slot(current, slot, chosen.candidate.text)
        steps.append(
            ItemStep(
                slot=slot,
                adopted=chosen.candidate.label,
                deltas=chosen.delta_now,
                replaced=replaced,
            )
        )

    if peaks:
        notes.append(
            f"조건부 고점 {len(peaks)}건 — 1판(현재 문맥)에서는 밀리지만 요구 축을 "
            f"채우면 우세하다. 추구하려면 그 축을 성립 조건으로 장부화하고 재측정할 것"
        )
    return ItemOptimizeResult(
        spec=current,
        steps=tuple(steps),
        conditional_peaks=tuple(peaks.values()),
        notes=tuple(notes),
    )
