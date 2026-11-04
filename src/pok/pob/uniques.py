"""유니크 **원문은 PoB가 갖고 있다** — 우리가 조립하지 않는다 (백로그 #34 B).

## 왜 조립하면 안 되나

생성기가 유니크 옵션을 텍스트로 직접 썼다가 **PoB에서 오류**가 났다(모리오르).
KB `data.explicits`에는 `[3 Random Socket Modifiers]` · `Has 4 Augment Sockets
(Hidden)` 같은 **플레이스홀더**가 섞여 있고, 무엇보다 **변형(Variant)과 모드 줄의
연결이 없다** — KB `variants`는 이름 목록뿐이다.

PoB의 `Data/Uniques/*.lua`에는 그 아이템의 **원문 전체**가 있다:

    Morior Invictus
    Grand Regalia
    Has Alt Variant: true
    Selected Variant: 29
    Variant: Spirit (Pre 0.2.0)
    …
    {variant:3}+(20-30) to Spirit          ← 변형과 모드가 여기서 묶인다

희귀에 쓴 것과 같은 원리다(#34 A): **명세만 고르고 나머지는 PoB가 만든다.**
여기서 우리가 고르는 것은 **어느 변형인가** 하나뿐이다.

## ⛔ 정본은 PoB 소스다

KB의 유니크 레코드는 조회·검색용이고, **아이템 텍스트의 정본은 여기**다(AD-1).
둘이 다르면 PoB 쪽이 맞다 — 계산도 PoB가 한다.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from pok.kb.pob_pin import pob_src_dir

# `Data/Uniques/*.lua`는 `[[ … ]]` 롱 스트링의 나열이다(첫 줄=이름, 둘째 줄=베이스).
_BLOCK = re.compile(r"\[\[\s*\n(.*?)\n\]\]", re.S)
_SELECTED = re.compile(r"^Selected( Alt)?( Variant)?( Two| Three| Four| Five)?:.*$", re.M)


@lru_cache(maxsize=1)
def _index(root_key: str = "") -> dict[str, str]:
    """유니크 이름(소문자) → 원문. 파일 전량을 한 번만 읽는다."""
    out: dict[str, str] = {}
    base = pob_src_dir(Path(root_key) if root_key else None) / "Data" / "Uniques"
    for path in sorted(base.rglob("*.lua")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _BLOCK.finditer(text):
            body = match.group(1)
            first = body.splitlines()[0].strip() if body.strip() else ""
            if first:
                out.setdefault(first.lower(), body)
    return out


def unique_raw(name: str, root: Path | None = None) -> str | None:
    """유니크 이름 → PoB 원문. 없으면 `None` — **지어내지 않는다**."""
    return _index(str(root) if root else "").get(name.strip().lower())


def variants(name: str, root: Path | None = None) -> tuple[str, ...]:
    """그 유니크가 가진 변형 이름들 (선언 순서 = `Selected Variant`의 1-기반 색인)."""
    raw = unique_raw(name, root)
    if raw is None:
        return ()
    return tuple(
        line.split(":", 1)[1].strip() for line in raw.splitlines() if line.startswith("Variant:")
    )


class UnknownVariantError(ValueError):
    """요청한 변형이 그 유니크에 없다 — 조용히 다른 걸 고르지 않는다."""


def render_unique(name: str, variant: str | None = None, root: Path | None = None) -> str | None:
    """PoB 원문 + 선택한 변형. 우리가 쓰는 것은 **`Selected Variant:` 한 줄뿐**이다.

    `variant`를 안 주면 PoB의 기본 선택(대개 최신판)을 그대로 둔다 — 우리가 고르지
    않은 것을 고른 척하지 않는다.

    ⚠ 이름이 목록에 없으면 **예외**다. 없는 변형을 조용히 무시하면 "골랐는데 안
    반영됨"이 되고, 그건 이 프로젝트가 반복해서 맞은 「조용한 0」이다(§0 ①).
    """
    raw = unique_raw(name, root)
    if raw is None:
        return None
    if variant is None:
        return raw
    names = variants(name, root)
    if variant not in names:
        raise UnknownVariantError(
            f"{name!r}에 변형 {variant!r}이 없다 — 있는 것: {list(names)[:8]}"
            f"{' …' if len(names) > 8 else ''}"
        )
    # `Selected Alt Variant…`까지 함께 지운다: 다중 변형 아이템에서 옛 선택이 남으면
    # PoB가 우리가 안 고른 조각을 계속 붙인다.
    body = _SELECTED.sub("", raw)
    lines = [ln for ln in body.splitlines() if ln.strip()]
    return "\n".join([*lines, f"Selected Variant: {names.index(variant) + 1}"])


def _configuration_of(raw: str) -> dict[str, Any]:
    labels = [
        line.split(":", 1)[1].strip() for line in raw.splitlines() if line.startswith("Variant:")
    ]
    keys = ["Selected Variant"] if labels else []
    encoded: dict[str, str] = {}
    duplicates: bool | None = None
    for line in raw.splitlines():
        key, separator, value = line.partition(":")
        value = value.strip()
        if not separator:
            continue
        if key.startswith("Has Alt Variant") and value == "true":
            keys.append(key.replace("Has ", "Selected ", 1))
        if key.startswith("Selected"):
            encoded[key] = value
        if key == "Allow Duplicate Variants" and value in ("true", "false"):
            duplicates = value == "true"
    selectors = []
    for key in dict.fromkeys(keys):
        encoded_value = encoded.get(key)
        index = int(encoded_value) if encoded_value and encoded_value.isdigit() else None
        selectors.append(
            {
                "key": key,
                "encoded_index": index,
                "encoded_label": labels[index - 1] if index and 1 <= index <= len(labels) else None,
                "origin": (
                    "source_encoded" if encoded_value is not None else "native_default_not_encoded"
                ),
            }
        )
    return {
        "name": raw.splitlines()[0],
        "base_type": raw.splitlines()[1] if len(raw.splitlines()) > 1 else "",
        "variants": [{"index": i, "label": label} for i, label in enumerate(labels, 1)],
        "selectors": selectors,
        "allow_duplicate_variants": duplicates,
        "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def catalogue_available(root: Path | None = None) -> bool:
    """Keep catalogue filesystem inspection inside the established PoB boundary."""
    return (pob_src_dir(root) / "Data" / "Uniques").is_dir()


def describe_configuration(name: str, root: Path | None = None) -> dict[str, Any] | None:
    """Describe exact native selector keys and variant indices; never infer KB alias binding."""
    raw = unique_raw(name, root)
    return _configuration_of(raw) if raw is not None else None


def render_configuration(
    name: str,
    selections: Mapping[str, Any] | None = None,
    root: Path | None = None,
) -> str | None:
    """Change only explicitly selected native controls, retaining every other source default.

    Unlike the legacy single-variant renderer, this supports all declared Alt
    controls. Explicit native duplicate prohibitions are validated; an absent
    policy remains undeclared rather than an inferred game rule.
    A rendered input is not proof of in-game availability or valid acquisition.
    """
    raw = unique_raw(name, root)
    if raw is None:
        return None
    if selections is not None and not isinstance(selections, Mapping):
        raise ValueError("selections must map native selector keys to labels or indices")
    schema = _configuration_of(raw)
    allowed = {row["key"] for row in schema["selectors"]}
    variants = schema["variants"]
    updates: dict[str, int] = {}
    for key, choice in (selections or {}).items():
        if key not in allowed:
            raise ValueError(f"Unknown native selector {key!r}; available: {sorted(allowed)}")
        if isinstance(choice, bool):
            raise ValueError("Variant indices must be integers, not booleans")
        if isinstance(choice, int):
            index = choice
        elif isinstance(choice, str):
            matching = [row["index"] for row in variants if row["label"] == choice]
            if len(matching) != 1:
                raise UnknownVariantError(f"Unknown or ambiguous native variant {choice!r}")
            index = matching[0]
        else:
            raise ValueError("Variant choices must be labels or 1-based integer indices")
        if not 1 <= index <= len(variants):
            raise UnknownVariantError(f"Variant index {index} outside 1..{len(variants)}")
        updates[key] = index
    if not updates:
        return raw
    selected = {
        row["key"]: row["encoded_index"]
        for row in schema["selectors"]
        if row["encoded_index"] is not None
    }
    selected.update(updates)
    if schema["allow_duplicate_variants"] is False and len(set(selected.values())) < len(selected):
        raise ValueError("Native source explicitly disallows duplicate variant choices")
    kept = [line for line in raw.splitlines() if line.partition(":")[0] not in updates]
    selected_lines = [
        f"{row['key']}: {updates[row['key']]}"
        for row in schema["selectors"]
        if row["key"] in updates
    ]
    return "\n".join([*kept, *selected_lines])
