"""희귀 아이템 최적화 — "이 빌드의 최선 희귀"를 결정적으로 생성 (사용자 승인 2026-08-06).

`optimize_items`의 유니크 비교 상대인 희귀안이 호출자 손에 있었다 — 비교의 절반이
세션 판단에 달려 있으면 유니크 채택 결론도 세션마다 흔들린다. 사용자가 아이템을
고르는 사고 4·5("포기 후 희귀 고려 → 희귀와 고유의 성능 비교")의 비교 기준을
기계로 내린다:

    슬롯의 합법 접사 풀(KB Modifier, origins=item = 크래프트 가능 표준 풀)에서
    그룹별 최고 티어를 뽑아 → 각 접사를 **단독으로 실측**(이 빌드 문맥의 델타) →
    점수 상위 접두 3 + 접미 3을 조립 → 조립본 실측 + 합법성 검사(RC4).

한계는 결과에 그대로 남긴다: 단독 델타 기반 그리디라 접사 간 상호작용은 조립 후
실측에서만 잡히고, 최종 합법성은 `ItemLegalityChecker`가 판정한다. 롤은 mid 고정 —
만점 롤 가정이 결론을 뒤집은 실측이 있다.

스폰 판정은 **KB base 레코드의 `spawn_tags`**(수집 당시 조사·수록된 정본)를 게임
방식대로 순서 매칭한다 — 처음엔 category→태그 손 매핑 근사를 썼다가 집중구의
`int_armour` 태그를 놓쳐 로컬 에너지 실드 접사 전부가 풀에서 빠졌다(사용자 지적
2026-08-06: "KB 구축 당시 속성 부여도 조사해서 포함"). 정본이 있는데 근사를 만들면
정본과 어긋난 만큼이 조용한 구멍이 된다.
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


@dataclass(frozen=True)
class AffixOption:
    label: str  # KB modifier id
    affix_type: str  # prefix | suffix | corrupted
    text: str  # 롤 해소된 문구 (여러 줄 가능)
    group: str
    ilvl: int
    origin: str = "item"  # item(표준 크래프트) | desecrated(신성모독) | corrupted(훼손)


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


def base_record(base_type: str, root: Path | None = None) -> Mapping[str, Any] | None:
    """베이스 이름 → KB 베이스 레코드 raw (rarity=normal, 이름 정확 일치)."""
    want = base_type.strip().lower()
    for record in _kb_records(root).values():
        if record.type != "Item":
            continue
        data = record.raw.get("data") or {}
        if data.get("rarity") == "unique":
            continue
        name = str((record.raw.get("name") or {}).get("en") or "").strip().lower()
        if name == want:
            return dict(record.raw)
    return None


def base_category(base_type: str, root: Path | None = None) -> str | None:
    """베이스 이름 → KB category (rarity=normal 베이스 레코드에서)."""
    record = base_record(base_type, root)
    return (record.get("data") or {}).get("category") if record else None


def _mod_spawns_on(weights: Mapping[str, Any], base_tags: frozenset[str]) -> bool:
    """게임의 스폰 규칙 재현: spawn_weights를 **순서대로** 훑어 베이스 태그와 처음
    일치하는 항목의 가중치가 판정한다 — `{'focus': 0, 'default': 1}`은 집중구 제외,
    `{'int_armour': 1, 'default': 0}`은 int 방어구(집중구 포함)에만 스폰."""
    for tag, weight in weights.items():
        if tag in base_tags:
            return bool(weight)
    return False


def _base_pages(item_class: str, base_tags: frozenset[str]) -> frozenset[str]:
    """베이스 → 신성모독 접사의 `applicable_pages` 이름들.

    desecrated 모드는 spawn_weights가 없고 poe2db 페이지명(`Foci`·`Boots_str_int` 등)
    으로 수록돼 있다 — item_class 복수형 + 방어구 속성 접미(spawn_tags의
    `str_int_armour` → `_str_int`)로 결정적으로 유도한다.
    """
    plural = {"Focus": "Foci"}.get(
        item_class, item_class if item_class.endswith("s") else item_class + "s"
    ).replace(" ", "_")
    pages = {plural}
    for tag in base_tags:
        if tag.endswith("_armour") and tag != "armour":
            pages.add(f"{plural}_{tag[: -len('_armour')]}")
    return frozenset(pages)


def enumerate_base_affixes(
    base_type: str,
    root: Path | None = None,
    *,
    roll: str = "mid",
    origins: tuple[str, ...] = ("item", "desecrated", "corrupted"),
) -> list[AffixOption]:
    """베이스에 부여 가능한 접사 풀 — (출처, 그룹)별 최고 티어(ilvl 최대)만.

    출처별 매칭(사용자 요구 2026-08-06 "에센스·훼손 등 모든 속성 부여"):
    - item(1,868건): `spawn_weights` x 베이스 `spawn_tags` 순서 매칭 — 실측:
      Sacred Focus는 {armour, default, focus, int_armour}라 로컬 ES 접사가 붙는다.
    - desecrated(249건): spawn_weights가 없어 `applicable_pages` x 베이스 페이지명.
    - corrupted(119건): spawn_weights 매칭 — 접사형이 `corrupted`(별도 칸)다.
    - ⚠ **완벽 에센스 전용 82건은 열거 불가** — spawn_weights 전부 0이고 부위 매핑이
      KB 미수록(ingest 갭, 2026-08-06 보고). 일반 에센스는 표준 풀 보장이라 item에
      포함돼 있다.
    """
    record = base_record(base_type, root)
    if record is None:
        return []
    data0 = record.get("data") or {}
    spawn_tags = data0.get("spawn_tags") or {}
    base_tags = frozenset(t for t, on in spawn_tags.items() if on)
    if not base_tags:
        return []
    pages = _base_pages(str(data0.get("item_class") or ""), base_tags)
    best_per_group: dict[tuple[str, str], tuple[int, Any, str]] = {}
    for record_ in _kb_records(root).values():
        if record_.type != "Modifier":
            continue
        data = record_.raw.get("data") or {}
        mod_origins = set(data.get("origins") or [])
        origin = next((o for o in origins if o in mod_origins), None)
        if origin is None:
            continue
        if origin == "desecrated":
            if not (set(data.get("applicable_pages") or []) & pages):
                continue
        elif not _mod_spawns_on(data.get("spawn_weights") or {}, base_tags):
            continue
        if data.get("affix_type") not in ("prefix", "suffix", "corrupted"):
            continue
        texts = data.get("texts") or []
        if not texts:
            continue
        key = (origin, str(data.get("group") or record_.id))
        ilvl = int(data.get("ilvl") or 0)
        held = best_per_group.get(key)
        if held is None or ilvl > held[0]:
            best_per_group[key] = (ilvl, record_, origin)
    out: list[AffixOption] = []
    for ilvl, record_, origin in best_per_group.values():
        data = record_.raw.get("data") or {}
        out.append(
            AffixOption(
                label=record_.id,
                affix_type=str(data.get("affix_type")),
                text="\n".join(resolve_rolls(str(t), roll) for t in data.get("texts") or []),
                group=str(data.get("group") or record_.id),
                ilvl=ilvl,
                origin=origin,
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
    counts = {"prefix": 0, "suffix": 0, "corrupted": 0}
    caps = {"prefix": prefix_count, "suffix": suffix_count, "corrupted": 1}
    for reading in ranked:
        kind = reading.option.affix_type
        if reading.score(weights) <= 0 or counts[kind] >= caps[kind]:
            continue
        chosen.append(reading)
        counts[kind] += 1

    # 훼손 모드는 접사 칸 밖(바알 오브 1회) — 합법성 검사는 접사만으로 하고,
    # 최종 텍스트에는 모드 + "Corrupted" 표기로 들어간다(PoB 관례).
    affix_chosen = [r for r in chosen if r.option.affix_type != "corrupted"]
    corrupt_chosen = [r for r in chosen if r.option.affix_type == "corrupted"]
    affix_text = "\n".join([naked, *(r.option.text for r in affix_chosen)])
    assembled = affix_text
    if corrupt_chosen:
        assembled = "\n".join([affix_text, *(r.option.text for r in corrupt_chosen), "Corrupted"])
    base_stats = run(spec)
    measured = run(_replace_slot(spec, slot, assembled))
    delta = {k: round(measured.get(k, 0.0) - base_stats.get(k, 0.0), 4) for k in measure}
    violations = tuple(
        f"{k} {measured.get(k, 0.0):g} < 바닥선 {v:g}"
        for k, v in (floors or {}).items()
        if measured.get(k, 0.0) < v
    )
    report = _checker(root).check(affix_text)

    by_origin = {o: sum(r.option.origin == o for r in chosen) for o in ("desecrated", "corrupted")}
    notes = [
        f"접사 풀 {len(pool)}건(출처·그룹별 최고 티어) 전량 단독 실측 — 롤 {roll} 고정",
        "단독 점수 그리디 조립 — 접사 간 상호작용은 조립 실측에만 반영된다",
    ]
    if by_origin["desecrated"]:
        notes.append(
            f"신성모독 접사 {by_origin['desecrated']}건 포함 — 무덤 제작 조달이 필요하다"
            f"(획득 경로가 티어 산정에 반영돼야 한다)"
        )
    if by_origin["corrupted"]:
        notes.append(
            "훼손 모드 1건 포함 — 바알 오브는 결과가 무작위라 **노린 모드는 도박**이다. "
            "합법성 검사는 접사만으로 했다(훼손 모드는 접사 칸 밖)"
        )
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
