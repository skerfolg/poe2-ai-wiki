"""Mock-only executable behavior tests: no model, MCP, web, or PoB calls."""

import asyncio
import copy
import importlib.util
import json
import sys
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[2] / "skills/build-generation/session.py"
SPEC = importlib.util.spec_from_file_location("generation_session_tests", PATH)
driver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = driver
SPEC.loader.exec_module(driver)


def candidate(key="A", status="retained", reason="Public reason"):
    return {
        "id": key,
        "label": key,
        "status": status,
        "components": [],
        "evidence_ids": [],
        "public_decision_reason": reason,
    }


def request(tool="get_entry", arguments=None):
    return {
        "tool": tool,
        "arguments_json": json.dumps(arguments or {"id": "skill.example"}),
        "purpose": "Read evidence",
    }


def answer(candidates=None, requests=None):
    candidates = candidates if candidates is not None else [candidate()]
    selected = [row["id"] for row in candidates if row["status"] == "selected"]
    return {
        "report": "Design only",
        "candidates": candidates,
        "selection": selected[0] if len(selected) == 1 else "",
        "tool_requests": requests or [],
    }


class FakeModel:
    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def __call__(self, prompt, schema, outdir, timeout_s):
        self.calls.append(
            {
                "context": json.loads(prompt),
                "schema": schema,
                "outdir": outdir,
                "timeout_s": timeout_s,
            }
        )
        value = self.answers[len(self.calls) - 1]
        if isinstance(value, Exception):
            raise value
        if callable(value):
            value = value(self.calls[-1]["context"])
        return {"execution_ok": True, "answer": copy.deepcopy(value), "provider": "injected-fake"}


class FakeReader:
    def __init__(self, response=None):
        self.calls = []
        self.response = (
            response if response is not None else {"is_error": False, "result": {"value": 37}}
        )

    async def __call__(self, tool, args):
        self.calls.append((tool, args))
        if isinstance(self.response, Exception):
            raise self.response
        return copy.deepcopy(self.response)


def run(tmp_path, model, reader=None, **kwargs):
    return asyncio.run(
        driver.run_generation_session(
            prompt="Caller supplied task",
            generator=model,
            reader=reader or FakeReader(),
            outdir=tmp_path / "session",
            allowed_tools={"get_entry", "search_kb"},
            **kwargs,
        )
    )


def test_three_actual_calls_receive_accumulated_public_outputs_and_real_results(tmp_path):
    def second(context):
        result = next(x for x in context["public_history"] if x["kind"] == "tool_result")
        assert result["value"]["raw_response"]["result"]["value"] == 37
        reply = answer(requests=[request("search_kb", {"query": "changed by 37"})])
        reply["report"] = "Evidence 37 changed the external decision"
        return reply

    def third(context):
        assert len(context["public_history"]) == 4
        assert (
            context["public_history"][2]["value"]["report"]
            == "Evidence 37 changed the external decision"
        )
        assert (
            context["public_history"][3]["value"]["request"]["arguments_json"]
            == '{"query": "changed by 37"}'
        )
        return answer(
            [candidate(status="selected", reason="External model chose after receiving evidence")]
        )

    model = FakeModel([answer(requests=[request()]), second, third])
    reader = FakeReader()
    result = run(tmp_path, model, reader, initial_evidence={"fixed": "packet"})
    assert len(model.calls) == 3 and len(reader.calls) == 2
    assert result["status"] == "complete"
    assert result["scope"] == "design_only"
    assert result["recommendation_ready"] is False and result["assembly_ready"] is False
    assert result["driver_selects_winner"] is False
    assert model.calls[2]["context"]["initial_evidence"] == {"fixed": "packet"}
    assert model.calls[2]["context"]["stage_query_budget"] == 0
    assert (tmp_path / "session/stage-1/queries/00.json").is_file()
    assert json.loads((tmp_path / "session/checkpoint.json").read_text())["event"] == "finished"


def test_duplicate_mcp_json_does_not_spend_model_result_budget_twice(tmp_path):
    payload = {"id": "mechanic.example", "stats": ["x" * 1300]}
    raw = {
        "is_error": False,
        "result": payload,
        "content": [
            {"type": "text", "text": json.dumps(payload)},
            {"type": "text", "text": "Additional non-duplicate note"},
        ],
    }
    model = FakeModel([answer(requests=[request()]), answer(), answer()])
    run(tmp_path, model, FakeReader(raw), limits=driver.Limits(public_result_chars=2600))
    public = model.calls[1]["context"]["public_history"][1]["value"]
    assert not public.get("truncated", False)
    assert public["raw_response"]["result"] == payload
    assert public["raw_response"]["content"] == [raw["content"][1]]
    assert public["projection"]["duplicate_json_text_blocks_omitted"] == 1
    saved = json.loads((tmp_path / "session/stage-1/queries/00.json").read_text())
    assert saved["raw_response"] == raw
    assert public["raw_sha256"] == driver._digest(saved)


def test_unstructured_null_and_nonduplicate_mcp_content_are_preserved():
    for raw in (
        {"is_error": False, "result": None, "content": [{"type": "text", "text": "unknown"}]},
        {"is_error": False, "result": {"x": 1}, "content": [{"type": "text", "text": '{"x":2}'}]},
        {"is_error": False, "result": {"x": 1}, "content": [{"type": "image", "data": "pixels"}]},
    ):
        entry = {"raw_response": raw}
        assert driver._public_query(entry) == entry


def test_reappearing_candidate_repairs_current_gap_but_preserves_history(tmp_path):
    model = FakeModel(
        [
            answer([candidate("A"), candidate("B")]),
            answer([candidate("A")]),
            answer([candidate("A"), candidate("B", "deferred")]),
        ]
    )
    result = run(tmp_path, model)
    assert result["status"] == "complete"
    assert result["structure_status"] == "valid"
    assert any(
        row["code"] == "candidate_missing" and row["candidate_id"] == "B" and row["stage"] == 2
        for row in result["diagnostics"]
    )
    assert result["incomplete_reasons"] == []
    assert model.calls[2]["context"]["candidate_history"]["B"][0]["value"]["status"] == "retained"
    assert len(result["candidate_history"]["B"]) == 2


def test_total_and_stage_quotas_are_checked_before_reader_and_not_reset(tmp_path):
    reader = FakeReader()
    model = FakeModel(
        [answer(requests=[request(), request()]), answer(requests=[request()]), answer()]
    )
    result = run(
        tmp_path, model, reader, limits=driver.Limits(total_tool_requests=2, stage_tool_requests=1)
    )
    assert len(reader.calls) == 1
    assert result["tool_requests"] == 3 and result["reader_calls"] == 1
    assert len(result["diagnostics"]) == 2
    assert result["execution_status"] == "complete"
    assert len(list((tmp_path / "session/stage-1/queries").glob("*.json"))) == 2
    assert model.calls[1]["context"]["query_budget_remaining"] == 0


def test_forbidden_and_bad_arguments_never_call_reader_but_consume_request_quota(tmp_path):
    bad = request()
    bad["arguments_json"] = "[]"
    reader = FakeReader()
    model = FakeModel(
        [answer(requests=[request("assemble_pob"), bad]), answer(requests=[request()]), answer()]
    )
    result = run(tmp_path, model, reader, limits=driver.Limits(total_tool_requests=2))
    assert reader.calls == []
    assert result["execution_status"] == "complete" and result["tool_requests"] == 3
    assert len(result["unresolved_diagnostics"]) == 3
    entries = [
        json.loads(path.read_text())
        for path in (tmp_path / "session/stage-1/queries").glob("*.json")
    ]
    assert {x["error"]["code"] for x in entries} == {"tool_not_allowed", "invalid_tool_arguments"}


@pytest.mark.parametrize(
    "raw",
    [
        {"is_error": True, "result": None, "why": "unsupported"},
        {"is_error": False, "result": {"value": None, "status": "unsupported"}},
    ],
)
def test_unknown_and_error_are_forwarded_verbatim_never_as_zero(tmp_path, raw):
    model = FakeModel([answer(requests=[request()]), answer(), answer()])
    result = run(tmp_path, model, FakeReader(raw))
    received = model.calls[1]["context"]["public_history"][1]["value"]
    assert received["raw_response"] == raw
    assert result["recommendation_ready"] is False
    if raw["is_error"]:
        assert result["execution_status"] == "complete"
        assert result["unresolved_diagnostics"][0]["assessment"] == "not_assessed_by_driver"


def test_generator_failure_records_no_retry_and_keeps_prior_results(tmp_path):
    model = FakeModel(
        [answer(requests=[request()]), RuntimeError("provider disconnected"), answer()]
    )
    result = run(tmp_path, model)
    assert len(model.calls) == 2 and result["stages_completed"] == 1
    assert result["final_answer"] is None
    assert (tmp_path / "session/stage-2/failure.json").is_file()
    assert len(result["public_history"]) == 2


def test_reader_timeout_is_cancelled_recorded_and_forwarded_without_retry(tmp_path):
    calls = []

    async def reader(tool, args):
        calls.append(tool)
        try:
            await asyncio.sleep(5)
        finally:
            calls.append("cancelled")

    model = FakeModel([answer(requests=[request()]), answer(), answer()])
    result = run(tmp_path, model, reader, limits=driver.Limits(tool_timeout_s=0.01))
    assert calls == ["get_entry", "cancelled"]
    assert result["execution_status"] == "complete"
    assert result["unresolved_diagnostics"][0]["code"] == "reader_exception"
    assert (
        model.calls[1]["context"]["public_history"][1]["value"]["error"]["type"] == "TimeoutError"
    )


def test_deadline_blocks_next_model_and_records_overrun(tmp_path):
    now = [0.0]

    def expired(context):
        now[0] = 4
        return answer(requests=[request()])

    model = FakeModel([expired, answer(), answer()])
    reader = FakeReader()
    result = run(
        tmp_path, model, reader, clock=lambda: now[0], limits=driver.Limits(total_timeout_s=3)
    )
    assert model.calls[0]["timeout_s"] == 3
    assert len(model.calls) == 1 and reader.calls == []
    assert result["incomplete_reasons"][0]["error"]["type"] == "TimeoutError"


def test_per_model_timeout_is_not_replaced_by_larger_session_budget(tmp_path):
    now = [0.0]

    def late(context):
        now[0] = 3
        return answer()

    model = FakeModel([late, answer(), answer()])
    result = run(
        tmp_path,
        model,
        clock=lambda: now[0],
        limits=driver.Limits(model_timeout_s=2, total_timeout_s=20),
    )
    assert len(model.calls) == 1 and result["stages_completed"] == 0
    assert "per-call timeout" in result["incomplete_reasons"][0]["error"]["message"]


def test_async_generator_timeout_cancels_without_retry(tmp_path):
    calls = []

    async def model(prompt, schema, outdir, timeout_s):
        calls.append("start")
        try:
            await asyncio.sleep(5)
        finally:
            calls.append("cancelled")

    result = run(tmp_path, model, limits=driver.Limits(model_timeout_s=0.01))
    assert calls == ["start", "cancelled"]
    assert result["model_calls"] == 1 and result["status"] == "incomplete"


def test_final_queries_are_all_preserved_but_never_executed(tmp_path):
    model = FakeModel([answer(), answer(), answer(requests=[request(), request()])])
    reader = FakeReader()
    result = run(tmp_path, model, reader)
    assert reader.calls == [] and result["status"] == "incomplete"
    assert len(result["final_answer"]["tool_requests"]) == 2
    assert len(list((tmp_path / "session/stage-3/queries").glob("*.json"))) == 2


def test_result_truncation_preserves_full_raw_and_labels_visible_prefix(tmp_path):
    raw = {"is_error": False, "result": {"text": "z" * 1000}}
    model = FakeModel([answer(requests=[request()]), answer(), answer()])
    run(tmp_path, model, FakeReader(raw), limits=driver.Limits(public_result_chars=200))
    public = model.calls[1]["context"]["public_history"][1]["value"]
    assert public["truncated"] is True and len(public["visible_prefix"]) == 200
    entry = json.loads((tmp_path / "session" / public["raw_file"]).read_text())
    assert entry["raw_response"] == raw and public["raw_sha256"] == driver._digest(entry)


def test_runtime_adapter_file_output_works_and_invalid_execution_does_not_pass(tmp_path):
    def model(prompt, schema, outdir, timeout_s):
        outdir.mkdir()
        (outdir / "answer.json").write_text(json.dumps(answer()))
        return {"execution_ok": len(list(outdir.parent.parent.glob("stage-*"))) < 2}

    result = run(tmp_path, model)
    assert result["stages_completed"] == 1 and result["model_calls"] == 2
    assert result["status"] == "incomplete"


def test_duplicate_ids_and_blank_disposition_reason_are_not_silent(tmp_path):
    model = FakeModel(
        [
            answer([candidate("A", "rejected", " ")]),
            answer([candidate("A"), candidate("A")]),
            answer(),
        ]
    )
    result = run(tmp_path, model)
    assert result["stages_completed"] == 1
    assert {row["code"] for row in result["incomplete_reasons"]} == {
        "candidate_reason_missing",
        "generator_failure",
    }
    assert (tmp_path / "session/stage-2/answer.raw.json").is_file()


def test_mutating_allowlist_and_existing_evidence_are_rejected(tmp_path):
    with pytest.raises(ValueError, match="read-query"):
        asyncio.run(
            driver.run_generation_session(
                prompt="Task",
                generator=None,
                reader=None,
                outdir=tmp_path / "bad",
                allowed_tools={"record_build"},
            )
        )
    assert not (tmp_path / "bad").exists()
    run(tmp_path, FakeModel([answer(), answer(), answer()]))
    with pytest.raises(FileExistsError):
        run(tmp_path, FakeModel([answer(), answer(), answer()]))


def test_explicit_adapter_failure_cannot_be_overridden_by_unrecognized_success_flag(tmp_path):
    def model(prompt, schema, outdir, timeout_s):
        return {"execution_ok": False, "valid_for_comparison": True, "answer": answer()}

    result = run(tmp_path, model)
    assert result["model_calls"] == 1 and result["stages_completed"] == 0
    assert result["status"] == "incomplete"


def test_four_initial_candidates_can_be_disposed_and_new_package_added(tmp_path):
    initial = [candidate(key) for key in "ABCD"]
    disposed = [
        candidate(key, "rejected", "External evidence rejected this mechanism") for key in "ABCD"
    ]
    model = FakeModel(
        [
            answer(initial),
            answer([*disposed, candidate("new-package")]),
            answer([candidate("new-package", "selected")]),
        ]
    )
    result = run(tmp_path, model)
    assert result["status"] == "complete"
    assert len(result["candidate_history"]) == 5
    assert result["archived_candidate_ids"] == list("ABCD")
    assert result["selection_status"] == "selected"
    assert model.calls[1]["schema"]["properties"]["candidates"]["maxItems"] == 12
    assert model.calls[2]["context"]["candidate_history"]["A"][-1]["value"]["status"] == "rejected"
    assert not any(row["code"] == "candidate_missing" for row in result["diagnostics"])


def test_caller_candidate_budget_is_enforced_without_changing_global_schema(tmp_path):
    initial = [candidate(key) for key in "ABCD"]
    model = FakeModel([answer(initial), answer([*initial, candidate("E")]), answer()])
    result = run(tmp_path, model, limits=driver.Limits(stage_candidates=4))
    assert result["execution_status"] == "incomplete"
    assert model.calls[0]["schema"]["properties"]["candidates"]["maxItems"] == 4
    assert driver.OUTPUT_SCHEMA["properties"]["candidates"]["maxItems"] == 12


@pytest.mark.parametrize("status", ["rejected", "deferred"])
def test_reasoned_disposition_may_leave_active_array_but_stays_in_history(tmp_path, status):
    model = FakeModel(
        [
            answer([candidate("A", status, "Explicit public disposition")]),
            answer([candidate("B")]),
            answer([candidate("B", "selected")]),
        ]
    )
    result = run(tmp_path, model)
    assert result["status"] == "complete" and result["archived_candidate_ids"] == ["A"]
    assert len(result["candidate_history"]["A"]) == 1


@pytest.mark.parametrize(
    "status,reason,code",
    [
        ("retained", "Still being considered", "candidate_missing"),
        ("selected", "Provisional winner", "candidate_missing"),
        ("rejected", " ", "candidate_reason_missing"),
    ],
)
def test_unresolved_candidate_omission_still_blocks_structure(tmp_path, status, reason, code):
    model = FakeModel(
        [
            answer([candidate("A", status, reason)]),
            answer([candidate("B")]),
            answer([candidate("B", "selected")]),
        ]
    )
    result = run(tmp_path, model)
    assert result["execution_status"] == "complete" and result["structure_status"] == "incomplete"
    assert {"code": code, "candidate_id": "A"} in result["incomplete_reasons"]


def test_recovered_query_does_not_permanently_fail_execution_or_erase_error(tmp_path):
    calls = []

    async def reader(tool, args):
        calls.append((tool, args))
        return {
            "is_error": len(calls) == 1,
            "result": None if len(calls) == 1 else {"evidence": "available"},
        }

    def final(context):
        responses = [
            row["value"]["raw_response"]
            for row in context["public_history"]
            if row["kind"] == "tool_result"
        ]
        assert responses == [
            {"is_error": True, "result": None},
            {"is_error": False, "result": {"evidence": "available"}},
        ]
        value = answer([candidate("A", "selected", "Later evidence supports this draft")])
        value["report"] = "Earlier query failed. New evidence recovered it; no PoB measurement."
        return value

    result = run(
        tmp_path,
        FakeModel([answer(requests=[request()]), answer(requests=[request()]), final]),
        reader,
    )
    assert result["status"] == "complete" and result["execution_status"] == "complete"
    assert result["unresolved_diagnostics"][0]["assessment"] == "not_assessed_by_driver"
    assert result["semantic_quality_verified"] is False and result["recommendation_ready"] is False
    assert len(calls) == 2  # Requested by the next model; no automatic retry.


@pytest.mark.parametrize(
    "selected_id,status,expected",
    [
        ("unknown", "selected", "selection_id_missing"),
        ("A", "retained", "selection_status_mismatch"),
        ("", "selected", "selection_missing_for_selected_candidate"),
    ],
)
def test_final_selection_is_structurally_bound_to_current_selected_candidate(
    tmp_path, selected_id, status, expected
):
    final = answer([candidate("A", status)])
    final["selection"] = selected_id
    result = run(tmp_path, FakeModel([answer(), answer(), final]))
    assert result["execution_status"] == "complete" and result["selection_status"] == "invalid"
    assert any(row["code"] == expected for row in result["structure_issues"])


def test_all_rejected_and_empty_final_array_has_explicit_no_selection(tmp_path):
    model = FakeModel(
        [
            answer([candidate("A")]),
            answer([candidate("A", "rejected", "The supplied evidence contradicts the mechanism")]),
            answer([]),
        ]
    )
    result = run(tmp_path, model)
    assert result["status"] == "complete" and result["selection_status"] == "no_selection"
    assert result["final_answer"]["candidates"] == []
    assert result["archived_candidate_ids"] == ["A"]


def search_read_request(**overrides):
    args = {"search_args": {"query": "Reload", "type": "Mechanic", "limit": 8}, "max_entries": 3}
    args.update(overrides)
    return request("search_and_read", args)


def run_with_operation(tmp_path, model, reader, **kwargs):
    return run(tmp_path, model, reader, tool_catalog=driver.VIRTUAL_TOOL_CATALOG, **kwargs)


class SearchReader:
    def __init__(self, search_result=None, detail_error_id=None):
        self.calls = []
        self.search_result = (
            search_result
            if search_result is not None
            else [
                {"id": "mechanic.third-name"},
                {"id": "skill.first-name"},
                {"id": "item.second-name"},
                {"id": "passive.outside"},
            ]
        )
        self.detail_error_id = detail_error_id

    async def __call__(self, tool, args):
        self.calls.append((tool, copy.deepcopy(args)))
        if tool == "search_kb":
            return {"is_error": False, "result": copy.deepcopy(self.search_result)}
        return {
            "is_error": args["id"] == self.detail_error_id,
            "result": None if args["id"] == self.detail_error_id else {"id": args["id"]},
        }


def test_search_and_read_makes_four_real_calls_and_records_original_rank(tmp_path):
    reader = SearchReader()
    model = FakeModel([answer(), answer(requests=[search_read_request()]), answer()])
    result = run_with_operation(tmp_path, model, reader)
    assert [name for name, _ in reader.calls] == [
        "search_kb",
        "get_entry",
        "get_entry",
        "get_entry",
    ]
    assert [args["id"] for _, args in reader.calls[1:]] == [
        "mechanic.third-name",
        "skill.first-name",
        "item.second-name",
    ]
    assert all(args["include_narrative"] is True for _, args in reader.calls[1:])
    assert result["tool_requests"] == result["reader_calls"] == 4
    assert result["operation_requests"] == 1
    operation = result["operation_history"][0]
    assert operation["underlying_query_attempts"] == 4
    assert [hit["result_rank"] for hit in operation["selected_hits"]] == [1, 2, 3]
    assert operation["selection_truncated_by_max_entries"] is True
    assert operation["outside_requested_range"] == [{"id": "passive.outside", "result_rank": 4}]
    assert "not a quality judgment" in operation["selection_policy"]
    details = [
        row["value"]
        for row in model.calls[2]["context"]["public_history"]
        if row["kind"] == "tool_result"
    ]
    assert len(details) == 4
    assert details[-1]["origin"]["result_rank"] == 3
    assert details[-1]["origin"]["search_evidence_id"] == details[0]["evidence_id"]
    assert len(list((tmp_path / "session/stage-2/queries").glob("*.json"))) == 4


@pytest.mark.parametrize(
    "limits",
    [
        driver.Limits(total_tool_requests=3),
        driver.Limits(stage_tool_requests=3),
    ],
)
def test_search_and_read_reads_only_remaining_shared_budget_and_reports_unread(tmp_path, limits):
    reader = SearchReader()
    model = FakeModel([answer(requests=[request(), search_read_request()]), answer(), answer()])
    result = run_with_operation(tmp_path, model, reader, limits=limits)
    assert [name for name, _ in reader.calls] == ["get_entry", "search_kb", "get_entry"]
    assert result["tool_requests"] == result["reader_calls"] == 3
    operation = result["operation_history"][0]
    assert operation["status"] == "partial"
    assert operation["underlying_query_attempts"] == 2
    assert len(operation["unread_hits"]) == 2
    assert {row["reason"] for row in operation["unread_hits"]} == {"tool_request_quota_exhausted"}


def test_operation_expansion_consumes_budget_before_later_direct_requests(tmp_path):
    reader = SearchReader()
    model = FakeModel([answer(requests=[search_read_request(), request()]), answer(), answer()])
    result = run_with_operation(
        tmp_path, model, reader, limits=driver.Limits(stage_tool_requests=4)
    )
    assert len(reader.calls) == 4
    assert result["tool_requests"] == 5 and result["reader_calls"] == 4
    blocked = json.loads((tmp_path / "session/stage-1/queries/04.json").read_text())
    assert blocked["error"]["code"] == "tool_request_quota_exhausted"


def test_operation_with_no_budget_does_not_claim_a_search_or_read(tmp_path):
    reader = SearchReader()
    model = FakeModel([answer(requests=[search_read_request()]), answer(), answer()])
    result = run_with_operation(
        tmp_path, model, reader, limits=driver.Limits(total_tool_requests=0)
    )
    assert reader.calls == []
    assert result["tool_requests"] == result["reader_calls"] == 0
    assert result["operation_requests"] == 1
    assert result["operation_history"][0]["underlying_query_attempts"] == 0
    assert result["operation_history"][0]["error"]["code"] == "tool_request_quota_exhausted"


def test_empty_search_diagnostic_is_never_followed_as_an_id(tmp_path):
    reader = SearchReader(
        [
            {"empty": True, "id": "not-a-hit", "why": ["No matching tokens"]},
            {"other": "unknown row"},
            {"id": "mechanic.actual"},
        ]
    )
    model = FakeModel([answer(requests=[search_read_request()]), answer(), answer()])
    result = run_with_operation(tmp_path, model, reader)
    assert [args["id"] for _, args in reader.calls[1:]] == ["mechanic.actual"]
    operation = result["operation_history"][0]
    assert operation["selected_hits"] == [{"id": "mechanic.actual", "result_rank": 3}]
    assert operation["skipped_rows"] == [
        {"result_rank": 1, "reason": "empty_search_diagnostic"},
        {"result_rank": 2, "reason": "no_record_id"},
    ]
    raw = json.loads((tmp_path / "session/stage-1/queries/00.json").read_text())
    assert raw["raw_response"]["result"][0]["why"] == ["No matching tokens"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ({"is_error": True, "result": None, "why": "unsupported"}, "search_failed"),
        ({"is_error": False, "result": None}, "search_result_not_list"),
        (
            {"is_error": False, "result": [{"empty": True, "why": ["No results"]}]},
            "no_readable_hits",
        ),
    ],
)
def test_operation_search_unknown_error_and_empty_preserve_response_without_invented_reads(
    tmp_path, raw, expected
):
    reader = FakeReader(raw)
    model = FakeModel([answer(requests=[search_read_request()]), answer(), answer()])
    result = run_with_operation(tmp_path, model, reader)
    assert len(reader.calls) == 1 and reader.calls[0][0] == "search_kb"
    assert result["operation_history"][0]["status"] == expected
    detail = next(
        row["value"]
        for row in model.calls[1]["context"]["public_history"]
        if row["kind"] == "tool_result"
    )
    assert detail["raw_response"] == raw


def test_detail_error_does_not_silently_drop_other_requested_reads_or_become_zero(tmp_path):
    reader = SearchReader(detail_error_id="skill.first-name")
    model = FakeModel([answer(requests=[search_read_request()]), answer(), answer()])
    result = run_with_operation(tmp_path, model, reader)
    assert len(reader.calls) == 4
    assert result["operation_history"][0]["status"] == "completed_with_errors"
    error = json.loads((tmp_path / "session/stage-1/queries/02.json").read_text())
    assert error["raw_response"] == {"is_error": True, "result": None}
    assert result["execution_status"] == "complete" and not result["semantic_quality_verified"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_entries": 0},
        {"max_entries": 4},
        {"max_entries": True},
        {"search_args": []},
        {"fields": [""]},
        {"include_narrative": "yes"},
        {"tool": "record_build"},
    ],
)
def test_invalid_operation_or_mutation_request_never_reaches_reader(tmp_path, overrides):
    reader = SearchReader()
    model = FakeModel([answer(requests=[search_read_request(**overrides)]), answer(), answer()])
    result = run_with_operation(tmp_path, model, reader)
    assert reader.calls == [] and result["tool_requests"] == 0
    assert result["operation_history"][0]["error"]["code"] == "invalid_operation_arguments"


def test_fields_and_narrative_override_are_passed_unchanged(tmp_path):
    reader = SearchReader()
    model = FakeModel(
        [
            answer(
                requests=[
                    search_read_request(
                        max_entries=1, fields=["id", "conditions"], include_narrative=False
                    )
                ]
            ),
            answer(),
            answer(),
        ]
    )
    run_with_operation(tmp_path, model, reader)
    assert reader.calls[1] == (
        "get_entry",
        {"id": "mechanic.third-name", "fields": ["id", "conditions"], "include_narrative": False},
    )


def test_operation_final_stage_and_unadvertised_dispatch_are_blocked(tmp_path):
    reader = SearchReader()
    model = FakeModel([answer(), answer(), answer(requests=[search_read_request()])])
    result = run_with_operation(tmp_path, model, reader)
    assert reader.calls == [] and result["structure_status"] == "incomplete"
    assert result["operation_history"][0]["error"]["code"] == "final_stage_query_not_allowed"
    other = tmp_path / "unadvertised"
    other.mkdir()
    model = FakeModel([answer(requests=[search_read_request()]), answer(), answer()])
    result = run(other, model, reader)
    assert reader.calls == []
    assert result["operation_history"][0]["error"]["code"] == "operation_not_advertised"


def test_operation_cannot_bypass_actual_read_tool_allowlist(tmp_path):
    reader = SearchReader()
    result = asyncio.run(
        driver.run_generation_session(
            prompt="Task",
            generator=FakeModel([answer(requests=[search_read_request()]), answer(), answer()]),
            reader=reader,
            outdir=tmp_path / "session",
            allowed_tools={"search_kb"},
            tool_catalog=driver.VIRTUAL_TOOL_CATALOG,
        )
    )
    assert reader.calls == []
    assert result["operation_history"][0]["error"]["code"] == "operation_dependencies_not_allowed"


def test_initial_coverage_index_lists_present_fields_without_certifying_or_suppressing_queries(
    tmp_path,
):
    packet = {
        "records": [
            {"id": "skill.example", "data": {"cost": 1}, "granted_instance": None},
            {"id": "mechanic.example", "narrative": "Prior supplied text"},
            {"empty": True},
        ]
    }
    reader = FakeReader({"is_error": False, "result": {"id": "skill.example", "new": True}})
    model = FakeModel([answer(requests=[request()]), answer(requests=[request()]), answer()])
    result = run(tmp_path, model, reader, initial_evidence=packet)
    index = model.calls[0]["context"]["initial_evidence_index"]
    assert index["status"] == "indexed"
    assert index["freshness_verified"] is False and index["query_cache"] is False
    assert index["coverage"] == [
        {
            "id": "skill.example",
            "record_position": 0,
            "top_level_fields": ["data", "granted_instance", "id"],
            "granted_instance_field_present": True,
            "narrative_field_present": False,
        },
        {
            "id": "mechanic.example",
            "record_position": 1,
            "top_level_fields": ["id", "narrative"],
            "granted_instance_field_present": False,
            "narrative_field_present": True,
        },
    ]
    assert index["skipped_rows"] == [{"record_position": 2, "reason": "no_record_id"}]
    assert all(call["context"]["initial_evidence_index"] == index for call in model.calls)
    assert model.calls[2]["context"]["initial_evidence"] == packet
    assert result["reader_calls"] == result["tool_requests"] == len(reader.calls) == 2


def test_coverage_index_preserves_duplicate_positions_and_unknown_shapes():
    duplicate = driver.initial_evidence_index(
        {
            "records": [
                {"id": "A", "name": "Old"},
                {"id": "A", "narrative": "New"},
            ]
        }
    )
    assert [row["record_position"] for row in duplicate["coverage"]] == [0, 1]
    assert (
        duplicate["coverage"][0]["top_level_fields"] != duplicate["coverage"][1]["top_level_fields"]
    )
    unknown = driver.initial_evidence_index({"records": None})
    assert unknown["status"] == "records_list_unavailable" and unknown["coverage"] == []
    assert unknown["freshness_verified"] is False


@pytest.mark.parametrize("selected_id", ["A", ""])
def test_multiple_selected_candidates_are_ambiguous_even_if_selection_names_one(
    tmp_path, selected_id
):
    final = answer([candidate("A", "selected"), candidate("B", "selected")])
    final["selection"] = selected_id
    result = run(tmp_path, FakeModel([answer(), answer(), final]))
    assert result["execution_status"] == "complete"
    assert result["selection_status"] == "invalid" and result["structure_status"] == "incomplete"
    assert {"code": "selection_multiple_selected", "candidate_ids": ["A", "B"]} in result[
        "structure_issues"
    ]
