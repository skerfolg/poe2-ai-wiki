"""룬 소켓 최적화 — 후보 열거·제약·**올바른 표기** (백로그 #33).

## 왜 자동이어야 하나

룬은 이 프로젝트에서 **두 번** 통째로 빠졌다. 첫 번째는 16칸 0% 사용으로 검사 5종을
통과했고(나중에 채우자 DPS +37~47%), 두 번째는 21칸을 채우자 **IgniteDPS 48,601 →
82,416 (+69.6%)**였다. `check_constraints(exhaustion.sockets)`는 **미사용을 보고만**
하고 채워 주지 않는다 — 그래서 두 번 다 빈 채로 넘어갔다.

비용은 낮다. 부위별로 델타가 있는 룬은 손에 꼽는다(실측: 장갑 4 · 투구 6 · 신발 4 ·
갑옷 11 · 집중구 1).

## ⚠ 표기를 틀리면 **조용한 과소 계상**이 된다

PoB는 `modLine.augmentType == "Rune"`일 때만 `socketedRuneEffectModifier`를 곱한다
(`Item.lua:2192-2209`). 그 표식은 `Sockets:`/`Rune:` **선언**을 읽어야 붙는다.
`{rune}` 줄만 손으로 적으면 모드는 들어가는데 **증폭이 조용히 빠진다.**

실측 2026-08-09 (완드 + `200% increased effect of Socketed Runes`):

    손기입 `{rune}30% increased Spell Damage`  → Δ +26.5
    `Rune: Greater Iron Rune` + 같은 시드 줄   → Δ +79.4   (**3.00배**)

그리고 `Rune:` 선언만 있고 시드 줄이 없으면 **Δ 0**이다 — 원시 텍스트에서는 PoB가
룬 문구를 스스로 채우지 않는다. 즉 **셋 다 있어야** 한다:

    Sockets: S S S
    Rune: Greater Iron Rune
    {rune}30% increased Spell Damage

`render_runed()`가 이 형식을 만든다 — 손으로 조립하지 말 것.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# 일반 룬(등급만 다른 같은 계열) — 같은 이름을 여러 칸에 박아도 된다.
_GENERIC = re.compile(r"\b(lesser|greater|perfect)\b", re.I)
# 유산 룬 — **전 장비 통틀어 1개**(사용자 확인 2026-08-09)
_LEGACY = re.compile(r"\blegacy\b", re.I)


@dataclass(frozen=True)
class RuneOption:
    """한 슬롯에 넣을 수 있는 룬 하나."""

    label: str  # KB modifier id
    name: str  # PoB `Rune:` 선언에 쓰는 이름
    lines: tuple[str, ...]  # 이 부위에서 조건 없이 부여되는 문구
    # ⛔ **조건부 줄을 빼지 말고 라벨을 붙여 노출한다** (#112 · AD-8). 조용히 빼면
    #    호출자가 「없다」와 「조건부다」를 구별하지 못한다 — 실측 2026-08-25:
    #    룬 287건 중 **227건 · 487줄**이 그렇게 사라지고 있었다.
    #    ⚠ 조건은 **샤먼 전용이 아니다** — `Fox Idol`이 그 조건을 해제한다
    #    ("Idols socketed in this item gain the benefits of their Bonded modifiers").
    #    그래서 「쓸 수 있나」는 여기서 못 정한다. **판정은 호출자 몫**(AD-3).
    bonded_lines: tuple[str, ...] = ()

    @property
    def is_legacy(self) -> bool:
        return bool(_LEGACY.search(self.name))

    @property
    def is_generic(self) -> bool:
        """등급 계열 — 중복 장착 가능."""
        return bool(_GENERIC.search(self.name))


def slot_keys(base_record: Mapping[str, Any]) -> frozenset[str]:
    """베이스가 받는 룬 `per_slot` 키들 — item_class·spawn_tags 양쪽에서 모은다.

    룬 레코드의 키는 `weapon`·`armour` 같은 넓은 것과 `wand`·`helmet` 같은 좁은 것이
    섞여 있다(실측: 21종). 어느 쪽으로 적혔든 잡히도록 **둘 다** 본다.
    """
    data = base_record.get("data") or {}
    keys = {str(data.get("item_class") or "").lower()}
    keys |= {str(t).lower() for t, on in (data.get("spawn_tags") or {}).items() if on}
    return frozenset(k for k in keys if k)


def enumerate_slot_runes(base_type: str, root: Path | None = None) -> list[RuneOption]:
    """이 베이스에 장착 가능한 룬 전량. `Bonded:` 줄은 **버리지 않고 갈라서 낸다** (#112).

    `lines`는 조건 없이 붙는 줄, `bonded_lines`는 **조건부** 줄이다. PoB는 이 조건을
    검사하지 않고 그대로 더하므로(KB `bonded_condition`) 시드에는 `lines`만 쓴다 —
    그건 그대로다. 바뀐 것은 **조건부 줄을 조용히 버리지 않는다**는 것이다(AD-8).

    ⚠ **조건이 「샤먼 전용」으로 고정이 아니다.** `Fox Idol`이 그것을 해제한다:
    *"Idols socketed in this item gain the benefits of their Bonded modifiers"*.
    엔진이 항상 빼면 Fox Idol 구성에서 **과소 계상**한다 — 실측 사례(사용자 실물
    `Morior Invictus`, 우상 5종)에서 냉기 저항 +12%·카오스 +8%·정신력 5%·
    **모든 스킬 퀄리티 +5%**가 통째로 누락됐다.

    ⛔ 「쓸 수 있나」는 여기서 못 정한다 — 판정은 호출자 몫이다(AD-3).
    """
    from pok.engine.rares import base_record as _base_record
    from pok.kb.store import load as store_load

    record = _base_record(base_type, root)
    if record is None:
        return []
    wanted = slot_keys(record)
    out: list[RuneOption] = []
    for entry in store_load(root).records.values():
        data = entry.raw.get("data") or {}
        if data.get("affix_type") != "rune":
            continue
        per_slot = data.get("per_slot") or {}
        applicable = [
            str(line)
            for key, texts in per_slot.items()
            if str(key).lower() in wanted
            for line in texts
        ]
        lines = [ln for ln in applicable if not ln.startswith("Bonded:")]
        bonded = [ln for ln in applicable if ln.startswith("Bonded:")]
        if lines or bonded:
            out.append(
                RuneOption(
                    label=entry.id,
                    name=str((entry.raw.get("name") or {}).get("en") or entry.id),
                    lines=tuple(dict.fromkeys(lines)),
                    bonded_lines=tuple(dict.fromkeys(bonded)),
                )
            )
    return sorted(out, key=lambda r: r.label)


def render_runed(item_text: str, runes: Sequence[RuneOption]) -> str:
    """아이템 텍스트에 룬을 **PoB가 증폭까지 태우는 형식**으로 박는다.

    ⛔ 손으로 `{rune}` 줄만 적지 말 것 — 모드는 들어가고 증폭만 빠진다(모듈 docstring).
    """
    if not runes:
        return item_text
    lines = [ln for ln in item_text.splitlines() if not ln.lower().startswith("sockets:")]
    body = [f"Sockets: {' '.join('S' for _ in runes)}"]
    for rune in runes:
        body.append(f"Rune: {rune.name}")
    for rune in runes:
        body += [f"{{rune}}{line}" for line in rune.lines]
    return "\n".join([*lines, *body])


def needs_rune_declaration(item_text: str) -> tuple[str, ...]:
    """`{rune}` 줄이 있는데 선언이 빠졌는가 — **조용한 과소 계상**의 조건.

    `render_runed`를 쓰라는 규율은 문서에만 있어서 강제력이 없었다(철칙 5). 손으로 적은
    텍스트는 여기서 잡는다 — PoB는 `Sockets:`/`Rune:`이 있어야 `augmentType == "Rune"`을
    붙이고, 그때만 `socketedRuneEffectModifier`를 곱한다. 없으면 오류 없이 **3.00배**
    적게 계산된다(실측 2026-08-09: Δ+26.5 vs +79.4).

    반경 주얼(`jewels.needs_radius_declaration`)과 **같은 계열**이라 같은 자리에서 낸다.
    """
    lines = item_text.splitlines()
    seeds = [ln for ln in lines if ln.lstrip().lower().startswith("{rune}")]
    if not seeds:
        return ()
    missing = [
        label
        for label, prefix in (("`Sockets:`", "sockets:"), ("`Rune:`", "rune:"))
        if not any(ln.lstrip().lower().startswith(prefix) for ln in lines)
    ]
    if not missing:
        return ()
    return (
        f"`{{rune}}` 줄 {len(seeds)}건이 있는데 {' · '.join(missing)} 선언이 없다 — PoB가 "
        "룬으로 인식하지 못해 **증폭이 조용히 빠진다**(실측 3.00배). 손으로 적지 말고 "
        "`engine.runes.render_runed`로 조립할 것",
    )


def check_rune_rules(runes: Sequence[RuneOption]) -> tuple[str, ...]:
    """장착 조합이 규칙을 지키는가 (사용자 확인 2026-08-09).

    - 유산(`Legacy of …`)은 **전 장비 통틀어 1개**
    - 고유명 룬은 **같은 이름 1개** (다른 이름끼리는 병용 가능)
    - 일반(`Lesser/Greater/Perfect …`)은 중복 가능
    """
    problems: list[str] = []
    legacies = [r.name for r in runes if r.is_legacy]
    if len(legacies) > 1:
        problems.append(f"유산 룬은 전 장비 통틀어 1개인데 {len(legacies)}개: {legacies}")
    seen: dict[str, int] = {}
    for rune in runes:
        if rune.is_generic or rune.is_legacy:
            continue
        seen[rune.name] = seen.get(rune.name, 0) + 1
    dupes = sorted(name for name, count in seen.items() if count > 1)
    if dupes:
        problems.append(f"고유명 룬은 같은 이름 1개인데 중복: {dupes}")
    return tuple(problems)


@dataclass(frozen=True)
class RuneFill:
    """한 슬롯의 룬 채움 결과."""

    slot: str
    chosen: tuple[RuneOption, ...]
    text: str  # 룬을 박은 아이템 텍스트
    delta: dict[str, float]  # 룬 없는 같은 아이템 대비
    measured: tuple[tuple[str, dict[str, float]], ...]  # 룬별 단독 델타 (전량, 절단 없음)


def optimize_runes(
    spec: dict[str, Any],
    slot: str,
    weights: Mapping[str, float],
    *,
    sockets: int,
    stats: tuple[str, ...] | None = None,
    root: Path | None = None,
    compute: Any = None,
    exclude_legacy: bool = False,
) -> RuneFill | None:
    """슬롯의 룬 칸을 **실측 그리디**로 채운다.

    각 룬을 1칸 넣어 단독 실측한 뒤, 점수 순으로 규칙을 지키며 칸을 채운다. 일반 룬은
    중복 가능하므로 최고점 하나로 남은 칸을 메운다 — 실제 운용이 그렇다.

    `exclude_legacy`는 **다른 슬롯이 이미 유산을 썼을 때** 준다(유산은 전 장비 1개).
    호출자가 슬롯을 돌며 관리한다 — 엔진은 한 슬롯만 본다(AD-3: 판단은 호출자).

    ⚠ **`sockets`는 지어내지 말 것** — 베이스의 `data.socket_limit`, 또는 유니크면
    그 유니크의 정의가 정한 칸 수다. 여기서 상한을 깎지 않는 이유는 유니크가 베이스
    한도를 넘는 경우가 실재하기 때문이다(Atziri's Splendour 6 > 4) — 깎으면 정상
    구성에서 칸을 **조용히 잃는다**. 초과는 `compute_pob`·`assemble_pob`이 PoB
    관측으로 잡아 거부한다(`item_sockets_legal`, #120).
    """
    from pok.engine.items import _default_compute, _replace_slot

    if sockets <= 0:
        return None
    run = compute or _default_compute()
    measure = tuple(stats or tuple(weights))
    current = next(
        (i for i in (spec.get("items") or []) if i.get("slot") == slot),
        None,
    )
    if current is None:
        return None
    base_text = str(current.get("text", ""))
    base_type = base_text.splitlines()[2] if len(base_text.splitlines()) > 2 else ""
    pool = [
        r for r in enumerate_slot_runes(base_type, root) if not (exclude_legacy and r.is_legacy)
    ]
    if not pool:
        return None

    naked = run(_replace_slot(spec, slot, render_runed(base_text, [])))
    scored: list[tuple[float, RuneOption, dict[str, float]]] = []
    for option in pool:
        measured = run(_replace_slot(spec, slot, render_runed(base_text, [option])))
        delta = {k: round(measured.get(k, 0.0) - naked.get(k, 0.0), 4) for k in measure}
        scored.append((sum(w * delta.get(k, 0.0) for k, w in weights.items()), option, delta))
    scored.sort(key=lambda x: x[0], reverse=True)

    chosen: list[RuneOption] = []
    for score, option, _ in scored:
        if len(chosen) >= sockets or score <= 0:
            break
        if check_rune_rules([*chosen, option]):
            continue  # 규칙 위반 — 다음 후보로
        chosen.append(option)
    # 남은 칸은 최고점 **일반** 룬으로 메운다 (중복 가능)
    best_generic = next((o for _, o, _ in scored if o.is_generic), None)
    if best_generic is not None:
        top = next(s for s, o, _ in scored if o is best_generic)
        while len(chosen) < sockets and top > 0:
            chosen.append(best_generic)
    if not chosen:
        return None
    text = render_runed(base_text, chosen)
    final = run(_replace_slot(spec, slot, text))
    return RuneFill(
        slot=slot,
        chosen=tuple(chosen),
        text=text,
        delta={k: round(final.get(k, 0.0) - naked.get(k, 0.0), 4) for k in measure},
        measured=tuple((o.label, d) for _, o, d in scored),
    )
