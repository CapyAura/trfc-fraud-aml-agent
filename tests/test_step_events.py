"""Offline tests for safe C4 step-event serialization and append behavior."""

import json
from datetime import datetime

import pytest

from eval.log_validation import validate_event
from eval.step_events import append_step_events, build_step_events


USAGE = {
    "calls": 2,
    "prompt_tokens": None,
    "completion_tokens": None,
    "max_prompt": None,
}


def trace_record(*, step=1, status="completed", error=None, result='{"ok":true}',
                 tool="get_account_risk_status"):
    return {
        "step": step,
        "tool_call_id": f"call-{step}",
        "tool_name": tool,
        "arguments": {"account_id": "ACC123", "nested": {"reason": "sensitive"}},
        "result": result,
        "status": status,
        "error": error,
    }


def test_event_serialization_matches_schema_and_uses_timezone_aware_timestamp():
    events, skipped = build_step_events(
        tool_trace=[trace_record(tool="freeze_account_temporarily")], usage=USAGE, run_id="run-1",
        question_id="case-1", scenario="freeze", execution_mode="unit_test",
    )

    assert skipped is None
    assert len(events) == 1
    event = events[0]
    assert event["record_type"] == "step_event"
    assert event["scenario"] == "freeze"
    assert event["execution_mode"] == "unit_test"
    assert event["status"] == "completed"
    assert event["scenario_evidence_status"] == "tool_call_completed_outcome_unverified"
    assert event["business_outcome_verified"] is False
    assert datetime.fromisoformat(event["timestamp"]).utcoffset() is not None
    assert validate_event(event) == []


def test_event_append_preserves_existing_records_and_creates_parent(tmp_path):
    path = tmp_path / "new" / "events.jsonl"
    path.parent.mkdir()
    original_row = build_step_events(
        tool_trace=[trace_record(tool="flag_suspicious_tx")], usage=USAGE, run_id="old-run",
        question_id="old-case", scenario="flag", execution_mode="unit_test",
    )[0][0]
    original = json.dumps(original_row) + "\n"
    path.write_text(original, encoding="utf-8")

    result = append_step_events(
        path, tool_trace=[trace_record(tool="flag_suspicious_tx")], usage=USAGE, run_id="run-2",
        question_id="case-2", scenario="flag", execution_mode="mock",
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    assert result.written == 1
    assert json.loads(lines[0]) == original_row
    assert validate_event(json.loads(lines[1])) == []
    assert json.loads(lines[1])["execution_mode"] == "mock"


def test_event_append_separates_existing_non_newline_terminated_content(tmp_path):
    path = tmp_path / "events.jsonl"
    original, _ = build_step_events(
        tool_trace=[trace_record(tool="flag_suspicious_tx")], usage=USAGE, run_id="old-run",
        question_id="old-case", scenario="flag", execution_mode="unit_test",
    )
    path.write_text(json.dumps(original[0]), encoding="utf-8")

    append_step_events(
        path, tool_trace=[trace_record(tool="flag_suspicious_tx")], usage=USAGE, run_id="run-2b",
        question_id="case-2b", scenario="flag", execution_mode="unit_test",
    )

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[0] == original[0]
    assert validate_event(rows[1]) == []


def test_nested_arguments_and_error_details_are_redacted_or_omitted(tmp_path):
    failed = trace_record(
        status="error",
        error="RuntimeError: API_KEY=synthetic-secret-value",
        result="RuntimeError: API_KEY=synthetic-secret-value",
        tool="flag_suspicious_tx",
    )
    failed["arguments"]["nested"]["password"] = "synthetic-password"
    failed["arguments"]["api_key"] = "synthetic-api-key"
    path = tmp_path / "events.jsonl"

    result = append_step_events(
        path, tool_trace=[failed], usage=USAGE, run_id="run-3",
        question_id="case-3", scenario="flag", execution_mode="unit_test",
    )

    serialized = path.read_text(encoding="utf-8")
    row = json.loads(serialized)
    assert result.written == 1
    assert "synthetic-secret-value" not in serialized
    assert "synthetic-password" not in serialized
    assert "synthetic-api-key" not in serialized
    assert row["args"]["account_id"] == "[REDACTED]"
    assert row["args"]["nested"]["reason"] == "[REDACTED]"
    assert row["args"]["nested"]["password"] == "[REDACTED]"
    assert row["args"]["api_key"] == "[REDACTED]"
    assert row["result"] == {
        "status": "error",
        "detail": "Tool call failed; diagnostic details omitted.",
    }
    assert "error" not in row
    assert validate_event(row) == []


def test_nested_json_result_and_unstructured_sensitive_text_are_redacted():
    nested_result = json.dumps({
        "status": "ok",
        "details": {"api_key": "nested-secret", "password": "nested-password"},
    })
    events, skipped = build_step_events(
        tool_trace=[trace_record(tool="flag_suspicious_tx", result=nested_result)],
        usage=USAGE, run_id="run-redact", question_id="case-redact",
        scenario="flag", execution_mode="unit_test",
    )
    serialized = json.dumps(events)
    assert skipped is None
    assert "nested-secret" not in serialized
    assert "nested-password" not in serialized
    assert "[REDACTED]" in serialized

    free_text_events, _ = build_step_events(
        tool_trace=[trace_record(
            tool="flag_suspicious_tx",
            result="authorization: Bearer synthetic-token-value; customer_id=ACC123",
        )],
        usage=USAGE, run_id="run-free-text", question_id="case-free-text",
        scenario="flag", execution_mode="unit_test",
    )
    free_text = json.dumps(free_text_events)
    assert "synthetic-token-value" not in free_text
    assert "ACC123" not in free_text


def test_exception_message_is_never_persisted_in_failed_event():
    trace = trace_record(
        status="error", error="RuntimeError: password=exception-secret",
        result="RuntimeError: password=exception-secret",
        tool="freeze_account_temporarily",
    )
    events, skipped = build_step_events(
        tool_trace=[trace], usage=USAGE, run_id="run-exception",
        question_id="case-exception", scenario="freeze", execution_mode="unit_test",
    )
    serialized = json.dumps(events)
    assert skipped is None
    assert "exception-secret" not in serialized
    assert "RuntimeError" not in serialized
    assert events[0]["result"]["status"] == "error"


def test_failed_run_keeps_partial_trace_without_raw_exception_text():
    events, skipped = build_step_events(
        tool_trace=[
            trace_record(step=1, tool="freeze_account_temporarily"),
            trace_record(
                step=2, status="error", error="OSError: private diagnostic",
                result="Tool error: OSError: private diagnostic",
            ),
        ],
        usage=USAGE, run_id="run-4", question_id="case-4",
        scenario="freeze", execution_mode="unit_test",
    )

    assert skipped is None
    assert [event["step"] for event in events] == [1, 2]
    assert [event["status"] for event in events] == ["completed", "error"]
    assert "private diagnostic" not in json.dumps(events)


@pytest.mark.parametrize(
    ("trace", "scenario", "mode", "reason"),
    [
        (None, "refusal", "unit_test", "tool_trace_unavailable"),
        ([], "freeze", "unit_test", "empty_tool_trace"),
        ([], "refusal", "unit_test", "authoritative_refusal_metadata_unavailable"),
        ([trace_record()], "flag", "dry_run", "dry_run_has_no_runtime_events"),
    ],
)
def test_unavailable_empty_and_refusal_only_traces_do_not_invent_events(
    trace, scenario, mode, reason,
):
    events, skipped = build_step_events(
        tool_trace=trace, usage=USAGE, run_id="run-5", question_id="case-5",
        scenario=scenario, execution_mode=mode,
    )
    assert events == []
    assert skipped == reason


def test_missing_usage_does_not_become_zero_or_emit_an_event():
    events, skipped = build_step_events(
        tool_trace=[trace_record(tool="flag_suspicious_tx")], usage=None, run_id="run-6",
        question_id="case-6", scenario="flag", execution_mode="unit_test",
    )
    assert events == []
    assert skipped == "usage_unavailable"


def test_fake_modes_are_written_as_declared_and_never_promoted_to_real():
    for mode in ("unit_test", "mock", "synthetic"):
        events, skipped = build_step_events(
            tool_trace=[trace_record(tool="flag_suspicious_tx")], usage=USAGE, run_id="run-mode",
            question_id="case-mode", scenario="flag", execution_mode=mode,
        )
        assert skipped is None
        assert events[0]["execution_mode"] == mode
        assert events[0]["execution_mode"] != "real"


@pytest.mark.parametrize(
    ("scenario", "trace"),
    [
        ("freeze", [trace_record(tool="get_account_risk_status")]),
        ("flag", [trace_record(tool="get_account_risk_status")]),
    ],
)
def test_case_scenario_without_matching_write_tool_is_not_recorded_as_action(scenario, trace):
    events, skipped = build_step_events(
        tool_trace=trace, usage=USAGE, run_id="run-mismatch",
        question_id="case-mismatch", scenario=scenario, execution_mode="unit_test",
    )
    assert events == []
    assert skipped == "scenario_write_tool_not_observed"


def test_refusal_event_requires_structured_runtime_metadata_and_trace():
    absent, reason = build_step_events(
        tool_trace=[trace_record()], usage=USAGE, run_id="run-refusal",
        question_id="case-refusal", scenario="refusal", execution_mode="unit_test",
    )
    assert absent == []
    assert reason == "authoritative_refusal_metadata_unavailable"

    events, reason = build_step_events(
        tool_trace=[trace_record()], usage=USAGE, run_id="run-refusal",
        question_id="case-refusal", scenario="refusal", execution_mode="unit_test",
        actual_outcome="refusal", actual_refusal_type="ii",
    )
    assert reason is None
    assert events[0]["actual_outcome"] == "refusal"
    assert events[0]["actual_refusal_type"] == "ii"
    assert events[0]["scenario_evidence_status"] == "structured_runtime_refusal_metadata"

    no_trace, reason = build_step_events(
        tool_trace=[], usage=USAGE, run_id="run-refusal",
        question_id="case-refusal", scenario="refusal", execution_mode="unit_test",
        actual_outcome="refusal", actual_refusal_type="ii",
    )
    assert no_trace == []
    assert reason == "refusal_event_not_supported_without_tool_trace"


def test_completed_write_tool_event_does_not_claim_business_success():
    events, reason = build_step_events(
        tool_trace=[trace_record(
            tool="freeze_account_temporarily", result="Account frozen successfully"
        )],
        usage=USAGE, run_id="run-unverified", question_id="case-unverified",
        scenario="freeze", execution_mode="unit_test",
    )
    assert reason is None
    assert events[0]["status"] == "completed"
    assert events[0]["business_outcome_verified"] is False
    assert events[0]["scenario_evidence_status"] == "tool_call_completed_outcome_unverified"


def test_invalid_or_naive_timestamp_fails_schema_validation():
    event = {
        "record_type": "step_event", "timestamp": "2026-10-14T10:00:00",
        "run_id": "run-7", "question_id": "case-7", "scenario": "refusal",
        "execution_mode": "unit_test", "step": 1, "tool": "refusal",
        "args": {}, "result": "not an actual event", "usage": USAGE,
    }
    assert "timestamp must be ISO-8601 with timezone" in validate_event(event)


def test_malformed_trace_is_rejected_before_append(tmp_path):
    path = tmp_path / "events.jsonl"
    existing, _ = build_step_events(
        tool_trace=[trace_record(tool="flag_suspicious_tx")], usage=USAGE, run_id="old-run",
        question_id="old-case", scenario="flag", execution_mode="unit_test",
    )
    original = json.dumps(existing[0]) + "\n"
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="malformed event"):
        append_step_events(
            path, tool_trace=[{"step": 1}], usage=USAGE, run_id="run-bad",
            question_id="case-bad", scenario="freeze", execution_mode="unit_test",
        )
    assert path.read_text(encoding="utf-8") == original


def test_append_rejects_existing_case_log_without_modifying_it(tmp_path):
    path = tmp_path / "existing-case.jsonl"
    original = '{"record_type":"case"}\n'
    path.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="non-event or invalid record"):
        append_step_events(
            path, tool_trace=[trace_record(tool="freeze_account_temporarily")], usage=USAGE, run_id="run-append",
            question_id="case-append", scenario="freeze", execution_mode="unit_test",
        )
    assert path.read_text(encoding="utf-8") == original


def test_evaluator_appends_partial_fake_trace_in_declared_test_mode_without_agent_call(
    tmp_path, monkeypatch,
):
    from eval import run_eval
    from eval.provenance import register_adapter

    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")
    called = []

    async def fake_adapter(_case):
        called.append("fake adapter")
        return {
            "answer": None,
            "actual_outcome": None,
            "status": "failed",
            "error": "runtime stopped after a tool call",
            "tool_trace": [trace_record(
                status="error", error="private diagnostic", tool="freeze_account_temporarily"
            )],
            "usage": USAGE,
        }

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    case = {
        "id": "fake-freeze-case", "question": "not executed by an agent",
        "category": "no_answer", "allowed_to_answer": False,
        "expected_outcome": "refusal", "expected": {}, "source_refs": [],
        "scenario": "freeze",
    }
    event_path = tmp_path / "events" / "steps.jsonl"
    case_path = tmp_path / "cases.jsonl"
    coroutine = run_eval.evaluate(
        [case], register_adapter(fake_adapter, mode="unit_test", provider_id="fake-step-events"), case_path, case_timeout=1,
        step_events_path=event_path, execution_mode="unit_test",
    )
    try:
        coroutine.send(None)
    except StopIteration as finished:
        summary = finished.value
    else:
        raise AssertionError("fake-only evaluator coroutine unexpectedly suspended")

    event_rows = [json.loads(line) for line in event_path.read_text(encoding="utf-8").splitlines()]
    assert called == ["fake adapter"]
    assert summary["failed"] == 1
    assert summary["step_event_log"] == {"written": 1, "skipped": {}, "errors": 0}
    assert event_rows[0]["execution_mode"] == "unit_test"
    assert event_rows[0]["status"] == "error"
    assert validate_event(event_rows[0]) == []


def test_evaluator_leaves_refusal_without_trace_unscorable_and_writes_no_event(
    tmp_path, monkeypatch,
):
    from eval import run_eval
    from eval.provenance import register_adapter

    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")
    calls = []

    async def fake_adapter(_case):
        calls.append(True)
        return {
            "answer": "refusal text is not a structured outcome",
            "actual_outcome": None,
            "actual_refusal_type": None,
            "tool_trace": [],
            "usage": None,
            "status": "completed",
        }

    async def immediate_wait_for(awaitable, timeout):
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    case = {
        "id": "refusal-without-metadata", "question": "synthetic test input",
        "category": "no_answer", "allowed_to_answer": False,
        "expected_outcome": "refusal", "expected": {}, "source_refs": [],
        "scenario": "refusal",
    }
    event_path = tmp_path / "refusal-events.jsonl"
    case_path = tmp_path / "refusal-case.jsonl"
    coroutine = run_eval.evaluate(
        [case], register_adapter(fake_adapter, mode="unit_test", provider_id="fake-refusal"), case_path, case_timeout=1,
        step_events_path=event_path, execution_mode="unit_test",
    )
    try:
        coroutine.send(None)
    except StopIteration as finished:
        summary = finished.value
    else:
        raise AssertionError("fake-only evaluator coroutine unexpectedly suspended")

    case_row = json.loads(case_path.read_text(encoding="utf-8"))
    assert calls == [True]
    assert summary["unscorable"] == 1
    assert summary["step_event_log"] == {
        "written": 0,
        "skipped": {"authoritative_refusal_metadata_unavailable": 1},
        "errors": 0,
    }
    assert case_row["actual_outcome"] is None
    assert case_row["actual_refusal_type"] is None
    assert not event_path.exists()


def test_case_serialization_failure_does_not_leave_step_event(tmp_path, monkeypatch):
    from eval import run_eval
    from eval.provenance import register_adapter

    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")
    case = {
        "id": "serialize-failure", "question": "synthetic test input",
        "category": "retrieval", "allowed_to_answer": True,
        "expected_outcome": "answer", "expected": {}, "source_refs": [],
        "scenario": "freeze",
    }

    async def fake_adapter(_case):
        trace = trace_record(tool="freeze_account_temporarily")
        trace["arguments"]["unserializable"] = object()
        return {
            "answer": "synthetic answer", "actual_outcome": "answer",
            "tool_trace": [trace], "usage": USAGE,
        }

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    event_path = tmp_path / "events.jsonl"
    case_path = tmp_path / "cases.jsonl"
    coroutine = run_eval.evaluate(
        [case], register_adapter(fake_adapter, mode="unit_test", provider_id="fake-serialization"), case_path, case_timeout=1,
        step_events_path=event_path, execution_mode="unit_test",
    )
    try:
        coroutine.send(None)
    except StopIteration as finished:
        summary = finished.value
    else:
        raise AssertionError("fake-only evaluator coroutine unexpectedly suspended")

    case_row = json.loads(case_path.read_text(encoding="utf-8"))
    assert summary["failed"] == 1
    assert summary["step_event_log"] == {
        "written": 0, "skipped": {"case_serialization_failed": 1}, "errors": 0,
    }
    assert case_row["status"] == "failed"
    assert not event_path.exists()


def test_dry_run_rejects_event_output_without_calling_adapter(tmp_path, monkeypatch):
    import sys
    from eval import run_eval

    output = tmp_path / "events.jsonl"
    monkeypatch.setattr(sys, "argv", [
        "run_eval", "--dry-run", "--step-events-output", str(output),
        "--execution-mode", "real",
    ])
    with pytest.raises(SystemExit) as raised:
        run_eval.main()
    assert raised.value.code == 2
    assert not output.exists()


def test_testset_rejects_invalid_explicit_scenario_before_evaluation():
    from eval.run_eval import DEFAULT_TESTSET, load_testset, validate_testset

    cases = load_testset(DEFAULT_TESTSET)
    cases[0] = {**cases[0], "scenario": "invented"}
    with pytest.raises(ValueError, match="unsupported C4 scenario"):
        validate_testset(cases)
