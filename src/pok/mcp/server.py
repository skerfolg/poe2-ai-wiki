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
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from pok.common import telemetry
from pok.common.paths import knowledge_dir
from pok.common.stdio import force_utf8_stdio
from pok.index.describe import describe_kb as _describe_kb
from pok.index.describe import describe_type as _describe_type
from pok.index.describe import find_by_value as _find_by_value
from pok.index.search import diagnose_empty as _diagnose_empty
from pok.index.search import get_entry as _get_entry
from pok.index.search import get_insight as _get_insight
from pok.index.search import related as _related
from pok.index.search import search as _search
from pok.index.search import search_insights as _search_insights
from pok.mcp.tools import build as _build
from pok.mcp.tools import constraints as _constraints
from pok.mcp.tools import explore as _explore
from pok.mcp.tools import tree as _tree


def _git_head(root: Path) -> tuple[str, str]:
    """(짧은 커밋, 제목). 실패해도 세션을 막지 않는다."""
    import subprocess

    try:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        subject = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--format=%s"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        ).stdout.strip()
        return commit, subject
    except Exception:
        return "", ""


# **기동 시점**의 HEAD — 이 프로세스가 실제로 로드한 코드의 판이다. 모듈 import 시
# 한 번 캡처해 두면, 이후 소스가 갱신돼도 이 값은 옛 커밋에 머문다. 그 불일치가
# 곧 "재시작 필요" 신호다(이관 D-1 — git HEAD만 보고하면 소스를 고치는 순간 commit이
# 따라 올라가서, 방지 장치가 방지하려는 조건에서 **항상 통과**한다).
_LOADED_COMMIT, _LOADED_SUBJECT = _git_head(knowledge_dir().parent)

mcp: FastMCP = FastMCP(
    "pok",
    instructions=(
        "PoE2 지식베이스(패치 0.5.x). 2단계 조회: search_kb로 후보를 좁히고 "
        "get_entry로 필요한 필드만 가져올 것(토큰 절약). 질의는 게임 텍스트 용어로 "
        "— 유저 은어('스태킹')가 아니라 효과 문구('maximum Life')가 매칭된다. "
        "⚠ **효과 문구는 대부분 영어로만 인덱싱돼 있다**(Skill·Support는 한글 0%) — "
        "이름은 한/영 모두 되지만 효과로 찾을 땐 영어 표기를 쓸 것. "
        "다단어는 AND 매칭. 0건이면 결과에 진단(`empty`/`why`)이 함께 오니 "
        "**파일을 뒤지기 전에 그것부터 읽을 것**. "
        "스태킹·「X당 Y」 사슬 탐색은 search_kb가 아니라 **scan_supply_edges·"
        "trace_chains**로(축별 공급·보상 엣지 전수, 다단 사슬·공존 진단). "
        "레코드의 verification 라벨(GAME_DATA > "
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
            telemetry.record(
                fn.__name__,
                _named(fn, args, kwargs),
                outcome=outcome,
                detail=telemetry.detail_of(result),
            )
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


def _hit_dict(hit: Any) -> dict[str, Any]:
    """히트 → dict. **비어 있는 해금 칸은 뺀다** — 압축 히트(D14)에 상시 None 세 칸을
    실으면 전 질의가 토큰을 무는데, 정작 신호가 필요한 건 제약이 걸린 소수다."""
    out = asdict(hit)
    for key in ("locked_to", "requires_nodes", "excluded_by_unlock", "pob_gap", "carrier_unknown"):
        if not out.get(key):
            out.pop(key, None)
    if "requires_nodes" in out:
        out["requires_nodes"] = list(out["requires_nodes"])
    return out


@tool
def search_kb(
    query: str | None = None,
    type: str | None = None,
    tags: list[str] | None = None,
    ascendancy: str | None = None,
    limit: int = 20,
    for_ascendancy: str | None = None,
) -> list[dict[str, Any]]:
    """KB 검색 (1단계 — 압축 히트). type은 Skill|Support|Passive|Item|Modifier|
    Resource|Mechanic|Defence, tags는 게임 공식 태그(소문자). 상세는 get_entry로.

    query는 **이름이면 한/영 모두**, **효과 문구면 사실상 영어만** 매칭된다
    (실측: 효과 문구 한글 보유율 Skill·Support 0% · Passive 19% · Modifier 45%).
    '공격 속도'는 0건, 'Attack Speed'는 5건이다.

    0건이면 빈 배열 대신 **진단 1건**(`{"empty": true, "why": [...]}`)이 온다 —
    왜 비었는지(한글·type 오해·AND 매칭)와 다른 타입의 건수·토큰별 건수가 들어 있다.
    "KB에 없다"고 단정하기 전에 이걸 읽을 것.

    ascendancy = 전직별 노드 열거 — 코드·영문·한글 아무 표기나 부분 일치
    ("블러드 메이지" · "Blood Mage" · "Witch1"). 포인트 예산 장부를 쓰려면
    그 전직의 노터블 전량이 필요하므로 limit을 넉넉히 준다(전직당 20건 안팎).
    query와 함께 쓰면 그 전직 안에서 좁힌다.

    **for_ascendancy = 지금 설계 중인 빌드의 전직.** `ascendancy`와 다른 축이다:
    저건 "그 전직이 **소유**한 노드" 필터, 이건 "그 전직으로 **해금 가능한가**"
    판정이다. 다른 전직 전용 해금 노드(Passive 176건)·선행 노드 요구(3건)를
    `excluded_by_unlock` 사유와 함께 표시한다 — **빼지 않고 표시한다**(조용히 빼면
    "KB에 없다"로 오독된다). 주면 히트에 `locked_to`·`requires_nodes`도 붙는다.
    ⚠ 트리 노터블을 고를 땐 반드시 줄 것: 실측 2026-08-07, 오라클 전용 「힘 소진」이
    인퍼널리스트 빌드의 치명타 병목 해법으로 사용자에게 제시됐다(B-13).

    **`pob_gap`이 붙은 히트는 PoB가 그 문구를 계산에 넣지 못한다** — 그 노드·룬의
    델타 0은 "값어치 없음"이 아니라 **"측정 안 됨"**이다. 트리 노드 501건(전체의
    10.2%)이 여기 해당한다(실측 2026-08-07). 그대로 측정해 버리면 원소 집정관
    계열처럼 축 하나가 통째로 0으로 잠긴다(#3). 상세·대체 조립은 get_entry의
    `pob_modeling`.

    **`carrier_unknown`이 붙은 히트는 그 접사를 실제로 다는 유니크를 못 찾은 것이다**
    — 모드가 KB에 있다는 것이 곧 획득 가능은 아니다. `item-exclusive` 5,488건 중
    **2,163건(39.4%)**이 여기 해당한다(실측 2026-08-10, PoB 유니크 정의 전량 + 생성
    유니크 대조). 빌드 세션이 하루에 5건 오판했고 둘은 설계 근거로 쓰였다가 뒤집혔다.
    ⛔ "획득 불가"가 아니라 **"확인 못 함"**이다 — 담체를 확인한 뒤에 근거로 쓸 것."""
    hits = _search(
        query=query,
        tags=tags,
        type_=type,
        ascendancy=ascendancy,
        limit=limit,
        for_ascendancy=for_ascendancy,
    )
    if hits:
        return [_hit_dict(h) for h in hits]
    # 0건이면 **왜 비었는지**를 함께 낸다. 빈 배열은 아무것도 말하지 않아서, 실측
    # 2026-08-05에 세션이 9번 모두 "KB에 없다"로 오판하고 파일 탐색으로 도피했다 —
    # 실제로는 한글 효과 문구·type 오해·AND 매칭 때문이었다.
    diag = _diagnose_empty(query=query, tags=tags, type_=type, ascendancy=ascendancy)
    return [
        {
            "empty": True,
            "why": list(diag.reasons),
            "other_types": [{"type": t, "count": n} for t, n in diag.other_types],
            "token_counts": [{"token": t, "count": n} for t, n in diag.token_counts],
        }
    ]


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
def server_info() -> dict[str, Any]:
    """이 MCP 서버가 **어느 판인지** — 로드된 커밋·소스 커밋·도구별 파라미터 지문.

    ⚠ **이관·수정 통보를 받으면 가장 먼저 부를 것.** MCP 서버는 기동 시점의 코드로
    상주하므로 재시작 전에는 새 도구·새 인자가 없다.

    판정 기준 (실측 2026-08-06 — 방지 장치 자신에게 C10이 재발한 뒤 개정):

    - `stale: true` (= `loaded_commit` ≠ `source_commit`) → **재시작 필요.**
      소스만 갱신되고 프로세스는 옛 코드다. 어느 한쪽 커밋만 보면 안 된다 —
      git HEAD만 보고하던 이전 판은 소스를 고치는 순간 commit이 따라 올라가서
      "최신"이라고 답했고, 그 상태에서 `axes` 호출이
      `Unexpected keyword argument`로 실패했다.
    - **쓰려는 도구가 목록에 없거나, 쓰려는 인자가 그 도구의 `params`에 없으면**
      → 재시작 필요. 이름 존재만으로는 부족하다 — 갱신의 상당수가 "기존 도구에
      인자 추가" 형태다(`axes`·`ids`·`attribute_choices`).

    재시작 전까지는 그 도구·인자에 의존하는 결론을 내지 않는다.
    """
    source_commit, source_subject = _git_head(knowledge_dir().parent)

    # **등록부에서 직접 읽는다** — 모듈 전역을 훑으면 데코레이터 반환 형태에 따라
    # 0종이 나온다(실측). 파라미터 지문은 등록된 inputSchema에서 뽑는다 — 이것이
    # "이 프로세스가 실제로 받는 인자"다(이관 D-2).
    import asyncio

    def _collect() -> Sequence[Any]:
        return asyncio.run(mcp.list_tools())

    try:
        registered = _collect()
    except RuntimeError:
        # 이미 이벤트 루프 안이면(서버 런타임) 별도 루프에서 돌린다
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            registered = pool.submit(_collect).result(timeout=10)

    # FastMCP FunctionTool의 스키마는 `parameters`에 있다 — `inputSchema`로 읽으면
    # 전 도구가 빈 지문으로 나온다(실측 2026-08-06, 첫 구현에서 그랬다)
    tools = {
        t.name: sorted((getattr(t, "parameters", None) or {}).get("properties", {}))
        for t in registered
    }
    stale = bool(_LOADED_COMMIT and source_commit and source_commit != _LOADED_COMMIT)
    # 사본을 빼고 로드했으면 **말한다** — 조용히 빼면 "왜 이 레코드가 안 보이지"가 된다(#21)
    from pok.kb.store import load as store_load

    try:
        skipped = list(store_load().skip_warnings)
    except Exception:  # 진단 도구는 KB가 깨져도 답해야 한다
        skipped = []
    return {
        "kb_skipped_copies": skipped,
        "loaded_commit": _LOADED_COMMIT,
        "loaded_subject": _LOADED_SUBJECT,
        "source_commit": source_commit,
        "source_subject": source_subject,
        "stale": stale,
        "source_root": str(knowledge_dir().parent),
        "tools": tools,
        "tool_count": len(tools),
        "note": (
            "⚠ stale=true — 소스가 갱신됐지만 이 프로세스는 옛 코드다. **서버 재시작 "
            "전에는 새 도구·인자가 없다.**"
            if stale
            else "이 목록·지문에 없는 도구/인자는 **이 프로세스에 없다** — 소스에 "
            "있어도 재시작 전에는 호출되지 않는다."
        ),
    }


@tool
def describe_kb() -> dict[str, Any]:
    """KB 전경 — 타입별 건수·관계 엣지 수·인사이트 수. **무엇이 있는지부터 볼 때.**

    `search_kb`는 레코드를 찾아주지만 "무엇이 어떤 형태로 있나"는 답하지 않는다.
    설계를 시작할 때·수집 갭을 의심할 때 여기서 시작해 describe_type으로 좁혀라.
    """
    return _describe_kb()


@tool
def describe_type(type: str, field: str | None = None) -> dict[str, Any]:
    """타입 하나의 **필드 충전율** — 어떤 필드가 몇 %나 채워져 있고 값이 어떤 꼴인지.

    `schema/*.schema.json`은 **정의**라서 이 질문에 답하지 못한다. 정의상 optional인
    필드가 실제로 100%일 수도 0%일 수도 있고, 그 차이가 설계 판단을 가른다
    (예: Skill의 `category`는 12.5%만 채워져 있어 그것으로 거르면 대부분을 놓친다).

    `field`를 주면 그 필드의 **값 분포**(빈도순)를 낸다 — "이 필드에 어떤 값들이
    실제로 오는가"를 볼 때. `korean_effect_pct`는 효과 문구 한글 보유율이라
    질의를 한국어로 쓸지 영어로 쓸지의 근거가 된다.

    ⛔ 이 질문 때문에 `knowledge/` NDJSON을 Grep/Read로 뒤지지 말 것 — 실측 4회
    반복된 도피 경로이고, 이 도구는 인덱스에서 수십 ms에 답한다.
    """
    profile = _describe_type(type, field=field)
    return {
        "type": profile.type,
        "total": profile.total,
        "korean_effect_pct": profile.korean_effect_pct,
        "verification": [{"label": lab, "count": n} for lab, n in profile.verification],
        "top_tags": [{"tag": t, "count": n} for t, n in profile.top_tags],
        "fields": [
            {
                "field": f.field,
                "count": f.count,
                "pct": f.pct,
                "value_types": list(f.value_types),
                "samples": list(f.samples),
            }
            for f in profile.fields
        ],
    }


@tool
def find_by_value(
    path: str,
    type: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    ids: list[str] | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    """`data` 안의 **수치로** 후보를 찾는다 — `search_kb`(텍스트)로는 닿지 않는 축.

    쓸 때: 자원이 얼마 남았고 **그 안에 들어가는 것**을 찾을 때.
    예) 정신력 40 잔여 → `find_by_value("reservation.max", type="Skill", maximum=40)`
        코스트 상한   → `find_by_value("cost.max", type="Skill", maximum=25)`

    `path`는 `data` 아래의 점 표기다. 리스트를 만나면 원소마다 갈라진다
    (`reservation.max` → `reservation[0].max`, `[1].max`, …). 어떤 경로가 있는지는
    `describe_type`의 필드 목록에서 본다.

    `ids`를 주면 **그 집합 안에서만** 찾는다 — "내 트리 112개 노드 중 이 필드를 가진
    것은?" 같은 조인이다. `minimum`·`maximum`을 생략하면 **필드를 가졌는지**만 본다
    (값 필터 없이 존재 검사). 예) `find_by_value("attribute_choice.value",
    ids=[내 트리 노드 id들])` → 능력치 택1 노드만 걸러낸다.

    값 오름차순으로만 낸다 — **순위나 적합성 판단은 하지 않는다**(AD-3).
    """
    return [
        {
            "id": h.id,
            "name_ko": h.name_ko,
            "name_en": h.name_en,
            "path": h.path,
            "value": h.value,
        }
        for h in _find_by_value(
            path, type_=type, minimum=minimum, maximum=maximum, ids=ids, limit=limit
        )
    ]


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
restore_pob_spec = tool(_build.restore_pob_spec)
measure_leverage = tool(_build.measure_leverage)

# 설계 루프 (P4.5, D26~D28)
check_constraints = tool(_constraints.check_constraints)
evaluate_objective = tool(_constraints.evaluate_objective)
parse_design_doc = tool(_constraints.parse_design_doc)
list_builds = tool(_constraints.list_builds)
compute_trigger_rate = tool(_constraints.compute_trigger_rate)

# 트리 최적화 도구 (P4) — tools/tree.py
connect_anchors = tool(_tree.connect_anchors)
optimize_tree = tool(_tree.optimize_tree)
measure_tree_slack = tool(_tree.measure_tree_slack)
evaluate_bundles = tool(_tree.evaluate_bundles)
evaluate_change_bundle = tool(_tree.evaluate_change_bundle)
optimize_items = tool(_tree.optimize_items)
optimize_rare = tool(_tree.optimize_rare)
list_implicits = tool(_tree.list_implicits)
optimize_runes = tool(_tree.optimize_runes)
find_clusters = tool(_tree.find_clusters)
passed_over_nodes = tool(_tree.passed_over_nodes)
suggest_anchors = tool(_tree.suggest_anchors)

# 능동 탐사 (P5) — tools/explore.py. 후보 생성만, 판정은 사람 게이트
scan_synergies = tool(_explore.scan_synergies)
discover_mechanics = tool(_explore.discover_mechanics)
find_hypotheses = tool(_explore.find_hypotheses)
# 담체↔페이로드 — 문구가 아니라 PoB 타입 시스템에서 나오는 발산 재료
find_carriers = tool(_explore.find_carriers)
find_payloads = tool(_explore.find_payloads)
# 스택 축 공급 그래프 (#91) — 「이 스탯은 어디로 흘러가나」, 사슬·순환 후보
scan_supply_edges = tool(_explore.scan_supply_edges)
trace_chains = tool(_explore.trace_chains)


def main() -> None:
    # stdio가 곧 JSON-RPC 채널이고 MCP는 UTF-8을 요구한다 — Windows 기본
    # 코드페이지로는 KB의 한글·기호가 그대로 나가지 못한다.
    force_utf8_stdio()
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
