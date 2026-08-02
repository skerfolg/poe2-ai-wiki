"""PoK MCP 서버 — KB 조회 도구 (P2, D6/AD-4).

얇은 어댑터: 모든 실질 로직은 `pok.index`(FTS5 + self-healing)에 있고, 여기는
도구 서명·토큰 예산(D14 2단계)만 관리한다. 판단·상태를 쌓지 말 것(AGENTS.md).

  search_kb  1단계 — 압축 히트 (id·이름·태그·검증 라벨만)
  get_entry  2단계 — 선별 상세 (fields로 필요한 필드만, 서술은 요청 시)
  related    관계 순회 — 정방향(정본) + 역방향(인덱스 생성) typed edges
  compute_pob / evaluate_delta / check_item_legality / assemble_pob
             빌드·계산 (P3, tools/build.py — PoB 오라클·RC4 검증·기록)

실행: PYTHONPATH=src python -m pok.mcp   (stdio)
등록: claude mcp add pok -- <venv>/bin/python -m pok.mcp  (env PYTHONPATH=src)
"""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from pok.common.paths import knowledge_dir
from pok.index.search import get_entry as _get_entry
from pok.index.search import related as _related
from pok.index.search import search as _search
from pok.mcp.tools import build as _build
from pok.mcp.tools import constraints as _constraints
from pok.mcp.tools import tree as _tree

mcp: FastMCP = FastMCP(
    "pok",
    instructions=(
        "PoE2 지식베이스(패치 0.5.x). 2단계 조회: search_kb로 후보를 좁히고 "
        "get_entry로 필요한 필드만 가져올 것(토큰 절약). 질의는 게임 텍스트 용어로 "
        "— 유저 은어('스태킹')가 아니라 효과 문구('최대 생명력', 'maximum Life')가 "
        "매칭된다. 다단어는 AND 매칭. 레코드의 verification 라벨(GAME_DATA > "
        "POB_CODE ≈ IN_GAME > SUPPORTED_INFERENCE > UNVERIFIED, CONTRADICTED=모순 "
        "경고)을 판단 신뢰도에 반영할 것."
    ),
)

_FRONT_ID = re.compile(r"^id:\s*(\S+)$", re.M)


def _narrative_index(knowledge: Path) -> dict[str, Path]:
    """wiki 서술 문서의 id → 경로 (호출 시 산출 — 파일 수가 작다)."""
    out: dict[str, Path] = {}
    wiki = knowledge / "wiki"
    if not wiki.exists():
        return out
    for md in wiki.rglob("*.md"):
        m = _FRONT_ID.search(md.read_text(encoding="utf-8")[:400])
        if m:
            out[m.group(1)] = md
    return out


@mcp.tool
def search_kb(
    query: str | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """KB 검색 (1단계 — 압축 히트). query는 한국어/영어 키워드(FTS5),
    type은 Skill|Support|Passive|Item|Modifier|Resource|Mechanic|Defence,
    tags는 게임 공식 태그(소문자). 상세는 get_entry로."""
    hits = _search(query=query, tags=tags, type_=type, limit=limit)
    return [asdict(h) for h in hits]


@mcp.tool
def get_entry(
    id: str,
    fields: list[str] | None = None,
    include_narrative: bool = False,
) -> dict[str, Any]:
    """엔티티 상세 (2단계). fields로 필요한 필드만 선별(생략 시 전체 레코드).
    include_narrative=True면 자체 재작성 서술 문서(있을 때)를 함께 반환."""
    record = _get_entry(id, fields=fields)
    if include_narrative:
        doc = _narrative_index(knowledge_dir()).get(id)
        if doc is not None:
            record["narrative"] = doc.read_text(encoding="utf-8")
    return record


@mcp.tool
def related(id: str, rel: str | None = None) -> list[dict[str, str]]:
    """관계 순회 — 정방향(정본 기록)과 역방향(인덱스 생성)을 모두 반환.
    rel로 특정 관계만(triggers|enables|scales_with|consumes|recovers|converts|
    reserves|conflicts_with|mitigates|requires|replaces|overlaps|invalidated_by)."""
    return _related(id, rel=rel)


# 빌드·계산 도구 (P3) — 시그니처·독스트링은 tools/build.py 가 정본
compute_pob = mcp.tool(_build.compute_pob)
evaluate_delta = mcp.tool(_build.evaluate_delta)
check_item_legality = mcp.tool(_build.check_item_legality)
assemble_pob = mcp.tool(_build.assemble_pob)
parse_pob = mcp.tool(_build.parse_pob)

# 설계 루프 (P4.5, D26~D28)
check_constraints = mcp.tool(_constraints.check_constraints)
evaluate_objective = mcp.tool(_constraints.evaluate_objective)
parse_design_doc = mcp.tool(_constraints.parse_design_doc)

# 트리 최적화 도구 (P4) — tools/tree.py
connect_anchors = mcp.tool(_tree.connect_anchors)
optimize_tree = mcp.tool(_tree.optimize_tree)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
