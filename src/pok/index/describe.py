"""메타 조회 — "KB에 **무엇이 어떤 형태로** 있나" (백로그 B-11).

`search_kb`는 *레코드를 찾아준다.* 그런데 설계 세션이 반복해서 물은 건 다른 것이다:
"스킬 레코드에 코스트 필드가 얼마나 채워져 있나", "어센던시 노드가 몇 개나 있나",
"한글 효과 문구는 얼마나 되나". **레코드가 아니라 충전율**을 묻는 질문이고,
도구 경로가 없어서 매번 `knowledge/` 직접 탐색으로 도피했다 — 실측 4회
(빌드 테스트 3건 + 2026-08-05 한글 보유율 조사).

`schema/*.schema.json`은 답이 못 된다. 그건 **정의**이고 세션이 알고 싶은 건
**실제로 채워진 정도**다. 정의상 optional인 필드가 실은 100% 채워져 있을 수도,
0%일 수도 있는데 그 차이가 설계 판단을 가른다.

산출은 **인덱스에서만** 한다(정본 재파싱 없이). 판단은 하지 않고 분포만 낸다(AD-3).
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.index.search import ensure_index

_HANGUL = re.compile(r"[\uac00-\ud7a3]")
_SAMPLE_VALUES = 3
_MAX_SAMPLE_LEN = 60


@dataclass(frozen=True)
class FieldStat:
    """`data` 필드 하나의 충전 상태."""

    field: str
    count: int  # 이 필드를 가진 레코드 수
    pct: float  # 타입 전체 대비 비율
    value_types: tuple[str, ...]  # 실제 값의 파이썬 타입 (str/int/list/dict/bool)
    samples: tuple[str, ...]  # 값 샘플 (길면 잘림)


@dataclass(frozen=True)
class TypeProfile:
    """한 타입의 전경 — 건수·필드 충전율·라벨 분포·상위 태그."""

    type: str
    total: int
    fields: tuple[FieldStat, ...]
    verification: tuple[tuple[str, int], ...]
    top_tags: tuple[tuple[str, int], ...]
    # 효과 문구에 한글이 실제로 들어 있는 레코드 비율 — 질의를 한국어로 쓸지의 근거.
    # **필드 이름으로 세면 안 된다**: 명명 규약이 타입마다 다르다(Passive는
    # `stats`가 한글이고 `stats_en`이 영어, Item·Modifier는 `*_ko`). `_ko` 접미사만
    # 세면 Passive가 19%로 보이지만 실제 한글 보유율은 100%다 — 실측 2026-08-05.
    korean_effect_pct: float


def _has_hangul(value: Any) -> bool:
    """값 어딘가에 한글이 있나 — 필드 **이름**이 아니라 **내용**으로 판정한다."""
    if isinstance(value, str):
        return bool(_HANGUL.search(value))
    if isinstance(value, dict):
        return any(_has_hangul(v) for v in value.values())
    if isinstance(value, list):
        return any(_has_hangul(v) for v in value)
    return False


def _sample(value: Any) -> str:
    if isinstance(value, str):
        text = value
    elif isinstance(value, list):
        text = f"[{len(value)}건] " + ", ".join(str(v) for v in value[:2])
    elif isinstance(value, dict):
        text = "{" + ", ".join(sorted(value)[:3]) + "}"
    else:
        text = str(value)
    text = " ".join(text.split())
    return text if len(text) <= _MAX_SAMPLE_LEN else text[:_MAX_SAMPLE_LEN] + "…"


def describe_type(
    type_: str,
    field: str | None = None,
    root: Path | None = None,
    db_path: Path | None = None,
) -> TypeProfile:
    """타입 하나의 필드 분포. `field`를 주면 그 필드의 **값 분포**를 자세히 낸다."""
    con = sqlite3.connect(ensure_index(root, db_path))
    try:
        rows = con.execute("SELECT id, json FROM records WHERE type=?", (type_,)).fetchall()
        if not rows:
            known = [r[0] for r in con.execute("SELECT DISTINCT type FROM records ORDER BY type")]
            raise KeyError(f"타입 없음: {type_!r} — 있는 타입: {', '.join(known)}")
        tag_rows = con.execute(
            "SELECT t.tag FROM tags t JOIN records r ON r.id = t.id WHERE r.type = ?",
            (type_,),
        ).fetchall()
    finally:
        con.close()

    total = len(rows)
    counts: Counter[str] = Counter()
    types: dict[str, set[str]] = {}
    samples: dict[str, list[str]] = {}
    verification: Counter[str] = Counter()
    field_values: Counter[str] = Counter()
    korean = 0

    for _rid, blob in rows:
        raw = json.loads(blob)
        data = raw.get("data") or {}
        verification[str(raw.get("verification", ""))] += 1
        if _has_hangul(data):
            korean += 1
        for key, value in data.items():
            counts[key] += 1
            types.setdefault(key, set()).add(type(value).__name__)
            bucket = samples.setdefault(key, [])
            if len(bucket) < _SAMPLE_VALUES:
                bucket.append(_sample(value))
        if field is not None and field in data:
            field_values[_sample(data[field])] += 1

    stats = [
        FieldStat(
            key,
            n,
            round(n / total * 100.0, 1),
            tuple(sorted(types[key])),
            # field를 지정했으면 그 필드는 **빈도순 값 분포**로 바꿔 보여준다
            tuple(f"{v} ({c}건)" for v, c in field_values.most_common(8))
            if field == key
            else tuple(samples[key]),
        )
        for key, n in counts.most_common()
    ]
    tags = Counter(t[0] for t in tag_rows)
    return TypeProfile(
        type=type_,
        total=total,
        fields=tuple(stats),
        verification=tuple(verification.most_common()),
        top_tags=tuple(tags.most_common(12)),
        korean_effect_pct=round(korean / total * 100.0, 1),
    )


def describe_kb(root: Path | None = None, db_path: Path | None = None) -> dict[str, Any]:
    """KB 전체 전경 — 타입별 건수·라벨. "무엇부터 볼지" 고를 때의 첫 화면."""
    con = sqlite3.connect(ensure_index(root, db_path))
    try:
        rows = con.execute(
            "SELECT type, COUNT(*), SUM(ascendancy != '') FROM records "
            "GROUP BY type ORDER BY 2 DESC"
        ).fetchall()
        rels = con.execute(
            "SELECT rel, COUNT(*) FROM relations GROUP BY rel ORDER BY 2 DESC"
        ).fetchall()
        insights = con.execute("SELECT COUNT(*) FROM insights").fetchone()[0]
    finally:
        con.close()
    return {
        "types": [{"type": t, "count": n, "with_ascendancy": int(a or 0)} for t, n, a in rows],
        "total": sum(n for _, n, _ in rows),
        "relations": [{"rel": r, "count": n} for r, n in rels],
        "insights": insights,
    }


@dataclass(frozen=True)
class ValueHit:
    """수치 조회 히트 — 어느 레코드의 어느 경로가 몇이었는지."""

    id: str
    name_ko: str
    name_en: str
    path: str
    value: float


def _walk(node: Any, parts: list[str], prefix: str = "") -> list[tuple[str, Any]]:
    """점 표기 경로를 따라간다. 리스트를 만나면 **모든 원소**로 갈라진다 —
    `reservation.max`는 `reservation`이 리스트라서 원소마다 값이 하나씩 나온다."""
    if not parts:
        return [(prefix, node)]
    head, rest = parts[0], parts[1:]
    out: list[tuple[str, Any]] = []
    if isinstance(node, list):
        for i, item in enumerate(node):
            out += _walk(item, parts, f"{prefix}[{i}]")
        return out
    if isinstance(node, dict) and head in node:
        out += _walk(node[head], rest, f"{prefix}.{head}" if prefix else head)
    return out


def find_by_value(
    path: str,
    type_: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    limit: int = 30,
    root: Path | None = None,
    db_path: Path | None = None,
) -> list[ValueHit]:
    """`data` 안의 **수치로** 레코드를 찾는다 — FTS로는 닿지 않는 축.

    실측 2026-08-05: 점유 검사기가 "정신력 40 남았다"까지는 냈는데 **그 40으로 무엇을
    넣을 수 있는지** 물을 경로가 없었다. `search_kb`는 텍스트만 매칭하고 `reservation`
    같은 수치 필드에는 닿지 못한다. 그래서 세션이 파일을 뒤지거나 후보를 포기했다.

    `path`는 점 표기이고 리스트를 만나면 원소마다 갈라진다
    (`reservation.max` → `data.reservation[0].max`, `[1].max`, …).

    후보 생성일 뿐 **순위나 판단은 하지 않는다**(AD-3) — 값 오름차순으로만 낸다.
    """
    parts = path.split(".")
    con = sqlite3.connect(ensure_index(root, db_path))
    try:
        sql = "SELECT id, name_ko, name_en, json FROM records"
        params: tuple[Any, ...] = ()
        if type_:
            sql += " WHERE type=?"
            params = (type_,)
        rows = con.execute(sql, params).fetchall()
    finally:
        con.close()

    hits: list[ValueHit] = []
    for rid, ko, en, blob in rows:
        raw = json.loads(blob)
        for found_path, value in _walk(raw.get("data") or {}, parts):
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            if minimum is not None and value < minimum:
                continue
            if maximum is not None and value > maximum:
                continue
            hits.append(ValueHit(rid, ko, en, found_path, float(value)))
    hits.sort(key=lambda h: (h.value, h.id))
    return hits[:limit]
