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
    seen: set[str] = set()
    for option in config_options(root):
        if option.var in already or option.var in seen or not option.conditions:
            continue
        keywords = _keywords_of(option.keywords)
        if not keywords:
            continue
        patterns = [re.compile(rf"\b{re.escape(k)}", re.I) for k in keywords]
        for source, lines in build_stats_text.items():
            blob = " ".join(lines)
            # **전부** 있어야 한다 — 하나만 걸리면 기능어 때문에 전 config가 잡힌다
            if all(p.search(blob) for p in patterns):
                out.append(
                    UnsetOption(
                        var=option.var,
                        label=option.label,
                        matched_keyword=" + ".join(keywords),
                        matched_in=source,
                        tooltip=option.tooltip,
                    )
                )
                seen.add(option.var)
                break
    return tuple(out)
