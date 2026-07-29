"""완전성 기준 ⑥⑦⑧ 공통 검증기 (KB_INGEST §4).

⑥ 교차 일관성 · ⑦ 정보량 하한 · ⑧ 획득 경로 커버리지 —
젬·트리·유니크가 **같은 함수**를 쓴다(중복 구현 금지). 각 ingest 모듈은 자기 소스를
`SourceEntity`로 정규화해 넘기기만 한다.

왜 필요한가 (2026-07-29 실증 3건, 전부 기존 5중 기준이 통과시킨 것):
  · 마스터리 368 — 수록했으나 배경 그래픽(정보량 0)  → ⑦
  · 성유 부여방법 누락 — 노드 884개에 "어떻게 얻는가"가 없음 → ⑧
  · 이름 불일치 22 — 같은 id인데 소스마다 다른 이름 → ⑥
공통 원인: 한 소스만 기준으로 순회하고, 교차 검증을 **존재 여부에만** 썼다.

설계 원칙:
- **검증기는 판정하지 않는다** — 세고 표본을 남길 뿐, 항목을 버리거나 고치지 않는다.
  수정 여부는 리포트를 본 사람이 정한다(KI-3 리포트+일괄승인).
- **양방향** — "한쪽에만 있음"은 항상 두 방향 모두 리포트한다(기준 ② 강화).
- **값 비교는 두 종류** — 스칼라 `facts`는 정확 불일치, 집합 `sets`는 방향별 차집합.
  집합을 문자열로 이어 붙여 비교하면 표기 차이만으로 전건 불일치가 되어 무용하다
  (실측: 젬 태그를 통짜 비교하면 931/931 "불일치").
- **제외도 드러낸다** — 원장 승인분으로 걸러낸 건수를 리포트에 남긴다(조용한 제외 금지).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

SAMPLE = 20
"""리포트에 남기는 표본 개수 (전체 건수는 count로 따로 표기)."""


@dataclass(frozen=True)
class SourceEntity:
    """검증기가 보는 엔티티의 최소 정규형 — 소스별 스키마를 여기로 접는다.

    key         매칭 키 (트리=노드 id, 젬·유니크=정규화 영문명)
    name        표시 이름 — key와 다를 수 있을 때만 ⑥ 이름 대조가 의미를 가진다
    substance   ⑦ 실질 정보 (stats/mods/효과 텍스트). 비면 "정보량 0" 후보
    acquisition ⑧ 획득 경로 라벨 (없으면 "어떻게 얻는지 모름")
    facts       ⑥ 스칼라 대조 필드 (tier, base_type …)
    sets        ⑥ 집합 대조 필드 (tags, stats …) — 방향별 차집합으로 본다
    structural  ⑦ 면제 — 효과가 없는 것이 정상인 구조 노드(주얼 슬롯 등)
    """

    key: str
    name: str
    substance: tuple[str, ...] = ()
    acquisition: tuple[str, ...] = ()
    facts: Mapping[str, str] = field(default_factory=dict)
    sets: Mapping[str, frozenset[str]] = field(default_factory=dict)
    structural: bool = False


def _compare(a: SourceEntity, b: SourceEntity, labels: tuple[str, str]) -> list[dict[str, Any]]:
    """두 엔티티의 이름·스칼라 fact 불일치 목록 (집합 fact는 호출부에서 따로 본다)."""
    la, lb = labels
    rows: list[dict[str, Any]] = []
    if a.name != b.name:
        rows.append({"key": a.key, "field": "name", la: a.name, lb: b.name})
    for fname in sorted(set(a.facts) & set(b.facts)):
        if a.facts[fname] != b.facts[fname]:
            rows.append({"key": a.key, "field": fname, la: a.facts[fname], lb: b.facts[fname]})
    return rows


def _index(
    entities: Iterable[SourceEntity], label: str
) -> tuple[dict[str, SourceEntity], list[dict[str, Any]]]:
    """key → 엔티티 (중복 key는 첫 항목 유지) + **중복 key 충돌** 목록.

    같은 key가 한 소스 안에 두 번 나오면서 값이 다르면, 뒤 항목이 조용히 버려지는
    자리다 — 교차 대사가 절대 볼 수 없는 사각지대라 여기서 잡는다.
    실측(0.5.4b): 유니크 목록의 '재배(cultivated)' 카드 47건이 base_type 자리에
    모드 텍스트 조각("(100", "+(20")을 담고 있었고, 그대로 KB에 실려 있었다.
    """
    out: dict[str, SourceEntity] = {}
    conflicts: list[dict[str, Any]] = []
    for e in entities:
        prev = out.get(e.key)
        if prev is None:
            out[e.key] = e
            continue
        conflicts.extend(_compare(prev, e, (f"{label}#1", f"{label}#2")))
    return out, conflicts


def _bucket(values: Sequence[Any], sample: int) -> dict[str, Any]:
    return {"count": len(values), "sample": list(values[:sample])}


# ── ⑥ 교차 일관성 ───────────────────────────────────────────────


def cross_source(
    primary: Iterable[SourceEntity],
    secondary: Iterable[SourceEntity],
    *,
    labels: tuple[str, str],
    compare_names: bool = False,
    known_only_in_secondary: Collection[str] = (),
    sample: int = SAMPLE,
) -> dict[str, Any]:
    """두 소스를 key로 맞대어 이름·값·집합 불일치와 **양방향** 단독 항목을 센다.

    `known_only_in_secondary`는 원장에서 승인된 2차 소스 전용 항목(PoE1 잔재 등)의 key —
    단독 목록에서 빼되 건수는 남긴다.
    """
    a_label, b_label = labels
    a, dup_a = _index(primary, a_label)
    b, dup_b = _index(secondary, b_label)
    shared = sorted(a.keys() & b.keys())
    known = set(known_only_in_secondary)

    name_mismatch: list[dict[str, Any]] = []
    fact_mismatch: list[dict[str, Any]] = []
    by_field: dict[str, int] = {}
    set_diff: dict[str, dict[str, list[dict[str, Any]]]] = {}

    for key in shared:
        ea, eb = a[key], b[key]
        for row in _compare(ea, eb, labels):
            if row["field"] == "name":
                if compare_names:
                    name_mismatch.append(row)
                continue
            by_field[row["field"]] = by_field.get(row["field"], 0) + 1
            fact_mismatch.append({**row, "name": ea.name})
        for sname in sorted(set(ea.sets) & set(eb.sets)):
            only_a = sorted(ea.sets[sname] - eb.sets[sname])
            only_b = sorted(eb.sets[sname] - ea.sets[sname])
            if not only_a and not only_b:
                continue
            slot = set_diff.setdefault(sname, {a_label: [], b_label: []})
            if only_a:
                slot[a_label].append({"key": key, "name": ea.name, "values": only_a})
            if only_b:
                slot[b_label].append({"key": key, "name": eb.name, "values": only_b})

    only_a_keys = sorted(a.keys() - b.keys())
    only_b_all = sorted(b.keys() - a.keys())
    only_b_keys = [k for k in only_b_all if k not in known]

    result: dict[str, Any] = {
        "sources": [a_label, b_label],
        "matched": len(shared),
        f"only_in_{a_label}": _bucket([a[k].name for k in only_a_keys], sample),
        f"only_in_{b_label}": _bucket([b[k].name for k in only_b_keys], sample),
        f"known_excluded_from_only_in_{b_label}": len(only_b_all) - len(only_b_keys),
        "fact_mismatch": {
            "count": len(fact_mismatch),
            "by_field": by_field,
            "sample": fact_mismatch[:sample],
        },
        f"duplicate_key_conflict_in_{a_label}": _bucket(dup_a, sample),
        f"duplicate_key_conflict_in_{b_label}": _bucket(dup_b, sample),
    }
    if compare_names:
        result["name_mismatch"] = _bucket(name_mismatch, sample)
    if set_diff:
        result["set_diff"] = {
            sname: {f"only_in_{side}": _bucket(rows, sample) for side, rows in sides.items()}
            for sname, sides in sorted(set_diff.items())
        }
    return result


# ── ⑦ 정보량 하한 ───────────────────────────────────────────────


def substance_floor(
    entities: Iterable[SourceEntity], *, scope: str, sample: int = SAMPLE
) -> dict[str, Any]:
    """수록 대상인데 실질 정보(stats/mods/효과)가 빈 레코드를 센다.

    마스터리 같은 구조·그래픽 노드가 조용히 섞이는 것을 차단한다. `structural=True`는
    "효과가 없는 게 정상"인 노드(주얼 슬롯·어센던시 시작점)라 면제하되 건수는 남긴다.
    """
    checked = 0
    exempt = 0
    empty: list[dict[str, str]] = []
    for e in entities:
        if e.structural:
            exempt += 1
            continue
        checked += 1
        if not any(s.strip() for s in e.substance):
            empty.append({"key": e.key, "name": e.name})
    return {
        "scope": scope,
        "checked": checked,
        "structural_exempt": exempt,
        "empty": _bucket(empty, sample),
    }


# ── ⑧ 획득 경로 커버리지 ─────────────────────────────────────────


def acquisition_coverage(
    entities: Iterable[SourceEntity], *, entity_type: str, sample: int = SAMPLE
) -> dict[str, Any]:
    """ "어떻게 얻는가"가 있는 비율. 낮으면 수집 누락 신호다.

    조건 1급 필드 원칙(RC1)의 적용 지점 — 획득 경로를 모르면 생성기가 그 엔티티를
    쓰기로 결정해도 실현 가능성·비용을 판단할 수 없다.
    """
    total = 0
    with_acq = 0
    routes: dict[str, int] = {}
    missing: list[dict[str, str]] = []
    for e in entities:
        total += 1
        if e.acquisition:
            with_acq += 1
            for r in e.acquisition:
                routes[r] = routes.get(r, 0) + 1
        else:
            missing.append({"key": e.key, "name": e.name})
    top = dict(sorted(routes.items(), key=lambda kv: (-kv[1], kv[0]))[:15])
    return {
        "entity_type": entity_type,
        "total": total,
        "with_acquisition": with_acq,
        "coverage": round(with_acq / total, 4) if total else 0.0,
        "routes_top": top,
        "distinct_routes": len(routes),
        "missing": _bucket(missing, sample),
    }


# ── 리포트 조립 ─────────────────────────────────────────────────


def verification_block(
    *,
    cross: Sequence[dict[str, Any]] = (),
    substance: Sequence[dict[str, Any]] = (),
    acquisition: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    """카테고리 리포트에 붙일 ⑥⑦⑧ 블록 (키 이름을 세 모듈에서 통일)."""
    return {
        "6_cross_source": list(cross),
        "7_substance_floor": list(substance),
        "8_acquisition_coverage": list(acquisition),
    }


__all__ = [
    "SAMPLE",
    "SourceEntity",
    "acquisition_coverage",
    "cross_source",
    "substance_floor",
    "verification_block",
]
