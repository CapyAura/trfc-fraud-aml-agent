"""Explicit offline structured-policy entry point; never invokes an LLM/MCP."""

from __future__ import annotations

from trfc.agent.loop import AgentRunResult
from trfc.agent.policy import StructuredPolicyRequest, evaluate_structured_request


def run_policy_offline(request: StructuredPolicyRequest) -> AgentRunResult:
    """Run the supported deterministic policy branch without external services.

    This API does not execute tools or mutate a database. Its facts must be
    supplied by the caller, so results have synthetic provenance and are not
    genuine production scenario evidence.
    """
    decision = evaluate_structured_request(request)
    return AgentRunResult(
        answer=decision.answer,
        actual_outcome=decision.actual_outcome,
        actual_refusal_type=decision.actual_refusal_type,
        policy_rule_id=decision.policy_rule_id,
        decision_source=decision.decision_source,
        claims=decision.claims,
        tool_trace=[],
        status="completed",
        policy_decision_status=decision.status,
        policy_reason_code=decision.reason_code,
    )
