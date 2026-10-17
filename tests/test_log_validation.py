import json

from eval.log_validation import validate_case, validate_event, validate_file


def case_row():
    return {
        "timestamp": "2026-10-13T12:00:00+00:00", "question_id": "q1",
        "category": "retrieval", "expected_outcome": "answer",
        "allowed_to_answer": True, "expected_refusal_type": None,
        "expected": {"criteria_type": "contains_all", "values": ["limit"]},
        "source_refs": ["DOC0001"], "actual_answer": "limit",
        "actual_outcome": "answer", "actual_refusal_type": None,
        "contexts": None, "claims": None, "tool_trace": [], "usage": None,
        "metrics": {}, "error": None, "status": "completed",
    }


def tool_trace_record():
    return {
        "step": 1, "tool_call_id": "call-1", "tool_name": "search_policy",
        "arguments": {"query": "transfer limits"}, "result": "[]",
        "status": "completed", "error": None,
    }


def event_row():
    return {
        "record_type": "step_event", "timestamp": "2026-10-13T12:00:00Z",
        "run_id": "run-test", "question_id": "q-freeze", "scenario": "freeze",
        "execution_mode": "unit_test", "step": 1, "tool": "freeze_account",
        "args": {"account_id": "TEST"}, "result": {"frozen": True},
        "usage": {"calls": 1, "prompt_tokens": 2, "completion_tokens": 3, "max_prompt": 4},
    }


def test_completed_case_schema_allows_unavailable_usage():
    assert validate_case(case_row()) == []


def test_policy_decision_status_rejects_untrusted_or_inconsistent_metadata():
    needs_info = case_row()
    needs_info.update({
        "policy_decision_status": "needs_information",
        "policy_reason_code": "payment_method_provenance_unverified",
        "status": "unscorable",
        "actual_outcome": None,
        "actual_refusal_type": None,
        "policy_rule_id": None,
        "decision_source": None,
    })
    assert validate_case(needs_info) == []

    forged_decision = dict(needs_info)
    forged_decision["actual_outcome"] = "refusal"
    forged_decision["actual_refusal_type"] = "i"
    assert "needs_information policy status cannot contain decision metadata" in validate_case(forged_decision)

    incomplete_decision = case_row()
    incomplete_decision["policy_decision_status"] = "decided"
    assert "decided policy status needs a structured decision_source" in validate_case(incomplete_decision)


def test_usage_keeps_calls_but_allows_unknown_provider_token_counts():
    row = case_row()
    row["usage"] = {
        "calls": 2, "prompt_tokens": None,
        "completion_tokens": None, "max_prompt": None,
    }
    assert validate_case(row) == []
    event = event_row()
    event["usage"] = row["usage"]
    assert validate_event(event) == []
    event["usage"] = {**row["usage"], "max_prompt": 3}
    assert "usage must contain calls and non-negative/unknown token counters" in validate_event(event)


def test_event_schema_accepts_declared_fixture_but_does_not_authenticate_it():
    assert validate_event(event_row()) == []
    assert event_row()["execution_mode"] == "unit_test"


def test_all_execution_modes_are_schema_labels_not_provenance_proof(tmp_path, capsys):
    from eval.log_validation import main

    path = tmp_path / "events.jsonl"
    for mode in ("real", "mock", "dry_run", "unit_test", "synthetic"):
        row = event_row()
        row["execution_mode"] = mode
        assert validate_event(row) == []
        path.write_text(json.dumps(row) + "\n", encoding="utf-8")
        assert main(["--kind", "event", str(path)]) == 0
        assert "Provenance/authenticity not verified" in capsys.readouterr().out


def test_event_rejects_missing_usage_and_bad_tool_arguments():
    row = event_row()
    row["usage"] = None
    row["args"] = []
    errors = validate_event(row)
    assert "args must be an object" in errors
    assert "usage must contain calls and non-negative/unknown token counters" in errors


def test_completed_row_with_wrong_outcome_is_invalid():
    row = case_row()
    row["actual_outcome"] = "unknown"
    assert "completed row needs actual_outcome answer or refusal" in validate_case(row)


def test_completed_rows_preserve_null_empty_and_populated_trace_states():
    unavailable = case_row()
    unavailable["tool_trace"] = None
    assert validate_case(unavailable) == []
    assert unavailable["tool_trace"] is None

    no_calls = case_row()
    no_calls["tool_trace"] = []
    assert validate_case(no_calls) == []
    assert no_calls["tool_trace"] == []

    with_calls = case_row()
    with_calls["tool_trace"] = [tool_trace_record()]
    assert validate_case(with_calls) == []
    assert with_calls["tool_trace"][0]["tool_name"] == "search_policy"


def test_case_jsonl_validation_does_not_convert_null_trace_to_empty_list(tmp_path):
    path = tmp_path / "completed-null-trace.jsonl"
    row = case_row()
    row["tool_trace"] = None
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    assert validate_file(path, "case") == []
    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert persisted["tool_trace"] is None


def test_trace_status_combinations_reject_inconsistent_empty_and_malformed_traces():
    failed_empty = case_row()
    failed_empty["status"] = "failed"
    failed_empty["error"] = "RuntimeError: interrupted before trace event"
    failed_empty["tool_trace"] = []
    assert "failed row cannot claim an empty completed tool trace" in validate_case(
        failed_empty
    )

    failed_partial = case_row()
    failed_partial["status"] = "failed"
    failed_partial["error"] = "RuntimeError: later model failure"
    failed_partial["tool_trace"] = [tool_trace_record()]
    assert validate_case(failed_partial) == []

    malformed = case_row()
    malformed["tool_trace"] = [{"tool_name": "search_policy"}]
    assert any("tool_trace must be null or a list" in error for error in validate_case(malformed))

    invalid_status = case_row()
    invalid_status["tool_trace"] = [{**tool_trace_record(), "status": []}]
    assert any("tool_trace must be null or a list" in error for error in validate_case(invalid_status))


def test_case_status_distinguishes_missing_outcome_runtime_error_and_not_applicable():
    missing_decision = case_row()
    missing_decision["status"] = "unscorable"
    missing_decision["actual_outcome"] = None
    missing_decision["metrics"] = {"refusal_correctness": None}
    assert validate_case(missing_decision) == []

    completed_without_trace = case_row()
    completed_without_trace["tool_trace"] = None
    assert validate_case(completed_without_trace) == []

    runtime_error = case_row()
    runtime_error["status"] = "failed"
    runtime_error["error"] = "RuntimeError: MCP unavailable"
    runtime_error["tool_trace"] = None
    assert validate_case(runtime_error) == []

    invalid_error = case_row()
    invalid_error["status"] = "failed"
    invalid_error["error"] = None
    assert "failed row needs a non-empty runtime error" in validate_case(invalid_error)

    failed_with_empty_trace = case_row()
    failed_with_empty_trace["status"] = "failed"
    failed_with_empty_trace["error"] = "RuntimeError: MCP unavailable"
    failed_with_empty_trace["tool_trace"] = []
    assert "failed row cannot claim an empty completed tool trace" in validate_case(
        failed_with_empty_trace
    )

    answer_with_refusal_type = case_row()
    answer_with_refusal_type["actual_refusal_type"] = "i"
    assert "actual_refusal_type is only applicable to a refusal outcome" in validate_case(
        answer_with_refusal_type
    )


def test_malformed_json_values_are_reported_without_crashing():
    row = event_row()
    row["scenario"] = {"unexpected": "object"}
    row["execution_mode"] = []
    assert "scenario must be freeze, flag, or refusal" in validate_event(row)
    assert any("execution_mode" in error for error in validate_event(row))


def test_claims_accept_bare_strings_and_judge_records():
    bare = case_row()
    bare["claims"] = ["limit"]
    assert validate_case(bare) == []

    judged = case_row()
    judged["claims"] = [{"text": "limit", "label": "supported",
                         "evidence_doc_id": "DOC0001"}]
    assert validate_case(judged) == []

    minimal = case_row()
    minimal["claims"] = [{"text": "limit"}]
    assert validate_case(minimal) == []

    wrong_label = case_row()
    wrong_label["claims"] = [{"text": "limit", "label": "maybe"}]
    assert "claims[0].label must be supported or unsupported" in validate_case(wrong_label)

    missing_text = case_row()
    missing_text["claims"] = [{"label": "supported"}]
    assert "claims[0].text must be a string" in validate_case(missing_text)

    bad_doc = case_row()
    bad_doc["claims"] = [{"text": "limit", "evidence_doc_id": "DOC1"}]
    assert any("evidence_doc_id" in error for error in validate_case(bad_doc))

    not_a_list = case_row()
    not_a_list["claims"] = {"text": "limit"}
    assert "claims must be null or a list" in validate_case(not_a_list)


def test_contexts_must_still_be_strings():
    row = case_row()
    row["contexts"] = [{"doc_id": "DOC0001"}]
    assert "contexts must be null or a list of strings" in validate_case(row)


def test_jsonl_errors_include_line_number_and_continue(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps(event_row()) + "\nnot json\n" + json.dumps(event_row()) + "\n", encoding="utf-8")
    errors = validate_file(path, "event")
    assert len(errors) == 1
    assert ":2: invalid JSON:" in errors[0]
