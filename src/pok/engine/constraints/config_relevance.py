"""관련 있는데 미설정인 PoB config — 기본값 0을 실측으로 오해하는 것을 막는다.

이관 건 3(2026-08-05). 같은 세션에서 두 번 당했다:

- `multiplierIncisionStackCount` 기본 0 → 절개가 무가치해 보여 **필수 젬을 뺄 뻔했다**
- `conditionBleedAggravated` 기본 off → 피 가시+저주로 상시 켜지는 축인데
  모든 출혈 수치가 절반으로 나왔다

`BUILD_DESIGN §2-3`이 "미설정 config의 델타 0을 효과 없음으로 읽지 않는다"를
규율로 못 박았지만, **규율만으로는 세션이 무엇을 켜야 하는지 모른다.** 그래서
도구가 알려준다 — 룬 소켓 `unused`와 같은 성격이다.

## 관련성은 PoB가 정의한다

`Modules/ConfigOptions.lua`의 각 항목이 `ifFlag`·`ifMod`·`ifCond`로 **자기가 언제
관련되는지**를 들고 있다(PoB가 UI에 표시할지 정할 때 쓰는 조건이다). 우리는 그
조건에서 뽑은 키워드를 **빌드의 젬 효과 문구**(KB `stats`, 2026-08-05 수록)와
대조한다. 추측이 아니라 양쪽 다 게임 데이터다.

## 판단하지 않는다 (AD-3)

"이걸 켜라"가 아니라 "이게 관련 있는데 안 켜져 있다"까지만 낸다. 실제로 꺼두는 게
맞는 축도 있다(적이 안 움직이는 상황을 재는 중일 수 있다). 판단은 호출자 몫이다.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pok.pob.catalog import ConfigOption

# 조건 단어가 **전부** 문구에 있어야 관련으로 본다(AND). 한 단어라도 걸리면 매칭하던
# 방식은 `Have`·`From`·`With` 같은 기능어 때문에 32건 중 대부분이 노이즈였다 —
# 실측 2026-08-05. 그래도 남는 흔한 단어는 신호가 되지 못하므로 매칭 대상에서 뺀다.
_STOPWORDS = frozenset(
    {
        "Condition", "Enemy", "Skill", "Skills", "Support", "Supported", "Total", "Base", "Level",
        # 시점·정도 부사 — 거의 모든 효과 문구에 나와서 단독으로는 관련성을 못 가른다
        "Recently", "Always", "Full", "Full life",
    }
)  # fmt: skip
_MIN_KEYWORD_LEN = 4

# ── 거짓 양성 차단 2종 (실측 2026-08-21) ────────────────────────────────
# 힌트가 틀리면 **없는 결함을 조사하게 만든다.** 실제로 원소 작렬에
# `multiplierFreezeShockIgniteOnEnemy`가 붙어서, 그 config를 1↔20으로 바꿔도 값이
# 안 변하는 것을 **PoB 버그로 의심하고 상류 보고 후보로 백로그에 올렸다**. 원인은
# 둘 다 이 매처에 있었다.

# ① 극성 — 부정 문장에 걸린 키워드는 관련성이 아니라 **반대**다.
#    원소 작렬의 매칭 근거는 `Cannot inflict Freeze, Shock or Ignite`였다.
#    그 스킬은 상태이상을 **못 거는데** "상태이상 수" config가 관련 있다고 나왔다.
_NEGATION = re.compile(
    r"\b(?:cannot|can't|never|no longer|do(?:es)? not|don't|doesn't|unaffected by|immune to)\b",
    re.I,
)

# ② `ifMult` 의미 — 승수를 **세우는** config는 그 승수를 **쓰는 접사**가 빌드에 있을
#    때만 값이 변한다. PoB에서 이 승수의 유일한 소비처는 `ModParser.lua`의
#    `"per freeze, shock and ignite on enemy"` 같은 **"per …" 문구**다. 그런 문구가
#    빌드에 없으면 config를 켜도 전 스탯이 그대로다(= 켜라고 알릴 이유가 없다).
_PER_PHRASE = re.compile(r"\bper\b", re.I)


@dataclass(frozen=True)
class UnsetOption:
    """관련 있는데 값이 없는 config 하나."""

    var: str
    label: str
    matched_keyword: str
    matched_in: str  # 어느 젬/문구에서 걸렸는지 (재현·반박 가능하게)
    tooltip: str = ""


def _keywords_of(option_keywords: Iterable[str]) -> list[str]:
    return [k for k in option_keywords if len(k) >= _MIN_KEYWORD_LEN and k not in _STOPWORDS]


def matching_sources(
    option: ConfigOption,
    build_stats_text: Mapping[str, list[str]],
) -> tuple[tuple[str, str], ...]:
    """이 config 항목의 관련성 조건에 걸리는 **(출처, 근거 문구) 전량**.

    `find_unset_options`(꺼진 것 찾기)와 `constraints.upkeep`(켠 것의 대가 찾기)이
    **같은 매처를 쓰도록** 뽑아 둔 것이다. 매처가 갈리면 한쪽에서 관련이라고 본 축을
    다른 쪽이 무관하다고 보게 되고, 그 불일치는 조용하다.
    """
    keywords = _keywords_of(option.keywords)
    if not keywords:
        return ()
    patterns = [re.compile(rf"\b{re.escape(k)}", re.I) for k in keywords]
    # 승수형(ifMult) config는 그 승수를 소비하는 "per …" 문구가 있어야 관련이다
    mult_only = bool(option.condition_kinds) and set(option.condition_kinds) == {"ifMult"}
    out: list[tuple[str, str]] = []
    for source, lines in build_stats_text.items():
        # 키워드가 **부정 아닌 문장에** 전부 있어야 한다. 줄 단위로 보는 것은
        # 부정어가 그 문장에만 걸리기 때문이다("Cannot inflict Freeze, Shock or
        # Ignite" 옆 줄에 멀쩡한 Freeze 문구가 있으면 그건 관련이 맞다).
        usable = [ln for ln in lines if not _NEGATION.search(ln)]
        if not usable:
            continue
        blob = " ".join(usable)
        # **전부** 있어야 한다 — 하나만 걸리면 기능어 때문에 전 config가 잡힌다
        if not all(p.search(blob) for p in patterns):
            continue
        if mult_only and not any(
            _PER_PHRASE.search(ln) and all(p.search(ln) for p in patterns) for ln in usable
        ):
            continue
        # 근거는 **한 줄에 전부 걸린 문장**을 우선한다 — 여러 줄에 흩어져 걸렸으면
        # 그중 하나를 골라도 반박에 쓸 수 없으므로 첫 줄로 물러선다.
        evidence = next((ln for ln in usable if all(p.search(ln) for p in patterns)), usable[0])
        out.append((source, evidence))
    return tuple(out)


def find_unset_options(
    build_stats_text: Mapping[str, list[str]],
    configured: Iterable[str],
    *,
    root: Path | None = None,
) -> tuple[UnsetOption, ...]:
    """빌드의 효과 문구 ↔ config 관련성 조건을 대조해 **미설정분**을 낸다.

    `build_stats_text` = {출처(젬 id 등): 효과 문구 줄들}. KB 레코드의 `data.stats`를
    그대로 넣으면 된다. `configured` = 이미 설정한 config 키들.
    """
    from pok.pob.catalog import config_options

    already = {str(c) for c in configured}
    out: list[UnsetOption] = []
    for option in config_options(root):
        if option.var in already or not option.conditions:
            continue
        hits = matching_sources(option, build_stats_text)
        if not hits:
            continue
        out.append(
            UnsetOption(
                var=option.var,
                label=option.label,
                matched_keyword=" + ".join(_keywords_of(option.keywords)),
                matched_in=hits[0][0],
                tooltip=option.tooltip,
            )
        )
    return tuple(out)
