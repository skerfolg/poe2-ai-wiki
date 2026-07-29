"""유니크 아이템 수집·정형화 (KB_INGEST §6-2 ③).

PoB 쪽은 `src/Data/Uniques/*.lua`의 텍스트 블록이 소스다(게임파일 유래 = 교차 대사 축).

블록 포맷:
    이름
    베이스타입
    Variant: <이름>        (0..N줄 — 과거 패치 변형 이력)
    League: / Requires: …  (선택 메타)
    Implicits: N           (선택)
    {tags:a,b}{variant:1,3}모드 텍스트

**변형 처리**: 마지막 Variant가 현재 패치본이다. `{variant:N}`이 붙은 모드는 해당
변형에만 유효하므로 현재 변형에 속하지 않는 모드는 버린다(과거 패치 값 오염 방지).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_BLOCK = re.compile(r"\[\[(.*?)\]\]", re.S)
_VARIANT_TAG = re.compile(r"\{variant:([\d,]+)\}")
_TAGS_TAG = re.compile(r"\{tags:([^}]*)\}")
_META_LINE = re.compile(
    r"^(Variant|League|Requires|Implicits|Source|Radius|Limited to|LevelReq|Has Alt Variant"
    r"|Selected Variant|Prefix|Suffix|Rune|Sockets|Talisman Tier)\s*:",
    re.I,
)


@dataclass
class UniqueItem:
    name: str
    base_type: str
    category: str
    variants: list[str] = field(default_factory=list)
    implicits: list[str] = field(default_factory=list)
    explicits: list[str] = field(default_factory=list)
    mod_tags: list[str] = field(default_factory=list)


def _strip_tags(line: str) -> str:
    return _TAGS_TAG.sub("", _VARIANT_TAG.sub("", line)).strip()


def parse_block(block: str, category: str) -> UniqueItem | None:
    """PoB 유니크 텍스트 블록 1개 → UniqueItem (현재 변형만)."""
    lines = [line.strip() for line in block.strip().splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    name, base_type = lines[0], lines[1]
    if name.startswith("{") or not base_type:
        return None

    variants: list[str] = []
    implicit_count = 0
    body: list[str] = []
    for line in lines[2:]:
        m = _META_LINE.match(line)
        if m:
            key = m.group(1).lower()
            value = line.split(":", 1)[1].strip()
            if key == "variant":
                variants.append(value)
            elif key == "implicits":
                implicit_count = int(value) if value.isdigit() else 0
            continue
        body.append(line)

    current_idx = str(len(variants)) if variants else None  # 마지막 = 현재 패치본
    kept: list[str] = []
    tags: set[str] = set()
    for line in body:
        vm = _VARIANT_TAG.search(line)
        if vm and current_idx is not None and current_idx not in vm.group(1).split(","):
            continue  # 과거 변형 전용 모드 — 버린다
        for tm in _TAGS_TAG.finditer(line):
            tags.update(t.strip() for t in tm.group(1).split(",") if t.strip())
        text = _strip_tags(line)
        if text:
            kept.append(text)

    return UniqueItem(
        name=name,
        base_type=base_type,
        category=category,
        variants=variants,
        implicits=kept[:implicit_count],
        explicits=kept[implicit_count:],
        mod_tags=sorted(tags),
    )


def parse_pob_uniques(uniques_dir: Path) -> list[UniqueItem]:
    """PoB Uniques 디렉터리 전체를 파싱한다 (Special/ 포함, 중복 이름은 첫 항목 유지)."""
    items: list[UniqueItem] = []
    seen: set[str] = set()
    paths = sorted(uniques_dir.glob("*.lua")) + sorted(uniques_dir.glob("Special/*.lua"))
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="replace")
        for block in _BLOCK.findall(text):
            item = parse_block(block, path.stem)
            if item is None or item.name in seen:
                continue
            seen.add(item.name)
            items.append(item)
    return items
