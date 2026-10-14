"""Adapters from runtime results and explicit offline policy inputs to eval rows.

The default adapter calls ``run_detailed`` and passes through its fields. The
separate offline adapter accepts a typed policy request and uses synthetic
provenance; it does not execute the LLM/MCP agent.
"""

from __future__ import annotations

from dataclasses import asdict
from functools import partial
from typing import Any

from trfc.agent.loop import AgentRunResult, run_detailed
from .provenance import RegisteredAdapter, _register_builtin_live_adapter, register_adapter


_RESULT_FIELDS = (
    "answer",
    "actual_outcome",
    "actual_refusal_type",
    "policy_rule_id",
    "decision_source",
    "contexts",
    "claims",
    "tool_trace",
    "usage",
    "status",
    "error",
    "policy_decision_status",
    "policy_reason_code",
)
_VALID_STATUSES = {"completed", "failed", "unscorable"}


_DEFAULT_PROVIDER = object()


async def _run_case(
    case: dict[str, Any], *, model_request: Any = _DEFAULT_PROVIDER
) -> dict[str, Any]:
    """Run one case and preserve the runtime's structured result verbatim.

    Missing metadata remains ``None``. In particular, no decision, refusal
    subtype, claim, usage, or trace state is inferred from answer text.
    Exceptions from ``run_detailed`` propagate to the evaluator, which records
    that case as failed and continues with subsequent cases.
    """
    if not isinstance(case, dict):
        raise TypeError("Evaluation case must be a dict")
    question = case.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Evaluation case needs a non-empty question")

    if model_request is _DEFAULT_PROVIDER:
        result = await run_detailed(question)
    else:
        result = await run_detailed(question, model_request=model_request)
    if not isinstance(result, AgentRunResult):
        raise TypeError("run_detailed() must return AgentRunResult")
    payload = asdict(result)

    status = payload.get("status")
    if status not in _VALID_STATUSES:
        raise ValueError("run_detailed() returned an invalid execution status")
    adapted = {name: payload.get(name) for name in _RESULT_FIELDS}
    # These fields are optional in the current runtime. Preserve them if a
    # compatible runtime result adds the approved structured decision metadata.
    adapted["policy_rule_id"] = getattr(result, "policy_rule_id", adapted["policy_rule_id"])
    adapted["decision_source"] = getattr(result, "decision_source", adapted["decision_source"])
    return adapted


async def _run_default_case(case: dict[str, Any]) -> dict[str, Any]:
    return await _run_case(case)


def _run_offline_policy_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate an explicitly structured request with the offline policy runtime."""
    from trfc.agent.offline import run_policy_offline
    from trfc.agent.policy import StructuredPolicyRequest

    if not isinstance(case, dict) or not isinstance(case.get("policy_request"), dict):
        raise ValueError("Offline policy case needs a structured policy_request object")
    allowed = {"intent", "evidence_ref", "payment_method_code", "transaction_log_status"}
    raw = case["policy_request"]
    extra = set(raw) - allowed
    if extra:
        raise ValueError("Offline policy request has unsupported fields")
    try:
        request = StructuredPolicyRequest(**raw)
    except TypeError as exc:
        raise ValueError("Offline policy request has malformed fields") from exc
    return asdict(run_policy_offline(request))


# This explicit registration is tied to run_detailed's built-in default provider.
run_case: RegisteredAdapter = _register_builtin_live_adapter(_run_default_case)
offline_policy_case: RegisteredAdapter = register_adapter(
    _run_offline_policy_case, mode="synthetic", provider_id="offline-policy-v1"
)


def build_adapter(
    model_request,
    *,
    mode: str,
    provider_id: str = "injected-provider",
) -> RegisteredAdapter:
    """Build an evaluator adapter around an explicitly injected fake provider.

    Injected providers can register as mock/unit_test/synthetic only. The
    standard builder deliberately offers no way to label one as ``real``.
    """
    if not callable(model_request):
        raise TypeError("model_request must be callable")
    handler = partial(_run_case, model_request=model_request)
    return register_adapter(handler, mode=mode, provider_id=provider_id)
