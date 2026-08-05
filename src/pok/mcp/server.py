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

import functools
import inspect
import re
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from pok.common import telemetry
from pok.common.paths import knowledge_dir
from pok.index.search import get_entry as _get_entry
from pok.index.search import get_insight as _get_insight
from pok.index.search import related as _related
from pok.index.search import search as _search
from pok.index.search import search_insights as _search_insights
from pok.mcp.tools import build as _build
from pok.mcp.tools import constraints as _constraints
from pok.mcp.tools import explore as _explore
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


def tool[F: Callable[..., Any]](fn: F) -> F:
    """도구를 등록하면서 호출 이력을 남긴다.

    무개입 테스트에서는 구조 세션이 생성 과정을 못 본다 — 도구가 스스로 남겨야
    결함 보고가 사람의 기억에 의존하지 않는다. 빈 결과(조회 0건)도 남기는 게
    핵심이다: 그건 실패가 아니라 KB 갭이거나 표기 오류라는 **신호**다(B-1 실측).

    `functools.wraps`로 시그니처를 보존해야 FastMCP가 스키마를 만든다.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:
            bound = _named(fn, args, kwargs)
            telemetry.record(
                fn.__name__, bound, outcome="error", detail=f"{type(exc).__name__}: {exc}"
            )
            raise
        outcome = telemetry.classify(result)
        if outcome != "ok":
            telemetry.record(fn.__name__, _named(fn, args, kwargs), outcome=outcome)
        return result

    return mcp.tool(wrapper)  # type: ignore[return-value]


def _named(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """위치 인자까지 이름을 붙여 기록한다 — 재현하려면 이름이 있어야 한다."""
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except (TypeError, ValueError):
        return {"args": list(args), **kwargs}


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


@tool
def search_kb(
    query: str | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
    ascendancy: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """KB 검색 (1단계 — 압축 히트). query는 한국어/영어 키워드(FTS5),
    type은 Skill|Support|Passive|Item|Modifier|Resource|Mechanic|Defence,
    tags는 게임 공식 태그(소문자). 상세는 get_entry로.

    ascendancy = 전직별 노드 열거 — 코드·영문·한글 아무 표기나 부분 일치
    ("블러드 메이지" · "Blood Mage" · "Witch1"). 포인트 예산 장부를 쓰려면
    그 전직의 노터블 전량이 필요하므로 limit을 넉넉히 준다(전직당 20건 안팎).
    query와 함께 쓰면 그 전직 안에서 좁힌다."""
    hits = _search(query=query, tags=tags, type_=type, ascendancy=ascendancy, limit=limit)
    return [asdict(h) for h in hits]


@tool
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


@tool
def search_insights(
    query: str | None = None,
    label: str | None = None,
    scope: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """승격된 인사이트 검색 (1단계 — 발췌 히트).

    인사이트 = 게임 데이터의 *사실*이 아니라 그 위에서 얻은 **판단·규율**이다.
    특히 "무엇이 **안 되는가**"(차단 경로·설계된 벽)가 많아, 설계를 시작하기 전과
    막다른 길을 만났을 때 먼저 조회하면 헛계산을 줄인다.

    query 생략 시 전량 목록(무엇이 있는지 훑기). label로 신뢰도 필터
    (IN_GAME|POB_CODE|GAME_DATA|SUPPORTED_INFERENCE 등). 전문은 get_insight로.

    scope는 3계층 사다리의 칸이다: `durable`(시즌을 넘어 유지) | `season`(이번
    시즌 관찰). 항구적 규칙만 보고 싶으면 scope="durable". 사다리 맨 위는
    canonical 레코드이므로, durable 인사이트의 **사실 부분은 이미 레코드에도
    있을 수 있다**(front matter의 promoted_to로 어느 레코드인지 확인).
    """
    return [asdict(h) for h in _search_insights(query=query, label=label, scope=scope, limit=limit)]


@tool
def get_insight(id: str) -> dict[str, Any]:
    """인사이트 전문 + 계보 (2단계). id는 `insight.<slug>` 또는 slug.

    meta에 검증 주체·피드백 id·패치가 들어 있다 — 이 판단이 어디서 왔는지
    역추적할 수 있어야 신뢰도를 스스로 판정할 수 있다.
    """
    return _get_insight(id)


@tool
def related(id: str, rel: str | None = None) -> list[dict[str, str]]:
    """관계 순회 — 정방향(정본 기록)과 역방향(인덱스 생성)을 모두 반환.
    rel로 특정 관계만(triggers|enables|scales_with|consumes|recovers|converts|
    reserves|conflicts_with|mitigates|requires|replaces|overlaps|invalidated_by)."""
    return _related(id, rel=rel)


# 빌드·계산 도구 (P3) — 시그니처·독스트링은 tools/build.py 가 정본
compute_pob = tool(_build.compute_pob)
evaluate_delta = tool(_build.evaluate_delta)
check_item_legality = tool(_build.check_item_legality)
assemble_pob = tool(_build.assemble_pob)
parse_pob = tool(_build.parse_pob)

# 설계 루프 (P4.5, D26~D28)
check_constraints = tool(_constraints.check_constraints)
evaluate_objective = tool(_constraints.evaluate_objective)
parse_design_doc = tool(_constraints.parse_design_doc)

# 트리 최적화 도구 (P4) — tools/tree.py
connect_anchors = tool(_tree.connect_anchors)
optimize_tree = tool(_tree.optimize_tree)

# 능동 탐사 (P5) — tools/explore.py. 후보 생성만, 판정은 사람 게이트
scan_synergies = tool(_explore.scan_synergies)
find_hypotheses = tool(_explore.find_hypotheses)


def main() -> None:
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
