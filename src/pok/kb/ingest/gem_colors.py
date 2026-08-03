"""보조 젬 색상(요구 속성) 수록 — 백로그 B-2 (2026-08-02).

색상 장부 검사(D27 ②)가 설계 문서의 수기 전사에 의존하던 것을 KB 조회로
바꾼다. 색상은 젬의 **요구 속성**에서 결정적으로 도출된다:

    힘(Str) → red · 민첩(Dex) → green · 지능(Int) → blue · 요구 없음 → colorless

원천은 PoB 젬 데이터(`reqStr/reqDex/reqInt`)이며 재수집 없이 오프라인 적용한다.
무색(요구 속성 0)은 별도 라벨로 남긴다 — 결정화된 면역류 조건의 분모 포함
방식이 미검증이라, 색상으로 뭉뚱그리지 않고 호출자가 판단하게 한다(AD-3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pok.kb.store import load as store_load
from pok.kb.store import patch_records

_ATTR_COLOR = (("reqStr", "red"), ("reqDex", "green"), ("reqInt", "blue"))


def color_of(gem: dict[str, Any]) -> tuple[str, list[str]]:
    """PoB 젬 레코드 → (색상, 근거 속성들). 복수 속성은 최대값 기준·근거 보존."""
    present = [(str(gem.get(attr) or 0), color, attr) for attr, color in _ATTR_COLOR]
    nonzero = [(int(v), color, attr) for v, color, attr in present if int(v) > 0]
    if not nonzero:
        return "colorless", []
    nonzero.sort(key=lambda t: -t[0])
    top = nonzero[0][0]
    tied = [c for v, c, _ in nonzero if v == top]
    color = tied[0] if len(tied) == 1 else "hybrid"
    return color, [attr for _, _, attr in nonzero]


def apply_gem_colors(raw_dir: Path, knowledge: Path) -> dict[str, Any]:
    """KB의 Support 레코드에 data.color·color_requirements를 수록한다 (멱등).

    매칭은 레코드의 영문명 ↔ PoB 젬 name. 미매칭은 건드리지 않고 보고만 한다.
    """
    pob_gems = json.loads((raw_dir / "pob" / "gems.json").read_text(encoding="utf-8"))
    by_name = {str(g.get("name", "")).lower(): g for g in pob_gems.values() if g.get("name")}
    kb = store_load(knowledge.parent)
    patches: dict[str, dict[str, Any]] = {}
    tally: dict[str, int] = {}
    unmatched: list[str] = []
    for r in kb.records.values():
        if r.type != "Support":
            continue
        gem = by_name.get(r.name_en.lower())
        if gem is None:
            unmatched.append(r.id)
            continue
        color, reqs = color_of(gem)
        tally[color] = tally.get(color, 0) + 1
        patches[r.id] = {"color": color, "color_requirements": reqs}

    # 정본 쓰기는 store 단일 경로로 (B-6)
    patch_records(patches, root=knowledge.parent)
    return {"updated": sum(tally.values()), "by_color": tally, "unmatched": unmatched}
