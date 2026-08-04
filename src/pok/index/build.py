"""knowledge/ → var/index.sqlite 빌드 (PROJECT_STRUCTURE §5).

인덱스는 순수 파생물 — 언제든 삭제·재생성 가능. 정본을 절대 수정하지 않는다.
빌드 시 source_fingerprint(정본 콘텐츠 해시)와 SCHEMA_VERSION을 각인해
self-healing(search.ensure_index)의 판정 근거로 쓴다.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from pok.common.paths import index_db_path, knowledge_dir
from pok.kb.insights import load_insights
from pok.kb.store import Store, load

# 인덱스 구조(테이블·칼럼) 변경 시 반드시 +1 → 기존 인덱스 자동 재빌드
SCHEMA_VERSION = 4  # v4: insights.scope — 3계층 사다리(season|durable)

_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE records (
    id TEXT PRIMARY KEY, type TEXT NOT NULL,
    name_ko TEXT NOT NULL, name_en TEXT NOT NULL,
    verification TEXT NOT NULL, json TEXT NOT NULL
);
CREATE TABLE tags (id TEXT NOT NULL, tag TEXT NOT NULL);
CREATE INDEX idx_tags_tag ON tags(tag);
CREATE TABLE relations (src TEXT NOT NULL, rel TEXT NOT NULL, target TEXT NOT NULL);
CREATE INDEX idx_rel_src ON relations(src);
CREATE INDEX idx_rel_target ON relations(target);  -- 역방향 조회 = 인덱스가 제공 (정본은 정방향만)
CREATE VIRTUAL TABLE fts USING fts5(id UNINDEXED, name_ko, name_en, tags, notes, body);

-- 인사이트는 레코드와 별도 테이블이다: 스키마도 성격도 다르다(사실 vs 판단·규율).
-- 같은 DB·같은 self-healing에 태우되 섞지는 않는다.
CREATE TABLE insights (
    id TEXT PRIMARY KEY, slug TEXT NOT NULL, title TEXT NOT NULL,
    label TEXT NOT NULL, scope TEXT NOT NULL, body TEXT NOT NULL, meta TEXT NOT NULL
);
CREATE VIRTUAL TABLE insights_fts USING fts5(id UNINDEXED, title, body);
"""

# data 안에서 검색 가치가 있는 텍스트 필드 (효과·설명 — 한/영)
_BODY_FIELDS = (
    "stats",
    "stats_en",
    "texts",
    "texts_ko",
    "effect",
    "effect_ko",
    "description",
    "implicit",
    "affix_name",
)


def _fts_body(raw: dict[str, object]) -> str:
    """레코드의 효과·설명 텍스트를 한 덩어리로 — FTS body 컬럼.

    실측(2026-07-30): 이름·태그만 색인하면 '생명력 증가'류 효과 질의가 0건이라
    MCP 소비 에이전트가 파일 grep으로 도피한다 — 효과 텍스트가 검색의 본체다.
    """
    data_obj = raw.get("data")
    data: dict[str, object] = data_obj if isinstance(data_obj, dict) else {}
    parts: list[str] = []
    for key in _BODY_FIELDS:
        v = data.get(key)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts += [str(x) for x in v]
    per_slot = data.get("per_slot")
    if isinstance(per_slot, dict):
        for slot_lines in per_slot.values():
            if isinstance(slot_lines, list):
                parts += [str(x) for x in slot_lines]
    return " ".join(parts)


def source_fingerprint(kdir: Path) -> str:
    """정본(knowledge/) 전체의 콘텐츠 해시 — git 상태와 무관하게 결정적."""
    h = hashlib.sha256()
    for p in sorted(kdir.rglob("*")):
        if p.is_file() and p.suffix in {".json", ".ndjson", ".md"}:
            h.update(str(p.relative_to(kdir)).replace("\\", "/").encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def build_index(root: Path | None = None, db_path: Path | None = None) -> Path:
    """정본을 로드·검증(store.load)한 뒤 인덱스를 원자적으로 재생성한다."""
    kdir = knowledge_dir(root)
    db = db_path or index_db_path(root)
    # 검증 실패 시 여기서 예외 → 잘못된 정본이 인덱스로 흘러가지 않음
    store: Store = load(root)

    tmp = db.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    try:
        con.executescript(_DDL)
        con.execute("INSERT INTO meta VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),))
        con.execute(
            "INSERT INTO meta VALUES ('source_fingerprint', ?)", (source_fingerprint(kdir),)
        )
        for r in store.records.values():
            con.execute(
                "INSERT INTO records VALUES (?,?,?,?,?,?)",
                (
                    r.id,
                    r.type,
                    r.name_ko,
                    r.name_en,
                    str(r.raw["verification"]),
                    json.dumps(r.raw, ensure_ascii=False),
                ),
            )
            con.executemany("INSERT INTO tags VALUES (?,?)", [(r.id, t) for t in r.tags])
            con.executemany(
                "INSERT INTO relations VALUES (?,?,?)",
                [(r.id, e["rel"], e["target"]) for e in r.relations],
            )
            con.execute(
                "INSERT INTO fts VALUES (?,?,?,?,?,?)",
                (
                    r.id,
                    r.name_ko,
                    r.name_en,
                    " ".join(r.tags),
                    str(r.raw.get("notes", "")),
                    _fts_body(r.raw),
                ),
            )
        for ins in load_insights(root):
            con.execute(
                "INSERT INTO insights VALUES (?,?,?,?,?,?,?)",
                (
                    ins.id,
                    ins.slug,
                    ins.title,
                    ins.label,
                    ins.scope,
                    ins.body,
                    json.dumps(ins.meta, ensure_ascii=False),
                ),
            )
            con.execute("INSERT INTO insights_fts VALUES (?,?,?)", (ins.id, ins.title, ins.body))
        con.commit()
    finally:
        con.close()
    tmp.replace(db)  # 원자적 교체 — 빌드 중 실패해도 기존 인덱스 보존
    return db
