"""합성 아이템 적법성 검증 — RC4 (절대 못 만드는 아이템 거부).

결정적 대조만 한다(AD-3): 아이템 텍스트의 모드 줄 하나하나를 KB Modifier와
매칭해 ① 존재 ② 수치가 티어 범위 안 ③ ilvl 충족 ④ 베이스에 스폰 가능
⑤ 접사 수(희귀 ≤3/≤3, 마법 ≤1/≤1) ⑥ 같은 group 중복 금지를 검사한다.

매칭 키 = 숫자·범위를 `#`로 치환한 정규화 텍스트 (KB texts와 동일 규칙).
스폰 판정: 베이스 spawn_tags 중 weight>0가 있으면 통과. weight가 전부 0이어도
acquisition에 essence·desecrated 등 비-크래프팅 경로가 있으면 CONDITIONAL
(경로 명시) — C-2 판정(2026-07-30)에서 확립한 "weight 0 ≠ 죽은 모드" 원칙.

접사 한도는 판 규칙(knowledge/crafting-rules/board-rules.json)에서 읽는다 —
장비 rare 3/3·magic 1/1, 주얼 rare 2/2 + 0.5 시즌 season_override(총 5모드,
3접미/2접두 또는 2접미/3접두). 하드코딩 금지(정본이 진실).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from pok.kb.store import load as store_load

_NUM = re.compile(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)|\d+(?:\.\d+)?")
_RANGE = re.compile(r"\((\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)\)")


def _norm(text: str) -> str:
    """수치·범위 → '#' 정규화 (매칭 키)."""
    return _NUM.sub("#", text).strip().lower()


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
        self._bases: dict[str, dict[str, Any]] = {}
        self._uniques: dict[str, dict[str, Any]] = {}  # 유니크 이름 → 레코드
        self._mods: dict[str, list[dict[str, Any]]] = {}  # 정규화 텍스트 → 후보 레코드들
        for r in kb.records.values():
            if r.type == "Item" and r.raw.get("data", {}).get("rarity") == "unique":
                self._uniques[r.name_en.lower()] = r.raw  # 유니크 우선 (category도 가질 수 있다)
            elif r.type == "Item" and r.raw.get("data", {}).get("category"):
                self._bases[r.name_en.lower()] = r.raw
            elif r.type == "Modifier" and {"item", "jewel"} & set(
                r.raw.get("data", {}).get("origins", [])
            ):  # jewel origin도 크래프팅 풀 — 주얼 베이스 검증에 필요 (2026-07-31)
                for text in r.raw["data"].get("texts", []):
                    self._mods.setdefault(_norm(text), []).append(r.raw)

    def check(self, item_text: str) -> LegalityReport:
        rarity, base_name, ilvl, mod_lines = _parse_item(item_text)
        if rarity == "unique":
            return self._check_unique(item_text)
        base = self._bases.get(base_name.lower())
        errors: list[str] = []
        if base is None:
            errors.append(f"베이스 미확인: {base_name!r}")
        verdicts: list[LineVerdict] = []
        matched: dict[str, dict[str, Any]] = {}  # modifier id → record (하이브리드 중복 제거)
        for line in mod_lines:
            verdict = self._check_line(line, base, ilvl)
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
        for affix, n in counts.items():
            if n > caps[affix]:
                errors.append(f"{affix} {n}개 — {cap_label} 한도 {caps[affix]} 초과")
        if sum(counts.values()) > total_cap:
            errors.append(f"접사 총 {sum(counts.values())}개 — {cap_label} 총한도 {total_cap} 초과")
        return LegalityReport(verdicts=tuple(verdicts), errors=tuple(errors))

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
        수치가 KB explicits의 롤 범위 안이면 LEGAL (모드풀 검사 부적용)."""
        lines = [ln.strip() for ln in item_text.strip().splitlines() if ln.strip()]
        name = lines[1] if len(lines) > 1 else ""
        rec = self._uniques.get(name.lower())
        if rec is None:
            return LegalityReport(verdicts=(), errors=(f"KB에 없는 유니크: {name!r}",))
        known = [
            _norm(t) for t in rec["data"].get("explicits", []) + rec["data"].get("implicits", [])
        ]
        ranged = rec["data"].get("explicits", []) + rec["data"].get("implicits", [])
        verdicts: list[LineVerdict] = []
        for ln in lines[3:]:
            low = ln.lower()
            if low.startswith(("item level:", "quality:", "sockets:", "implicits:", "--")):
                continue
            if _norm(ln) not in known:
                verdicts.append(LineVerdict(ln, "UNKNOWN", reason="유니크 고정 모드에 없음"))
                continue
            ok, why = _values_in_range(ln, ranged)
            verdicts.append(
                LineVerdict(ln, "LEGAL", rec["id"])
                if ok
                else LineVerdict(ln, "ILLEGAL", rec["id"], f"롤 범위 밖: {why}")
            )
        return LegalityReport(verdicts=tuple(verdicts))

    def _check_line(self, line: str, base: dict[str, Any] | None, ilvl: int) -> LineVerdict:
        candidates = self._mods.get(_norm(line), [])
        if not candidates:
            return LineVerdict(line, "UNKNOWN", reason="KB에 일치하는 모드 텍스트 없음")
        reasons: list[str] = []
        conditional: LineVerdict | None = None  # LEGAL 후보가 뒤에 있을 수 있다 — 즉시 반환 금지
        for rec in candidates:
            d = rec["data"]
            ok, why = _values_in_range(line, d.get("texts", []))
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
                    return LineVerdict(line, "LEGAL", rec["id"])
                routes = [a for a in d.get("acquisition", []) if a not in ("crafting-currency",)]
                if routes:
                    conditional = conditional or LineVerdict(
                        line, "CONDITIONAL", rec["id"], f"경로 한정: {', '.join(routes)}"
                    )
                    continue
                reasons.append(f"{rec['id']}: 이 베이스에 스폰 불가 (weight 0·경로 없음)")
                continue
            return LineVerdict(line, "LEGAL", rec["id"])
        if conditional is not None:
            return conditional
        return LineVerdict(line, "ILLEGAL", reason=" / ".join(reasons))


def _parse_item(text: str) -> tuple[str, str, int, list[str]]:
    """buildxml.ItemSpec.text 형식 파서 (우리가 생성하는 형식 — 엄격)."""
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
    ilvl = 1
    mod_lines: list[str] = []
    for ln in rest:
        low = ln.lower()
        if low.startswith("item level:"):
            ilvl = int(ln.split(":", 1)[1].strip())
        elif low.startswith(("quality:", "sockets:", "--")):
            continue
        else:
            mod_lines.append(ln)
    return rarity, base_name, ilvl, mod_lines


def _values_in_range(line: str, texts: list[str]) -> tuple[bool, str]:
    """줄의 수치들이 어느 한 티어 텍스트의 범위 안에 있는지."""
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
                lo, hi = float(m.group(1)), float(m.group(2))
                if not lo <= v <= hi:
                    fit = False
                    break
            elif float(span.group()) != v:
                fit = False
                break
        if fit:
            return True, ""
    return False, f"수치 {line_nums} 가 티어 범위 밖"
