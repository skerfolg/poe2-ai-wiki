"""검색 + self-healing (PROJECT_STRUCTURE §5).

ensure_index()가 (없음 | KB 수정 | 버전업) 3트리거를 감지해 자동 재빌드한다 —
어떤 에이전트도 "재빌드"를 기억할 필요가 없다.
"""

from __future__ import annotations

import json
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
