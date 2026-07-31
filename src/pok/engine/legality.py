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

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

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
            elif r.type == "Modifier" and {"item", "jewel", "desecrated"} & set(
                r.raw.get("data", {}).get("origins", [])
            ):  # jewel origin도 크래프팅 풀 — 주얼 베이스 검증에 필요 (2026-07-31).
                # desecrated도 합성 검증 풀에 포함(사용자 지시 2026-07-31) —
                # spawn_weights가 없어 _route_base_fit의 pages/scope 신호로 판정된다.
                for text in r.raw["data"].get("texts", []):
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
        rarity, base_name, ilvl, mod_lines = _parse_item(item_text)
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
        for line in mod_lines:
            verdict = self._check_line(line, base, ilvl, suffix_effect=suffix_effect)
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
        meta = ("item level:", "quality:", "sockets:", "implicits:", "--")
        mod_lines = [ln for ln in lines[3:] if not ln.lower().startswith(meta)]
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
                verdicts.append(LineVerdict(ln, "UNKNOWN", reason="유니크 고정 모드에 없음"))
                continue
            ok, why = _values_in_range(ln, ranged)
            verdicts.append(
                LineVerdict(ln, "LEGAL", rec["id"])
                if ok
                else LineVerdict(ln, "ILLEGAL", rec["id"], f"롤 범위 밖: {why}")
            )
        return LegalityReport(verdicts=tuple(verdicts))

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
            elif notable["data"].get("acquisition") != "liquid-emotion":
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

    def _check_line(
        self, line: str, base: dict[str, Any] | None, ilvl: int, *, suffix_effect: float = 0.0
    ) -> LineVerdict:
        candidates = self._mods.get(_norm(line), [])
        if not candidates:
            return LineVerdict(line, "UNKNOWN", reason="KB에 일치하는 모드 텍스트 없음")
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
