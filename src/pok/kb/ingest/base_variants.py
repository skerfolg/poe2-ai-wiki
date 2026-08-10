"""동명 베이스의 **변종 전부**를 수록한다 (백로그 #32).

## 보고는 절반이 틀렸다

이관 보고는 *"완드 16종 전부 `implicits: None`, 목걸이 23종 전부 `implicits: None` —
KB에 베이스 implicit이 통째로 없다"*였다. **필드 이름을 잘못 봤다** — 정본은 단수
`data.implicit`이고, 실측 베이스 1,768종 중 **573종**이 이미 갖고 있다
(`item.attuned-wand` = `Grants Skill: Level (1-20) Mana Drain`).

## 진짜 결함은 동명 변종이다

PoB의 `Data/Bases/*.lua`는 **같은 이름에 여러 번 대입한다** — Lua 테이블이라
나중 것이 앞의 것을 덮고, 우리 덤프(`scripts/pob_dump.lua`)도 그대로 덮었다.
실측: 31종이 총 **96개 정의**를 갖는데 KB에는 31개만 남아 **65개가 사라졌다.**

    Runemastered Runic Fork  3개
      (30-50)% chance for Spell Skills to fire 2 additional Projectiles
      (30-50)% increased Mana Regeneration Rate
      +300 to maximum Runic Ward            ← KB엔 이것만 있었다

셋은 인게임에서 **다른 아이템**이다. 하나만 실으면 베이스 선택이 조용히 틀린다 —
실제로 이 갭 때문에 빌드 세션이 `Runeseeker's Call`을 "지어낸 수치"로 오판해
희귀 쇠스랑으로 갈아치웠다(딜 -41%).

## 왜 파이썬으로 읽나

덤프를 고쳐도(고쳤다 — 아래) 그건 **다음 수집부터** 듣는다. 지금 정본을 채우려면
원본을 직접 읽어야 한다. 형식이 규칙적이라 정규식으로 충분하고, 어긋나면 건수가
맞지 않아 테스트가 잡는다.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from pok.kb.pob_pin import pob_src_dir

_ASSIGN = re.compile(r'itemBases\["([^"]+)"\]\s*=\s*\{')
_IMPLICIT = re.compile(r'^\s*implicit\s*=\s*"((?:[^"\\]|\\.)*)"', re.M)


def _blocks(text: str) -> Iterator[tuple[str, str]]:
    """`itemBases["이름"] = { … }` 블록을 (이름, 본문)으로 잘라 낸다.

    중괄호 깊이로 끝을 찾는다 — `tags = { … }` 같은 중첩이 있어 첫 `}`로는 못 자른다.
    """
    for match in _ASSIGN.finditer(text):
        depth, i = 1, match.end()
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        yield match.group(1), text[match.end() : i - 1]


def scan_variants(root: Path | None = None) -> dict[str, list[str]]:
    """베이스 이름 → implicit 문구 **전량**(정의 순서, 중복 제거).

    implicit이 없는 정의는 빈 문자열로 세지 않는다 — 변종 구분이 implicit 말고 다른
    데 있을 수도 있으니 **없는 것을 지어내지 않는다.**
    """
    out: dict[str, list[str]] = {}
    for path in sorted(pob_src_dir(root).glob("Data/Bases/*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for name, body in _blocks(text):
            found = _IMPLICIT.search(body)
            if not found:
                continue
            lines = out.setdefault(name, [])
            if found.group(1) not in lines:
                lines.append(found.group(1))
    return out


def variant_patch(name: str, variants: dict[str, list[str]]) -> dict[str, Any]:
    """그 베이스에 붙일 `data` 조각 — 변종이 하나뿐이면 **아무것도 붙이지 않는다**.

    전부에 `implicit_variants`를 달면 1,768종에 잡음이 붙는다. 정보가 있는 31종에만
    붙여 "이 이름은 여러 아이템이다"라는 사실이 눈에 띄게 한다.
    """
    lines = variants.get(name) or []
    if len(lines) < 2:
        return {}
    return {"implicit_variants": lines}
