"""검색 + self-healing (PROJECT_STRUCTURE §5).

ensure_index()가 (없음 | KB 수정 | 버전업) 3트리거를 감지해 자동 재빌드한다 —
어떤 에이전트도 "재빌드"를 기억할 필요가 없다.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pok.index.build as _build
from pok.common.paths import index_db_path, knowledge_dir
from pok.index.build import build_index, source_fingerprint


@dataclass(frozen=True)
class Hit:
    """압축 히트 (D14 1단계 — 토큰 최소화)."""

    id: str
    type: str
    name_ko: str
    name_en: str
    tags: list[str]
    verification: str


def _meta(con: sqlite3.Connection, key: str) -> str | None:
    try:
        row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    except sqlite3.DatabaseError:
        return None
    return None if row is None else str(row[0])


def ensure_index(root: Path | None = None, db_path: Path | None = None) -> Path:
    """인덱스가 없거나(①) 정본이 바뀌었거나(②) 스키마가 바뀌면(③) 재빌드."""
    db = db_path or index_db_path(root)
    if not db.exists():  # ① 없음 (PC 이동·삭제)
        return build_index(root, db)
    con = sqlite3.connect(db)
    try:
        stale = (
            _meta(con, "schema_version") != str(_build.SCHEMA_VERSION)  # ③ 버전업
            # ② KB 수정
            or _meta(con, "source_fingerprint") != source_fingerprint(knowledge_dir(root))
        )
    finally:
        con.close()
    return build_index(root, db) if stale else db


def _connect(root: Path | None, db_path: Path | None) -> sqlite3.Connection:
    return sqlite3.connect(ensure_index(root, db_path))


def search(
    query: str | None = None,
    tags: list[str] | None = None,
    type_: str | None = None,
    ascendancy: str | None = None,
    limit: int = 20,
    root: Path | None = None,
    db_path: Path | None = None,
) -> list[Hit]:
    """search_kb 1단계 — 압축 히트 반환 (D14)."""
    con = _connect(root, db_path)
    try:
        where, params = [], []
        if query:
            # 토큰별 quote 후 AND — '생명력 증가'가 "최대 생명력 10% 증가"에 매칭되게
            # (정확 구문으로 감싸면 인접하지 않은 다단어 질의가 전부 0건이 된다, 실측)
            tokens = [t for t in query.split() if t]
            safe = " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)
            where.append("r.id IN (SELECT id FROM fts WHERE fts MATCH ?)")
            params.append(safe)
        if type_:
            where.append("r.type = ?")
            params.append(type_)
        if ascendancy:
            # 코드·영문·한글 중 아무 표기로나 — 부분 일치
            where.append("r.ascendancy LIKE ?")
            params.append(f"%{ascendancy}%")
        for t in tags or []:
            where.append("r.id IN (SELECT id FROM tags WHERE tag = ?)")
            params.append(t)
        sql = "SELECT r.id, r.type, r.name_ko, r.name_en, r.verification FROM records r"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY r.id LIMIT ?"
        params.append(str(limit))
        rows = con.execute(sql, params).fetchall()
        out: list[Hit] = []
        for rid, rtype, ko, en, ver in rows:
            tag_rows = con.execute("SELECT tag FROM tags WHERE id=?", (rid,)).fetchall()
            out.append(Hit(rid, rtype, ko, en, [t[0] for t in tag_rows], ver))
        return out
    finally:
        con.close()


_HANGUL = re.compile(r"[\uac00-\ud7a3]")

# 실측 0.5.4b — 이름(name.ko)은 전 타입 100% 한글이지만 **효과 문구는 타입마다 다르다**.
# 값의 내용으로 센 비율(필드 이름이 아니라): Passive 99.6% · Mechanic 60% ·
# Modifier 45.0% · Item 28.8% · **Skill 0.2% · Support 0.0%**.
# 그래서 '공격 속도'는 Support에서 0건이고 Passive에서는 129건이 나온다. 이 비대칭을
# 모르면 소비자는 "KB에 없다"로 오판하고 파일 탐색으로 도피한다(실측 2026-08-05, 9건).
# 현재 값은 describe_type(type).korean_effect_pct 로 언제든 다시 잰다.
_KO_SPARSE_TYPES = ("Skill", "Support")
_KO_EFFECT_COVERAGE = "Passive 99.6% · Modifier 45% · Item 29% — 그러나 **Skill 0.2% · Support 0%**"


@dataclass(frozen=True)
class EmptyDiagnosis:
    """0건인 **이유**. 빈 배열은 아무것도 말하지 않는다 — 그게 문제였다.

    실측 2026-08-05(빌드 테스트 3회차): `search_kb` 빈 결과 9건이 전부 KB 갭이
    아니라 **질의 방식** 때문이었다. 한글 효과 문구(5건) · type 오해(`Rune`을
    Item에서 찾음, 실제론 Modifier) · AND 매칭으로 과도하게 좁힘(`Jewel Attack
    Speed`). 도구가 침묵하니 세션은 KB에 없다고 결론내고 파일을 뒤졌다.
    """

    reasons: tuple[str, ...]
    # type 필터를 풀면 어느 타입에 몇 건 — `Rune`이 Modifier에 있다는 걸 이게 잡는다
    other_types: tuple[tuple[str, int], ...] = ()
    # 토큰별 건수 — AND라서 0인지, 정말 없는 토큰이 있는지 가른다
    token_counts: tuple[tuple[str, int], ...] = ()


def diagnose_empty(
    query: str | None = None,
    tags: list[str] | None = None,
    type_: str | None = None,
    ascendancy: str | None = None,
    root: Path | None = None,
    db_path: Path | None = None,
) -> EmptyDiagnosis:
    """0건 질의를 되짚어 원인 후보를 낸다. 판단은 하지 않고 **사실만** 낸다(AD-3)."""
    reasons: list[str] = []
    other: list[tuple[str, int]] = []
    tokens: list[tuple[str, int]] = []

    if query and _HANGUL.search(query):
        where = (
            f"type={type_!r}는 효과 문구가 **사실상 영어뿐이다**. "
            if type_ in _KO_SPARSE_TYPES
            else ""
        )
        reasons.append(
            f"질의에 한글이 있다. 이름은 전 타입 한/영 모두 인덱싱되지만 **효과 문구의 "
            f"한글 보유율은 타입마다 크게 다르다**({_KO_EFFECT_COVERAGE}). {where}"
            f"효과로 찾는 중이라면 영어 표기로 재시도하라 — 예: '공격 속도'→'Attack Speed'"
        )

    if type_:
        # 같은 질의를 type 없이 — 다른 타입에 있으면 분류를 오해한 것이다
        loose = search(
            query=query, tags=tags, ascendancy=ascendancy, limit=200, root=root, db_path=db_path
        )
        counts: dict[str, int] = {}
        for hit in loose:
            counts[hit.type] = counts.get(hit.type, 0) + 1
        other = tuple(sorted(counts.items(), key=lambda kv: -kv[1]))  # type: ignore[assignment]
        if counts:
            top = ", ".join(f"{t} {n}건" for t, n in list(other)[:4])
            reasons.append(
                f"type={type_!r}에는 없지만 **다른 타입에는 있다** — {top}. "
                f"type을 빼고 다시 찾아보라 (룬은 Item이 아니라 Modifier다)"
            )

    if query:
        parts = [t for t in query.split() if t]
        if len(parts) > 1:
            # 다단어는 AND — 한 토큰만 없어도 전체가 0이 된다
            for part in parts:
                n = len(
                    search(
                        query=part,
                        tags=tags,
                        type_=type_,
                        ascendancy=ascendancy,
                        limit=200,
                        root=root,
                        db_path=db_path,
                    )
                )
                tokens.append((part, n))
            dead = [t for t, n in tokens if n == 0]
            if dead:
                reasons.append(
                    f"다단어는 **AND 매칭**이라 한 토큰만 없어도 0건이다. "
                    f"어느 레코드에도 없는 토큰: {', '.join(repr(d) for d in dead)}"
                )
            elif all(n > 0 for _, n in tokens):
                reasons.append(
                    "다단어는 **AND 매칭**이다 — 토큰이 각각은 있지만 **한 레코드에 "
                    "함께 있지는 않다**. 토큰을 줄이거나 tags 필터로 좁혀라"
                )

    if tags:
        reasons.append(f"tags={tags} 필터가 걸려 있다 — 태그는 게임 공식 소문자 표기다")
    if ascendancy and not reasons:
        reasons.append(f"ascendancy={ascendancy!r}가 어떤 표기와도 부분 일치하지 않았다")
    if not reasons:
        reasons.append(
            "필터로는 설명되지 않는다 — 정말 KB에 없을 수 있다. 수집 갭이라면 "
            "ingest 문제이지 인사이트로 우회할 것이 아니다(KD-5)"
        )
    return EmptyDiagnosis(tuple(reasons), tuple(other), tuple(tokens))


def get_entry(
    entity_id: str,
    fields: list[str] | None = None,
    root: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """get_entry 2단계 — 선별 상세 (D14). fields로 필요한 필드만."""
    con = _connect(root, db_path)
    try:
        row = con.execute("SELECT json FROM records WHERE id=?", (entity_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise KeyError(f"엔티티 없음: {entity_id}")
    raw: dict[str, Any] = json.loads(row[0])
    if fields:
        return {k: raw[k] for k in ["id", "type", *fields] if k in raw}
    return raw


@dataclass(frozen=True)
class InsightHit:
    """인사이트 압축 히트 — 본문 대신 **매칭 지점 발췌**를 준다.

    인사이트는 레코드와 달리 본문이 곧 내용이라, 이름만 돌려주면 소비자가 결국
    전문을 읽어야 한다(그러면 검색한 의미가 없다). 발췌를 붙여 "이걸 펼칠지"를
    한 번에 판단하게 한다 — 2단계 조회(D14)의 인사이트판이다.
    """

    id: str
    slug: str
    title: str
    label: str
    scope: str
    excerpt: str


def search_insights(
    query: str | None = None,
    label: str | None = None,
    scope: str | None = None,
    limit: int = 10,
    root: Path | None = None,
    db_path: Path | None = None,
) -> list[InsightHit]:
    """인사이트 검색 1단계 — 발췌 히트.

    query 없이 호출하면 전량 목록(라벨 필터 가능). 인사이트는 수가 적으므로
    "무엇이 있는지" 훑는 용도도 정당하다.
    """
    con = _connect(root, db_path)
    try:
        params: list[str] = []
        if query:
            tokens = [t for t in query.split() if t]
            safe = " OR ".join('"' + t.replace('"', '""') + '"' for t in tokens)
            # 레코드 검색은 AND(정확도 우선)지만 인사이트는 OR다 — 모수가 수십 건이라
            # 좁히기보다 관련될 만한 것을 놓치지 않는 쪽이 낫다.
            sql = (
                "SELECT i.id, i.slug, i.title, i.label, i.scope, "
                "snippet(insights_fts, 2, '', '', ' … ', 24) "
                "FROM insights_fts f JOIN insights i ON i.id = f.id "
                "WHERE insights_fts MATCH ?"
            )
            params.append(safe)
        else:
            sql = (
                "SELECT i.id, i.slug, i.title, i.label, i.scope, "
                "substr(i.body, 1, 160) FROM insights i"
            )
        for column, value in (("label", label), ("scope", scope)):
            if value:
                # 앞에 조건이 하나라도 있으면 WHERE 절이 이미 열려 있다
                opened = bool(query) or "WHERE" in sql
                sql += (" AND" if opened else " WHERE") + f" i.{column} = ?"
                params.append(value)
        sql += " ORDER BY i.slug LIMIT ?"
        params.append(str(limit))
        rows = con.execute(sql, params).fetchall()
        return [
            InsightHit(i, sl, t, lb, sc, " ".join(str(x).split())) for i, sl, t, lb, sc, x in rows
        ]
    finally:
        con.close()


def get_insight(
    insight_id: str,
    root: Path | None = None,
    db_path: Path | None = None,
) -> dict[str, Any]:
    """인사이트 2단계 — 본문 전문 + 계보(front matter)."""
    con = _connect(root, db_path)
    try:
        row = con.execute(
            "SELECT id, slug, title, label, scope, body, meta FROM insights WHERE id=? OR slug=?",
            (insight_id, insight_id),
        ).fetchone()
    finally:
        con.close()
    if row is None:
        raise KeyError(f"인사이트 없음: {insight_id}")
    return {
        "id": row[0],
        "slug": row[1],
        "title": row[2],
        "label": row[3],
        "scope": row[4],
        "body": row[5],
        "meta": json.loads(row[6]),
    }


def related(
    entity_id: str,
    rel: str | None = None,
    root: Path | None = None,
    db_path: Path | None = None,
) -> list[dict[str, str]]:
    """관계 조회 — 정방향(정본 기록) + 역방향(인덱스 생성) 모두."""
    con = _connect(root, db_path)
    try:
        sql_f = "SELECT src, rel, target FROM relations WHERE src=?"
        sql_r = "SELECT src, rel, target FROM relations WHERE target=?"
        params_f: list[str] = [entity_id]
        params_r: list[str] = [entity_id]
        if rel:
            sql_f += " AND rel=?"
            sql_r += " AND rel=?"
            params_f.append(rel)
            params_r.append(rel)
        edges = [
            {"src": s, "rel": r, "target": t, "direction": "forward"}
            for s, r, t in con.execute(sql_f, params_f).fetchall()
        ] + [
            {"src": s, "rel": r, "target": t, "direction": "reverse"}
            for s, r, t in con.execute(sql_r, params_r).fetchall()
        ]
        return edges
    finally:
        con.close()
