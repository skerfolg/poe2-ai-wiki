"""PoB가 모델링하지 못하는 것을 KB에 표시한다 (이관 4 C1·C3).

PoB는 계산 오라클이지만 **전지하지 않다.** 두 가지 형태로 조용히 빠진다:

**① 룬 슬롯 매칭 실패.** `Data/ModRunes.lua`의 일부 룬은 슬롯 키가
`["martial weapon wand or staff"]`인데, `Classes/Item.lua:1789`의
`GetSocketedAugmentTypes()`는 `baseType`(weapon)과 `specificType`(two hand mace)만
반환하고 `Item.lua:1172`가 **정확 문자열 일치**로 매칭한다. 복합 키는 어느 쪽과도
같지 않아 통째로 누락된다. 사용자 확인: **게임에서는 철퇴에 장착 가능하다.**

**② 모드 문구 자체가 파서에 없음.** 형태는 실재하지만 **현재 검출된 계열은 없다**
(`_UNPARSED_PATTERNS` 참고 — 여기 있던 `radius-grant`는 오탐이었다).

## 스캐너는 영문만 본다 (2026-08-07)

한글(`texts_ko`)은 **신뢰할 수 없는 입력이었다.** 수집 파서가 옆 모드의 줄을 섞어
넣어 en/ko 줄 수가 어긋난 Modifier가 1,536건이었고, 그 오염된 한글에 반경 정규식이
매칭해 **비반경 모드 519건 전량**에 `radius-grant`가 붙었다. 그 플래그는 세션이
측정 방법을 바꾸는 근거로 쓰이므로, 잘못 붙으면 표기 오류가 아니라 작업 계획을
왜곡한다 — 실제로 한 세션이 "주얼 소켓은 PoB에서 구조적으로 저평가된다"로 읽고
최적화 회차를 늘릴 뻔했다. 스캐너의 판단 근거는 **영문(`texts`·`per_slot`)뿐**이다.

## 왜 PoB를 안 고치나

`external/pob/<스냅샷>/`은 재현성을 위해 **손대지 않는다**(AD-2/D4 — 새 버전은 새
클론이다). 대신 **KB에 미모델링을 표시하고 대체 조립 경로를 안내한다** — B-3에서
`pob_computable: false` 유니크를 다룬 것과 같은 방식이다.

## 대체 조립 (사용자 지시 2026-08-05)

*"PoB에서 지원하지 않더라도 우리는 효과를 예상해서 적용해 볼 수 있지 않을까요?
정확하진 않더라도 추산 어느 정도 된다는 알려줄 수 있을 것 같은데요."*

맞다 — 룬 문구를 **아이템 텍스트에 직접 써 넣으면** PoB가 접사로 파싱해 계산에
들어간다. 그건 실측이 아니라 **추산**이므로 그 사실을 산출물에 남긴다(B-3의
`substitute_modeling`과 같은 계약).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

# `GetSocketedAugmentTypes()`(Item.lua:1786)가 내는 두 값이 매칭 대상이다:
#
#   baseType     = weapon | armour | caster        (wand·staff·sceptre 태그면 caster)
#   specificType = warstaff→quarterstaff · shield+evasion→buckler · 그 외 itemType
#
# `itemType`은 베이스의 `type`(우리 `item_class`)이다 — **`category`가 아니다**.
# 우리 `category`는 subType 기반이라 specificType과 다르고, 그걸 넣으면 정상 룬까지
# 미매칭으로 잡힌다(실측 2026-08-05: 3건이어야 할 것이 124건으로 나왔다).
_POB_BASE_TYPES = frozenset({"weapon", "armour", "caster"})
_POB_SPECIAL_TYPES = frozenset({"quarterstaff", "buckler"})


@dataclass(frozen=True)
class PobGap:
    """PoB가 못 다루는 항목 하나."""

    record_id: str
    kind: str  # "rune-slot-unmatched" | …
    detail: str
    workaround: str


def matchable_slot_keys(root: Path | None = None) -> frozenset[str]:
    """PoB가 룬 슬롯으로 인식할 수 있는 키 전량 (베이스의 type·subType)."""
    from pok.kb.store import load as store_load

    out: set[str] = set(_POB_BASE_TYPES) | set(_POB_SPECIAL_TYPES)
    for record in store_load(root).records.values():
        data = record.raw.get("data") or {}
        if not data.get("spawn_tags"):
            continue  # 베이스만
        item_class = data.get("item_class")
        if isinstance(item_class, str) and item_class:
            out.add(item_class.strip().lower())
    return frozenset(out)


def scan_rune_slot_gaps(root: Path | None = None) -> list[PobGap]:
    """슬롯 키가 PoB의 매칭 집합에 없는 룬 — **계산에서 통째로 빠지는 것들**."""
    from pok.kb.store import load as store_load

    matchable = matchable_slot_keys(root)
    gaps: list[PobGap] = []
    for record in store_load(root).records.values():
        data = record.raw.get("data") or {}
        per_slot = data.get("per_slot")
        if not isinstance(per_slot, dict):
            continue
        unmatched = [k for k in per_slot if str(k).strip().lower() not in matchable]
        if not unmatched:
            continue
        lines = [t for key in unmatched for t in per_slot[key]]
        gaps.append(
            PobGap(
                record_id=record.id,
                kind="rune-slot-unmatched",
                detail=(
                    f"슬롯 키 {unmatched}가 PoB의 매칭 집합에 없다 — "
                    f"`GetSocketedAugmentTypes()`는 베이스의 type·subType만 반환하고 "
                    f"정확 문자열 일치로 비교하므로 이 룬은 계산에서 통째로 빠진다"
                ),
                workaround=(
                    "**대체 조립**: 이 줄들을 아이템 텍스트에 직접 써 넣으면 PoB가 "
                    "접사로 파싱해 반영한다 — 실측이 아니라 **추산**이므로 산출물에 "
                    f"그 사실을 남길 것(manifest `substitute_modeling`). 줄: {lines}"
                ),
            )
        )
    return gaps


def apply_gap_flags(root: Path | None = None, *, write: bool = True) -> dict[str, Any]:
    """검출된 갭을 레코드에 표시한다 — 조회하면 바로 보이게."""
    from pok.kb.store import patch_records

    gaps = [*scan_rune_slot_gaps(root), *scan_unparsed_mod_texts(root)]
    updates = {
        gap.record_id: {
            "pob_modeling": {
                "supported": False,
                "kind": gap.kind,
                "detail": gap.detail,
                "workaround": gap.workaround,
            }
        }
        for gap in gaps
    }
    if write and updates:
        patch_records(updates, root=root)
    return {"flagged": sorted(updates), "count": len(updates)}


# ModParser가 아는 문구인지 보는 대신, **패턴 자체가 없는 계열**을 짚는다.
# 전 모드를 ModParser와 대조하려면 그 거대한 파일의 정규식을 전부 해석해야 하는데,
# 지금 필요한 건 "우리가 아는 미모델링 계열이 KB 어디에 있는가"다.
#
# ⛔ **여기 넣는 정규식은 영문 문구여야 한다** — 판단 근거는 `texts`·`per_slot`뿐이고
#    `texts_ko`는 보지 않는다(모듈 docstring "스캐너는 영문만 본다").
#
# `radius-grant`는 철회했다 (2026-08-07). 두 근거 모두 무너졌다:
#   ① 관측된 519건은 전부 **오염된 한글**에만 매칭했다 — 영문 근거 0건.
#   ② PoB에 패턴이 **있다**: `Modules/ModParser.lua:7041`의
#      `^(%w+) Passive Skills in Radius also grant (.*)$`가 부여 문구를 재귀 파싱해
#      노드 종류(Small/Notable)별로 적용하고, `Modules/CalcSetup.lua:122`의
#      `runRadiusJewelFunc`이 반경 안 노드에 그 목록을 돌린다. 미모델링이 아니다.
#   원래 관측("`JewelBleedingEffect`는 PoB에서 한 줄인데 KB엔 반경 부여 줄이 있다")도
#   오염으로 설명된다 — 그 반경 줄은 별개 모드(`JewelRadiusBleedingEffect`)의 것이고,
#   `JewelBleedingEffect`가 한 줄인 건 **실제로 한 줄이기 때문**이었다.
_UNPARSED_PATTERNS: tuple[tuple[str, str, str], ...] = ()


def scannable_lines(data: dict[str, Any]) -> list[str]:
    """판정 근거로 삼는 줄 — **영문만**.

    `texts_ko`를 넣으면 수집 오염이 그대로 미모델링 판정이 된다. 실측 2026-08-07:
    그렇게 `radius-grant`가 519건 붙었고 영문 근거는 0건이었다. 한글 번역은 원문의
    파생이지 PoB가 파싱하는 대상이 아니므로, 애초에 판정 축이 될 수 없다.

    타입마다 영문 문구가 담기는 키가 다르다: Modifier·룬은 `texts`/`per_slot`,
    트리 노드는 `stats_en`이다. 후자를 빼 두면 트리 파싱 갭(`pob.parse_gaps`)이
    "영문 근거 없이 붙은 플래그"로 보인다 — 근거는 있고 이 함수가 못 본 것뿐이다.
    """
    lines: list[str] = []
    for key in ("texts", "per_slot", "stats_en"):
        value = data.get(key)
        if isinstance(value, list):
            lines.extend(str(t) for t in value)
        elif isinstance(value, dict):
            lines.extend(str(x) for v in value.values() for x in v)
    return lines


def scan_unparsed_mod_texts(root: Path | None = None) -> list[PobGap]:
    """PoB `ModParser`에 패턴이 없는 문구를 가진 모드 (이관 4 C3)."""
    import re

    from pok.kb.store import load as store_load

    compiled = [(kind, re.compile(pat, re.I), why) for kind, pat, why in _UNPARSED_PATTERNS]
    gaps: list[PobGap] = []
    for record in store_load(root).records.values():
        data = record.raw.get("data") or {}
        texts = scannable_lines(data)
        if not texts:
            continue
        for kind, pattern, why in compiled:
            if any(pattern.search(line) for line in texts):
                gaps.append(
                    PobGap(
                        record_id=record.id,
                        kind=kind,
                        detail=why,
                        workaround=(
                            "**대체 조립**: 부여되는 효과를 주얼 텍스트에 직접 써 넣거나 "
                            "`JewelSpec.allocates`로 노터블을 트리에 편입해 **효과만** "
                            "재현한다(B-3 선례). 실측이 아니라 **추산**이므로 산출물에 "
                            "그 사실을 남길 것"
                        ),
                    )
                )
                break
    return gaps
