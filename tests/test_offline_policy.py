import json

import pytest

from eval.agent_adapter import offline_policy_case
from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset
from trfc.agent import loop
from trfc.agent.offline import run_policy_offline
from trfc.agent.policy import StructuredPolicyRequest, evaluate_structured_request


def _run_immediate(coroutine, monkeypatch):
    from eval import run_eval

    async def immediate_wait_for(awaitable, timeout):
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("offline evaluator coroutine unexpectedly suspended")


def test_caller_asserted_scope_facts_do_not_produce_authoritative_decisions():
    included = evaluate_structured_request(StructuredPolicyRequest(
        intent="payment_method_scope", evidence_ref="case:method-1", payment_method_code="PM01",
    ))
    assert included.status == "needs_information"
    assert included.actual_outcome is None
    assert included.policy_rule_id is None
    assert included.reason_code == "payment_method_provenance_unverified"

    excluded = evaluate_structured_request(StructuredPolicyRequest(
        intent="payment_method_scope", evidence_ref="case:method-2",
        payment_method_code="third_party_ewallet",
    ))
    assert excluded.status == "needs_information"
    assert excluded.actual_outcome is None and excluded.actual_refusal_type is None
    assert excluded.policy_rule_id is None
    assert excluded.reason_code == "payment_method_provenance_unverified"
    assert excluded.claims is None


def test_caller_asserted_log_status_does_not_produce_refusal():
    deleted = evaluate_structured_request(StructuredPolicyRequest(
        intent="transaction_log_assessment", evidence_ref="case:logs-1",
        transaction_log_status="deleted_after_retention",
    ))
    assert deleted.status == "needs_information"
    assert deleted.actual_outcome is None and deleted.actual_refusal_type is None
    assert deleted.policy_rule_id is None
    assert deleted.reason_code == "transaction_log_provenance_unverified"

    sync = evaluate_structured_request(StructuredPolicyRequest(
        intent="transaction_log_assessment", evidence_ref="case:logs-2",
        transaction_log_status="sync_error",
    ))
    assert sync.status == "needs_information"
    assert sync.actual_outcome is None and sync.actual_refusal_type is None
    assert sync.reason_code == "transaction_log_provenance_unverified"


@pytest.mark.parametrize("policy_request,reason", [
    (StructuredPolicyRequest("payment_method_scope", evidence_ref="r"), "payment_method_code_unavailable"),
    (StructuredPolicyRequest("payment_method_scope", payment_method_code="PM01"), "source_evidence_reference_unavailable"),
    (StructuredPolicyRequest("payment_method_scope", evidence_ref="r", payment_method_code="unknown"), "payment_method_provenance_unverified"),
    (StructuredPolicyRequest("payment_method_scope", evidence_ref="r", payment_method_code="PM01"), "payment_method_provenance_unverified"),
    (StructuredPolicyRequest("transaction_log_assessment", evidence_ref="r", transaction_log_status="unknown"), "transaction_log_provenance_unverified"),
    (StructuredPolicyRequest("freeze", evidence_ref="r"), "authoritative_rule_match_and_approval_source_unavailable"),
    (StructuredPolicyRequest("flag", evidence_ref="r"), "authoritative_rule_match_and_approval_source_unavailable"),
])
def test_missing_or_unsupported_facts_stay_unavailable(policy_request, reason):
    decision = evaluate_structured_request(policy_request)
    assert decision.status == "needs_information"
    assert decision.actual_outcome is None
    assert decision.actual_refusal_type is None
    assert decision.policy_rule_id is None
    assert decision.decision_source is None
    assert decision.reason_code == reason


def test_invalid_structured_input_is_rejected():
    with pytest.raises(ValueError, match="intent is invalid"):
        evaluate_structured_request(StructuredPolicyRequest("classify_from_text"))
    with pytest.raises(ValueError, match="transaction_log_status is invalid"):
        evaluate_structured_request(StructuredPolicyRequest(
            "transaction_log_assessment", evidence_ref="r", transaction_log_status="partial_guess",
        ))
    with pytest.raises(ValueError, match="contradictory"):
        evaluate_structured_request(StructuredPolicyRequest(
            "payment_method_scope", evidence_ref="r", payment_method_code="PM01",
            transaction_log_status="complete",
        ))
    with pytest.raises(ValueError, match="contradictory"):
        evaluate_structured_request(StructuredPolicyRequest(
            "freeze", evidence_ref="r", payment_method_code="PM01",
        ))


def test_offline_adapter_rejects_caller_forged_authorization_and_freshness_fields():
    with pytest.raises(ValueError, match="unsupported fields"):
        offline_policy_case({"policy_request": {
            "intent": "freeze", "evidence_ref": "r",
            "operator_id": "controller-1", "approval_ref": "approved-1",
            "observed_at": "2099-01-01T00:00:00+00:00",
        }})


def test_offline_runtime_and_evaluator_fail_closed_without_llm(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated-never-opened.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")

    def forbidden(*args, **kwargs):
        raise AssertionError("offline policy path must not call the live agent/provider")

    monkeypatch.setattr(loop, "run_detailed", forbidden)
    monkeypatch.setattr(loop, "call_llm_async", forbidden)
    result = run_policy_offline(StructuredPolicyRequest(
        intent="payment_method_scope", evidence_ref="case:offline-1",
        payment_method_code="crypto",
    ))
    assert result.status == "completed"
    assert result.actual_outcome is None
    assert result.actual_refusal_type is None
    assert result.tool_trace == []
    assert result.usage is None
    assert result.claims is None

    case = dict(load_testset(DEFAULT_TESTSET)[8])
    case["policy_request"] = {
        "intent": "payment_method_scope",
        "evidence_ref": "case:offline-1",
        "payment_method_code": "crypto",
    }
    cases_path = tmp_path / "cases.jsonl"
    decisions_path = tmp_path / "decisions.jsonl"
    summary = _run_immediate(evaluate(
        [case], offline_policy_case, cases_path, decision_events_path=decisions_path,
    ), monkeypatch)
    assert summary["unscorable"] == 1
    row = json.loads(cases_path.read_text(encoding="utf-8"))
    assert row["status"] == "unscorable"
    assert row["policy_decision_status"] == "needs_information"
    assert row["policy_reason_code"] == "payment_method_provenance_unverified"
    assert row["actual_outcome"] is None
    assert row["actual_refusal_type"] is None
    assert row["tool_trace"] == []
    assert row["usage"] is None
    assert row["claims"] is None
    assert not decisions_path.exists()
    assert offline_policy_case.provenance.execution_mode == "synthetic"

    from eval.provenance import resolve_execution_mode
    with pytest.raises(ValueError, match="conflicts with registered"):
        resolve_execution_mode(offline_policy_case, "real")


def test_offline_needs_information_is_unscorable_without_decision_event(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated-never-opened.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")
    case = dict(load_testset(DEFAULT_TESTSET)[10])
    case["policy_request"] = {
        "intent": "transaction_log_assessment",
        "evidence_ref": "case:offline-2",
        "transaction_log_status": "sync_error",
    }
    cases_path = tmp_path / "cases.jsonl"
    decisions_path = tmp_path / "decisions.jsonl"
    summary = _run_immediate(evaluate(
        [case], offline_policy_case, cases_path, decision_events_path=decisions_path,
    ), monkeypatch)
    row = json.loads(cases_path.read_text(encoding="utf-8"))
    assert summary["unscorable"] == 1
    assert row["status"] == "unscorable"
    assert row["policy_decision_status"] == "needs_information"
    assert row["actual_outcome"] is None
    assert row["policy_reason_code"] == "transaction_log_provenance_unverified"
    assert not decisions_path.exists()


def test_subclassing_structured_policy_request_is_rejected():
    class SubclassedRequest(StructuredPolicyRequest):
        extra_field: str = "spoofed"

    subclassed = SubclassedRequest("payment_method_scope", evidence_ref="r", payment_method_code="PM01")
    with pytest.raises(TypeError, match="request must be StructuredPolicyRequest"):
        evaluate_structured_request(subclassed)


def test_evaluator_clears_decision_metadata_on_failed_or_invalid_status(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated-never-opened.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")

    case = dict(load_testset(DEFAULT_TESTSET)[0])

    def spoofed_failed_adapter(_case):
        return {
            "answer": "some answer",
            "actual_outcome": "answer",
            "actual_refusal_type": "i",
            "policy_rule_id": "RULE_1",
            "decision_source": "spoofed.source",
            "policy_decision_status": "decided",
            "status": "failed",
            "error": "runtime crash",
        }

    cases_path = tmp_path / "failed_cases.jsonl"
    summary = _run_immediate(evaluate([case], spoofed_failed_adapter, cases_path), monkeypatch)
    assert summary["failed"] == 1
    row = json.loads(cases_path.read_text(encoding="utf-8"))
    assert row["status"] == "failed"
    assert row["actual_outcome"] is None
    assert row["actual_refusal_type"] is None
    assert row["policy_rule_id"] is None
    assert row["decision_source"] is None
    assert row["policy_decision_status"] is None

    def invalid_status_adapter(_case):
        return {
            "answer": "some answer",
            "actual_outcome": "answer",
            "status": "unrecognized_status",
        }

    invalid_path = tmp_path / "invalid_cases.jsonl"
    summary2 = _run_immediate(evaluate([case], invalid_status_adapter, invalid_path), monkeypatch)
    assert summary2["failed"] == 1
    row2 = json.loads(invalid_path.read_text(encoding="utf-8"))
    assert row2["status"] == "failed"
    assert "invalid execution status" in row2["error"]
    assert row2["actual_outcome"] is None


def test_contradictory_policy_decision_status_and_refusal_subtype_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated-never-opened.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")

    case = dict(load_testset(DEFAULT_TESTSET)[0])

    # Needs-information with contradictory outcome/subtype
    def needs_info_with_outcome_adapter(_case):
        return {
            "answer": "answer text",
            "actual_outcome": "refusal",
            "actual_refusal_type": "i",
            "policy_decision_status": "needs_information",
            "policy_reason_code": "payment_method_provenance_unverified",
            "status": "completed",
        }

    p1 = tmp_path / "needs_info_outcome.jsonl"
    s1 = _run_immediate(evaluate([case], needs_info_with_outcome_adapter, p1), monkeypatch)
    assert s1["unscorable"] == 1
    r1 = json.loads(p1.read_text(encoding="utf-8"))
    assert r1["status"] == "unscorable"
    assert r1["actual_outcome"] is None
    assert r1["actual_refusal_type"] is None
    assert r1["policy_decision_status"] == "needs_information"

    # Answer outcome with contradictory refusal subtype
    def answer_with_refusal_subtype_adapter(_case):
        return {
            "answer": "answer text",
            "actual_outcome": "answer",
            "actual_refusal_type": "ii",
            "status": "completed",
        }

    p2 = tmp_path / "answer_subtype.jsonl"
    s2 = _run_immediate(evaluate([case], answer_with_refusal_subtype_adapter, p2), monkeypatch)
    assert s2["completed"] == 1
    r2 = json.loads(p2.read_text(encoding="utf-8"))
    assert r2["status"] == "completed"
    assert r2["actual_outcome"] == "answer"
    assert r2["actual_refusal_type"] is None


def test_unscorable_status_clears_candidate_decision_fields_and_persists_unscorable(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated-never-opened.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")

    case = dict(load_testset(DEFAULT_TESTSET)[0])

    def unscorable_adapter_with_candidate_metadata(_case):
        return {
            "answer": "valid answer text",
            "actual_outcome": "answer",
            "actual_refusal_type": "i",
            "policy_rule_id": "RULE_DOC0009",
            "decision_source": "upstream.risk_engine",
            "policy_decision_status": "decided",
            "status": "unscorable",
        }

    p = tmp_path / "unscorable_cases.jsonl"
    s = _run_immediate(evaluate([case], unscorable_adapter_with_candidate_metadata, p), monkeypatch)
    assert s["unscorable"] == 1
    assert s["completed"] == 0
    assert s["failed"] == 0
    row = json.loads(p.read_text(encoding="utf-8"))
    assert row["status"] == "unscorable"
    assert row["actual_outcome"] is None
    assert row["actual_refusal_type"] is None
    assert row["policy_rule_id"] is None
    assert row["decision_source"] is None
    assert row["policy_decision_status"] is None


def test_invalid_structured_identifier_and_decided_status_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated-never-opened.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")

    case = dict(load_testset(DEFAULT_TESTSET)[0])

    # Case 1: decided status with invalid decision_source (contains spaces)
    def invalid_decision_source_adapter(_case):
        return {
            "answer": "answer text",
            "actual_outcome": "answer",
            "decision_source": "invalid source with spaces",
            "policy_rule_id": "RULE_1",
            "policy_decision_status": "decided",
            "status": "completed",
        }

    p1 = tmp_path / "invalid_source.jsonl"
    s1 = _run_immediate(evaluate([case], invalid_decision_source_adapter, p1), monkeypatch)
    assert s1["completed"] == 1
    r1 = json.loads(p1.read_text(encoding="utf-8"))
    assert r1["decision_source"] is None
    assert r1["policy_decision_status"] is None  # cleared because decision_source was invalid
    assert r1["policy_rule_id"] == "RULE_1"

    # Case 2: invalid policy_rule_id
    def invalid_policy_rule_adapter(_case):
        return {
            "answer": "answer text",
            "actual_outcome": "answer",
            "decision_source": "valid_source",
            "policy_rule_id": "invalid rule with spaces!",
            "policy_decision_status": "decided",
            "status": "completed",
        }

    p2 = tmp_path / "invalid_rule.jsonl"
    s2 = _run_immediate(evaluate([case], invalid_policy_rule_adapter, p2), monkeypatch)
    assert s2["completed"] == 1
    r2 = json.loads(p2.read_text(encoding="utf-8"))
    assert r2["policy_rule_id"] is None
    assert r2["decision_source"] == "valid_source"
    assert r2["policy_decision_status"] == "decided"


def test_agent_adapter_accepts_unscorable_status(monkeypatch):
    from eval import agent_adapter
    from trfc.agent.loop import AgentRunResult

    runtime = AgentRunResult(
        answer="unscorable answer",
        status="unscorable",
    )

    async def fake_run_detailed(question):
        return runtime

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)

    async def _invoke():
        return await agent_adapter.run_case({"question": "test question"})

    try:
        coro = _invoke()
        coro.send(None)
    except StopIteration as finished:
        result = finished.value
    assert result["status"] == "unscorable"
    assert result["answer"] == "unscorable answer"
