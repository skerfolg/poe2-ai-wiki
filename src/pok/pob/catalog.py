"""PoB 카탈로그 — 유효한 `gem_id`·`config` 키 (이관 건 3, 2026-08-05).

**존재하지 않는 `gem_id`를 넣어도 오류가 나지 않았다.** PoB가 `nameSpec`(표시 이름)으로
대체 해석하기 때문인데, 이름까지 틀리거나 모호했다면 **젬이 소리 없이 사라지고**
세션은 낮은 숫자를 실측으로 받아 그걸 근거로 설계했을 것이다. 실제로 한 세션이
트리 62포인트를 잘못된 id로 최적화한 뒤에야 발견했다.

같은 계열의 결함이 한 세션에서 3건 나왔다 — 전부 "조용한 성능 저하, 명시적 실패 없음":

1. 없는 `gem_id` → 이름 폴백, 경고 없음
2. `multiplierIncisionStackCount` 기본 0 → 절개가 무가치해 보임(필수 젬을 뺄 뻔했다)
3. `conditionBleedAggravated` 기본 off → 상시 켜지는 축인데 출혈 수치가 절반

## 관련 config를 결정적으로 판정할 수 있다

`Modules/ConfigOptions.lua`의 각 항목은 **자기가 언제 관련되는지**를 들고 있다:

    { var = "multiplierIncisionStackCount", ifFlag = "Condition:CanInflictIncision", … }
    { var = "conditionBleedAggravated",     ifMod  = "BleedChance", … }

PoB가 UI에 표시할지 정할 때 쓰는 조건이다. 우리는 그 조건 문자열을 **빌드의 젬 효과
문구(KB `stats`, 2026-08-05 수록)와 대조**해 "관련 있는데 미설정"을 낸다. 추측이
아니라 PoB 자신의 관련성 정의를 쓰는 것이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pok.kb.pob_pin import pob_src_dir

_GEM_ID = re.compile(r'\["(Metadata/Items/Gems/[^"]+)"\]')
_NAME_SPEC = re.compile(r'name\s*=\s*"([^"]+)"')
# 항목 시작만 잡고 **다음 항목 시작 직전까지**를 본문으로 삼는다. 블록을 정규식으로
# 닫으려 하면 중첩 `{}`(apply 함수 본문)에서 어긋나 절반을 놓친다 — 실측 2026-08-05:
# 1023개 중 542개만 잡혔다.
_CONFIG_START = re.compile(r'\{\s*var\s*=\s*"(\w+)"')
_COND_KEYS = ("ifFlag", "ifMod", "ifCond", "ifEnemyCond", "ifSkill", "ifSkillList", "ifMult")
_LABEL = re.compile(r'label\s*=\s*"([^"]*)"')
_TOOLTIP = re.compile(r'tooltip\s*=\s*"([^"]*)"')


def pob_src(root: Path | None = None) -> Path:
    return pob_src_dir(root)


@dataclass(frozen=True)
class ConfigOption:
    """PoB config 항목 하나 — 언제 관련되는지를 자기가 안다."""

    var: str
    label: str
    conditions: tuple[str, ...]  # ifFlag/ifMod/… 값들 (관련성 판정용)
    tooltip: str = ""

    @property
    def keywords(self) -> tuple[str, ...]:
        """조건 문자열에서 뽑은 매칭 키워드 — `Condition:CanInflictIncision` → `Incision`."""
        out: list[str] = []
        for cond in self.conditions:
            bare = cond.split(":")[-1]
            # 접두 기능어를 떼면 남는 게 실제 대상이다 — CanInflictIncision → Incision
            bare = re.sub(
                r"^(Can|Is|Are|Has|Have|Do|Using|While|Enemy|Your)+(Inflict|Be|Have)?", "", bare
            )
            # CamelCase를 단어로 — CanInflictIncision → Incision
            words = re.findall(r"[A-Z][a-z]{2,}", bare)
            out.extend(words or ([bare] if bare else []))
        return tuple(dict.fromkeys(out))


@lru_cache(maxsize=4)
def gem_ids(root: Path | None = None) -> frozenset[str]:
    """PoB가 아는 `gem_id` 전량 (`Data/Gems.lua`)."""
    text = (pob_src(root) / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    return frozenset(_GEM_ID.findall(text))


@lru_cache(maxsize=4)
def gem_names(root: Path | None = None) -> dict[str, str]:
    """표시 이름 → gem_id. 이름만 아는 호출자에게 정본 id를 알려주려는 것."""
    text = (pob_src(root) / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for match in re.finditer(r'\["(Metadata/Items/Gems/[^"]+)"\]\s*=\s*\{(.*?)\n\t\}', text, re.S):
        name = _NAME_SPEC.search(match.group(2))
        if name:
            out.setdefault(name.group(1), match.group(1))
    return out


@lru_cache(maxsize=4)
def config_options(root: Path | None = None) -> tuple[ConfigOption, ...]:
    """PoB config 항목 전량 (`Modules/ConfigOptions.lua`)."""
    text = (pob_src(root) / "Modules" / "ConfigOptions.lua").read_text(
        encoding="utf-8", errors="replace"
    )
    starts = list(_CONFIG_START.finditer(text))
    out: list[ConfigOption] = []
    for i, match in enumerate(starts):
        var = match.group(1)
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        body = text[match.end() : end]
        conditions: list[str] = []
        for key in _COND_KEYS:
            conditions.extend(re.findall(rf'{key}\s*=\s*"([^"]+)"', body))
        label = _LABEL.search(body)
        tooltip = _TOOLTIP.search(body)
        out.append(
            ConfigOption(
                var=var,
                label=label.group(1) if label else "",
                conditions=tuple(conditions),
                tooltip=tooltip.group(1) if tooltip else "",
            )
        )
    return tuple(out)


@lru_cache(maxsize=4)
def config_vars(root: Path | None = None) -> frozenset[str]:
    return frozenset(o.var for o in config_options(root))


def _similar(name: str, pool: list[str], limit: int = 5) -> list[str]:
    """오타·표기 차이를 넘어 근접 후보 — 막다른 길 대신 다음 수를 준다."""
    import difflib

    return difflib.get_close_matches(name, pool, n=limit, cutoff=0.6)


def suggest_gem_ids(unknown: str, root: Path | None = None) -> list[str]:
    """미지의 gem_id에 대한 정본 후보. 이름으로 준 경우도 잡는다."""
    ids = gem_ids(root)
    by_name = gem_names(root)
    # "Heavy Swing" 처럼 표시 이름을 넣은 경우가 흔하다
    if unknown in by_name:
        return [by_name[unknown]]
    tail = unknown.rsplit("/", 1)[-1]
    hits = _similar(unknown, sorted(ids))
    if not hits:
        hits = [i for i in sorted(ids) if tail.lower() in i.lower()][:5]
    if not hits:
        name_hits = _similar(tail, sorted(by_name))
        hits = [by_name[n] for n in name_hits]
    return hits


def suggest_config_vars(unknown: str, root: Path | None = None) -> list[str]:
    return _similar(unknown, sorted(config_vars(root)))


# ── statSet 카탈로그 (백로그 #52) ────────────────────────────────────────
# 한 스킬이 **모드(파트)를 여럿 갖는다** — 구형 번개는 `[1] Ball Lightning` ·
# `[2] Fire-Infused` · `[3] Ignited Ground` 셋이고 셋이 다른 스킬이나 마찬가지다
# (실측 2026-08-10: `WithIgniteDPS` 2,387 / 32,231 / **47,329**). 지정하지 않으면
# PoB는 조용히 1번을 쓴다 — 20배 낮은 수치가 정상으로 보인다(§0 ①).
_GRANTED_EFFECT_ID = re.compile(r'grantedEffectId\s*=\s*"([^"]+)"')
_SKILL_BLOCK = re.compile(r'^skills\["([^"]+)"\]\s*=\s*\{', re.M)
_STAT_SETS = re.compile(r"\bstatSets\s*=\s*\{")


def _match_brace(text: str, start: int) -> int:
    """`text[start]`의 `{`에 대응하는 `}`의 인덱스. 문자열·주석 안의 괄호는 세지 않는다."""
    depth, i, n = 0, start, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':  # Lua 짧은 문자열
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch == "-" and text.startswith("--", i):
            nl = text.find("\n", i)
            i = n if nl < 0 else nl
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


@lru_cache(maxsize=4)
def granted_effects(root: Path | None = None) -> dict[str, str]:
    """`gem_id` → `grantedEffectId`. statSet 선택 XML의 키가 이 값이다."""
    text = (pob_src(root) / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for match in re.finditer(r'\["(Metadata/Items/Gems/[^"]+)"\]\s*=\s*\{', text):
        end = _match_brace(text, match.end() - 1)
        effect = _GRANTED_EFFECT_ID.search(text, match.end(), end if end > 0 else len(text))
        if effect:
            out[match.group(1)] = effect.group(1)
    return out


@lru_cache(maxsize=4)
def stat_set_labels(root: Path | None = None) -> dict[str, tuple[str, ...]]:
    """`grantedEffectId` → statSet 라벨들 (1번부터 순서대로).

    ⚠ `Data/Gems.lua`의 `additionalStatSet1/2`로 세지 않는다 — exporter 전용이라
    PoB 계산엔 소비처가 없다(`grep -rl additionalStatSet` → `Data/Gems.lua`,
    `Export/Scripts/skills.lua` 둘뿐). 색인의 유효 범위를 정하는 것은 `statSets`다.
    """
    out: dict[str, tuple[str, ...]] = {}
    for path in sorted((pob_src(root) / "Data" / "Skills").glob("*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _SKILL_BLOCK.finditer(text):
            end = _match_brace(text, match.end() - 1)
            if end < 0:
                continue
            sets = _STAT_SETS.search(text, match.end(), end)
            if sets is None:
                continue
            sets_end = _match_brace(text, sets.end() - 1)
            if sets_end < 0:
                continue
            out[match.group(1)] = tuple(_child_labels(text, sets.end(), sets_end))
    return out


def _child_labels(text: str, start: int, end: int) -> list[str]:
    """`statSets = { {…}, {…} }`의 **직속 자식**마다 `label`을 뽑는다 (없으면 빈 문자열)."""
    labels: list[str] = []
    i = start
    while i < end:
        if text[i] == "{":
            child_end = _match_brace(text, i)
            if child_end < 0:
                break
            found = _LABEL.search(text, i, child_end)
            labels.append(found.group(1) if found else "")
            i = child_end + 1
            continue
        i += 1
    return labels


def stat_sets(gem_id: str, root: Path | None = None) -> tuple[str, tuple[str, ...]]:
    """`gem_id` → (`grantedEffectId`, statSet 라벨들). 모르는 젬이면 `("", ())`."""
    effect = granted_effects(root).get(gem_id, "")
    return effect, stat_set_labels(root).get(effect, ())


# ── skillTypes 카탈로그 — 「무엇이 무엇을 담을 수 있나」의 원천 ────────────────
# 담체 판정(어느 메타/토템/트리거에 이 스킬을 넣을 수 있나)은 **레코드 문구에 없다.**
# PoB의 `requireSkillTypes`/`excludeSkillTypes`에만 있다. 그래서 `discover_mechanics`
# 같은 사전 매칭으로는 구조적으로 못 찾는다(그 도구가 스스로 밝힌 한계).
# 실측 2026-08-11: 「주문 토템에 구형 번개를 넣을 수 있다」를 손으로 알아내야 했고,
# 「까부르는 화염은 `fromItem`이라 젬 소켓 자체가 불가」를 놓쳐 설계가 한 바퀴 헛돌았다.
_SKILL_TYPES = re.compile(r"(?<!minion)\bskillTypes\s*=\s*\{")
# 소환수 스킬의 타입 — PoB는 **요구 판정에만** 함께 본다
# (`doesTypeExpressionMatch(require, skillTypes, minionTypes)`; 배제엔 안 넘긴다).
# 실측 2026-08-11: 스킬 42종이 이걸 갖고 보조 150종이 `ignoreMinionTypes`를 쓴다 —
# 빠뜨리면 소환수 빌드에서 **거짓 배제**가 난다.
_MINION_TYPES = re.compile(r"\bminionSkillTypes\s*=\s*\{")
_IGNORE_MINION = re.compile(r"\bignoreMinionTypes\s*=\s*true")
_REQUIRE_TYPES = re.compile(r"\brequireSkillTypes\s*=\s*\{")
_EXCLUDE_TYPES = re.compile(r"\bexcludeSkillTypes\s*=\s*\{")
_ADD_TYPES = re.compile(r"\baddSkillTypes\s*=\s*\{")
_TYPE_REF = re.compile(r"SkillType\.(\w+)")
_FROM_ITEM = re.compile(r"\bfromItem\s*=\s*true")
_CANNOT_BE_SUPPORTED = re.compile(r"\bcannotBeSupported\s*=\s*true")
_SUPPORT_GEMS_ONLY = re.compile(r"\bsupportGemsOnly\s*=\s*true")
_IS_SUPPORT = re.compile(r"\bsupport\s*=\s*true")
_SKILL_NAME = re.compile(r'\bname\s*=\s*"([^"]*)"')


@dataclass(frozen=True)
class SkillGate:
    """한 스킬(또는 보조/메타 젬)의 담체 판정 재료 — PoB 정의 그대로."""

    skill_id: str
    name: str
    types: frozenset[str]
    # ⚠ require/exclude는 **후위(RPN) 식**이라 순서가 의미를 갖는다 —
    # `{Spell, Totemable, AND}`는 "둘 다"이고 집합이 아니다(CalcTools.doesTypeExpressionMatch).
    require: tuple[str, ...]
    exclude: tuple[str, ...]
    adds: tuple[str, ...]
    # 소환수 타입 — 요구 판정에서만 쓰인다(PoB와 동일)
    minion_types: frozenset[str]
    ignore_minion_types: bool
    from_item: bool
    cannot_be_supported: bool
    support_gems_only: bool
    is_support: bool


def _types_in(text: str, start: int, end: int) -> tuple[str, ...]:
    return tuple(m.group(1) for m in _TYPE_REF.finditer(text, start, end))


def _block_types(text: str, pattern: re.Pattern[str], start: int, end: int) -> tuple[str, ...]:
    found = pattern.search(text, start, end)
    if found is None:
        return ()
    close = _match_brace(text, found.end() - 1)
    if close < 0:
        return ()
    return _types_in(text, found.end(), close)


_ADDITIONAL_EFFECT_ID = re.compile(r'additionalGrantedEffectId\d+\s*=\s*"([^"]+)"')


@lru_cache(maxsize=4)
def gem_effect_ids(root: Path | None = None) -> dict[str, tuple[str, ...]]:
    """`gem_id` → 그 젬이 주는 grantedEffect **전량**(주 + additional).

    ⚠ 메타 젬은 **반쪽이 둘**이다 — 주문 토템은 `grantedEffectId`가 소환 스킬이고
    보조 판정을 하는 쪽은 `additionalGrantedEffectId1`이다. 주 id만 보면
    "주문 토템은 보조가 아니다"라는 틀린 답이 나온다.
    """
    text = (pob_src(root) / "Data" / "Gems.lua").read_text(encoding="utf-8", errors="replace")
    out: dict[str, tuple[str, ...]] = {}
    for match in re.finditer(r'\["(Metadata/Items/Gems/[^"]+)"\]\s*=\s*\{', text):
        end = _match_brace(text, match.end() - 1)
        stop = end if end > 0 else len(text)
        ids: list[str] = []
        primary = _GRANTED_EFFECT_ID.search(text, match.end(), stop)
        if primary:
            ids.append(primary.group(1))
        ids.extend(m.group(1) for m in _ADDITIONAL_EFFECT_ID.finditer(text, match.end(), stop))
        if ids:
            out[match.group(1)] = tuple(ids)
    return out


@lru_cache(maxsize=4)
def effect_display_names(root: Path | None = None) -> dict[str, str]:
    """`grantedEffectId` → 젬 표시 이름.

    보조 반쪽의 `skills[...].name`은 내부 id인 경우가 많다
    (`SupportMetaTotemSpellTotemPlayer`) — 사람에게 보일 이름은 젬 쪽에 있다.
    """
    # ⚠ `gem_names()`는 **이름 → gem_id** 방향이다. 뒤집어 쓴다.
    by_id = {gem_id: name for name, gem_id in gem_names(root).items()}
    out: dict[str, str] = {}
    for gem_id, effects in gem_effect_ids(root).items():
        label = by_id.get(gem_id)
        if not label:
            continue
        for effect in effects:
            out.setdefault(effect, label)
    return out


@lru_cache(maxsize=4)
def skill_gates(root: Path | None = None) -> dict[str, SkillGate]:
    """`skills[...]` 전량의 담체 판정 재료. 키는 PoB 스킬 id."""
    out: dict[str, SkillGate] = {}
    for path in sorted((pob_src(root) / "Data" / "Skills").glob("*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _SKILL_BLOCK.finditer(text):
            end = _match_brace(text, match.end() - 1)
            if end < 0:
                continue
            head = match.end()
            name = _SKILL_NAME.search(text, head, end)
            out[match.group(1)] = SkillGate(
                skill_id=match.group(1),
                name=name.group(1) if name else match.group(1),
                types=frozenset(_block_types(text, _SKILL_TYPES, head, end)),
                require=_block_types(text, _REQUIRE_TYPES, head, end),
                exclude=_block_types(text, _EXCLUDE_TYPES, head, end),
                adds=_block_types(text, _ADD_TYPES, head, end),
                minion_types=frozenset(_block_types(text, _MINION_TYPES, head, end)),
                ignore_minion_types=_IGNORE_MINION.search(text, head, end) is not None,
                from_item=_FROM_ITEM.search(text, head, end) is not None,
                cannot_be_supported=_CANNOT_BE_SUPPORTED.search(text, head, end) is not None,
                support_gems_only=_SUPPORT_GEMS_ONLY.search(text, head, end) is not None,
                is_support=_IS_SUPPORT.search(text, head, end) is not None,
            )
    return out
