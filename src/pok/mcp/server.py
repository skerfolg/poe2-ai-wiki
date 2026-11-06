"""PoK MCP 서버 — KB 조회 도구 (P2, D6/AD-4).

얇은 어댑터: 모든 실질 로직은 `pok.index`(FTS5 + self-healing)에 있고, 여기는
도구 서명·토큰 예산(D14 2단계)만 관리한다. 판단·상태를 쌓지 말 것(AGENTS.md).

  search_kb  1단계 — 압축 히트 (id·이름·태그·검증 라벨만)
  get_entry  2단계 — 선별 상세 (fields로 필요한 필드만, 서술은 요청 시)
  related    관계 순회 — 정방향(정본) + 역방향(인덱스 생성) typed edges
  compute_pob / evaluate_delta / check_item_legality / assemble_pob
             빌드·계산 (P3, tools/build.py — PoB 오라클·RC4 검증·기록)

실행: PYTHONPATH=src python -m pok.mcp   (stdio)
등록: README.md의 Claude/Codex 설정 절차 (Codex: scripts/configure_codex.py).
"""

from __future__ import annotations

import copy
import functools
import hashlib
import inspect
import json
import re
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
from fastmcp.tools.base import ToolResult
from fastmcp.tools.function_tool import FunctionTool
from mcp.types import CallToolResult, TextContent

from pok.artifacts import tool_results
from pok.artifacts.design_record import FORMAT as _DESIGN_FORMAT
from pok.artifacts.design_record import canonical_bytes
from pok.artifacts.design_record import record_schema as _design_schema
from pok.common import telemetry
from pok.common.execution import checkpoint, current_execution
from pok.common.paths import knowledge_dir, runtime_paths
from pok.common.stdio import force_utf8_stdio
from pok.engine import design_service as _design_service
from pok.engine import document_selection as _document_selection
from pok.engine import pob_documents as _pob_documents
from pok.engine.execution_requests import RequestExecutionError, RequestManager
from pok.engine.measurement_provenance import (
    compare_observations,
    observe_loaded_execution,
    observe_sources,
)
from pok.index.describe import describe_kb as _describe_kb
from pok.index.describe import describe_type as _describe_type
from pok.index.describe import find_by_value as _find_by_value
from pok.index.search import diagnose_empty as _diagnose_empty
from pok.index.search import get_entry as _get_entry
from pok.index.search import get_insight as _get_insight
from pok.index.search import get_variant_pool as _get_variant_pool
from pok.index.search import related as _related
from pok.index.search import search as _search
from pok.index.search import search_insights as _search_insights
from pok.mcp.tools import build as _build
from pok.mcp.tools import constraints as _constraints
from pok.mcp.tools import explore as _explore
from pok.mcp.tools import tree as _tree
from pok.pob.runner import _META_PROTOCOL as _POB_META_PROTOCOL


def _git_head(root: Path) -> tuple[str, str]:
    """(짧은 커밋, 제목). 실패해도 세션을 막지 않는다."""
    import subprocess
    import tempfile

    # Windows subprocess.run(timeout=...) drains captured pipes after killing
    # the parent. A descendant retaining an output handle can make that drain
    # unbounded. Identity discovery must work even while diagnosing this failure.
    try:
        with tempfile.TemporaryFile() as output:
            result = subprocess.run(
                [
                    "git",
                    "-c",
                    f"safe.directory={root.resolve().as_posix()}",
                    "-C",
                    str(root),
                    "log",
                    "-1",
                    "--format=%h%n%s",
                ],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=5,
                check=False,
            )
            if result.returncode != 0:
                return "", ""
            output.seek(0)
            lines = output.read(8192).decode("utf-8", errors="replace").splitlines()
        if len(lines) < 2:
            return "", ""
        return lines[0].strip(), lines[1].strip()
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
        "그리고 **크기를 말하기 전에 scan_scalers**로 분해할 것 — 「X당 Y」는 "
        "곱연산(more)·가산(increased)·횟수·게이지·반경이 뒤섞여 있고, 상한·프록시 "
        "귀속·획득 불가(unused)까지 봐야 배율을 오독하지 않는다. "
        "레코드의 verification 라벨(GAME_DATA > "
        "POB_CODE ≈ IN_GAME > SUPPORTED_INFERENCE > UNVERIFIED, CONTRADICTED=모순 "
        "경고)을 판단 신뢰도에 반영할 것."
    ),
)

_FRONT_ID = re.compile(r"^id:\s*(\S+)$", re.M)

#: 도구 이름 → 파라미터 지문(정렬). **등록 시점에 동기로** 채운다 (#150).
#:
#: `server_info`가 `asyncio.run(mcp.list_tools())`로 등록부를 읽었는데, FastMCP는 동기
#: 도구를 **워커 스레드**에서 돌리므로 그 안에서 `asyncio.run`은 새 루프를 띄워 서버
#: 루프에 묶인 코루틴을 기다렸다 — 스탠드얼론에선 0.0초, 서버 안에선 **영원히**
#: 안 돌아왔다(실측 2026-09-09: 1800초 무응답 뒤 중단). 폴백의 `ThreadPoolExecutor`
#: `with` 블록은 `shutdown(wait=True)`라 `timeout=10`이 아무것도 못 풀었다. stale 탐지기가
#: 자기 자신을 못 쓰는 꼴이었다. 지문은 FastMCP가 스키마를 만드는 **같은 경로**
#: (`FunctionTool.from_function`)에서 뽑으므로 주입 인자(`Context`)가 빠지는 것까지 같다 —
#: 둘의 일치는 `tests/unit/test_mcp_server_info.py`가 잠근다.
_TOOL_PARAMS: dict[str, list[str]] = {}
_WIRE_RESULT_BYTES = 16_000
_REQUESTS = RequestManager(persist=True)
_REQUEST_TIMEOUT_S = 600.0
_SEARCH_TOOLS = frozenset(
    {
        "optimize_tree",
        "optimize_items",
        "optimize_rare",
        "optimize_runes",
        "evaluate_bundles",
    }
)
_SINGLE_CALC_TOOLS = frozenset({"compute_pob", "compute_pob_document"})
_EXECUTION_CONTROLS = frozenset(
    {
        "get_execution_status",
        "cancel_execution",
        "read_execution_result",
        "recover_execution",
    }
)


def _execution_budget(tool_name: str, options: dict[str, Any], arguments: dict[str, Any]) -> float:
    default, maximum = (
        (300.0, 1200.0)
        if tool_name in _SEARCH_TOOLS
        else (
            (180.0, 180.0)
            if tool_name in _SINGLE_CALC_TOOLS
            else (_REQUEST_TIMEOUT_S, _REQUEST_TIMEOUT_S)
        )
    )
    requested = options.get("timeout_s")
    internal = arguments.get("time_budget_s") if tool_name in _SEARCH_TOOLS else None
    for value in (requested, internal):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not 0 < value <= maximum
        ):
            raise ValueError(
                f"{tool_name} timeout must be positive and at most {maximum:g} seconds"
            )
    limits = [float(value) for value in (requested, internal) if value is not None]
    return min(limits) if limits else default


def _wire_json(result: ToolResult) -> str:
    """Use the actual MCP encoding, including nonfinite numbers becoming null."""
    wire = CallToolResult(
        content=result.content,
        structuredContent=result.structured_content,
        isError=result.is_error,
        _meta=result.meta,
    )
    return wire.model_dump_json(by_alias=True, exclude_none=True)


def _wire_size(result: ToolResult) -> int:
    """Count both MCP copies (text and structured JSON), including escaping."""
    return len(_wire_json(result).encode("utf-8"))


def tool[F: Callable[..., Any]](fn: F, *, literal_arguments: frozenset[str] = frozenset()) -> F:
    """도구를 등록하면서 호출 이력을 남긴다.

    무개입 테스트에서는 구조 세션이 생성 과정을 못 본다 — 도구가 스스로 남겨야
    결함 보고가 사람의 기억에 의존하지 않는다. 빈 결과(조회 0건)도 남기는 게
    핵심이다: 그건 실패가 아니라 KB 갭이거나 표기 오류라는 **신호**다(B-1 실측).

    `functools.wraps`로 시그니처를 보존해야 FastMCP가 스키마를 만든다.
    """

    unknown_literals = literal_arguments - inspect.signature(fn).parameters.keys()
    if unknown_literals:
        raise ValueError(f"Unknown literal tool arguments: {sorted(unknown_literals)}")

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

    # Direct Python calls retain the original return value. Only the registered
    # MCP boundary expands references and stores oversized wire responses.
    schema = FunctionTool.from_function(wrapper)

    @functools.wraps(fn)
    def wire_wrapper(*args: Any, **kwargs: Any) -> Any:
        checkpoint()
        wire_limit = _WIRE_RESULT_BYTES - (512 if current_execution() is not None else 0)
        bound = inspect.signature(fn).bind(*args, **kwargs)
        bound.apply_defaults()
        for name, value in list(bound.arguments.items()):
            if name != "ctx" and name not in literal_arguments and isinstance(value, dict | list):
                bound.arguments[name] = tool_results.resolve_references(value)
        inputs = copy.deepcopy(
            {name: value for name, value in bound.arguments.items() if name != "ctx"}
        )
        measurement = fn.__name__ in {"compute_pob", "evaluate_delta", "compute_pob_document"}
        observed_before = observe_sources() if measurement else None
        loaded_before = observe_loaded_execution(entrypoint=wire_wrapper) if measurement else None
        result = wrapper(*bound.args, **bound.kwargs)
        observation = (
            compare_observations(observed_before, observe_sources())
            if observed_before is not None
            else None
        )
        converted = schema.convert_result(result)
        wire_json = _wire_json(converted)
        checkpoint()
        if not measurement and len(wire_json.encode("utf-8")) <= wire_limit:
            return converted
        # Save the logical JSON that the original MCP boundary actually sends,
        # not its pre-serialization Python object (which can contain inf/NaN).
        wire = json.loads(wire_json)
        nonstandard_json: dict[str, str] = {}
        wrapped = (schema.output_schema or {}).get("x-fastmcp-wrap-result") is True
        logical_result = wire.get("structuredContent")
        if logical_result is not None:
            if wrapped:
                logical_result = logical_result["result"]
        else:
            # Unstructured ordinary JSON/text returns use FastMCP's text copy.
            text = wire["content"][0]["text"]

            def nonfinite(token: str) -> None:
                # Untyped FastMCP content can contain Infinity/NaN literals.
                # Preserve that exact text as source, but references must be
                # standard JSON just like typed structured results.
                nonstandard_json["unstructured_json_text"] = text

            logical_result = (
                text if isinstance(result, str) else json.loads(text, parse_constant=nonfinite)
            )
        checkpoint()
        manifest = tool_results.store_result(
            fn.__name__,
            inputs,
            logical_result,
            source={
                "module": fn.__module__,
                "function": fn.__qualname__,
                "loaded_commit": _LOADED_COMMIT,
                **({"source_observation": observation} if observation is not None else {}),
                **(
                    {
                        "loaded_execution_observation": {
                            "before": loaded_before,
                            "after": observe_loaded_execution(entrypoint=wire_wrapper),
                            "scope": "observed_memory_components_not_full_execution_certification",
                        }
                    }
                    if loaded_before is not None
                    else {}
                ),
                **nonstandard_json,
            },
        )
        # Bind the receipt to the result before adding its own reference. This
        # avoids recursive hashes and leaves the measured payload unchanged.
        measurement_ref = {"$pok_result": manifest["id"], "path": "/result"}
        if measurement and isinstance(logical_result, dict):
            public = {**logical_result, "measurement_ref": measurement_ref}
            public_result = schema.convert_result(public)
            if _wire_size(public_result) <= wire_limit:
                return public_result
        envelope = tool_results.notice(manifest, logical_result)
        if (
            fn.__name__ == "update_design_record"
            and isinstance(logical_result, dict)
            and ("change_summary" in logical_result)
        ):
            envelope["change_summary"] = logical_result["change_summary"]
            envelope["change_details"] = {
                key: {"$pok_result": manifest["id"], "path": "/result/" + key}
                for key in ("changed_decision_ids", "review_required_ids", "current_assessment")
            }
        if measurement:
            envelope["measurement_ref"] = measurement_ref
        if nonstandard_json:
            envelope["normalization"] = {
                "nonfinite_numbers": "null",
                "original_text_ref": {
                    "$pok_result": manifest["id"],
                    "path": "/source/unstructured_json_text",
                },
            }
        bounded = ToolResult(
            content=envelope,
            structured_content={"result": envelope} if wrapped else envelope,
            meta={"fastmcp": {"wrap_result": True}} if wrapped else None,
        )
        if _wire_size(bounded) > wire_limit:
            raise ValueError("Tool-result handoff exceeds the MCP wire budget")
        return bounded

    # A list-returning tool keeps its original small-result wrapper. Its declared
    # schema additionally permits the reference envelope for a large response.
    output_schema = schema.output_schema
    if output_schema is not None:
        envelope_schema = {
            "type": "object",
            "required": ["stored_tool_result"],
            "properties": {"stored_tool_result": {"const": True}},
        }
        if output_schema.get("x-fastmcp-wrap-result"):
            properties = output_schema.get("properties", {})
            output_schema = {
                **output_schema,
                "properties": {
                    **properties,
                    "result": {"anyOf": [properties["result"], envelope_schema]},
                },
            }
        else:
            output_schema = {
                "type": "object",
                "anyOf": [output_schema, envelope_schema],
                **({"$defs": output_schema["$defs"]} if "$defs" in output_schema else {}),
            }
    _TOOL_PARAMS[schema.name] = sorted((schema.parameters or {}).get("properties", {}))

    @functools.wraps(fn)
    async def supervised_wrapper(*args: Any, **kwargs: Any) -> Any:
        if fn.__name__ in _EXECUTION_CONTROLS:
            # Control requests must remain available while a target is stopping.
            import asyncio

            return await asyncio.to_thread(wire_wrapper, *args, **kwargs)
        context = get_context()
        owner = f"{context.session_id}/{context.request_id}"
        metadata = context.request_context.meta if context.request_context is not None else None
        options = metadata.model_dump().get("pok_execution", {}) if metadata is not None else {}
        if not isinstance(options, dict) or set(options) - {"request_id", "timeout_s"}:
            raise ValueError("Unsupported pok_execution request metadata")
        arguments = {key: value for key, value in _named(fn, args, kwargs).items() if key != "ctx"}
        timeout = _execution_budget(fn.__name__, options, arguments)
        revision = "sha256:" + hashlib.sha256(canonical_bytes(arguments)).hexdigest()

        def encode_result(value: ToolResult, execution_ref: dict[str, str]) -> str:
            value.meta = {**(value.meta or {}), "pok_execution": execution_ref}
            if _wire_size(value) > _WIRE_RESULT_BYTES:
                raise ValueError("Execution result exceeds the reserved MCP wire budget")
            return _wire_json(value)

        try:
            result, reference = await _REQUESTS.run(
                functools.partial(wire_wrapper, *args, **kwargs),
                owner=owner,
                tool=fn.__name__,
                timeout_s=float(timeout),
                request_id=options.get("request_id"),
                input_revision=revision,
                request_json=canonical_bytes(arguments).decode("utf-8"),
                result_encoder=encode_result,
            )
        except RequestExecutionError as stopped:
            status = _REQUESTS.status(stopped.reference)
            details = (status.get("error") or {}).get("details", {})
            partial = details.get("tree_search_checkpoint")
            if fn.__name__ != "optimize_tree" or not isinstance(partial, dict):
                raise
            if partial.get("format") != "pok.tree-search-checkpoint.v1":
                raise
            # This remains a failed/incomplete request. Expose recovery rather
            # than silently discarding an independently measured prior input.
            return ToolResult(
                content=[
                    TextContent(
                        type="text",
                        text=f"{stopped}; a measured partial tree is available via "
                        "get_execution_status. "
                        "It is not a completed search or a recommendation.",
                    )
                ],
                structured_content={
                    "format": "pok.interrupted-search.v1",
                    "ok": False,
                    "state": status["state"],
                    "result_available": False,
                    "execution_ref": stopped.reference,
                    "partial_checkpoint": {
                        "status_tool": "get_execution_status",
                        "status_arguments": {"execution_ref": stopped.reference},
                        "path": "/error/details/tree_search_checkpoint",
                        "claim": "measured_partial_not_complete_or_recommended",
                    },
                    "finished_checkpoint_ref": status["persistence"]["finished_ref"],
                },
                is_error=True,
                meta={"pok_execution": stopped.reference},
            )
        result.meta = {**(result.meta or {}), "pok_execution": reference}
        if _wire_size(result) > _WIRE_RESULT_BYTES:
            raise ValueError("Execution result exceeds the reserved MCP wire budget")
        return result

    mcp.tool(supervised_wrapper, output_schema=output_schema)
    return wrapper  # type: ignore[return-value]


@tool
def get_execution_status(execution_ref: dict[str, Any]) -> dict[str, Any]:
    """Inspect one process-local request. Missing history never means completed."""
    return _REQUESTS.status(execution_ref)


@tool
def cancel_execution(execution_ref: dict[str, Any]) -> dict[str, Any]:
    """Request cooperative cancellation; inspect worker/resource confirmation separately."""
    return _REQUESTS.cancel(execution_ref)


@tool
def recover_execution(execution_ref: dict[str, Any]) -> dict[str, Any]:
    """Verify saved request/result checkpoints from this or an older server.

    Nonterminal evidence does not prove a worker stopped. Never replay an
    operation, adopt a build, or terminate a historical PID here.
    """
    return _REQUESTS.recover(execution_ref)


@tool
def read_execution_result(execution_ref: dict[str, Any]) -> dict[str, Any]:
    """Recover a completed wire result while its server incarnation retains it."""
    return {
        "execution": _REQUESTS.status(execution_ref),
        "wire_result": json.loads(_wire_json(_REQUESTS.result(execution_ref))),
    }


def create_design_record(design_id: str, goal: str) -> dict[str, Any]:
    """Create an immutable pre-PoB design record with automatic evidence inspection.

    Preserve record_json as text or use record_ref; do not reserialize it in JS.
    The caller owns the current reference. No build choices are made here.
    """
    return _design_service.create_design(design_id, goal)


create_design_record = tool(create_design_record)


def capture_design_material(
    build_spec: dict[str, Any] | None = None,
    build_code: str | None = None,
    xml_text: str | None = None,
    metadata_ref: dict[str, Any] | None = None,
    selection: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Snapshot explicit spec/XML/metadata as immutable schema-valid material refs.

    Supply a spec and/or one XML source (build_code or xml_text). metadata_ref
    accepts an existing artifact_id/name/sha256 blob; media_type is optional.
    All component hashes, media types and material revision are generated here.
    Pass returned material to update_design_record with op='set_material'.
    This preserves raw inputs; it does not choose sets or certify equivalence.
    """
    return _design_service.capture_material(
        build_spec=build_spec,
        build_code=build_code,
        xml_text=xml_text,
        metadata_ref=metadata_ref,
        selection=selection,
    )


capture_design_material = tool(
    capture_design_material, literal_arguments=frozenset({"metadata_ref", "selection"})
)


@tool
def select_pob_document_effect(
    xml_ref: dict[str, Any],
    expected_revision: str,
    document_measurement_ref: dict[str, Any],
    active_index: int,
    stat_set_index: int | None = None,
    native_timeout_s: float = 180,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Select an observed effect/mode on this exact XML, then remeasure the candidate.

    active_index indexes native effects, not gem slots. Modes must occur in the
    document-bound observation. Unmapped/reindexed/item-generated groups fail
    before editing. MAIN only: CALCS, comments and inactive data remain intact.
    native_selection_matched verifies this selection, not game feasibility or
    execution identity. Failure retains the candidate and an immutable report.
    """
    return _document_selection.select_effect(
        xml_ref,
        expected_revision,
        document_measurement_ref,
        active_index,
        stat_set_index,
        native_timeout_s=native_timeout_s,
        use_cache=use_cache,
    )


@tool
def compute_pob_document(
    xml_ref: dict[str, Any],
    stats: list[str] | None = None,
    native_timeout_s: float = 180,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Calculate exactly the verified XML bytes and store a document-bound native receipt.

    No BuildSpec reconstruction or implicit set selection occurs. stats=['*']
    returns all values; [] returns observation only. The immutable receipt keeps
    all native stats and the exact XML regardless of this response filter.
    native_timeout_s limits the native subprocess, not the whole request lifetime.
    Execution identity/game feasibility remain unverified.
    """
    return _pob_documents.measure_document(
        xml_ref,
        stats=list(_build.DEFAULT_STATS) if stats is None else stats,
        native_timeout_s=native_timeout_s,
        use_cache=use_cache,
    )


@tool
def read_pob_document_measurement(
    document_measurement_ref: dict[str, Any], xml_ref: dict[str, Any]
) -> dict[str, Any]:
    """Verify a complete native measurement bundle belongs to exactly this XML.

    The result binds document bytes and observations. It does not certify engine
    execution identity, game legality, or a new document edited afterwards.
    """
    return _pob_documents.load_document_measurement(document_measurement_ref, xml_ref)


@tool
def read_pob_document(xml_ref: dict[str, Any]) -> dict[str, Any]:
    """Read exact verified XML text; large source is returned through result paging.

    This is byte integrity, not native calculation or game validation.
    """
    return _pob_documents.read_document(xml_ref)


@tool
def prepare_pob_delivery(
    xml_ref: dict[str, Any],
    code_ref: dict[str, Any] | None = None,
    include_code: bool = False,
) -> dict[str, Any]:
    """Publish an exact XML/code bundle for file delivery instead of model transcription.

    References require artifact_id/name/sha256. A supplied code must decode to
    the exact XML or fail; it is never silently repaired. Omit code_ref to encode
    the XML directly. include_code is for direct machine consumption, not prose
    recopying. This checks transport bytes, not game feasibility or build quality.
    """
    return _pob_documents.prepare_delivery(xml_ref, code_ref=code_ref, include_code=include_code)


@tool
def inspect_pob_document(
    xml_ref: dict[str, Any], tag: str | None = None, offset: int = 0, limit: int = 20
) -> dict[str, Any]:
    """Inspect raw XML nodes, with stable element paths under the returned revision.

    Paths count element children only. raw_attributes retain exact attribute
    tokens for compare-and-set edits; attributes are standard XML decoded values.
    This does not calculate or validate the build in-game.
    """
    return _pob_documents.inspect_document(xml_ref, tag=tag, offset=offset, limit=limit)


def edit_pob_document(
    xml_ref: dict[str, Any], expected_revision: str, changes: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply explicit XML edits as one immutable child document.

    Each change requires path, tag, attribute, expected_raw_value and value.
    op defaults to set_attribute. upsert_child_attribute additionally requires
    child_tag, identity_attribute and identity_value, matching one direct child.
    set_text edits a leaf body using path/tag/expected_raw_value/value, with no
    attribute field. inspect_pob_document supplies its exact raw_text token.
    Only selected value spans change; comments/unknown/inactive sections remain.
    A conflict publishes nothing. This does not rebind an old spec or sidecar;
    inspect/measure the new document before treating old evidence as current.
    """
    return _pob_documents.edit_document(xml_ref, expected_revision, changes)


edit_pob_document = tool(edit_pob_document, literal_arguments=frozenset({"changes"}))


@tool
def get_design_record_schema() -> dict[str, Any]:
    """Return the runtime design-record schema for explicit edits and client validation.

    Schema validity alone is not revision integrity, evidence verification, or
    in-game feasibility. Preserve sealed record_json as text across JS clients.
    """
    return _design_schema()


def read_design_record(record_ref: dict[str, Any]) -> dict[str, Any]:
    """Verify checkpoint bytes and inspect current evidence; return sealed JSON and Markdown.

    Historical structural assessment is separate from current_assessment.
    Neither assessment certifies in-game feasibility or XML/spec equivalence.
    """
    return _design_service.read_design(record_ref)


read_design_record = tool(read_design_record, literal_arguments=frozenset({"record_ref"}))


def inspect_design_record(record_ref: dict[str, Any]) -> dict[str, Any]:
    """Verify a checkpoint and inspect current evidence without returning its full document."""
    return _design_service.inspect_design(record_ref)


inspect_design_record = tool(inspect_design_record, literal_arguments=frozenset({"record_ref"}))


@tool
def list_design_records(
    design_id: str | None = None, offset: int = 0, limit: int = 20
) -> dict[str, Any]:
    """Find verified immutable design checkpoints without selecting a current head.

    Pagination counts artifact directories, including legacy/nonmatching entries.
    Follow next_offset even for an empty records page. Listing verifies stored
    bytes, not current evidence; use inspect_design_record for a fresh inspection.
    """
    return _design_service.list_designs(design_id=design_id, offset=offset, limit=limit)


def import_design_document(
    design_id: str,
    document_text: str | None = None,
    source_ref: dict[str, Any] | None = None,
    goal: str | None = None,
) -> dict[str, Any]:
    """Preserve legacy source and create an unclassified design record with inspection.

    Supply exactly one: literal document_text (UTF-8), or source_ref with
    artifact_id/name/sha256 for exact stored bytes. No filesystem path is accepted.
    Legacy confirmed text never automatically becomes a user-fixed decision.
    """
    return _design_service.import_design(
        design_id, document_text=document_text, source_ref=source_ref, goal=goal
    )


import_design_document = tool(import_design_document, literal_arguments=frozenset({"source_ref"}))


def update_design_record(
    record_ref: dict[str, Any],
    expected_revision: str,
    changes: list[dict[str, Any]],
    user_decisions: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply explicit edits as a child checkpoint and automatically inspect evidence.

    A stale expected_revision fails. Existing checkpoints remain immutable.
    user_decisions records caller-reported decisions, not authenticated consent.
    Embedded evidence references in changes stay literal and are inspected as data.
    """
    return _design_service.update_design(
        record_ref, expected_revision, changes, user_decisions=user_decisions
    )


update_design_record = tool(
    update_design_record,
    literal_arguments=frozenset({"record_ref", "changes", "user_decisions"}),
)


def attach_pob_document_measurement(
    record_ref: dict[str, Any],
    expected_revision: str,
    document_measurement_ref: dict[str, Any],
    evidence_id: str,
    label: str,
    description: str,
    path: str = "/stats",
    usage: str = "current",
    material_revision: str | None = None,
    decision_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Link verified XML measurement evidence as an immutable design revision.

    Current usage requires the current XML and compatible native selection.
    Comparison/historical usage requires the original material_revision.
    This does not certify game feasibility or loaded execution identity.
    """
    return _design_service.link_document_measurement(
        record_ref,
        expected_revision,
        document_measurement_ref,
        evidence_id=evidence_id,
        label=label,
        description=description,
        path=path,
        usage=usage,
        material_revision=material_revision,
        decision_ids=decision_ids or (),
    )


attach_pob_document_measurement = tool(
    attach_pob_document_measurement,
    literal_arguments=frozenset({"record_ref", "document_measurement_ref"}),
)


def _named(fn: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    """위치 인자까지 이름을 붙여 기록한다 — 재현하려면 이름이 있어야 한다."""
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return dict(bound.arguments)
    except (TypeError, ValueError):
        return {"args": list(args), **kwargs}


@tool
def get_tool_result(
    result_id: str,
    path: str = "/result",
    offset: int = 0,
    limit: int = 20,
    mode: str = "entries",
) -> dict[str, Any]:
    """Read a saved tool result by JSON pointer, with bounded complete JSON pages.

    Entries include exact value_ref objects for large children. mode='json'
    recovers any entire subtree as chunks; follow next_offset until null.
    A reference can be used inside dict inputs without transcribing its contents:
    {"$pok_result": id, "path": "/inputs/variants/x", "overrides": {
      "derived_from": {"$pok_result": id, "path": "/result/variant_reviews/x/derived_from"}}}.
    Overrides replace only explicitly named top-level fields. References do not
    add freshness, measurement, selection, or recommendation status.
    """
    return tool_results.read_page(result_id, path, offset, limit, mode)


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
    for key in ("locked_to", "requires_nodes", "excluded_by_unlock", "pob_gap", "carrier_unknown",
                "acquisition", "passive_kind"):
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
    category: str | None = None,
    sub_type: str | None = None,
    acquisition: str | None = None,
) -> list[dict[str, Any]]:
    """KB 검색 (1단계 — 압축 히트). type은 Skill|Support|Passive|Item|Modifier|
    Resource|Mechanic|Defence, tags는 게임 공식 태그(소문자). 상세는 get_entry로.

    acquisition은 Passive 획득 경로 필터다. anoint-only=일반 트리 연결로 찍을 수 없는 성유 후보,
    anointable=일반 성유 가능, anoint=둘의 합집합이다. query 없이 전량 조회할 수 있고
    주얼 홈도 포함한다. acquisition/passive_kind로 구분한 뒤 get_entry로 제약을 읽는다.
    anoint-only는 과대망상 등 다른 아이템의 부여까지 금지한다는 뜻은 아니다.

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
    ⛔ "획득 불가"가 아니라 **"확인 못 함"**이다 — 담체를 확인한 뒤에 근거로 쓸 것.

    **`category`·`sub_type` = 속성으로 열거하는 축**(#147). Item의 `tags`는 **비어
    있어서** 부위를 물을 경로가 tags엔 없다 — 분류는 `category`(`boots`·`helmet`·
    `body`·`shield` … 29종)와 `sub_type`(`Evasion/Energy Shield`·`Armour/Evasion` …
    14종)에 있다. 대소문자는 접어서 대조하므로 `describe_type`이 보여 준 표기를
    그대로 넣으면 된다.
    ⚠ **이름 토큰으로 훑지 말 것**: 실측 2026-09-09, `query="Boots"`로 16종을 보고
    「신발에는 회피/ES 듀얼 베이스가 없다」고 판정했는데 실제로는 `category="boots"`가
    **217건**이고 이름군이 Boots(회피)·Sandals(ES)·Greaves(방어도)로 갈려 있었다.
    0건이면 알아챘겠지만 **그럴듯한 부분집합**이 나와서 갭이 안 보였다."""
    # 획득 경로는 FTS 문구가 아니다. 전용 주얼 홈도 포함하며 트리 거리를 요구하지 않는다.
    # anoint = 전체, anoint-only = 전용, anointable = 일반 트리의 성유 가능 노드.
    hits = _search(
        query=query,
        tags=tags,
        type_=type,
        ascendancy=ascendancy,
        limit=limit,
        for_ascendancy=for_ascendancy,
        category=category,
        sub_type=sub_type,
        acquisition=acquisition,
    )
    if hits:
        return [_hit_dict(h) for h in hits]
    # 0건이면 **왜 비었는지**를 함께 낸다. 빈 배열은 아무것도 말하지 않아서, 실측
    # 2026-08-05에 세션이 9번 모두 "KB에 없다"로 오판하고 파일 탐색으로 도피했다 —
    # 실제로는 한글 효과 문구·type 오해·AND 매칭 때문이었다.
    diag = _diagnose_empty(
        query=query,
        tags=tags,
        type_=type,
        ascendancy=ascendancy,
        category=category,
        sub_type=sub_type,
        acquisition=acquisition,
    )
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
    include_narrative=True면 자체 재작성 서술 문서(있을 때)를 함께 반환.

    **아이템이 부여하는 Skill에는 `granted_instance`가 fields와 무관하게 붙는다**
    (#167). 부여 인스턴스는 젬과 **별개**다 — 같은 스킬 젬을 직접 등록한 것과
    **중복해서** 돌고(부재 목걸이 Cast on Dodge + 젬 Cast on Dodge = 2개), 목걸이
    베이스가 주는 것은 **정신력을 점유하지 않는다**. 레코드의 `reservation`은 젬
    인스턴스의 값이다. 부여원은 `granted_by`(불완전)가 아니라 아이템 문구에서 뽑는다."""
    record = _get_entry(id, fields=fields)
    if include_narrative:
        doc = _narrative_index(knowledge_dir()).get(id)
        if doc is not None:
            record["narrative"] = doc.read_text(encoding="utf-8")
    return record


@tool
def get_variant_pool(
    route: str = "vaal-orb-mutated-unique",
    query: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """함양 공용 변이 풀을 조회한다. query는 이름/효과 부분문자열(영문 권장).

    특정 아이템 전용 목록이 아니다. 적용 가능성·교체 대상·공존과 롤은 별도 검증한다.
    get_entry로 선택한 Modifier의 수치/출처를 읽는다. 페이지 순서는 적합성 순위가 아니다.
    """
    return _get_variant_pool(route=route, query=query, offset=offset, limit=limit)


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


def _server_capabilities() -> dict[str, Any]:
    return {
        "runtime_storage": {
            "data_home_env": "POK_DATA_HOME",
            "data_home_layout": "artifacts_subdirectory",
            "cache_home_env": "POK_CACHE_HOME",
            "cache_home_layout": "directory_itself",
            "absolute_paths_required": True,
            "explicit_root_precedence": True,
            "unset_layout": "project_artifacts_and_var",
        },
        "explicit_calculation": {
            "tool": "compute_pob",
            "argument": {"input_policy": "explicit"},
            "contract_version": 2,
            "procedure_deficits": "reported_not_blocking",
            "automatic_completion": False,
            "recommendation_checked": False,
            "legacy_default_preserved": True,
        },
        "explicit_assembly": {
            "tool": "assemble_pob",
            "argument": {"input_policy": "explicit"},
            "automatic_item_replacement": False,
            "attribute_choices_required": True,
            "legality_and_native_checks_preserved": True,
            "legacy_default_preserved": True,
        },
        "comparison_recommendation": {
            "contract_version": 2,
            "evidence": "saved_evaluate_delta_result_id",
            "scope": "declared_components_and_compared_candidates",
            "input_binding": "selected_signatures_and_config",
            "final_design_record_required": True,
            "design_reference_field": "optimization_contract.design_ref",
            "adopted_pending_review": "blocking",
            "game_feasibility_certified": False,
            "global_optimum_proven": False,
        },
        "calculator_cache": {
            "format": "pok.pob-cache.v2",
            "binding": "xml_protocol_loaded_adapter_code_and_observed_calculator_content",
            "unavailable_observation": "cache_disabled",
            "changed_during_calculation": "not_published",
            "loaded_native_modules": "not_verified",
            "external_system_libraries": "not_verified",
        },
        "daemon_startup_observation": {
            "format": "pok.daemon-startup-observation.v1",
            "result_field": "meta.daemon_execution",
            "inspect_tool": "inspect_pob_runtime",
            "scope": "shared_daemon_only_for_inspection",
            "starts_process_for_inspection": False,
            "loaded_native_modules": "not_verified",
        },
        "request_execution": {
            "format": "pok.execution-ref.v1",
            "server_instance": _REQUESTS.instance,
            "request_metadata": "_meta.pok_execution",
            "default_timeout_s": _REQUEST_TIMEOUT_S,
            "maximum_timeout_s": 1200.0,
            "default_timeout_scope": "generic_fallback_only_see_profiles",
            "budget_profiles": {
                "single_calculation": {
                    "tools": sorted(_SINGLE_CALC_TOOLS),
                    "default_s": 180,
                    "maximum_s": 180,
                },
                "selective_search": {
                    "tools": sorted(_SEARCH_TOOLS),
                    "default_s": 300,
                    "maximum_s": 1200,
                },
                "generic": {"default_s": _REQUEST_TIMEOUT_S, "maximum_s": _REQUEST_TIMEOUT_S},
            },
            "cleanup_grace_s": _REQUESTS.cleanup_grace_s,
            "status_tool": "get_execution_status",
            "cancel_tool": "cancel_execution",
            "result_tool": "read_execution_result",
            "recovery_tool": "recover_execution",
            "persistence_enabled": _REQUESTS.persist,
            "persistence_format": "pok.execution-checkpoint.v1",
            "retention": "bounded_live_history_and_immutable_checkpoints",
            "restart_recovery": "verified_checkpoint_retrieval_not_replay",
            "python_preemption": "cooperative_only",
            "process_tree_termination": "owned_job_or_group_scope_reported_per_resource",
            "client_wait_cancel": "does_not_imply_server_cancel",
        },
        "native_command_lifetime": {
            "owned_containment_paths": [
                "pob.runner",
                "pob.daemon",
                "pob.item_editor",
                "pob.roundtrip",
                "pob.parse_gaps",
                "pob.item_parse_gaps",
            ],
            "pending_native_paths": [],
            "daemon_default_timeout_s": 180,
            "deadline_scope": "single_command_including_lock_wait",
            "progress_extends_deadline": False,
            "termination_scope": "owned_windows_job_or_posix_process_group",
            "posix_group_escape": "not_prevented",
            "single_driver_output": "regular_file_snapshot_no_pipe_drain",
            "whole_request_deadline": "cooperative_request_scope",
            "mcp_cancellation_propagation": "explicit_notification_or_cancel_execution",
        },
        "design_records": {
            "format": _DESIGN_FORMAT,
            "schema_tool": "get_design_record_schema",
            "material_snapshot_tool": "capture_design_material",
            "xml_measurement_attachment_tool": "attach_pob_document_measurement",
            "provider_bindings": {
                "build_spec": "json_pointer_value",
                "pob_xml": "exact_subtree_at_element_path",
                "xml_pointer_source": "inspect_pob_document",
                "active_supplier_semantics": "not_checked",
            },
            "operations": [
                "create_design_record",
                "read_design_record",
                "update_design_record",
                "inspect_design_record",
                "list_design_records",
                "import_design_document",
            ],
            "current_head": "caller_owned",
            "automatic_current_evidence_inspection": ["create", "read", "update", "import"],
            "xml_spec_equivalence": "not_checked",
            "game_feasibility": "not_checked",
        },
        "measurement_receipts": {
            "tools": ["compute_pob", "evaluate_delta", "compute_pob_document"],
            "result_size_independent": True,
            "source_identity": (
                "disk_and_scoped_memory_observations_not_full_execution_certification"
            ),
            "loaded_observation_field": "source.loaded_execution_observation",
        },
        "unique_item_configuration": {
            "tool": "prepare_unique_item",
            "format": "pok.unique-item-configuration.v1",
            "preserves_unspecified_selectors": True,
            "duplicate_choices": "as_declared_by_native_source",
            "kb_alias_binding": "not_performed",
            "calculation_or_game_validation": "not_performed",
        },
        "socket_provenance": {
            "format": "pok.socket-sidecar.v1",
            "create_tool": "create_socket_sidecar",
            "rebind_tool": "rebind_socket_sidecar",
            "restore_tool": "restore_pob_spec",
            "binding": ["exact_xml", "restored_projection_revision", "item_text"],
            "claim": "caller_declarations_not_drop_verification",
        },
        "xml_selection": {
            "saved_active_sets": True,
            "explicit_override_fields": [
                "item_set",
                "skill_set",
                "tree_spec",
                "config_set",
                "weapon_set",
                "main_group",
            ],
            "tree_identity": "one_based_ordinal",
            "set_identity": "numeric_id",
            "main_group_and_stat_mode_overrides": "main_group_only",
            "full_xml_spec_equivalence": "not_checked",
        },
        "native_selection_receipt": {
            "format": "pok.native-selection.v1",
            "source_field": "meta.nativeSelection",
            "cache_protocol": _POB_META_PROTOCOL,
            "scope": "native_main_environment_not_game_legality",
        },
        "pob_documents": {
            "tools": [
                "read_pob_document",
                "prepare_pob_delivery",
                "inspect_pob_document",
                "edit_pob_document",
                "compute_pob_document",
                "read_pob_document_measurement",
                "select_pob_document_effect",
            ],
            "edit_scope": "explicit_attributes_leaf_text_and_identified_children",
            "edit_operations": ["set_attribute", "set_text", "upsert_child_attribute"],
            "unknown_and_inactive_bytes": "preserved_outside_edited_span",
            "post_edit_spec_metadata_rebinding": "required_not_automatic",
            "measurement_ref_format": "pok.document-measurement-ref.v1",
            "measurement_binding": "verified_exact_xml_subject_not_execution_identity",
            "delivery_format": "pok.pob-delivery.v1",
            "delivery_scope": "verified_exact_xml_code_bytes_not_build_validation",
            "effect_selection": "observed_bounds_direct_source_mapping_then_remeasure",
            "selection_report_format": "pok.document-selection.v1",
        },
    }


@tool
def get_server_capabilities() -> dict[str, Any]:
    """Full runtime capability contract; server_info retains a bounded summary."""
    return _server_capabilities()


def _capability_summary() -> dict[str, Any]:
    full = _server_capabilities()
    fields = {
        "request_execution": [
            "format",
            "server_instance",
            "request_metadata",
            "default_timeout_s",
            "maximum_timeout_s",
            "default_timeout_scope",
            "cleanup_grace_s",
            "status_tool",
            "cancel_tool",
            "result_tool",
            "recovery_tool",
        ],
        "design_records": ["format", "schema_tool", "current_head"],
        "measurement_receipts": ["source_identity"],
        "socket_provenance": ["format", "claim"],
        "native_selection_receipt": ["format", "source_field", "cache_protocol", "scope"],
        "pob_documents": ["measurement_ref_format", "selection_report_format"],
    }
    return {
        "details_tool": "get_server_capabilities",
        **{name: {key: full[name][key] for key in keys} for name, keys in fields.items()},
    }


@tool
def server_info(include_kb_diagnostics: bool = True) -> dict[str, Any]:
    """이 MCP 서버가 **어느 판인지** — 로드된 커밋·소스 커밋·도구별 파라미터 지문.

    `include_kb_diagnostics=False`면 진단은 null로 생략한다. `pob_runtime_declaration`은
    설정 pin 선언이며 실제 Native 실행 identity나 수동 worker와의 계산 동등성 인증이 아니다.

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
    # 0종이 나온다(실측). 파라미터 지문은 스키마에서 뽑는다 — 이것이 "이 프로세스가
    # 실제로 받는 인자"다(이관 D-2).
    # ⛔ **이벤트 루프에 기대지 않는다** (#150). `asyncio.run(mcp.list_tools())`는 서버
    #    런타임(워커 스레드) 안에서 영원히 안 돌아왔고, 이 도구가 바로 그것을 확인하라고
    #    만든 도구였다. 등록 시점에 동기로 채운 `_TOOL_PARAMS`를 읽는다.
    tools = {name: list(params) for name, params in sorted(_TOOL_PARAMS.items())}
    stale = bool(_LOADED_COMMIT and source_commit and source_commit != _LOADED_COMMIT)
    identity_status = "verified" if _LOADED_COMMIT and source_commit else "unavailable"
    # 사본을 빼고 로드했으면 **말한다** — 조용히 빼면 "왜 이 레코드가 안 보이지"가 된다(#21)
    from pok.kb.store import cached_diagnostics
    from pok.pob.versions import runtime_declaration

    kb_diagnostics = cached_diagnostics() if include_kb_diagnostics else None
    return {
        "kb_skipped_copies": kb_diagnostics["skipped_copies"]
        if kb_diagnostics is not None
        else None,
        "kb_diagnostics": kb_diagnostics,
        "kb_diagnostics_included": include_kb_diagnostics,
        "pob_runtime_declaration": runtime_declaration(),
        "loaded_commit": _LOADED_COMMIT,
        "loaded_subject": _LOADED_SUBJECT,
        "source_commit": source_commit,
        "source_subject": source_subject,
        "stale": stale,
        "identity_status": identity_status,
        "source_root": str(knowledge_dir().parent),
        "runtime_paths": runtime_paths(),
        "tools": tools,
        "tool_count": len(tools),
        "capabilities": _capability_summary(),
        "note": (
            "Git 식별 불가: 최신 실행을 인증하지 않는다."
            if identity_status == "unavailable"
            else "소스 변경됨: 서버 재시작 필요."
            if stale
            else "등록된 도구·인자만 호출 가능. 소스 변경 후 재시작 필요."
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
    예) 정신력 40 잔여 → `find_by_value("reservation.at_max_level", type="Skill", maximum=40)`
        코스트 상한   → `find_by_value("cost.max", type="Skill", maximum=25)`

    점유는 레벨이 오르면 줄기도 한다. `at_max_level`은 최고 레벨 값이고,
    `min`/`max`는 크기순 경계다. 특정 젬 레벨로 쓸 때는 해당 레벨의 점유도 확인한다.
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
create_socket_sidecar = tool(_build.create_socket_sidecar)
inspect_pob_runtime = tool(_build.inspect_pob_runtime)
prepare_unique_item = tool(_build.prepare_unique_item)
rebind_socket_sidecar = tool(
    _build.rebind_socket_sidecar,
    literal_arguments=frozenset(
        {"source_xml_ref", "sidecar_ref", "target_xml_ref", "target_selection"}
    ),
)
measure_leverage = tool(_build.measure_leverage)
check_pob_stability = tool(_build.check_pob_stability)
# 켠 config의 유지 비용 (#145) — 「이 표기가 팩에서도 서나」. `compute_pob`이 정적
# 신고를 반환에 붙이고, 이 도구는 `measure=True`로 **조건별 실제 기여까지** 잰다.
audit_config_upkeep = tool(_build.audit_config_upkeep)

# 설계 루프 (P4.5, D26~D28)
check_constraints = tool(_constraints.check_constraints)
evaluate_objective = tool(_constraints.evaluate_objective)
parse_design_doc = tool(_constraints.parse_design_doc)
list_builds = tool(_constraints.list_builds)
compute_trigger_rate = tool(_constraints.compute_trigger_rate)

# 트리 최적화 도구 (P4) — tools/tree.py
connect_anchors = tool(_tree.connect_anchors)
optimize_tree = tool(_tree.optimize_tree)
prepare_tree_variant = tool(_tree.prepare_tree_variant)
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
# 메커니즘 상태 그래프 (#92) — 「무엇이 무엇을 만들고 먹나」, 상태 전이 사슬
scan_state_edges = tool(_explore.scan_state_edges)
trace_mechanism_chains = tool(_explore.trace_mechanism_chains)
# 3층 교차 순회 (#95) — 스탯·상태·객체를 한 사슬로, 마디마다 층 꼬리표
trace_cross_chains = tool(_explore.trace_cross_chains)
# 스케일러 크기 판정 (#102) — 「담체가 많다」를 「배율이 크다」로 오독하지 않도록
scan_scalers = tool(_explore.scan_scalers)
# 적대 조합 (#131) — 위 그래프들이 못 보는 축: A가 만드는 것을 B가 **금지**한다.
# 「없는 공백」이 아니라 **「있는 충돌」** — 담체 한 칸이 통째로 죽는데 신호가 없었다.
scan_antagonists = tool(_explore.scan_antagonists)
# 조건 성립기 (#125) — 「이 노드를 살리려면 무엇이 필요한가」. 상태 그래프(#92)가
# 다루는 **가하는 상태**가 아니라 **자신이 처한 상태**다. 주체(자신/적)가 축에 있다.
scan_enablers = tool(_explore.scan_enablers)


def main() -> None:
    # stdio가 곧 JSON-RPC 채널이고 MCP는 UTF-8을 요구한다 — Windows 기본
    # 코드페이지로는 KB의 한글·기호가 그대로 나가지 못한다.
    force_utf8_stdio()
    mcp.run()  # stdio


if __name__ == "__main__":
    main()
