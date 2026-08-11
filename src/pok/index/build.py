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
# v6: records.unlock — 해금 제약을 검색 히트에 실어 보낸다(B-13)
# v7: fts body에 minion_stats — 소환수 효과 검색(#8-b 분리 후 도달 경로)
SCHEMA_VERSION = 9  # v9: records.carrier_unknown — 담체 미확인 접사를 히트에 실어 보낸다(#39)

_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE records (
    id TEXT PRIMARY KEY, type TEXT NOT NULL,
    name_ko TEXT NOT NULL, name_en TEXT NOT NULL,
    verification TEXT NOT NULL, json TEXT NOT NULL,
    -- 전직 식별자: "Witch1 Blood Mage 블러드 메이지" 처럼 코드·영문·한글을 한 줄로.
    -- 어느 표기로 물어도 찾히게 — 표기 불일치가 조회 실패의 단골 원인이다(B-1).
    ascendancy TEXT NOT NULL DEFAULT '',
    -- data.unlock_constraint 원문(JSON). **조회 히트에 실어 보내기 위한** 칼럼이다:
    -- 차단이 조립 시점(assemble_pob)에만 있으면 세션은 그 전에 이미 잘못된 설계
    -- 결론을 낸다(B-13 실측 2026-08-07 — 오라클 전용 노드를 인퍼널리스트 빌드의
    -- 병목 해법으로 제시). 후보를 내는 **모든 지점**에서 같은 판정이 나와야 한다.
    unlock TEXT NOT NULL DEFAULT '',
    -- data.pob_modeling 요약. 같은 이유로 히트에 싣는다: PoB가 못 읽는 문구는
    -- **경고 없이 델타 0**으로 나오고(pok.pob.parse_gaps), 세션은 그걸 "값어치
    -- 없음"이라는 실측으로 오독한다. 레코드 본문(get_entry)에만 두면 후보를 훑는
    -- 단계에서 안 보이고, 오독은 그 단계에서 굳는다(B-13과 같은 구조).
    pob_gap TEXT NOT NULL DEFAULT '',
    carrier_unknown INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_records_asc ON records(ascendancy);
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


def _ascendancy_key(raw: dict[str, object]) -> str:
    """전직 코드·영문·한글을 한 문자열로 — 어느 표기로 물어도 찾히게."""
    data_obj = raw.get("data")
    data: dict[str, object] = data_obj if isinstance(data_obj, dict) else {}
    code = data.get("ascendancy")
    if not code:
        return ""
    names = data.get("ascendancy_name")
    parts = [str(code)]
    if isinstance(names, dict):
        parts += [str(v) for v in names.values() if v]
    return " ".join(parts)


def _unlock_key(raw: dict[str, object]) -> str:
    """해금 제약 원문(JSON) — 없으면 빈 문자열.

    두 꼴이 있다(실측 2026-08-07, Passive 179건): `{"ascendancy": "Oracle",
    "nodes": [5571]}` 176건은 **전직 전용**, `{"nodes": [...]}` 3건은 **선행 노드
    요구**(예: 탈주자의 길 — 3개 노터블을 먼저 찍어야 열린다). 후자는 `ascendancy`가
    없어 전직 대조만으로는 걸러지지 않는다.
    """
    data_obj = raw.get("data")
    data: dict[str, object] = data_obj if isinstance(data_obj, dict) else {}
    unlock = data.get("unlock_constraint")
    return json.dumps(unlock, ensure_ascii=False) if isinstance(unlock, dict) and unlock else ""


def _pob_gap_key(raw: dict[str, object]) -> str:
    """PoB 미모델링 표기 → 히트에 실을 한 줄. 없으면 빈 문자열.

    `pob_modeling`은 두 계열이 쓴다: 룬 슬롯 미매칭(`kb.pob_gaps`)과 트리 문구
    미파싱(`pob.parse_gaps`). 어느 쪽이든 소비자가 알아야 할 것은 같다 —
    **이 레코드의 측정값은 일부(또는 전부) 빠져 있다.** 그래서 kind만 싣는다.
    """
    data_obj = raw.get("data")
    data: dict[str, object] = data_obj if isinstance(data_obj, dict) else {}
    modeling = data.get("pob_modeling")
    if not isinstance(modeling, dict) or modeling.get("supported") is not False:
        return ""
    return str(modeling.get("kind") or "unmodeled")


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
    # 소환수 스탯은 `[{entity, stats}]` 꼴이라 위의 문자열/리스트 분기에 걸리지 않는다.
    # 색인 안 하면 **찾을 수 없는 곳으로 옮긴 셈**이 된다 — #8-b 전에는 (엉뚱한 주인
    # 밑이긴 해도) `stats`에 있어서 검색은 됐다. 도구 갭을 만들면 세션은 파일 탐색으로
    # 도피한다(철칙 5 따름정리). 실체 이름도 함께 넣어 "해골 서리 마법사"로도 닿게 한다.
    minions = data.get("minion_stats")
    if isinstance(minions, list):
        for entity in minions:
            if not isinstance(entity, dict):
                continue
            parts.append(str(entity.get("entity", "")))
            lines = entity.get("stats")
            if isinstance(lines, list):
                parts += [str(x) for x in lines]
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
                "INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    r.id,
                    r.type,
                    r.name_ko,
                    r.name_en,
                    str(r.raw["verification"]),
                    json.dumps(r.raw, ensure_ascii=False),
                    _ascendancy_key(r.raw),
                    _unlock_key(r.raw),
                    _pob_gap_key(r.raw),
                    1 if (r.raw.get("data") or {}).get("carrier_unknown") else 0,
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
