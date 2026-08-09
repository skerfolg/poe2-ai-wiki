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
from collections.abc import Mapping, Sequence
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
    # item(표준 크래프트) | desecrated(뼈 무덤 제작) | corrupted(훼손) | essence(에센스 부여)
    origin: str = "item"
    # PoB가 이 문구를 아이템 모드로 **읽지 못한다**(KB `pob_modeling.supported: false`).
    # 그러면 단독 실측 델타가 0으로 나오고 그리디는 절대 안 고른다 — 조립된 희귀가
    # **바닥값**이 되는데 그 사실이 어디에도 안 남는다(백로그 #22).
    pob_unmeasurable: bool = False


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
    # PoB가 문구를 못 읽어 **점수를 매길 수 없는** 접사 (백로그 #22). 이것들이 있으면
    # 조립된 희귀는 그 축을 뺀 **바닥값**이다 — 고점이 아니다.
    unmeasurable: tuple[AffixOption, ...] = ()


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
    """베이스 → desecrated·essence 접사의 `applicable_pages` 이름들.

    이들 모드는 spawn_weights가 없고 poe2db 페이지명(`Foci`·`Boots_str_int` 등)
    으로 수록돼 있다 — 페이지 슬러그(정본 kb.item_classes — Staves·Foci 등
    불규칙 복수 포함) + 방어구 속성 접미(spawn_tags의 `str_int_armour` →
    `_str_int`)로 결정적으로 유도한다.
    """
    from pok.kb.item_classes import page_of_class

    plural = page_of_class(item_class)
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
    origins: tuple[str, ...] = ("item", "jewel", "desecrated", "corrupted", "essence"),
) -> list[AffixOption]:
    """베이스에 부여 가능한 접사 풀 — (출처, 그룹)별 최고 티어(ilvl 최대)만.

    출처별 매칭(사용자 요구 2026-08-06 "에센스·훼손 등 모든 속성 부여"):
    - item(1,868건): `spawn_weights` x 베이스 `spawn_tags` 순서 매칭 — 실측:
      Sacred Focus는 {armour, default, focus, int_armour}라 로컬 ES 접사가 붙는다.
    - desecrated(249건): spawn_weights가 없어 `applicable_pages` x 베이스 페이지명.
    - jewel(377건): 주얼 전용 크래프팅 풀 — spawn_weights 매칭(`jewel`·`intjewel` 등).
      빠뜨리면 주얼 후보가 훼손 모드뿐이 된다(실측 2026-08-06 빌드 회차: 11건).
    - corrupted(119건): spawn_weights 매칭 — 접사형이 `corrupted`(별도 칸)다.
    - essence: **에센스 전용 부여**(`granted_by` 보유 ∧ 자연 스폰 전무 →
      `applicable_pages` x 베이스 페이지명, 2026-08-06 ingest 갭 해소분 83건).
      자연 스폰도 되는 에센스 부여 모드는 item 축이 이미 잡는다 — 여기서 또
      잡으면 이중 계상이므로 applicable_pages 보유분(=스폰 전무분)만 본다.
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
        # 에센스 축은 PoB 계보(origins)가 아니라 부여 실체(granted_by)가 판별한다
        # — 합금 모드의 origins는 item이라 계보만 보면 스폰 검사로 탈락한다.
        origin: str | None
        if (
            "essence" in origins
            and data.get("granted_by")
            and set(data.get("applicable_pages") or []) & pages
        ):
            origin = "essence"
        else:
            origin = next((o for o in origins if o != "essence" and o in mod_origins), None)
        if origin is None:
            continue
        if origin == "desecrated":
            if not (set(data.get("applicable_pages") or []) & pages):
                continue
        elif origin != "essence" and not _mod_spawns_on(data.get("spawn_weights") or {}, base_tags):
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
                pob_unmeasurable=(data.get("pob_modeling") or {}).get("supported") is False,
            )
        )
    return sorted(out, key=lambda a: a.label)


@functools.lru_cache(maxsize=2)
def _checker(root: Path | None) -> Any:
    from pok.engine.legality import ItemLegalityChecker

    return ItemLegalityChecker(knowledge_dir(root))


def _affix_caps(base_type: str, root: Path | None) -> tuple[int, int, str]:
    """(접두 한도, 접미 한도, 라벨) — 정본 판 규칙에서. 주얼은 2/2로 장비와 다르다."""
    import json

    category = (base_record(base_type, root) or {}).get("data", {}).get("category") or ""
    rules = knowledge_dir(root) / "crafting-rules" / "board-rules.json"
    caps = (
        json.loads(rules.read_text(encoding="utf-8")).get("affix_caps", {})
        if rules.exists()
        else {}
    )
    section = caps.get(category) or caps.get("equipment") or {}
    rare = section.get("rare") if isinstance(section, dict) else None
    if not isinstance(rare, dict):
        return 3, 3, "equipment(기본값)"
    label = category if caps.get(category) else "equipment"
    return int(rare.get("prefixes", 3)), int(rare.get("suffixes", 3)), label


def _resolve_jewel_slot(spec: Mapping[str, Any], slot: str) -> tuple[str, str]:
    """주얼 슬롯을 소켓으로 해소한다 — 해소 실패는 **말한다**(델타 0의 침묵 방지).

    실측 2026-08-06(빌드 회차): `slot="Jewel"`로 부르면 PoB가 모르는 슬롯명이라
    아이템이 통째로 무시되고 **모든 접사 델타가 0**으로 나왔다. 0은 "효과 없음"으로
    읽혀 주얼이 저스펙으로 출고됐다 — 측정 실패가 측정 결과로 위장한 사례다.
    """
    if not slot.startswith("Jewel"):
        return slot, ""
    allocated = set(spec.get("tree_nodes") or ())
    if "@" in slot:
        node = int(slot.split("@", 1)[1])
        if allocated and node not in allocated:
            return slot, (
                f"⚠ 소켓 {node}가 tree_nodes에 없다 — PoB는 **할당된** 소켓의 주얼만 "
                f"반영하므로 델타가 전부 0으로 나온다. 트리에 소켓을 먼저 할당할 것"
            )
        return slot, ""
    return slot, (
        "⚠ slot='Jewel'에는 소켓이 없다 — `Jewel@<소켓 node_id>` 형태로 부르고 그 "
        "소켓이 tree_nodes에 할당돼 있어야 한다. 지금 측정된 델타는 **전부 무효**다"
    )


def _assemble_text(
    naked: str, chosen: Sequence[AffixReading], *, include_corrupted: bool = True
) -> str:
    """벌거벗은 베이스 + 채택 접사 → 아이템 텍스트.

    훼손 모드는 접사 칸 밖(바알 오브 1회)이라 맨 뒤에 `Corrupted` 표기와 함께 붙인다
    (PoB 관례). 조립을 한 곳에 모은 이유: 그리디가 **조립하면서 검사**하려면 시험용
    텍스트와 최종 텍스트가 같은 함수에서 나와야 한다(#23).
    """
    affixes = [r for r in chosen if r.option.affix_type != "corrupted"]
    corrupted = (
        [r for r in chosen if r.option.affix_type == "corrupted"] if include_corrupted else []
    )
    text = "\n".join([naked, *(r.option.text for r in affixes)])
    if corrupted:
        text = "\n".join([text, *(r.option.text for r in corrupted), "Corrupted"])
    return text


def optimize_rare(
    spec: dict[str, Any],
    slot: str,
    base_type: str,
    weights: Mapping[str, float],
    *,
    stats: tuple[str, ...] | None = None,
    floors: Mapping[str, float] | None = None,
    prefix_count: int | None = None,
    suffix_count: int | None = None,
    roll: str = "mid",
    root: Path | None = None,
    compute: ComputeFn | None = None,
) -> RareOptimizeResult:
    """이 빌드 문맥에서 그 베이스로 만들 수 있는 최선 희귀를 조립·실측한다.

    각 접사를 벌거벗은 베이스 위에 **단독으로** 실측해 점수를 매기고(문맥 반영 —
    같은 접사도 빌드마다 델타가 다르다), 상위 접두·접미를 조립해 다시 잰다.
    단독 점수 그리디라 접사 간 상호작용은 조립 실측에만 반영된다 — 그 한계와
    합법성 판정이 결과에 그대로 남는다.

    접사 한도는 **정본 판 규칙**에서 읽는다(장비 3/3, 주얼 2/2) — 하드코딩 3/3으로
    주얼을 조립하면 못 만드는 아이템이 나온다. 주얼은 `slot="Jewel@<소켓 node_id>"`
    로 부르고 그 소켓이 `tree_nodes`에 할당돼 있어야 한다 — 아니면 PoB가 무시해
    **모든 델타가 0으로 나온다**(실측 2026-08-06 빌드 회차: 주얼이 저스펙으로 출고).
    """
    measure = stats or tuple(weights)
    run = compute or _default_compute()
    pool = enumerate_base_affixes(base_type, root, roll=roll)
    notes_pre: list[str] = []
    slot, socket_note = _resolve_jewel_slot(spec, slot)
    if socket_note:
        notes_pre.append(socket_note)
    # Item Level이 없으면 legality가 기본 1로 파싱해 고티어 접사 전부를 "스폰 불가"로
    # 판정한다(실측 2026-08-06: ilvl 70 접사가 룬 경로로 밀림) — 풀 최고 ilvl로 명시.
    item_level = max((a.ilvl for a in pool), default=1)
    # 베이스 암시적은 **텍스트에 적어야** PoB가 반영한다(실측 2026-08-06: 돌의 주먹
    # 암시적을 빼면 델타 0, 적으면 +100 ES·+300 회피) — 정본에서 읽어 자동 기재한다.
    implicit = str((base_record(base_type, root) or {}).get("data", {}).get("implicit") or "")
    implicit_lines = [resolve_rolls(implicit, roll)] if implicit else []
    naked = "\n".join(
        [
            "Rarity: RARE",
            f"Engineered {slot}",
            base_type,
            f"Item Level: {item_level}",
            f"Implicits: {len(implicit_lines)}",
            *implicit_lines,
        ]
    )
    naked_stats = run(_replace_slot(spec, slot, naked))

    readings: list[AffixReading] = []
    for option in pool:
        measured = run(_replace_slot(spec, slot, f"{naked}\n{option.text}"))
        delta = {k: round(measured.get(k, 0.0) - naked_stats.get(k, 0.0), 4) for k in measure}
        readings.append(AffixReading(option=option, delta=delta))

    cap_pre, cap_suf, cap_label = _affix_caps(base_type, root)
    if prefix_count is not None:
        cap_pre = prefix_count
    if suffix_count is not None:
        cap_suf = suffix_count
    ranked = sorted(readings, key=lambda r: r.score(weights), reverse=True)
    chosen: list[AffixReading] = []
    counts = {"prefix": 0, "suffix": 0, "corrupted": 0}
    caps = {"prefix": cap_pre, "suffix": cap_suf, "corrupted": 1}
    skipped_illegal: list[str] = []
    for reading in ranked:
        kind = reading.option.affix_type
        if reading.score(weights) <= 0 or counts[kind] >= caps[kind]:
            continue
        # **조립하면서 검사한다** (백로그 #23). 사후 검사만 하면 반환 `text`를 그대로
        # 못 쓰고 매번 손으로 재조립해야 한다 — 실측 2026-08-09(투구): `legal: false`로
        # 접두 초과·group 중복이 나왔다.
        #
        # 왜 개수만 세면 안 되나: 그리디는 **후보 단위**로 세는데 검사기는 **매칭된
        # 모드 id 단위**로 센다. 하이브리드 한 후보가 두 줄이면 검사기가 서로 다른
        # 모드 둘로 매칭할 수 있어 3개를 골랐는데 5개로 세진다(실측). 그래서 개수
        # 계산을 맞추는 대신 **검사기에게 직접 묻는다** — 판정 주체가 하나가 된다.
        trial = _assemble_text(naked, [*chosen, reading], include_corrupted=False)
        if not _checker(root).check(trial).is_legal:
            skipped_illegal.append(reading.option.label)
            continue
        chosen.append(reading)
        counts[kind] += 1

    assembled = _assemble_text(naked, chosen)
    base_stats = run(spec)
    measured = run(_replace_slot(spec, slot, assembled))
    delta = {k: round(measured.get(k, 0.0) - base_stats.get(k, 0.0), 4) for k in measure}
    violations = tuple(
        f"{k} {measured.get(k, 0.0):g} < 바닥선 {v:g}"
        for k, v in (floors or {}).items()
        if measured.get(k, 0.0) < v
    )
    report = _checker(root).check(_assemble_text(naked, chosen, include_corrupted=False))

    by_origin = {
        o: sum(r.option.origin == o for r in chosen) for o in ("desecrated", "corrupted", "essence")
    }
    # PoB가 못 읽는 접사는 단독 델타가 0이라 **그리디가 절대 안 고른다** — 조립 결과가
    # 그 축을 뺀 바닥값이 되는데, 말하지 않으면 "이 베이스의 고점"으로 읽힌다(#22).
    # 실측 2026-08-09: `Amber Amulet` 접사 풀 82건 중 **32건(39%)**이 여기 해당한다.
    unmeasurable = tuple(o for o in pool if o.pob_unmeasurable)
    notes = [
        *notes_pre,
        f"접사 풀 {len(pool)}건(출처·그룹별 최고 티어) 전량 단독 실측 — 롤 {roll} 고정",
        f"접사 한도 {cap_pre}접두/{cap_suf}접미 — 정본 판 규칙({cap_label})",
        "단독 점수 그리디 조립 — 접사 간 상호작용은 조립 실측에만 반영된다",
    ]
    if implicit_lines:
        notes.append(f"베이스 암시적 자동 기재: {implicit_lines[0]} — 안 적으면 PoB가 반영 안 한다")
    if all(all(abs(v) < 1e-9 for v in r.delta.values()) for r in readings) and readings:
        notes.append(
            "⚠ **모든 접사 델타가 0** — 측정이 성립하지 않았다는 신호다(슬롯명 오류·"
            "미할당 소켓 등). '효과 없음'으로 읽지 말 것"
        )
    if by_origin["desecrated"]:
        notes.append(
            f"desecrated(뼈 무덤 제작) 접사 {by_origin['desecrated']}건 포함 — 뼈 조달이 필요하다"
            f"(획득 경로가 티어 산정에 반영돼야 한다)"
        )
    if by_origin["corrupted"]:
        notes.append(
            "훼손 모드 1건 포함 — 바알 오브는 결과가 무작위라 **노린 모드는 도박**이다. "
            "합법성 검사는 접사만으로 했다(훼손 모드는 접사 칸 밖)"
        )
    if by_origin["essence"]:
        notes.append(
            f"에센스 전용 부여 접사 {by_origin['essence']}건 포함 — 해당 에센스 조달이 "
            f"필요하고 부여는 확정적이다 (어느 에센스인지는 KB Modifier의 granted_by)"
        )
    if not report.is_legal:
        notes.append("⚠ 합법성 위반 — 이 조합은 실제로 만들 수 없다. errors 확인")
    if unmeasurable:
        sample = ", ".join(o.label for o in unmeasurable[:3])
        notes.append(
            f"⚠ 접사 {len(pool)}건 중 **{len(unmeasurable)}건은 PoB가 문구를 못 읽는다** — "
            f"단독 델타가 0이라 그리디가 절대 고르지 않는다. 이 조립은 그 축을 뺀 "
            f"**바닥값**이지 고점이 아니다. 전량은 `unmeasurable`에 있다 (예: {sample}). "
            f"등가 문구로 바꿔 `ItemSpec.substitutes`에 넣으면 **추산**으로는 잴 수 있다"
        )
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
        unmeasurable=unmeasurable,
    )
