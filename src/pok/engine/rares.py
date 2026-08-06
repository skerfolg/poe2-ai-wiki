"""희귀 아이템 최적화 — "이 빌드의 최선 희귀"를 결정적으로 생성 (사용자 승인 2026-08-06).

`optimize_items`의 유니크 비교 상대인 희귀안이 호출자 손에 있었다 — 비교의 절반이
세션 판단에 달려 있으면 유니크 채택 결론도 세션마다 흔들린다. 사용자가 아이템을
고르는 사고 4·5("포기 후 희귀 고려 → 희귀와 고유의 성능 비교")의 비교 기준을
기계로 내린다:

    슬롯의 합법 접사 풀(KB Modifier, origins=item = 크래프트 가능 표준 풀)에서
    그룹별 최고 티어를 뽑아 → 각 접사를 **단독으로 실측**(이 빌드 문맥의 델타) →
    점수 상위 접두 3 + 접미 3을 조립 → 조립본 실측 + 합법성 검사(RC4).

한계는 결과에 그대로 남긴다: 단독 델타 기반 그리디라 접사 간 상호작용은 조립 후
실측에서만 잡히고, 스폰 태그 매칭은 근사(베이스 태그 순서 미반영)라 최종 합법성은
`ItemLegalityChecker`가 판정한다. 롤은 mid 고정 — 만점 롤 가정이 결론을 뒤집은
실측이 있다.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir
from pok.engine.items import (
    ComputeFn,
    _default_compute,
    _kb_records,
    _replace_slot,
    _req_shortfall,
    resolve_rolls,
)

# 접사 스폰 가중치 태그 근사 — KB base 레코드의 category → 그 베이스가 가질 태그들.
# 방어구는 속성 조합 태그(str_armour 등)를 전부 포함한다: 베이스의 속성형을 텍스트로
# 판별할 수 없어 넓게 잡고, 과포함은 최종 합법성 검사가 거른다(결과에 판정이 남는다).
_ARMOUR_FAMILY = frozenset(
    {"armour", "str_armour", "dex_armour", "int_armour", "str_dex_armour",
     "str_int_armour", "dex_int_armour", "str_dex_int_armour"}
)  # fmt: skip
_CATEGORY_TAGS: dict[str, frozenset[str]] = {
    "helmet": frozenset({"helmet"}) | _ARMOUR_FAMILY,
    "body": frozenset({"body_armour"}) | _ARMOUR_FAMILY,
    "gloves": frozenset({"gloves"}) | _ARMOUR_FAMILY,
    "boots": frozenset({"boots"}) | _ARMOUR_FAMILY,
    "shield": frozenset({"shield"}) | _ARMOUR_FAMILY,
    "buckler": frozenset({"shield"}) | _ARMOUR_FAMILY,
    "focus": frozenset({"focus"}),
    "quiver": frozenset({"quiver"}),
    "belt": frozenset({"belt"}),
    "amulet": frozenset({"amulet"}),
    "ring": frozenset({"ring"}),
    **{
        w: frozenset({w, "weapon"})
        for w in ("mace", "bow", "spear", "staff", "warstaff", "wand", "sceptre",
                  "sword", "axe", "dagger", "claw", "crossbow", "flail", "talisman")
    },
}  # fmt: skip


@dataclass(frozen=True)
class AffixOption:
    label: str  # KB modifier id
    affix_type: str  # prefix | suffix
    text: str  # 롤 해소된 문구 (여러 줄 가능)
    group: str
    ilvl: int


@dataclass(frozen=True)
class AffixReading:
    option: AffixOption
    delta: dict[str, float]

    def score(self, weights: Mapping[str, float]) -> float:
        return sum(w * self.delta.get(k, 0.0) for k, w in weights.items())


@dataclass(frozen=True)
class RareOptimizeResult:
    text: str  # 조립된 최선 희귀 — PoB 파스 가능
    delta: dict[str, float]  # 현재 스펙 대비 (이 희귀를 채택하면 얻는 것)
    chosen: tuple[AffixReading, ...]
    table: tuple[AffixReading, ...]  # 단독 실측 전량 — 절단 없음
    legal: bool
    legality_errors: tuple[str, ...]
    floor_violations: tuple[str, ...]
    req_shortfall: dict[str, float]
    notes: tuple[str, ...]


def base_category(base_type: str, root: Path | None = None) -> str | None:
    """베이스 이름 → KB category (rarity=normal 베이스 레코드에서)."""
    want = base_type.strip().lower()
    for record in _kb_records(root).values():
        if record.type != "Item":
            continue
        data = record.raw.get("data") or {}
        if data.get("rarity") == "unique":
            continue
        name = str((record.raw.get("name") or {}).get("en") or "").strip().lower()
        if name == want:
            return data.get("category")
    return None


def enumerate_base_affixes(
    base_type: str, root: Path | None = None, *, roll: str = "mid"
) -> list[AffixOption]:
    """베이스에 스폰 가능한 표준 접사 풀 — 그룹별 최고 티어(ilvl 최대)만.

    origins에 "item"이 있는 Modifier = 크래프트 가능 표준 풀(1,868건 실측)이다.
    desecrated·corrupted 등 특수 획득 풀은 여기 안 들어간다 — 그건 획득 경로가
    티어 산정에 반영돼야 하는 별개 축이다.
    """
    category = base_category(base_type, root)
    tags = _CATEGORY_TAGS.get(category or "")
    if not tags:
        return []
    best_per_group: dict[str, tuple[int, Any]] = {}
    for record in _kb_records(root).values():
        if record.type != "Modifier":
            continue
        data = record.raw.get("data") or {}
        if "item" not in (data.get("origins") or []):
            continue
        weights = data.get("spawn_weights") or {}
        if not any(weights.get(tag) for tag in tags):
            continue
        if data.get("affix_type") not in ("prefix", "suffix"):
            continue
        texts = data.get("texts") or []
        if not texts:
            continue
        group = str(data.get("group") or record.id)
        ilvl = int(data.get("ilvl") or 0)
        held = best_per_group.get(group)
        if held is None or ilvl > held[0]:
            best_per_group[group] = (ilvl, record)
    out: list[AffixOption] = []
    for ilvl, record in best_per_group.values():
        data = record.raw.get("data") or {}
        out.append(
            AffixOption(
                label=record.id,
                affix_type=str(data.get("affix_type")),
                text="\n".join(resolve_rolls(str(t), roll) for t in data.get("texts") or []),
                group=str(data.get("group") or record.id),
                ilvl=ilvl,
            )
        )
    return sorted(out, key=lambda a: a.label)


@functools.lru_cache(maxsize=2)
def _checker(root: Path | None) -> Any:
    from pok.engine.legality import ItemLegalityChecker

    return ItemLegalityChecker(knowledge_dir(root))


def optimize_rare(
    spec: dict[str, Any],
    slot: str,
    base_type: str,
    weights: Mapping[str, float],
    *,
    stats: tuple[str, ...] | None = None,
    floors: Mapping[str, float] | None = None,
    prefix_count: int = 3,
    suffix_count: int = 3,
    roll: str = "mid",
    root: Path | None = None,
    compute: ComputeFn | None = None,
) -> RareOptimizeResult:
    """이 빌드 문맥에서 그 베이스로 만들 수 있는 최선 희귀를 조립·실측한다.

    각 접사를 벌거벗은 베이스 위에 **단독으로** 실측해 점수를 매기고(문맥 반영 —
    같은 접사도 빌드마다 델타가 다르다), 상위 접두·접미를 조립해 다시 잰다.
    단독 점수 그리디라 접사 간 상호작용은 조립 실측에만 반영된다 — 그 한계와
    합법성 판정이 결과에 그대로 남는다.
    """
    measure = stats or tuple(weights)
    run = compute or _default_compute()
    pool = enumerate_base_affixes(base_type, root, roll=roll)
    # Item Level이 없으면 legality가 기본 1로 파싱해 고티어 접사 전부를 "스폰 불가"로
    # 판정한다(실측 2026-08-06: ilvl 70 접사가 룬 경로로 밀림) — 풀 최고 ilvl로 명시.
    item_level = max((a.ilvl for a in pool), default=1)
    naked = f"Rarity: RARE\nEngineered {slot}\n{base_type}\nItem Level: {item_level}\nImplicits: 0"
    naked_stats = run(_replace_slot(spec, slot, naked))

    readings: list[AffixReading] = []
    for option in pool:
        measured = run(_replace_slot(spec, slot, f"{naked}\n{option.text}"))
        delta = {k: round(measured.get(k, 0.0) - naked_stats.get(k, 0.0), 4) for k in measure}
        readings.append(AffixReading(option=option, delta=delta))

    ranked = sorted(readings, key=lambda r: r.score(weights), reverse=True)
    chosen: list[AffixReading] = []
    counts = {"prefix": 0, "suffix": 0}
    caps = {"prefix": prefix_count, "suffix": suffix_count}
    for reading in ranked:
        kind = reading.option.affix_type
        if reading.score(weights) <= 0 or counts[kind] >= caps[kind]:
            continue
        chosen.append(reading)
        counts[kind] += 1

    assembled = "\n".join([naked, *(r.option.text for r in chosen)])
    base_stats = run(spec)
    measured = run(_replace_slot(spec, slot, assembled))
    delta = {k: round(measured.get(k, 0.0) - base_stats.get(k, 0.0), 4) for k in measure}
    violations = tuple(
        f"{k} {measured.get(k, 0.0):g} < 바닥선 {v:g}"
        for k, v in (floors or {}).items()
        if measured.get(k, 0.0) < v
    )
    report = _checker(root).check(assembled)

    notes = [
        f"접사 풀 {len(pool)}건(그룹별 최고 티어) 전량 단독 실측 — 롤 {roll} 고정",
        "단독 점수 그리디 조립 — 접사 간 상호작용은 조립 실측에만 반영된다",
    ]
    if not report.is_legal:
        notes.append("⚠ 합법성 위반 — 이 조합은 실제로 만들 수 없다. errors 확인")
    return RareOptimizeResult(
        text=assembled,
        delta=delta,
        chosen=tuple(chosen),
        table=tuple(ranked),
        legal=report.is_legal,
        legality_errors=tuple(report.errors),
        floor_violations=violations,
        req_shortfall=_req_shortfall(measured, base_stats),
        notes=tuple(notes),
    )
