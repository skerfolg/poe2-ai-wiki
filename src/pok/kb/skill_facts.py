"""KB 기반 스킬 게이트 — 판정은 **정본을** 읽는다 (#63 P2).

`hosting.py`(담체↔페이로드)와 statSet 게이트(`pob/buildxml.py`)가 런타임에
gitignore된 파생물(`external/pob/**/Data/`)을 직독하던 것을 여기로 바꾼다:
사실은 `kb/ingest/skill_types.py`가 KB `data.pob`에 수록하고(출처·커밋 핀 포함),
런타임은 이 모듈이 KB에서 읽는다. 철칙 2(파생을 진실로 취급 금지)의 강제 지점이다.

부수 효과 둘: ① 이 사실들이 `search_kb`·`get_entry`로도 닿는다 ② CI에
`Data/Skills/sup_dex.lua` 하나뿐이어도 게이트 전량이 돈다(KB는 git 정본이라
항상 있다) — #62에서 통합 테스트 5건이 통째로 깨졌던 계열의 구조적 해소.

⚠ 커버리지는 KB 수록분이다. PoB에만 있고 KB에 없는 스킬(수집 리포트의
`pob_only_gems`)은 여기 안 나온다 — 그 갭은 조용히 숨기지 않고
`kb/ingest/skill_types.py`의 리포트가 낸다(KI-7).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.kb.store import Store
from pok.kb.store import load as store_load


@dataclass(frozen=True)
class SkillGate:
    """한 스킬(또는 보조/메타 젬 반쪽)의 담체 판정 재료 — KB `data.pob.effects[]`."""

    skill_id: str  # PoB grantedEffectId — statSet 선택 XML의 키이기도 하다
    name: str  # 레코드 표시 이름(en) — 보조 반쪽도 젬 이름을 물려받는다
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
    # KB 연결 고리 — 질의 해석(record id·한글 이름)과 statSet 게이트가 쓴다
    record_id: str = ""
    name_ko: str = ""
    gem_id: str = ""
    stat_sets: tuple[str, ...] = ()


def _gate(record_raw: dict[str, Any], effect: dict[str, Any]) -> SkillGate:
    name = record_raw.get("name", {})
    return SkillGate(
        skill_id=str(effect["id"]),
        name=str(name.get("en", "")),
        types=frozenset(effect.get("types", ())),
        require=tuple(effect.get("require", ())),
        exclude=tuple(effect.get("exclude", ())),
        adds=tuple(effect.get("adds", ())),
        minion_types=frozenset(effect.get("minion_types", ())),
        ignore_minion_types=bool(effect.get("ignore_minion_types", False)),
        from_item=bool(effect.get("from_item", False)),
        cannot_be_supported=bool(effect.get("cannot_be_supported", False)),
        support_gems_only=bool(effect.get("support_gems_only", False)),
        is_support=bool(effect.get("support", False)),
        record_id=str(record_raw.get("id", "")),
        name_ko=str(name.get("ko", "")),
        gem_id=str(record_raw.get("data", {}).get("pob", {}).get("gem_id", "")),
        stat_sets=tuple(effect.get("stat_sets", ())),
    )


# `store.load`가 지문 캐시라 같은 KB면 같은 객체가 온다 — 파생도 그 객체에 묶는다.
# KB가 바뀌면 지문이 달라져 store 객체가 새로 오고, 여기서도 다시 만든다(self-healing).
_Facts = tuple[Store, dict[str, SkillGate], dict[str, tuple[str, ...]]]
_CACHE: _Facts | None = None


def _facts(root: Path | None = None) -> _Facts:
    global _CACHE
    store = store_load(root)
    if _CACHE is not None and _CACHE[0] is store:
        return _CACHE
    gates: dict[str, SkillGate] = {}
    by_gem: dict[str, tuple[str, ...]] = {}
    for record in store.records.values():
        if record.type not in ("Skill", "Support"):
            continue
        pob = record.raw.get("data", {}).get("pob")
        if not pob:
            continue
        effects = pob.get("effects", [])
        if gem_id := pob.get("gem_id"):
            by_gem[str(gem_id)] = tuple(str(e["id"]) for e in effects)
        for effect in effects:
            gates[str(effect["id"])] = _gate(record.raw, effect)
    _CACHE = (store, gates, by_gem)
    return _CACHE


def skill_gates(root: Path | None = None) -> dict[str, SkillGate]:
    """KB에 수록된 게이트 전량. 키는 PoB grantedEffectId."""
    return _facts(root)[1]


def gem_effects(root: Path | None = None) -> dict[str, tuple[str, ...]]:
    """`gem_id` → grantedEffect id들(주 + additional). 메타 젬은 반쪽이 둘이다."""
    return _facts(root)[2]


def primary_effect(gem_id: str, root: Path | None = None) -> str:
    """`gem_id` → 주 grantedEffectId — statSet 선택 XML의 키. 모르면 빈 문자열."""
    effects = gem_effects(root).get(gem_id, ())
    return effects[0] if effects else ""


def stat_sets(gem_id: str, root: Path | None = None) -> tuple[str, tuple[str, ...]]:
    """`gem_id` → (주 grantedEffectId, statSet 라벨들 — 1번부터 순서대로).

    모르는 젬이면 `("", ())` — 라벨 2개 이상인데 색인을 안 주면 PoB가 조용히
    1번으로 계산하는 것(#52)을 막는 게이트가 이 값을 쓴다.
    """
    effects = gem_effects(root).get(gem_id, ())
    if not effects:
        return "", ()
    gate = skill_gates(root).get(effects[0])
    return effects[0], (gate.stat_sets if gate else ())
