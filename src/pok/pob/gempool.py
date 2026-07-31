"""PoB 스냅샷의 젬 카탈로그 결정적 파싱 — Prism of Belief 변형 풀.

믿음의 분광기(Prism of Belief)는 "+(1-3) to Level of all <스킬> Skills" 한 줄이
랜덤 스킬로 롤되는 고유 주얼이다. 어떤 스킬이 롤될 수 있는지는 PoB
`Data/Uniques/Special/Generated.lua`의 prism 블록이 정의한다:

    data.gems 중 support 아님 · excludedGems(Detonate Minion, Rhoa Mount) 아님
    · grantedEffect가 hidden/fromItem/fromTree 아님
    + 표시명 치환: "Spectre: {0}" → "Summon Spectre", "Companion: {0}" → "Tamed Companion"

여기서는 같은 규칙을 스냅샷의 `Data/Gems.lua`(젬 → grantedEffectId·support 태그)와
`Data/Skills/*.lua`(효과 → hidden/fromItem/fromTree 플래그)에서 재현한다.
fromItem = 무기 부여 스킬(예: Bow Shot·Firebolt) — 젬이 아니므로 프리즘 풀 제외.

LuaJIT 실행 없이 줄 단위 파싱만 한다(기계 생성 파일 — 형식 고정, 결정적).
"""

from __future__ import annotations

import functools
import re
from pathlib import Path

# Generated.lua prism 블록의 excludedGems 그대로
EXCLUDED_GEMS = frozenset({"Detonate Minion", "Rhoa Mount"})

_SKILL_HEAD = re.compile(r'^skills\["([^"]+)"\] = \{')
_SKILL_FLAG = re.compile(r"^\t(hidden|fromItem|fromTree) = true,$")
_GEM_HEAD = re.compile(r'^\t\["(Metadata[^"]+)"\] = \{$')
_GEM_NAME = re.compile(r'^\t\tname = "([^"]*)",$')
_GEM_EFFECT = re.compile(r'^\t\tgrantedEffectId = "([^"]*)",$')
_GEM_SUPPORT = re.compile(r"^\t\t\tsupport = true,$")


def _effect_flags(skills_dir: Path) -> dict[str, frozenset[str]]:
    """Skills/*.lua → 효과 id → {hidden|fromItem|fromTree} (테이블 1층 키만)."""
    flags: dict[str, set[str]] = {}
    for path in sorted(skills_dir.glob("*.lua")):
        cur: set[str] | None = None
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            head = _SKILL_HEAD.match(line)
            if head:
                cur = flags.setdefault(head.group(1), set())
                continue
            if cur is not None:
                flag = _SKILL_FLAG.match(line)
                if flag:
                    cur.add(flag.group(1))
    return {k: frozenset(v) for k, v in flags.items()}


@functools.lru_cache(maxsize=4)
def prism_gem_names(src_dir: str) -> frozenset[str]:
    """스냅샷 src 디렉터리 → Prism of Belief가 롤 가능한 스킬 표시명 집합."""
    src = Path(src_dir)
    flags = _effect_flags(src / "Data" / "Skills")
    names: set[str] = set()
    cur_name: str | None = None
    cur_effect: str | None = None
    cur_support = False
    in_gem = False

    def flush() -> None:
        nonlocal cur_name, cur_effect, cur_support
        if cur_name and cur_effect and not cur_support and cur_name not in EXCLUDED_GEMS:
            fl = flags.get(cur_effect)
            if fl is not None and not fl & {"hidden", "fromItem", "fromTree"}:
                display = cur_name.replace("Spectre: {0}", "Summon Spectre").replace(
                    "Companion: {0}", "Tamed Companion"
                )
                names.add(display)
        cur_name, cur_effect, cur_support = None, None, False

    for line in (src / "Data" / "Gems.lua").read_text(encoding="utf-8").splitlines():
        if _GEM_HEAD.match(line):
            flush()
            in_gem = True
            continue
        if not in_gem:
            continue
        if m := _GEM_NAME.match(line):
            cur_name = m.group(1)
        elif m := _GEM_EFFECT.match(line):
            cur_effect = m.group(1)
        elif _GEM_SUPPORT.match(line):
            cur_support = True
    flush()
    return frozenset(names)


__all__ = ["EXCLUDED_GEMS", "prism_gem_names"]
