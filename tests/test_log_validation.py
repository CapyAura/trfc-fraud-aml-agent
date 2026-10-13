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
        "contexts": None, "claims": None, "tool_trace": None, "usage": None,
        "metrics": {}, "error": None, "status": "completed",
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


def test_event_schema_accepts_declared_fixture_but_does_not_authenticate_it():
    assert validate_event(event_row()) == []
    assert event_row()["execution_mode"] == "unit_test"


def test_event_rejects_missing_usage_and_bad_tool_arguments():
    row = event_row()
    row["usage"] = None
    row["args"] = []
    errors = validate_event(row)
    assert "args must be an object" in errors
    assert "usage must contain non-negative integer counters" in errors


def test_completed_row_with_wrong_outcome_is_invalid():
    row = case_row()
    row["actual_outcome"] = "unknown"
    assert "completed row needs actual_outcome answer or refusal" in validate_case(row)


def test_malformed_json_values_are_reported_without_crashing():
    row = event_row()
    row["scenario"] = {"unexpected": "object"}
    row["execution_mode"] = []
    assert "scenario must be freeze, flag, or refusal" in validate_event(row)
    assert any("execution_mode" in error for error in validate_event(row))


def test_jsonl_errors_include_line_number_and_continue(tmp_path):
    path = tmp_path / "trace.jsonl"
    path.write_text(json.dumps(event_row()) + "\nnot json\n" + json.dumps(event_row()) + "\n", encoding="utf-8")
    errors = validate_file(path, "event")
    assert len(errors) == 1
    assert ":2: invalid JSON:" in errors[0]
