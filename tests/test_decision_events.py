"""Fake-only tests for the separate C4 decision-event channel."""

import json

import pytest

from eval.decision_events import append_decision_event, build_decision_event
from eval.log_validation import validate_decision_event, validate_file


def _fields(**overrides):
    fields = {
        "run_id": "run-unit-1",
        "question_id": "case-unit-1",
        "execution_mode": "unit_test",
        "actual_outcome": "refusal",
        "actual_refusal_type": "ii",
        "policy_rule_id": None,
        "decision_source": "fake_policy.branch_v1",
        "tool_trace": [],
    }
    fields.update(overrides)
    return fields


def test_refusal_without_tool_call_is_a_decision_not_a_tool_event():
    event, reason = build_decision_event(**_fields())

    assert reason is None
    assert event["record_type"] == "decision_event"
    assert event["actual_outcome"] == "refusal"
    assert event["actual_refusal_type"] == "ii"
    assert event["tool_trace_status"] == "complete"
    assert event["tool_call_count"] == 0
    assert "tool" not in event and "step" not in event
    assert event["business_outcome_verified"] is False
    assert validate_decision_event(event) == []


@pytest.mark.parametrize(("outcome", "refusal_type"), [("answer", None), ("refusal", "i"), ("refusal", "ii")])
def test_all_project_outcome_and_refusal_types_validate(outcome, refusal_type):
    event, reason = build_decision_event(
        **_fields(actual_outcome=outcome, actual_refusal_type=refusal_type),
    )
    assert reason is None
    assert event["actual_outcome"] == outcome
    assert event["actual_refusal_type"] == refusal_type
    assert validate_decision_event(event) == []


def test_unavailable_trace_stays_unavailable_and_not_zero_calls():
    event, reason = build_decision_event(**_fields(tool_trace=None))

    assert reason is None
    assert event["tool_trace_status"] == "unavailable"
    assert event["tool_call_count"] is None


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"actual_outcome": None}, "actual_outcome_unavailable"),
        ({"actual_outcome": "refusal", "actual_refusal_type": None}, "actual_refusal_type_unavailable"),
        ({"actual_outcome": "answer", "actual_refusal_type": "i"}, "refusal_type_on_answer_outcome"),
        ({"decision_source": None}, "decision_source_unavailable"),
        ({"tool_trace": [{"malformed": True}]}, "tool_trace_invalid"),
    ],
)
def test_incomplete_or_inconsistent_runtime_metadata_does_not_emit(overrides, reason):
    event, skipped = build_decision_event(**_fields(**overrides))
    assert event is None
    assert skipped == reason


@pytest.mark.parametrize(
    ("overrides", "skip_reason"),
    [
        ({"actual_refusal_type": "iii"}, "actual_refusal_type_unavailable"),
        ({"tool_trace": "not-a-list"}, "tool_trace_invalid"),
    ],
)
def test_invalid_runtime_labels_or_trace_do_not_emit(overrides, skip_reason):
    event, reason = build_decision_event(**_fields(**overrides))
    assert event is None
    assert reason == skip_reason


@pytest.mark.parametrize(
    "overrides",
    [
        {"policy_rule_id": "rule id with spaces"},
        {"decision_source": "unstructured decision explanation"},
    ],
)
def test_malformed_identifiers_are_rejected(overrides):
    with pytest.raises(ValueError):
        build_decision_event(**_fields(**overrides))


def test_validator_rejects_refusal_answer_and_trace_inconsistencies(tmp_path):
    event, _ = build_decision_event(**_fields())
    bad_subtype = {**event, "actual_refusal_type": None}
    assert "refusal decision needs actual_refusal_type i or ii" in validate_decision_event(bad_subtype)

    bad_trace = {**event, "tool_trace_status": "unavailable", "tool_call_count": 0}
    assert "unavailable tool trace must have null tool_call_count" in validate_decision_event(bad_trace)

    path = tmp_path / "decision-events.jsonl"
    path.write_text(json.dumps(event) + "\n" + json.dumps(bad_subtype) + "\n", encoding="utf-8")
    errors = validate_file(path, "decision")
    assert len(errors) == 1
    assert ":2:" in errors[0]


def test_append_is_append_only_and_schema_validation_succeeds(tmp_path):
    path = tmp_path / "nested" / "decisions.jsonl"
    assert append_decision_event(path, **_fields()) is None
    original = path.read_text(encoding="utf-8")
    assert append_decision_event(path, **_fields(run_id="run-unit-2")) is None
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert path.read_text(encoding="utf-8").startswith(original)
    assert [row["run_id"] for row in rows] == ["run-unit-1", "run-unit-2"]
    assert validate_file(path, "decision") == []


def test_evaluator_writes_only_runtime_supplied_decision_and_no_fake_tool_event(tmp_path, monkeypatch):
    from eval import agent_adapter, run_eval
    from eval.provenance import register_adapter
    from eval.run_eval import DEFAULT_TESTSET, load_testset
    from trfc.agent.loop import AgentRunResult

    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated-eval.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")
    case = {**load_testset(DEFAULT_TESTSET)[0], "id": "expected-answer-actual-refusal"}
    case["scenario"] = "refusal"
    provider_calls = []

    def fake_provider(messages, *, tools):
        provider_calls.append(messages)
        return "fake response"

    async def fake_run_detailed(question, *, model_request):
        model_request([{"role": "user", "content": question}], tools=[])
        result = AgentRunResult(
            answer="A fake-provider response containing refusal language.",
            actual_outcome="refusal",
            actual_refusal_type="ii",
            tool_trace=[],
            status="completed",
        )
        # Simulate only the agreed structured runtime fields; this is a unit
        # fixture and cannot be used as genuine scenario evidence.
        result.policy_rule_id = None
        result.decision_source = "fake_policy.branch_v1"
        return result

    async def immediate_wait_for(awaitable, timeout):
        return await awaitable

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    adapter = agent_adapter.build_adapter(
        fake_provider, mode="unit_test", provider_id="fake-policy-provider",
    )
    case_path = tmp_path / "cases.jsonl"
    tool_path = tmp_path / "tool-events.jsonl"
    decision_path = tmp_path / "decision-events.jsonl"

    coroutine = run_eval.evaluate(
        [case], adapter, case_path, case_timeout=1,
        step_events_path=tool_path, decision_events_path=decision_path,
        execution_mode="unit_test",
    )
    try:
        coroutine.send(None)
    except StopIteration as finished:
        result_summary = finished.value
    else:
        raise AssertionError("fake-only evaluator coroutine unexpectedly suspended")

    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    assert provider_calls == [[{"role": "user", "content": case["question"]}]]
    assert result_summary["completed"] == 1
    assert decision["actual_outcome"] == "refusal"
    assert decision["question_id"] == case["id"]
    assert decision["execution_mode"] == "unit_test"
    assert decision["tool_trace_status"] == "complete"
    assert decision["tool_call_count"] == 0
    assert not tool_path.exists()
    assert validate_file(decision_path, "decision") == []
