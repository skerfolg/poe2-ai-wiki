"""`item-exclusive` 접사의 **담체 아이템**을 확인한다 (백로그 #39).

## ⚠ 이 모듈이 `pob/`에 있는 이유

담체 판정의 근거가 **PoB 유니크 정의**다. `kb/`에 두면 의존 방향(`kb`는 `pob`를
import 못 한다)을 어긴다 — 실제로 어겼다가 import-linter가 커밋을 막았다.
결과를 정본에 쓰는 것은 `pob → kb` 방향이라 괜찮다.

## 왜 필요한가

`origins: ["item-exclusive"]` 모드는 "어느 유니크에 붙박이로 달린 모드"라는 뜻인데,
KB에는 **그 유니크가 무엇인지 적혀 있지 않다.** 그래서 모드 레코드의 존재가 곧
획득 가능성으로 읽힌다 — 빌드 세션 하루에 **5건 오판**했고 둘은 설계 근거로 쓰였다가
뒤집혔다(`modifier.uniquestatlifereservation1` "Reserves 15% of Life"로 점유 원장을
짰다가 폐기).

## 담체는 세 갈래다 — 하나만 보면 틀린다

1. **정적 유니크** — `Data/Uniques/*.lua`의 `[[…]]` 블록에 문구가 그대로 있다
2. **생성 유니크** — `Special/Generated.lua`가 접사 풀에서 **만들어 낸다**.
   `Against the Darkness`(`UniqueJewelRadius*`) · `Prism of Belief` ·
   `Megalomaniac` · `Heart of the Well`(`UniqueHeart*`) · `Loreweave`(`UniqueLoreweave*`) ·
   `Passage`(`PassageUnique*`) · 「살점 도가니」(`UniqueVivisectionPrice*`)
3. **키스톤** — `From Nothing`이 키스톤 전량을 변형으로 싣는다

⚠ ①만 보면 **가짜 고아**가 나온다. 실측 2026-08-10: ①만으로 2,266건(41%)이 고아로
보였는데 ②③을 세니 2,163건(39.4%)이었다 — 103건이 생성 유니크의 것이었다.

## ⛔ "담체 미확인"은 "획득 불가"가 아니다

우리가 확인하지 못했다는 사실을 적을 뿐이다. PoB 데이터 밖의 경로(신규 유니크·
아직 미구현)일 수 있다 — 그래서 필드 이름이 `carrier_unknown`이지 `unobtainable`이
아니다. 「모른다」와 「없다」를 섞지 않는 것이 이 프로젝트의 반복 교훈이다.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

# `Special/Generated.lua`의 `modName:match("^…")` 전량 — 생성 유니크가 소비하는 접두.
# 스냅샷을 올리면 이 목록을 다시 확인할 것(테스트가 존재 여부를 잠근다).
GENERATED_PREFIXES: tuple[str, ...] = (
    "UniqueJewelRadius",
    "UniqueVivisectionPrice",
    "PassageUnique",
    "UniqueHeart",
    "UniqueLoreweave",
)
# 바알 함양이 **사후에** 붙이는 변이 접사 — 어느 정적 유니크 정의에도 없다.
# 그래서 "유니크 원문 대조" 방식으로는 **구조적으로** 담체를 못 찾고, 계열 전량이
# `carrier_unknown`이 되어 설계 근거로 쓰이지 못했다(`[빌드]` 이관 D2, 2026-08-11).
# PoB 데이터가 뒷받침한다: `affix = ""` · `weightKey = {}`(정상 풀에서 롤 불가)인데
# `tradeHashes`는 있다 — 즉 **실재하고 거래되는** 모드다(사용자 인게임 확인: 래스피스
# 구체 함양본). 담체는 "바알 함양 오브를 쓴 유니크"이고, 그건 아는 사실이지 미확인이 아니다.
VAAL_MUTATED_TAG = "mutatedunique_vaal"
VAAL_MUTATED_PREFIX = "UniqueMutatedVaal"

# 0.5 베리시움 각인 — 제작이 **특정 유니크에** 붙이는 전용 암시(`[빌드]` 이관 D5).
# 바알 변이(위)와 같은 계열이지만 결정적으로 다른 점: **담체 이름이 키에 박혀 있다**
# (`BloodThornVerisiumImplicitBleedMagnitude1` → Blood Thorn). 그래서 "모른다"가 아니라
# **누구인지 말할 수 있다** — 그 이름을 `carrier_item`으로 낸다(제안 G의 역참조를
# 이 계열에서 먼저 실현하는 셈이다).
VERISIUM_MARKER = "VerisiumImplicit"
_NON_ALNUM = re.compile(r"[^a-z0-9]")
_NUM = re.compile(r"\(\d+(?:\.\d+)?-\d+(?:\.\d+)?\)|\d+(?:\.\d+)?")
_DECORATION = re.compile(r"^(?:\{[a-z]+(?::[^}]*)?\})+", re.I)


def _norm(text: str) -> str:
    """수치를 `#`로 뭉갠 매칭 키 — 롤 범위가 달라도 같은 문구로 본다."""
    return " ".join(_NUM.sub("#", text).split()).lower()


def carrier_index(root: Path | None = None) -> set[str]:
    """유니크 원문 전량의 문구 키. 장식 접두(`{variant:N}`)를 벗긴 형태도 함께 넣는다."""
    from pok.pob.uniques import _index

    keys: set[str] = set()
    for raw in _index(str(root) if root else "").values():
        for line in raw.splitlines():
            if not line.strip():
                continue
            keys.add(_norm(line))
            keys.add(_norm(_DECORATION.sub("", line)))
    return keys


def _fold_name(name: str) -> str:
    """아이템 이름 매칭 키 — 발음 구별 기호·공백·아포스트로피를 뭉갠다.

    ⚠ 이걸 빼면 `Mjölner`가 `mjolner`와 안 맞아 **실존 담체를 놓친다**(실측).
    """
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM.sub("", ascii_only.lower())


def unique_name_index(root: Path | None = None) -> dict[str, str]:
    """유니크 이름(접힌 꼴) → KB 아이템 id. 관사 `the`를 뗀 형태도 함께 넣는다.

    PoB 키가 관사를 빼는 경우가 있다 — `SentryFaster…`의 담체는 `The Sentry`다.
    """
    from pok.kb.store import load as store_load

    out: dict[str, str] = {}
    for record in store_load(root).records.values():
        if record.type != "Item":
            continue
        key = _fold_name(str(record.raw.get("name", {}).get("en") or ""))
        if not key:
            continue
        out.setdefault(key, record.id)
        if key.startswith("the"):
            out.setdefault(key.removeprefix("the"), record.id)
    return out


def verisium_carrier(data: dict[str, Any], uniques: dict[str, str]) -> str | None:
    """베리시움 각인의 담체 아이템 id — 키 접두를 유니크 이름과 맞춘다. 못 찾으면 None."""
    key = str(data.get("pob_key") or "")
    if VERISIUM_MARKER not in key:
        return None
    return uniques.get(_fold_name(key.split(VERISIUM_MARKER)[0]))


def carrier_kind(data: dict[str, Any], carriers: set[str]) -> str:
    """이 모드의 담체가 어느 갈래인가 — `static` | `generated` | `vaal-mutated` | `unknown`."""
    texts = [str(t) for t in (data.get("texts") or [])]
    if texts and any(_norm(t) in carriers for t in texts):
        return "static"
    if str(data.get("pob_key") or "").startswith(GENERATED_PREFIXES):
        return "generated"
    tags = {str(t) for t in (data.get("mod_tags") or [])}
    if VAAL_MUTATED_TAG in tags or str(data.get("pob_key") or "").startswith(VAAL_MUTATED_PREFIX):
        return "vaal-mutated"
    return "unknown"


def apply_carrier_flags(root: Path | None = None, *, write: bool = True) -> dict[str, Any]:
    """담체 미확인 모드에 `carrier_unknown: true`를 붙인다 (확인되면 지운다).

    ⛔ 붙이는 것은 **우리가 확인하지 못했다는 사실**이지 "획득 불가"가 아니다.
    """
    from pok.kb.store import load as store_load
    from pok.kb.store import patch_records

    carriers = carrier_index(root)
    uniques = unique_name_index(root)
    store = store_load(root)
    updates: dict[str, dict[str, Any]] = {}
    counts = {"static": 0, "generated": 0, "vaal-mutated": 0, "unknown": 0}
    verisium_resolved = 0
    for record_id, record in store.records.items():
        data = record.raw.get("data") or {}
        if record.type != "Modifier" or "item-exclusive" not in (data.get("origins") or []):
            continue
        if not data.get("texts"):
            continue
        kind = carrier_kind(data, carriers)
        # 베리시움 각인은 담체를 **이름까지** 안다 — 그러면 미확인이 아니다
        carrier_item = verisium_carrier(data, uniques)
        if carrier_item:
            kind = "static"
            verisium_resolved += 1
        counts[kind] += 1
        flagged = bool(data.get("carrier_unknown"))
        patch: dict[str, Any] = {}
        if kind == "unknown" and not flagged:
            patch["carrier_unknown"] = True
        elif kind != "unknown" and flagged:
            patch["carrier_unknown"] = None  # 담체가 확인됐다
        if data.get("carrier_item") != carrier_item:
            patch["carrier_item"] = carrier_item
        # 「모른다」가 아니라 **어떻게 얻는지 안다**는 것을 적는다 — 담체가 특수 경로인
        # 계열은 그 경로를 이름으로 남겨야 설계가 근거로 쓸 수 있다(도박성은 별개 판단).
        want = "vaal-orb-mutated-unique" if kind == "vaal-mutated" else None
        if data.get("carrier_route") != want:
            patch["carrier_route"] = want
        if patch:
            updates[record_id] = patch
    if write and updates:
        patch_records(updates, root=root)
    return {
        **counts,
        "verisium_resolved": verisium_resolved,
        "changed": len(updates),
        "wrote": bool(write),
    }
