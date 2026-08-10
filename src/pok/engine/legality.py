"""합성 아이템 적법성 검증 — RC4 (절대 못 만드는 아이템 거부).

결정적 대조만 한다(AD-3): 아이템 텍스트의 모드 줄 하나하나를 KB Modifier와
매칭해 ① 존재 ② 수치가 티어 범위 안 ③ ilvl 충족 ④ 베이스에 스폰 가능
⑤ 접사 수(희귀 ≤3/≤3, 마법 ≤1/≤1) ⑥ 같은 group 중복 금지를 검사한다.

매칭 키 = 숫자·범위를 `#`로 치환한 정규화 텍스트 (KB texts와 동일 규칙).
스폰 판정: 베이스 spawn_tags 중 weight>0가 있으면 통과. weight가 전부 0이어도
acquisition에 essence·desecrated 등 비-크래프팅 경로가 있으면 CONDITIONAL
(경로 명시) — C-2 판정(2026-07-30)에서 확립한 "weight 0 ≠ 죽은 모드" 원칙.
단 CONDITIONAL은 "경로 존재"만으로 주지 않는다(#34) — 그 경로가 이 베이스에
적용 가능한지(_route_base_fit)를 반증 가능한 신호(spawn_weights 명시 클래스 키·
applicable_pages·scope)로 함께 판정한다. poe2db:normal은 일반 모드 풀(화폐
크래프팅) 표지이므로 비크래프팅 경로로 치지 않는다.

접사 한도는 판 규칙(knowledge/crafting-rules/board-rules.json)에서 읽는다 —
장비 rare 3/3·magic 1/1, 주얼 rare 2/2 + 0.5 시즌 season_override(총 5모드,
3접미/2접두 또는 2접미/3접두). 하드코딩 금지(정본이 진실).
"""

from __future__ import annotations

import contextlib
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pok.engine.jewels import RADIUS_LABELS, needs_radius_declaration
from pok.engine.runes import needs_rune_declaration
from pok.kb.store import load as store_load

_NUM = re.compile(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)|\d+(?:\.\d+)?")
_RANGE = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")
# 선택지 열거 "(A/B/C)" — 고유 주얼 롤 변형 표기 (unique_fixes 규약). 범위 "(a-b)"와 구분됨
_ENUM = re.compile(r"\(([^()]*/[^()]*)\)")
# 크래프팅과 동치인 획득 표지 — 비크래프팅 "경로"가 아니다 (#34).
# poe2db:normal = 일반 모드 풀(화폐 크래프팅으로 붙는 풀)의 poe2db 표지.
_CRAFT_EQUIVALENT = ("crafting-currency", "poe2db:normal")

# 접미어 효과 접두 (주얼) — 인게임 표시 접미 수치는 이 효과가 이미 곱해진 최종값이다.
# PoB는 이 줄을 계산에 반영하지 않으므로(실측 2026-07-31: 효과 줄 유무 DPS 동일
# 51,792.2 vs 수동 1.6배 반영 59,000.7) 접미 수치를 최종 표시값으로 합성하는 것이
# 정직한 모델링이고, 적법성은 접미 티어 범위 상한을 x(1+효과/100)로 확장해 판정한다.
_SUFFIX_EFFECT = re.compile(r"^(\d+(?:\.\d+)?)% increased Effect of Suffixes$", re.IGNORECASE)


_RUNE_PREFIX = re.compile(r"^\s*\{rune\}\s*", re.I)
# PoB 아이템 텍스트의 **스펙 줄**(모드가 아니다). `Item.lua`가 specName으로 읽는다.
_SPEC_LINE_PREFIXES = (
    "quality:",
    "sockets:",
    "implicits:",
    "rune:",
    "radius:",
    "requires:",
    "--",
    # `BuildRaw()`가 쓰는 나머지 스펙 줄 (#34). 이게 없어서 **검사기가 자기 도구의
    # 출력을 거부했다** — 실측 2026-08-09: 명세로 생성한 목걸이에서 스펙 줄 10개가
    # 전부 UNKNOWN으로 찍혔다. #30(스펙 줄 오독)과 같은 계열이고, 그때 목록이
    # 부족했던 것이다. 근거는 `Item.lua::BuildRaw` L1396~1601의 기록 순서.
    "crafted:",
    "prefix:",
    "suffix:",
    "catalyst:",
    "catalystquality:",
    "levelreq:",
    "league:",
    "unique id:",
    "variant:",
    "selected variant:",
    "has alt variant",
    "selected alt variant",
    "allow duplicate variants",
    "limited to:",
    "charm slots:",
    "spirit:",
    "armour:",
    "evasion:",
    "energy shield:",
    "ward:",
    "unreleased:",
    "item level:",
)
# 사용자가 **의도적으로** 넣은 줄. PoB가 `{custom}`으로 표시하고 `Craft()`도 이것만
# 보존한다(L1698). "KB에 없다"가 아니라 "규격 밖인 걸 알고 넣었다"이므로 UNKNOWN과
# 구분한다 — 실측 2026-08-09: 사용자 목걸이의 `+7% to Fire Spell Critical Hit Chance`.
_CUSTOM_PREFIX = re.compile(r"^\s*\{custom\}", re.I)
# PoB `writeModLine`(L1461~1503)이 모드 줄 앞에 붙이는 **장식 접두** 전부.
# `{range:0.5}`·`{tags:attribute}`·`{enchant}` 같은 것으로, 문구가 아니라 표기다.
# 벗기지 않으면 KB 매칭이 통째로 실패한다 — 실측 2026-08-09: 명세 형식으로 바꾸자
# 베이스 임플리싯 `{range:0.5}+(10-15) to Intelligence`가 UNKNOWN이 되면서 조립
# 시도가 전부 실격 판정을 받아 **접사를 하나도 못 골랐다**.
_MOD_DECORATION = re.compile(
    r"^\s*(?:\{(?:range|corruptedRange|variant|tags):[^}]*\}|"
    r"\{(?:enchant|fractured|desecrated|mutated|crafted|unscalable)\})+",
    re.I,
)
# 촉매 — `Item.lua:14`의 목록 순서가 곧 `catalystTags`(L20~)의 인덱스다.
# 배율은 `(100 + quality)/100`이고 **모드 태그가 촉매 태그와 겹칠 때만** 걸린다(L32~57).
_CATALYST_TAGS: dict[str, frozenset[str]] = {
    "flesh": frozenset({"life"}),
    "neural": frozenset({"mana"}),
    "carapace": frozenset({"defences", "armour", "evasion", "energyshield"}),
    "uul-netol's": frozenset({"physical"}),
    "xoph's": frozenset({"fire"}),
    "tul's": frozenset({"cold"}),
    "esh's": frozenset({"lightning"}),
    "chayula's": frozenset({"chaos"}),
    "reaver": frozenset({"attack"}),
    "sibilant": frozenset({"caster"}),
    "skittering": frozenset({"speed"}),
    "adaptive": frozenset({"attribute"}),
    "necrotic": frozenset({"minion"}),
}
# 값 없이 서는 **표식**
_SPEC_MARKERS = frozenset({"corrupted", "mirrored", "split", "unidentified"})
# 아이템이 소켓 룬 효과를 올리는 줄 (유니크 `Runeseeker's Call` 등)
_RUNE_EFFECT = re.compile(r"(\d+(?:\.\d+)?)%\s+increased effect of Socketed Runes", re.I)


def _mod_texts(data: dict[str, Any]) -> list[str]:
    """모드의 효과 문구 — `texts` 우선, 없으면 슬롯별 `per_slot` 전량.

    룬은 같은 이름이라도 장착 슬롯(무기/방어구/주문구)에 따라 효과가 다르므로
    `per_slot`에 나뉘어 있다. 어느 슬롯 표기로 적혀 오든 매칭되게 전부 색인한다.
    """
    texts = list(data.get("texts") or [])
    if texts:
        return texts
    per_slot = data.get("per_slot")
    if isinstance(per_slot, dict):
        return [str(t) for lines in per_slot.values() if isinstance(lines, list) for t in lines]
    return []


def _norm(text: str) -> str:
    """수치·범위 → '#' 정규화 (매칭 키).

    공백도 정규화한다: 연속 공백 붕괴 + '%' 앞 공백 제거 — 훼손 풀 원문은
    "(10-18) % chance…"처럼 % 앞에 공백이 있어 인게임 표기("14% chance…")와
    키가 어긋난다 (양쪽 모두 이 함수를 거치므로 대칭 안전).
    """
    collapsed = " ".join(_NUM.sub("#", text).split())
    return collapsed.replace(" %", "%").lower()


def _expand_enum(text: str) -> list[str]:
    """ "(A/B/C)" 선택지 열거를 개별 텍스트들로 펼친다 (없으면 원문 그대로 1개).

    고유 주얼의 롤 변형 표기(KB unique_fixes 규약) — 실물 아이템엔 선택지 하나만
    롤되므로, 대조는 펼친 각 형태와 해야 한다. 열거가 여러 개면 데카르트 곱.
    """
    m = _ENUM.search(text)
    if m is None:
        return [text]
    out: list[str] = []
    for option in m.group(1).split("/"):
        head = text[: m.start()] + option + text[m.end() :]
        out.extend(_expand_enum(head))
    return out


def _magnitudes(text: str) -> list[float]:
    """문구의 수치들 — `(10-15)` 같은 **범위는 상단**을 쓴다.

    `_NUM`은 범위 표기까지 한 토큰으로 잡으므로 그대로 `float()`에 넣으면 터진다
    (실측 2026-08-10: 벨트 임플리싯 `(8-12)% increased Cast Speed`에서 조립이 죽었다).
    """
    out: list[float] = []
    for token in _NUM.findall(text):
        span = _RANGE.fullmatch(token)
        out.append(float(span.group(2)) if span else float(token))
    return out


def _base_implicits(base: dict[str, Any] | None) -> dict[str, str]:
    """베이스가 달고 나오는 임플리싯 줄들 — 정규화 키 → 원문 (백로그 #57).

    KB `data.implicit`은 **여러 줄일 수 있다**(`Invoking Belt`은 시전 속도 + 부적
    칸 둘). 줄 단위로 쪼개야 두 번째 줄이 미아가 되지 않는다.
    """
    raw = str(((base or {}).get("data") or {}).get("implicit") or "")
    out: dict[str, str] = {}
    for line in raw.splitlines():
        stripped = _MOD_DECORATION.sub("", line).strip()
        if stripped:
            out[_norm(stripped)] = stripped
    return out


def _match_implicit(line: str, implicits: dict[str, str]) -> LineVerdict | None:
    """이 줄이 베이스 임플리싯인가 — 맞으면 값이 베이스 범위 안인지까지 본다.

    ⚠ 적힌 값이 **아직 롤되지 않은 범위**일 수 있다 — PoB 명세 형식은
    `{range:0.5}(8-12)% increased Cast Speed`처럼 범위를 그대로 두고 비율만
    장식으로 얹는다. 그래서 접사용 롤 대조를 그대로 쓰면 자기 출력이 실격난다.
    적힌 수치 전부가 베이스 범위의 봉투 안이면 통과다.
    """
    stripped = _MOD_DECORATION.sub("", line).strip()
    source = implicits.get(_norm(stripped))
    if source is None:
        return None
    bounds = [(float(lo), float(hi)) for lo, hi in _RANGE.findall(source)] or [
        (v, v) for v in _magnitudes(source)
    ]
    low, high = min(b[0] for b in bounds), max(b[1] for b in bounds)
    written = _magnitudes(stripped) + [float(lo) for lo, _ in _RANGE.findall(stripped)]
    outside = [v for v in written if v < low - 1e-6 or v > high + 1e-6]
    if not outside:
        return LineVerdict(line, "LEGAL", reason="베이스 임플리싯 — 접사 칸을 쓰지 않는다")
    return LineVerdict(
        line,
        "ILLEGAL",
        reason=f"베이스 임플리싯 범위 밖: {outside} ∉ [{low:g}, {high:g}] (베이스: {source!r})",
    )


def _rune_value_note(line: str, rune: dict[str, Any]) -> str:
    """ "룬으로는 가능"에 **그 룬의 실제 값**을 붙인다 (백로그 #56, 2026-08-10).

    매칭 키는 숫자를 `#`로 죽인 정규화 텍스트라 `+40 to Intelligence`가
    `+12` 룬에 붙는다 — 그래도 CONDITIONAL이 나오니 호출자는 **그 수치로 가능**
    하다고 읽는다. 실측: `+40 to Intelligence` → `greater-resolve-rune`(실제 +12,
    3.3배) · `+25 to all Attributes` → `legacy-of-erians-cobble`(실제 +5, 5배).
    보고자는 레코드를 따로 열어 보고서야 알았다 — §0 ①의 값 판본이다.

    ⛔ 여기서 위반이라고 단정하지 않는다: 같은 룬을 여러 칸에 박는 것이 정상
    운용이라 소켓 수를 알아야 상한이 정해진다(그 판정은 `_rune_value_verdict`가
    `{rune}` 표기 경로에서 한다). 여기선 **사실을 보이고 필요한 칸 수를 준다.**
    """
    written = _magnitudes(line)
    per_slot = (rune.get("data") or {}).get("per_slot") or {}
    values: dict[str, float] = {}
    for slot, texts in per_slot.items():
        for text in texts:
            if _norm(text) == _norm(line):
                nums = _magnitudes(str(text))
                if nums:
                    values[str(slot)] = max(nums)
    if not written or not values:
        return ""
    want, best = max(written), max(values.values())
    shown = " · ".join(f"{v:g} ({s})" for s, v in sorted(values.items()))
    if abs(want - best) < 1e-6:
        return f". 이 룬 1개 값 = {shown} — 선언값과 같다"
    needed = math.ceil(want / best) if best > 0 else 0
    return (
        f". ⚠ **이 룬 1개 값은 {shown}이고 선언값 {want:g}과 다르다** — "
        f"그 수치를 내려면 소켓 {needed}칸이 필요하다(룬 효과 증폭 없을 때). "
        f"칸 수는 `Sockets:` 선언으로 적어야 값 판정이 돈다"
    )


@dataclass(frozen=True)
class LineVerdict:
    line: str
    status: str  # LEGAL | CONDITIONAL | ILLEGAL | UNKNOWN
    modifier_id: str | None = None
    reason: str = ""


@dataclass(frozen=True)
class LegalityReport:
    verdicts: tuple[LineVerdict, ...]
    errors: tuple[str, ...] = field(default=())  # 구조 위반 (접사 수·group 중복 등)

    @property
    def is_legal(self) -> bool:
        return not self.errors and all(v.status in ("LEGAL", "CONDITIONAL") for v in self.verdicts)


class ItemLegalityChecker:
    """KB를 인덱싱해 두고 아이템 텍스트를 검사한다 (로드 1회, 검사 N회)."""

    _FALLBACK_CAPS: ClassVar[dict[str, dict[str, int]]] = {
        "rare": {"prefixes": 3, "suffixes": 3},
        "magic": {"prefixes": 1, "suffixes": 1},
    }

    def __init__(self, knowledge: Path) -> None:
        kdir = knowledge if knowledge.name == "knowledge" else knowledge / "knowledge"
        rules = kdir / "crafting-rules" / "board-rules.json"
        self._affix_caps: dict[str, Any] = (
            json.loads(rules.read_text(encoding="utf-8")).get("affix_caps", {})
            if rules.exists()
            else {}
        )
        kb = store_load(knowledge.parent if knowledge.name == "knowledge" else knowledge)
        self._root = knowledge.parent if knowledge.name == "knowledge" else knowledge
        self._bases: dict[str, dict[str, Any]] = {}
        self._uniques: dict[str, dict[str, Any]] = {}  # 유니크 이름 → 레코드
        self._mods: dict[str, list[dict[str, Any]]] = {}  # 정규화 텍스트 → 후보 레코드들
        # 고유 주얼 전략 모듈용 색인 (2026-07-31, 사용자 확립 "주얼별 전략 모듈")
        self._heart: dict[str, list[dict[str, Any]]] = {}  # Heart of the Well 훼손 풀
        self._notables: dict[str, dict[str, Any]] = {}  # 본 트리+어센 노터블 (Megalomaniac)
        self._skills: set[str] = set()  # KB Skill 표시명 (Prism of Belief)
        for r in kb.records.values():
            if r.type == "Item" and r.raw.get("data", {}).get("rarity") == "unique":
                self._uniques[r.name_en.lower()] = r.raw  # 유니크 우선 (category도 가질 수 있다)
            elif r.type == "Item" and r.raw.get("data", {}).get("category"):
                self._bases[r.name_en.lower()] = r.raw
            elif r.type == "Modifier" and {"item", "jewel", "desecrated", "rune"} & set(
                r.raw.get("data", {}).get("origins", [])
            ):  # jewel origin도 크래프팅 풀 — 주얼 베이스 검증에 필요 (2026-07-31).
                # desecrated도 합성 검증 풀에 포함(사용자 지시 2026-07-31) —
                # spawn_weights가 없어 _route_base_fit의 pages/scope 신호로 판정된다.
                # rune은 `texts`가 없고 슬롯별 `per_slot`을 쓴다 — 그래서 origin만
                # 넣으면 색인이 비고, 실제로 룬 16줄이 전부 UNKNOWN이었다(2026-08-05).
                for text in _mod_texts(r.raw["data"]):
                    self._mods.setdefault(_norm(text), []).append(r.raw)
            elif r.type == "Modifier" and "heart-of-the-well" in r.raw.get("data", {}).get(
                "origins", []
            ):
                for text in r.raw["data"].get("texts", []):
                    self._heart.setdefault(_norm(text), []).append(r.raw)
            elif r.type == "Passive" and r.raw.get("data", {}).get("kind") == "notable":
                self._notables[r.name_en.lower()] = r.raw
            elif r.type == "Skill":
                self._skills.add(r.name_en.lower())

    def check(self, item_text: str) -> LegalityReport:
        rarity, base_name, ilvl, mod_lines, sockets, rune_effect = _parse_item(item_text)
        if rarity == "unique":
            return self._check_unique(item_text)
        base = self._bases.get(base_name.lower())
        errors: list[str] = []
        if base is None:
            errors.append(f"베이스 미확인: {base_name!r}")
        verdicts: list[LineVerdict] = []
        matched: dict[str, dict[str, Any]] = {}  # modifier id → record (하이브리드 중복 제거)
        # 접미어 효과 접두가 있으면(그 줄 자체는 접두로 정상 검사) 접미 상한을 확장한다
        suffix_effect = next(
            (float(m.group(1)) for ln in mod_lines if (m := _SUFFIX_EFFECT.match(ln))), 0.0
        )
        catalyst, catalyst_quality = parse_catalyst(item_text)
        # **베이스 임플리싯은 접사가 아니다** (백로그 #57, 2026-08-10). 고르는 것이
        # 아니라 베이스가 달고 나오는 줄이라 접사 풀에서 찾으면 안 나온다 — 실측:
        # `Invoking Belt`의 `Has 1 Charm Slot`이 UNKNOWN으로 찍혔다(KB 접사 표기는
        # `+1 charm slot`). 그런데 그 줄은 `optimize_rare`가 **자기가 자동 기재**한
        # 것이라, 조립 중 적법성 검사가 **모든 시도에서** 실패해 접사를 하나도 못
        # 고르고 `legal: False`만 남았다. 정본은 베이스 레코드의 `implicit`이다.
        implicits = _base_implicits(base)
        for line in mod_lines:
            if (found := _match_implicit(line, implicits)) is not None:
                verdicts.append(found)
                continue
            verdict = self._check_line(
                line,
                base,
                ilvl,
                suffix_effect=suffix_effect,
                sockets=sockets,
                rune_effect=rune_effect,
                catalyst=catalyst,
                catalyst_quality=catalyst_quality,
            )
            verdicts.append(verdict)
            if verdict.modifier_id:
                matched[verdict.modifier_id] = next(
                    m
                    for cands in self._mods.values()
                    for m in cands
                    if m["id"] == verdict.modifier_id
                )
        # 접사 수·group 배타 (매칭된 모드 기준 — UNKNOWN 줄은 여기 안 들어간다)
        category = (base or {}).get("data", {}).get("category")
        caps, total_cap, cap_label = self._affix_limits(rarity, category)
        counts = {"prefix": 0, "suffix": 0}
        groups: dict[str, str] = {}
        for rec in matched.values():
            d = rec["data"]
            affix = d.get("affix_type")
            if affix in counts:
                counts[affix] += 1
            g = d.get("group")
            if g:
                if g in groups:
                    errors.append(f"group 중복: {g} ({groups[g]} vs {rec['id']})")
                groups[g] = rec["id"]
        cap_errors = False
        for affix, n in counts.items():
            if n > caps[affix]:
                errors.append(f"{affix} {n}개 — {cap_label} 한도 {caps[affix]} 초과")
                cap_errors = True
        if sum(counts.values()) > total_cap:
            errors.append(f"접사 총 {sum(counts.values())}개 — {cap_label} 총한도 {total_cap} 초과")
            cap_errors = True
        if cap_errors:
            errors.extend(self._rune_hint(mod_lines))
        # 반경 부여 줄이 있는데 `Radius:` 선언이 없으면 **조용히 0**이 된다(제안 B).
        # 실측 2026-08-09: 선언 없이는 반경 내 노터블 6개에도 Δ0, `Radius: Very Large`면
        # CritChance 10.44 → 15.84. 오류가 아니라 과소 계상이라 아무도 모른다.
        if needs_radius_declaration(item_text):
            errors.append(
                "반경 부여 줄이 있는데 `Radius:` 선언이 없다 — PoB가 반경을 정하지 못해 "
                f"**아무 노드도 안 걸리고 델타가 0이 된다**. {list(RADIUS_LABELS)} 중 그 "
                "주얼의 실제 반경을 적을 것(engine.jewels.render_radius_jewel)"
            )
        # 룬도 같은 계열이다 — 선언이 없으면 모드는 들어가고 **증폭만** 빠진다(3.00배).
        errors.extend(needs_rune_declaration(item_text))
        return LegalityReport(verdicts=tuple(verdicts), errors=tuple(errors))

    def _rune_hint(self, mod_lines: list[str]) -> list[str]:
        """접사 칸이 넘쳤을 때, **룬으로도 붙는 줄**이 섞여 있으면 그렇게 말해 준다.

        룬 접두(`{rune}`)를 붙이면 접사 칸 밖으로 빠지는데, 규약을 모르면 오류가
        "접미 4개 — 초과"로만 보여 원인이 룬이라는 단서가 없다. 실측 2026-08-06
        (빌드 회차): 세션이 이 오류를 만나고 **룬 소켓 13칸 중 6칸을 비운 채
        출고**했다 — 냉기 저항 병목이 그대로 남았다. 규약을 아는 사람만 통과하는
        검사는 조용한 손실을 만든다.

        평문 줄은 접사 풀에 **먼저** 매칭되므로 매칭 결과만 봐서는 룬 가능성을 알 수
        없다 — 줄 텍스트로 룬 색인을 다시 조회해야 한다.
        """
        runic = [ln for ln in mod_lines if not _RUNE_PREFIX.match(ln) and self._rune_line(ln)]
        if not runic:
            return []
        sample = "; ".join(ln.strip()[:40] for ln in runic[:2])
        return [
            f"↳ 위 줄 중 {len(runic)}건은 **룬으로도 붙는다**({sample}"
            f"{'…' if len(runic) > 2 else ''}) — 룬으로 쓸 것이면 줄 앞에 `{{rune}}`를 "
            f"붙여라. 접사 칸에서 빠져 이 초과가 해소된다 "
            f"(소켓 여유는 check_constraints(exhaustion.sockets)로 확인)"
        ]

    def _affix_limits(self, rarity: str, category: str | None) -> tuple[dict[str, int], int, str]:
        """판 규칙의 접사 한도 → ({prefix, suffix} 한도, 총한도, 라벨).

        베이스 category 섹션(예: jewel rare 2/2)이 있으면 그것을, 없으면
        equipment를 쓴다. season_override(0.5 주얼: 총 5모드 — 3접미/2접두 또는
        2접미/3접두)는 "한쪽 +1·총합 +1"로 해석한다 — 3/3(총 6)은 불허.
        """
        section = self._affix_caps.get(category or "", {})
        raw = section.get(rarity) if isinstance(section, dict) else None
        label = f"{category} {rarity}"
        if not isinstance(raw, dict):
            section = {}
            raw = self._affix_caps.get("equipment", {}).get(rarity)
            label = f"equipment {rarity}"
        if not isinstance(raw, dict):
            raw = self._FALLBACK_CAPS.get(rarity, self._FALLBACK_CAPS["rare"])
        caps = {"prefix": int(raw["prefixes"]), "suffix": int(raw["suffixes"])}
        total = caps["prefix"] + caps["suffix"]
        if section.get("season_override"):
            caps = {k: v + 1 for k, v in caps.items()}
            total += 1
            label += " (season_override)"
        return caps, total, label

    def _check_unique(self, item_text: str) -> LegalityReport:
        """유니크 = 고정 모드 아이템. 이름이 KB 유니크에 실존하고 각 모드 줄의
        수치가 KB explicits의 롤 범위 안이면 LEGAL (모드풀 검사 부적용).

        롤이 고정 텍스트가 아닌 고유 주얼 3종(Prism of Belief·Megalomaniac·
        Heart of the Well)은 전용 모듈로 위임한다 — KB 레코드의 플레이스홀더
        ("Specific Skill"·"Allocates Passive Skill"·"[Custom Desecrated …]")는
        실물 아이템 줄과 직접 대조가 불가능하기 때문(사용자 확립 2026-07-31)."""
        lines = [ln.strip() for ln in item_text.strip().splitlines() if ln.strip()]
        name = lines[1] if len(lines) > 1 else ""
        rec = self._uniques.get(name.lower())
        if rec is None:
            return LegalityReport(verdicts=(), errors=(f"KB에 없는 유니크: {name!r}",))
        # ⚠ 여기 **자기만의 5개짜리 목록**이 있었다 — 같은 규칙이 두 벌이면 어긋난다
        # (§0 ④ 판정 주체가 둘이면 어긋난다). 실측 2026-08-10: `_SPEC_LINE_PREFIXES`에
        # `variant:`를 넣어 뒀는데도 유니크 경로가 그걸 안 타서 `Variant:` 두 줄이
        # UNKNOWN으로 찍혔다. `item.the-unborn-lich`는 **변형 12종**이고 변형을 적어야
        # 어느 스킬을 부여받는지 정해지는데, 적으면 비적법이 됐다(§0 ⑤).
        mod_lines = [
            ln
            for ln in lines[3:]
            if not ln.lower().startswith(_SPEC_LINE_PREFIXES) and ln.lower() not in _SPEC_MARKERS
        ]
        special = {
            "prism of belief": self._check_prism,
            "megalomaniac": self._check_megalomaniac,
            "heart of the well": self._check_heart,
        }.get(name.lower())
        if special is not None:
            return special(rec, mod_lines)
        # "(A/B/C)" 선택지 열거(고유 주얼 롤 변형)는 펼쳐서 대조한다
        ranged = [
            e
            for t in rec["data"].get("explicits", []) + rec["data"].get("implicits", [])
            for e in _expand_enum(t)
        ]
        known = [_norm(t) for t in ranged]
        verdicts: list[LineVerdict] = []
        for ln in mod_lines:
            if _norm(ln) not in known:
                # **유니크에도 룬 소켓이 있다.** 고정 모드에 없다고 UNKNOWN으로 끝내면
                # 유니크 무기·방어구의 룬 계획이 조립 게이트를 통과하지 못한다 —
                # 실측 2026-08-05: `Gain 5% of Damage as Extra Damage of all Elements`가
                # 그렇게 막혔다. 일반 아이템 경로에는 이미 있는 폴백을 여기에도 둔다.
                rune = self._rune_line(ln)
                verdicts.append(
                    rune
                    if rune is not None
                    else LineVerdict(ln, "UNKNOWN", reason="유니크 고정 모드에도 룬 풀에도 없음")
                )
                continue
            ok, why = _values_in_range(ln, ranged)
            verdicts.append(
                LineVerdict(ln, "LEGAL", rec["id"])
                if ok
                else LineVerdict(ln, "ILLEGAL", rec["id"], f"롤 범위 밖: {why}")
            )
        return LegalityReport(verdicts=tuple(verdicts))

    def _rune_line(self, line: str) -> LineVerdict | None:
        """이 문구가 **룬으로** 붙일 수 있는 것인가 (유니크·일반 공통 판정).

        룬은 접사와 별개 축이라 아이템 희귀도와 무관하게 소켓에 들어간다.

        ⚠ `{rune}` 접두를 **여기서 벗긴다** (백로그 #56). 일반 아이템 경로는
        `_check_line`이 미리 벗기지만 유니크 경로는 원문 그대로 넘겨서, 규약대로
        `{rune}+12 to Intelligence`라고 적으면 정규화 키가 어긋나
        `UNKNOWN: 유니크 고정 모드에도 룬 풀에도 없음`이 났다 — 표기법을 지킨
        쪽이 거부당한 것이다. 그래서 한 회차가 **룬 4칸을 비워 뒀다**(#33이 그 축을
        DPS +69.6%로 재 뒀는데도). 금지하려면 대안 경로가 통해야 한다(철칙 5 따름정리).
        """
        line = _RUNE_PREFIX.sub("", line, count=1).strip()
        for cand in self._mods.get(_norm(line), []):
            if "rune" in (cand.get("data") or {}).get("origins", []):
                return LineVerdict(
                    line,
                    "CONDITIONAL",
                    str(cand["id"]),
                    "고정 모드는 아니지만 **룬으로는 가능** — 유니크에도 룬 소켓이 있다. "
                    "소켓 한도는 check_constraints(exhaustion.sockets)로 검사하라"
                    + _rune_value_note(line, cand),
                )
        return None

    def _check_prism(self, rec: dict[str, Any], mod_lines: list[str]) -> LegalityReport:
        """Prism of Belief: "+N to Level of all <스킬> Skills" 1줄 (+Corrupted).

        N은 1~3, <스킬>은 실존 스킬 젬(KB Skill 레코드) ∩ PoB prism 변형 풀
        (Generated.lua 제외 규칙 재현 — support·hidden·fromItem(무기 부여)·
        fromTree·excludedGems 제외, pob/gempool.py)."""
        from pok.pob.gempool import prism_gem_names
        from pok.pob.versions import resolve_snapshot

        pool = prism_gem_names(str(resolve_snapshot(self._root).src_dir))
        verdicts: list[LineVerdict] = []
        errors: list[str] = []
        rolls = 0
        for ln in mod_lines:
            if ln.lower() == "corrupted":
                verdicts.append(LineVerdict(ln, "LEGAL", rec["id"]))
                continue
            m = re.fullmatch(r"\+(\d+) to Level of all (.+) Skills", ln)
            if m is None:
                verdicts.append(LineVerdict(ln, "UNKNOWN", reason="Prism of Belief 모드 형식 아님"))
                continue
            rolls += 1
            level, skill = int(m.group(1)), m.group(2)
            if not 1 <= level <= 3:
                verdicts.append(
                    LineVerdict(ln, "ILLEGAL", rec["id"], f"롤 범위 밖: +{level} (허용 +1~+3)")
                )
            elif skill not in pool:
                verdicts.append(
                    LineVerdict(
                        ln,
                        "ILLEGAL",
                        rec["id"],
                        f"{skill!r}: PoB prism 풀 밖 (서포트·숨김·무기/트리 부여 제외 규칙)",
                    )
                )
            elif skill.lower() not in self._skills:
                verdicts.append(
                    LineVerdict(
                        ln,
                        "UNKNOWN",
                        rec["id"],
                        f"{skill!r}: KB Skill 레코드 없음 (PoB 풀엔 존재 — KB 커버리지 확인 필요)",
                    )
                )
            else:
                verdicts.append(
                    LineVerdict(ln, "LEGAL", rec["id"], "실존 스킬 젬 (KB Skill ∩ PoB prism 풀)")
                )
        if rolls != 1:
            errors.append(f"스킬 레벨 줄 {rolls}개 — 정확히 1줄이 롤된다")
        return LegalityReport(verdicts=tuple(verdicts), errors=tuple(errors))

    def _check_megalomaniac(self, rec: dict[str, Any], mod_lines: list[str]) -> LegalityReport:
        """Megalomaniac: "Allocates <노터블>" 2~3줄 (+Corrupted).

        노터블은 본 트리 실존 노터블이어야 하고, PoB Generated.lua 필터
        (isNotable ∧ recipe)를 따라 recipe(리퀴드 이모션) 보유분만 풀에 든다.
        롤은 랜덤 — LEGAL 대신 CONDITIONAL로 조달 가정(트레이드 전제)을 기록에
        남긴다 (validation.json lines에 그대로 실린다)."""
        verdicts: list[LineVerdict] = []
        errors: list[str] = []
        allocs = 0
        for ln in mod_lines:
            if ln.lower() == "corrupted":
                verdicts.append(LineVerdict(ln, "LEGAL", rec["id"]))
                continue
            m = re.fullmatch(r"Allocates (.+)", ln)
            if m is None:
                verdicts.append(LineVerdict(ln, "UNKNOWN", reason="Megalomaniac 모드 형식 아님"))
                continue
            allocs += 1
            notable = self._notables.get(m.group(1).lower())
            if notable is None:
                verdicts.append(
                    LineVerdict(ln, "UNKNOWN", rec["id"], f"{m.group(1)!r}: 실존 노터블 아님")
                )
            elif notable["data"].get("ascendancy"):
                verdicts.append(
                    LineVerdict(
                        ln, "ILLEGAL", notable["id"], "어센던시 노터블 — Megalomaniac 풀 밖"
                    )
                )
            elif notable["data"].get("acquisition") != "anointable":
                verdicts.append(
                    LineVerdict(
                        ln,
                        "ILLEGAL",
                        notable["id"],
                        "recipe(리퀴드 이모션) 없는 노터블 — PoB 풀 필터(isNotable ∧ recipe) 밖",
                    )
                )
            else:
                verdicts.append(
                    LineVerdict(
                        ln,
                        "CONDITIONAL",
                        notable["id"],
                        "랜덤 롤 조달 가정(트레이드 전제) — 실존 노터블(recipe 보유)",
                    )
                )
        if allocs not in (2, 3):
            errors.append(f"Allocates 줄 {allocs}개 — 2~3개여야 함")
        return LegalityReport(verdicts=tuple(verdicts), errors=tuple(errors))

    def _check_heart(self, rec: dict[str, Any], mod_lines: list[str]) -> LegalityReport:
        """Heart of the Well: 훼손 선택 풀에서 접두 2·접미 2를 **선택**한다.

        풀 = KB origins "heart-of-the-well" (ModVeiled.lua UniqueHeart* 수록분,
        kb/ingest/heart_mods.py). 수치는 티어 범위 대조, 접두/접미 각 2개 한도,
        같은 group 중복 금지, weight 0(스폰 불가) 거부."""
        verdicts: list[LineVerdict] = []
        errors: list[str] = []
        counts = {"prefix": 0, "suffix": 0}
        groups: dict[str, str] = {}
        for ln in mod_lines:
            candidates = self._heart.get(_norm(ln), [])
            if not candidates:
                verdicts.append(
                    LineVerdict(ln, "UNKNOWN", reason="Heart of the Well 훼손 풀에 없음")
                )
                continue
            reasons: list[str] = []
            verdict: LineVerdict | None = None
            for cand in candidates:
                d = cand["data"]
                ok, why = _values_in_range(ln, d.get("texts", []))
                if not ok:
                    reasons.append(f"{cand['id']}: {why}")
                    continue
                weights = d.get("spawn_weights", {})
                if not any(v > 0 for v in weights.values()):
                    reasons.append(f"{cand['id']}: 스폰 불가 (weight 0)")
                    continue
                affix = str(d.get("affix_type"))
                if affix in counts:
                    counts[affix] += 1
                g = d.get("group")
                if g:
                    if g in groups:
                        errors.append(f"group 중복: {g} ({groups[g]} vs {cand['id']})")
                    groups[g] = cand["id"]
                verdict = LineVerdict(ln, "LEGAL", cand["id"], "훼손 선택 풀 (아이템 자체 제공)")
                break
            verdicts.append(
                verdict
                if verdict is not None
                else LineVerdict(ln, "ILLEGAL", reason=" / ".join(reasons))
            )
        for affix, n in counts.items():
            if n > 2:
                errors.append(f"{affix} {n}개 — Heart of the Well 한도 2 초과")
        return LegalityReport(verdicts=tuple(verdicts), errors=tuple(errors))

    def _near_texts(self, line: str, limit: int = 3) -> list[str]:
        """정규화 키가 안 맞을 때 표기 확인용 근접 후보 (토큰 유사도 상위 N).

        UNKNOWN의 흔한 원인은 KB 부재가 아니라 **표기 차이**다(실증 2026-08-02:
        "+N to maximum Spirit" vs 정본 "+N to Spirit"). 후보를 보여주면 호출자가
        오타·표기를 스스로 교정할 수 있다.
        """
        want = {t for t in re.findall(r"[a-z]+", _norm(line)) if len(t) > 2}
        if not want:
            return []
        scored: list[tuple[float, str]] = []
        for key in self._mods:
            got = {t for t in re.findall(r"[a-z]+", key) if len(t) > 2}
            if not got:
                continue
            overlap = len(want & got)
            if overlap:
                scored.append((overlap / len(want | got), key))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [key for score, key in scored[:limit] if score >= 0.34]

    def _rune_value_verdict(
        self,
        line: str,
        runes: list[dict[str, Any]],
        sockets: int,
        rune_effect: float,
    ) -> LineVerdict:
        """룬 줄의 **수치**가 실제 룬 값으로 설명되는가 (백로그 #31).

        문구가 룬 풀에 있는지만 보고 통과시켜 왔다 — 값 범위를 안 봤다. 실측 2026-08-09:
        `150% increased Spell Damage`(실제 룬 30%)가 **5배**인 채 통과했다. 일반 접사에는
        티어 범위 검사가 있는데 **룬에만 없었다**.

        상한 = 룬 1개 값 * 소켓 수 * (1 + `increased effect of Socketed Runes`/100).
        같은 룬을 여러 칸에 박는 것이 정상 운용이라 소켓 수를 곱한다. 소켓 수를 모르면
        (선언이 없으면) **판정하지 않는다** — 모르는 것을 위반이라 말하지 않는다.
        """
        written = [float(x) for x in _NUM.findall(line)]
        pool = [
            float(v)
            for rune in runes
            for lines in ((rune.get("data") or {}).get("per_slot") or {}).values()
            for text in lines
            if _norm(text) == _norm(line)
            for v in _NUM.findall(text)
        ]
        base_verdict = LineVerdict(
            line,
            "LEGAL",
            modifier_id=str(runes[0]["id"]),
            reason="룬 부여 — 소켓 한도는 check_constraints(sockets)로 검사",
        )
        if not written or not pool or sockets <= 0:
            return base_verdict
        ceiling = max(pool) * sockets * (1.0 + rune_effect / 100.0)
        if max(written) <= ceiling + 1e-6:
            return base_verdict
        return LineVerdict(
            line,
            "ILLEGAL",
            modifier_id=str(runes[0]["id"]),
            reason=(
                f"룬 값이 설명되지 않는다 — 적힌 {max(written):g} > 상한 {ceiling:g} "
                f"(룬 1개 {max(pool):g} * 소켓 {sockets} * 룬 효과 +{rune_effect:g}%). "
                f"소켓 수나 `increased effect of Socketed Runes`를 아이템에 적었는지 확인할 것"
            ),
        )

    def _check_line(
        self,
        line: str,
        base: dict[str, Any] | None,
        ilvl: int,
        *,
        suffix_effect: float = 0.0,
        sockets: int = 0,
        rune_effect: float = 0.0,
        catalyst: str = "",
        catalyst_quality: float = 0.0,
    ) -> LineVerdict:
        # `{custom}`은 사용자가 **규격 밖인 걸 알고** 넣은 줄이다(PoB `Craft()`도 이것만
        # 보존한다, L1698). "KB에 없다"와 섞으면 진짜 미수록 신호가 묽어진다.
        if "{custom}" in line.lower():
            body = _MOD_DECORATION.sub("", _CUSTOM_PREFIX.sub("", line, count=1), count=1).strip()
            return LineVerdict(
                line,
                "CONDITIONAL",
                reason=(
                    "사용자가 **의도적으로 넣은** 커스텀 줄 — 규격 밖임을 알고 넣은 것이라 "
                    "미수록(UNKNOWN)과 구분한다. 수치는 검증되지 않는다"
                    + _custom_hint(self._mods, body)
                ),
            )
        # PoB는 룬 부여 줄을 `{rune}` 접두로 표기한다. 룬은 일반 접사와 **다른 풀**이라
        # 접두를 무시하면 동명 접사에 먼저 매칭돼 "티어 범위 밖"으로 오판한다
        # (실측 2026-08-05: 룬 16줄이 전부 UNKNOWN·오판이었다).
        # 장식 접두를 먼저 벗긴다 — `{rune}`·`{custom}`은 **의미**가 있어 위에서 이미
        # 갈랐고, 나머지는 표기라 매칭 전에 떼어야 한다.
        line = _MOD_DECORATION.sub("", line, count=1).strip()
        rune_line = bool(_RUNE_PREFIX.match(line))
        if rune_line:
            line = _RUNE_PREFIX.sub("", line, count=1).strip()
        candidates = self._mods.get(_norm(line), [])
        if rune_line:
            # 룬 줄은 룬 풀에서만 찾는다 — 티어 범위는 룬에 적용되지 않는다(고정값)
            runes = [c for c in candidates if "rune" in (c.get("data") or {}).get("origins", [])]
            if runes:
                return self._rune_value_verdict(line, runes, sockets, rune_effect)
            return LineVerdict(
                line, "UNKNOWN", reason="`{rune}` 표기지만 룬 풀에 일치 없음 — 표기 확인 필요"
            )
        if not candidates:
            near = self._near_texts(line)
            hint = (
                f" — 표기 확인 후보: {'; '.join(near)}"
                if near
                else " (근접 후보 없음 — 실제 미수록일 수 있다)"
            )
            # UNKNOWN은 "KB 부재"가 아니라 "매칭 실패"다 — 표기 차이가 흔한 원인이므로
            # 근접 후보를 함께 돌려줘 오진(KB 갭으로 단정)을 구조적으로 막는다 (2026-08-02).
            return LineVerdict(line, "UNKNOWN", reason=f"KB에 일치하는 모드 텍스트 없음{hint}")
        reasons: list[str] = []
        conditional: LineVerdict | None = None  # LEGAL 후보가 뒤에 있을 수 있다 — 즉시 반환 금지
        for rec in candidates:
            d = rec["data"]
            ok, why = _values_in_range(line, d.get("texts", []))
            note = ""
            if (
                not ok
                and suffix_effect > 0
                and d.get("affix_type") == "suffix"
                and "jewel" in d.get("origins", [])
            ):
                # 접미어 효과 선반영: 표시 수치 = 롤 x (1+효과/100) — 상한 확장 재검사.
                # 효과 접두는 주얼 풀의 Local 모드(LocalSuffixEffect)이므로 같은 아이템
                # (주얼) 풀의 접미에만 적용한다 — 동일 텍스트의 장비 티어는 확장 금지.
                ok, why = _values_in_range(
                    line, d.get("texts", []), hi_scale=1.0 + suffix_effect / 100.0
                )
                if ok:
                    note = f"접미어 효과 {suffix_effect:g}% 반영 상한"
            if not ok and catalyst:
                # 촉매는 접사 수치를 **실제로** 올린다 — `Craft()`가 `getCatalystScalar`를
                # `applyRange`에 태운다(L1723). 검사기가 이걸 모르면 **정상 아이템을
                # 티어 범위 밖으로 찍는다** — 실측 2026-08-09: 사용자 정본 목걸이의
                # `50% increased Evasion Rating`(Sibilant 40)이 그렇게 ILLEGAL이 됐다.
                scalar = catalyst_scalar(catalyst, catalyst_quality, d.get("mod_tags") or [])
                if scalar > 1.0:
                    ok, why = _values_in_range(line, d.get("texts", []), hi_scale=scalar)
                    if ok:
                        note = f"촉매 {catalyst} {catalyst_quality:g}% 반영 상한"
            if not ok:
                reasons.append(f"{rec['id']}: {why}")
                continue
            if int(d.get("ilvl", 1)) > ilvl:
                reasons.append(f"{rec['id']}: 요구 ilvl {d['ilvl']} > 아이템 {ilvl}")
                continue
            if base is not None:
                weights = d.get("spawn_weights", {})
                tags = base.get("data", {}).get("spawn_tags", [])
                if any(weights.get(t, 0) > 0 for t in tags):
                    return LineVerdict(line, "LEGAL", rec["id"], note)
                routes = [a for a in d.get("acquisition", []) if a not in _CRAFT_EQUIVALENT]
                if routes:
                    fit, why_unfit = _route_base_fit(d, base)
                    if not fit:
                        reasons.append(
                            f"{rec['id']}: 경로({', '.join(routes)}) 있으나 베이스 부적합"
                            f" — {why_unfit}"
                        )
                        continue
                    reason = f"경로 한정: {', '.join(routes)}"
                    conditional = conditional or LineVerdict(
                        line, "CONDITIONAL", rec["id"], f"{reason} / {note}" if note else reason
                    )
                    continue
                reasons.append(f"{rec['id']}: 이 베이스에 스폰 불가 (weight 0·경로 없음)")
                continue
            return LineVerdict(line, "LEGAL", rec["id"], note)
        if conditional is not None:
            return conditional
        # 접사로는 못 붙지만 **룬 풀에 같은 문구가 있으면** 룬으로는 가능하다.
        # PoB 표기는 `{rune}` 접두인데 손으로 아이템을 쓸 때는 그걸 모르므로, 접두
        # 없는 룬 문구가 일반 접사에 매칭돼 "티어 범위 밖"으로 거부되고 접사 한도까지
        # 잡아먹었다 — 실측 2026-08-05: 그 때문에 룬 17칸을 조립본에서 빼야 했고
        # 전달 PoB가 실제치를 과소평가했다(DPS -6.6%·EHP -6.9%).
        runes = [c for c in candidates if "rune" in (c.get("data") or {}).get("origins", [])]
        if runes:
            return LineVerdict(
                line,
                "CONDITIONAL",
                str(runes[0]["id"]),
                "접사로는 불가하나 **룬으로는 가능** — PoB 표기는 `{rune}` 접두다. "
                "소켓 한도는 check_constraints(exhaustion.sockets)로 검사하라"
                + _rune_value_note(line, runes[0]),
            )
        return LineVerdict(line, "ILLEGAL", reason=" / ".join(reasons))


def _route_base_fit(d: dict[str, Any], base: dict[str, Any]) -> tuple[bool, str]:
    """비크래프팅 경로(essence·liquid·desecration 등)가 이 베이스에 적용 가능한가 (#34).

    "경로 존재"만으로 CONDITIONAL을 주지 않는다 — 반증 가능한 신호를 순서대로 대조:
    ① spawn_weights의 명시 클래스 키(값 무관 — C-2 "weight 0 ≠ 죽은 모드":
       0은 화폐 크래프팅 불가·클래스 호환의 표기다. 예: liquid 주얼 모드 {"jewel": 0})
    ② applicable_pages (poe2db 페이지명 — 베이스 category·영문명과 대조)
    ③ scope (equipment | jewel | waystone)
    신호가 전혀 없으면 반증 불가 → 적용 가능으로 두고 CONDITIONAL을 유지한다.
    """
    base_data = base.get("data", {})
    tags = {t for t in base_data.get("spawn_tags", {}) if t != "default"}
    explicit = {k for k in d.get("spawn_weights", {}) if k != "default"}
    if explicit:
        if tags & explicit:
            return True, ""
        return False, f"클래스 타깃({', '.join(sorted(explicit))}) 밖 베이스"
    category = str(base_data.get("category", ""))
    name = str(base.get("name", {}).get("en", "")).lower()
    pages = d.get("applicable_pages")
    if pages:
        # item_class가 있으면 페이지 슬러그 조인(정본 kb.item_classes)이 결정적이다
        # — 문자열 휴리스틱은 Staves·Foci 같은 불규칙 복수에서 틀렸다(실측 2026-08-06).
        item_class = str(base_data.get("item_class") or "")
        if item_class:
            from pok.kb.item_classes import page_matches_class

            if any(page_matches_class(str(p), item_class) for p in pages):
                return True, ""
            pages_s = ", ".join(map(str, pages))
            return False, f"applicable_pages({pages_s}) 밖 베이스({item_class})"
        for page in pages:
            p = str(page).lower().replace("_", " ").rstrip("s")
            if p and (p in name or name in p or (category and (category in p or p in category))):
                return True, ""
        pages_s = ", ".join(map(str, pages))
        return False, f"applicable_pages({pages_s}) 밖 베이스({category or name})"
    scope = str(d.get("scope", ""))
    if scope:
        kind = category if category in ("jewel", "waystone") else "equipment"
        if scope != kind:
            return False, f"scope {scope} ≠ 베이스 종류 {kind}"
    return True, ""


def parse_catalyst(text: str) -> tuple[str, float]:
    """`Catalyst:` + `CatalystQuality:` → (촉매 이름 소문자, 퀄리티). 없으면 ("", 0.0).

    촉매는 **접사 수치를 실제로 올린다** — `Item.lua::Craft`가 `getCatalystScalar`를
    태워 `applyRange`에 넘긴다(L1723). 실측 2026-08-09(사용자 정본 목걸이, Sibilant):
    퀄리티 0 → 주문 피해 30% · 20 → **36%** · 40 → **42%**. 검사기가 이걸 모르면
    정상 아이템을 "티어 범위 밖"으로 찍는다.
    """
    name, quality = "", 0.0
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("catalyst:"):
            name = line.split(":", 1)[1].strip().lower()
        elif low.startswith("catalystquality:"):
            with contextlib.suppress(ValueError):
                quality = float(line.split(":", 1)[1].strip())
    return name, quality


def catalyst_scalar(catalyst: str, quality: float, mod_tags: Sequence[str]) -> float:
    """모드 태그가 촉매 태그와 겹치면 `(100 + quality)/100`, 아니면 1.0 (`Item.lua:32~57`)."""
    tags = _CATALYST_TAGS.get(catalyst)
    if not tags or not mod_tags:
        return 1.0
    if tags & {str(tag).lower() for tag in mod_tags}:
        return (100.0 + quality) / 100.0
    return 1.0


def _parse_item(text: str) -> tuple[str, str, int, list[str], int, float]:
    """buildxml.ItemSpec.text 형식 파서 (우리가 생성하는 형식 — 엄격).

    반환에 **소켓 수·룬 효과**가 포함된다 — 룬 값 검증(#31)의 분모다.
    """
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines or not lines[0].lower().startswith("rarity:"):
        raise ValueError("첫 줄이 'Rarity:' 가 아님")
    rarity = lines[0].split(":", 1)[1].strip().lower()
    if rarity in ("normal",):
        base_name, rest = lines[1], lines[2:]
    else:
        if len(lines) < 3:
            raise ValueError("이름·베이스 줄 부족")
        base_name, rest = lines[2], lines[3:]
    # ⚠ PoB 정본(`BuildRaw`)에는 `Item Level:` 줄이 **없다** — `LevelReq:`만 쓴다.
    # 1로 두면 고티어 접사가 전부 "요구 ilvl 초과"로 찍힌다: 실측 2026-08-09, 명세로
    # 생성한 목걸이에서 `IncreasedEvasionRatingPercent7`((45-50)%, 실제 50%)이 그렇게
    # ILLEGAL이 됐다. `LevelReq:`가 있으면 거기서 유도한다 — PoB 자신의 관계식이
    # `LevelReq = max(base.req.level, floor(mod.level * 0.8))`(`Craft` L1722)이므로
    # **모드 레벨 상한 ≈ LevelReq / 0.8**이다. 둘 다 없으면 예전대로 1(보수적).
    ilvl = 1
    level_req = 0
    sockets = 0
    rune_effect = 0.0
    mod_lines: list[str] = []
    for ln in rest:
        low = ln.lower()
        if low.startswith("sockets:"):
            # `Sockets: S S S S S` — 칸 하나가 토큰 하나다
            sockets = len(ln.split(":", 1)[1].split())
        elif match := _RUNE_EFFECT.search(ln):
            rune_effect = max(rune_effect, float(match.group(1)))
        if low.startswith("item level:"):
            ilvl = int(ln.split(":", 1)[1].strip())
        elif low.startswith("levelreq:"):
            with contextlib.suppress(ValueError):
                level_req = int(float(ln.split(":", 1)[1].strip()))
        elif low.startswith(_SPEC_LINE_PREFIXES) or low in _SPEC_MARKERS:
            # PoB의 **스펙 줄·표식**이지 모드가 아니다. `Sockets:`·`Rune:`·`Radius:`는
            # `Item.lua:570-580`이 읽는 선언이고 `Corrupted`는 표식이다. 모드로 판정하면
            # **정상 빌드가 비적법으로 찍히고**, 그러면 경고가 신호를 잃는다 —
            # 실측 2026-08-09: 진짜 실격 4건과 이 오탐 6건이 한 목록에 섞여 나왔다(#30).
            #
            # `implicits:` 헤더도 같다 — render_unique가 내는 형식(PoB 허용)이 UNKNOWN으로
            # 판정돼 is_legal을 오염시켰다(실측 2026-08-06). 개수만 버리고 뒤따르는
            # 암묵 모드 줄 자체는 여전히 모드로 검사한다.
            continue
        else:
            mod_lines.append(ln)
    if ilvl == 1 and level_req:
        # `LevelReq = floor(mod.level * 0.8)`의 역산 — **올림**이다. 실측 2026-08-09:
        # `IncreasedEvasionRatingPercent7`은 level 77이고 floor(77*0.8) = **61**이라
        # 사용자 정본의 `LevelReq: 61`과 맞는다. 내림을 쓰면 76이 나와 그 접사를
        # 1 차이로 거부한다(만들다 실제로 걸렸다).
        ilvl = math.ceil(level_req / 0.8)
    return rarity, base_name, ilvl, mod_lines, sockets, rune_effect


def _values_in_range(line: str, texts: list[str], *, hi_scale: float = 1.0) -> tuple[bool, str]:
    """줄의 수치들이 어느 한 티어 텍스트의 범위 안에 있는지.

    hi_scale > 1 은 접미어 효과 선반영(주얼): 표시 수치가 롤 x 배율이므로 범위
    상한만 배율만큼 확장해 대조한다 (하한은 유지 — 미적용 표기도 통과 허용).
    """
    line_nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", line)]
    for text in texts:
        if _norm(text) != _norm(line):
            continue
        spans = list(_NUM.finditer(text))
        if len(spans) != len(line_nums):
            continue
        fit = True
        for span, v in zip(spans, line_nums, strict=True):
            m = _RANGE.fullmatch(span.group())
            if m:
                lo, hi = float(m.group(1)), float(m.group(2)) * hi_scale
                if not lo <= v <= hi + 1e-9:
                    fit = False
                    break
            elif abs(float(span.group()) * hi_scale - v) > 1e-9 and float(span.group()) != v:
                fit = False
                break
        if fit:
            return True, ""
    scaled = " (접미어 효과 확장 포함)" if hi_scale > 1 else ""
    return False, f"수치 {line_nums} 가 티어 범위 밖{scaled}"


def _custom_hint(mods: dict[str, list[dict[str, Any]]], line: str) -> str:
    """이 커스텀 문구가 **KB에 실재하는 모드**인가 — 있으면 그걸 쓰라고 말한다.

    실측 2026-08-09: 사용자가 *"PoB에 없어서 커스텀으로 넣었다"*고 한
    `+7% to Fire Spell Critical Hit Chance`는 실은
    `modifier.genesistreefirespellbasecriticalchancecrafted`(「조프」, +(4-5)%)이고,
    7%는 **최대롤 5% x Sibilant 촉매 40%**다. 커스텀 대신 모드 id로 넣을 수 있었다.
    """
    for cand in mods.get(_norm(line), []):
        data = cand.get("data") or {}
        key = data.get("pob_key")
        if key:
            return (
                f" — 이 문구는 KB에 **실재한다**: `{cand['id']}` (`{key}`). "
                f"커스텀 대신 `Suffix: {{range:1}}{key}`로 넣으면 수치·촉매를 PoB가 만든다"
            )
    return ""
