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
    per_path: dict[Path, dict[str, dict[str, Any]]] = {}
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
        per_path.setdefault(r.path, {})[r.id] = {
            "color": color,
            "color_requirements": reqs,
        }

    for path, by_id in per_path.items():
        if path.suffix == ".ndjson":
            lines = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec["id"] in by_id:
                    rec["data"] = {**rec["data"], **by_id[rec["id"]]}
                lines.append(json.dumps(rec, ensure_ascii=False))
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        else:
            rec = json.loads(path.read_text(encoding="utf-8"))
            rec["data"] = {**rec["data"], **by_id[rec["id"]]}
            path.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    store_load(knowledge.parent)  # 병합 후 재검증 — 실패 시 예외
    return {"updated": sum(tally.values()), "by_color": tally, "unmatched": unmatched}
