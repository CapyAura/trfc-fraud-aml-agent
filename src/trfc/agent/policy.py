"""Fail-closed validation for explicit, structured policy input proposals.

This module never parses a free-form question or answer. Inputs are supplied
explicitly by an offline caller and therefore carry synthetic provenance until
an authenticated production source is integrated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PolicyStatus = Literal["needs_information"]


@dataclass(frozen=True, slots=True)
class StructuredPolicyRequest:
    """Caller-provided candidate facts; none are trusted by this contract.

    ``evidence_ref`` identifies the caller's source record. The offline API
    validates that a reference is present but does not authenticate its origin.
    """

    intent: str
    evidence_ref: str | None = None
    payment_method_code: str | None = None
    transaction_log_status: str | None = None


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    status: PolicyStatus
    answer: str | None = None
    actual_outcome: Literal["answer", "refusal"] | None = None
    actual_refusal_type: Literal["i", "ii"] | None = None
    policy_rule_id: str | None = None
    decision_source: str | None = None
    claims: list[str] | None = None
    reason_code: str | None = None


def _needs_information(reason_code: str) -> PolicyDecision:
    return PolicyDecision(status="needs_information", reason_code=reason_code)


def evaluate_structured_request(request: StructuredPolicyRequest) -> PolicyDecision:
    """Validate the request, then require a trusted fact source before deciding.

    Malformed shape/value types raise ``ValueError`` (invalid input). Valid but
    incomplete or unauthenticated facts return ``needs_information``. No
    current input provider authenticates the payment-method or transaction-log
    fields. Freeze and flag intents are unsupported until authenticated
    controller approval and a structured rule-match source are available.
    """
    if type(request) is not StructuredPolicyRequest:
        raise TypeError("request must be StructuredPolicyRequest")
    if not isinstance(request.intent, str) or request.intent not in {
        "payment_method_scope", "transaction_log_assessment", "freeze", "flag"
    }:
        raise ValueError("intent is invalid")
    for field_name in ("evidence_ref", "payment_method_code", "transaction_log_status"):
        value = getattr(request, field_name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{field_name} must be a non-empty string or null")

    if request.intent in {"freeze", "flag"}:
        if request.payment_method_code is not None or request.transaction_log_status is not None:
            raise ValueError("freeze/flag request contains contradictory policy context")
        return _needs_information("authoritative_rule_match_and_approval_source_unavailable")

    if request.intent == "payment_method_scope":
        if request.transaction_log_status is not None:
            raise ValueError("payment scope request contains contradictory transaction-log context")
        method = request.payment_method_code
        if method is None:
            return _needs_information("payment_method_code_unavailable")
        if not request.evidence_ref:
            return _needs_information("source_evidence_reference_unavailable")
        # A caller-supplied reference is not proof that the classification was
        # produced by an authenticated source. No such provider exists here.
        return _needs_information("payment_method_provenance_unverified")

    if request.payment_method_code is not None:
        raise ValueError("transaction-log request contains contradictory payment-method context")
    log_status = request.transaction_log_status
    if log_status is None:
        return _needs_information("transaction_log_completeness_unavailable")
    if log_status not in {"complete", "deleted_after_retention", "sync_error", "unknown"}:
        raise ValueError("transaction_log_status is invalid")
    if not request.evidence_ref:
        return _needs_information("source_evidence_reference_unavailable")
    # The current MCP transaction tool returns rows/errors, not a verified
    # completeness/retention status. A string supplied by a caller cannot
    # establish deletion or synchronization state.
    return _needs_information("transaction_log_provenance_unverified")
