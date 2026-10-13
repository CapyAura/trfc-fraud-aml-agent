"""Deterministic evaluation helpers.

Faithfulness is intentionally conservative: it only scores explicit claims that
are exact substrings (case-insensitive) of retrieved context. This is not a
semantic judge; paraphrases and unsupported claims are unscorable/unsupported.
"""

from __future__ import annotations

import re
from typing import Any


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_literal(text: str, literal: str) -> bool:
    """Match a normalized phrase without accepting a substring of a token."""
    phrase = _norm(literal)
    if not phrase:
        return False
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", _norm(text)) is not None


def faithfulness(answer: str | None, contexts: list[str] | None,
                 claims: list[str] | None = None) -> float | None:
    """Fraction of supplied factual claims literally supported by context.

    Returns None when answer/context/claim segmentation is unavailable. The
    function never treats an empty answer as a perfect score.
    """
    if not answer or not contexts or claims is None:
        return None
    factual_claims = [claim.strip() for claim in claims if claim and claim.strip()]
    if not factual_claims:
        return None
    answer_norm = _norm(answer)
    # Reject malformed adapter claims instead of allowing a caller to provide
    # claims unrelated to the response and obtain an artificially high score.
    if any(not _contains_literal(answer_norm, claim) for claim in factual_claims):
        return None
    joined_context = _norm("\n".join(contexts))
    return sum(
        _contains_literal(joined_context, claim) for claim in factual_claims
    ) / len(factual_claims)


def context_precision(question: str | None, contexts: list[str] | None,
                      relevant_sources: list[str] | None = None) -> float | None:
    """Precision of retrieved contexts by explicit source ID relevance.

    Context strings must carry a DOCnnnn identifier. Without gold relevant
    sources or retrieved contexts, the metric is unscorable (None).
    """
    if not question or not contexts or relevant_sources is None or not relevant_sources:
        return None
    retrieved_ids = [
        next(iter(re.findall(r"(?<![A-Z0-9])DOC\d{4}(?![A-Z0-9])", context, flags=re.IGNORECASE)), None)
        for context in contexts
    ]
    if not retrieved_ids:
        return None
    # Missing source metadata is unknown, not proof of irrelevance.
    if any(source is None for source in retrieved_ids):
        return None
    relevant = {source.upper() for source in relevant_sources}
    return sum(
        source.upper() in relevant for source in retrieved_ids if source is not None
    ) / len(retrieved_ids)


def answer_correctness(answer: str | None, expected: dict[str, Any] | None,
                       allowed_to_answer: bool) -> bool | None:
    """Check objective `contains_all` criteria for answerable questions."""
    if not allowed_to_answer or not answer or not expected:
        return None
    values = expected.get("values")
    if expected.get("criteria_type") != "contains_all" or not isinstance(values, list) or not values:
        return None
    return all(_contains_literal(answer, str(value)) for value in values)


def refusal_rate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Score answer/refusal decisions and subtype correctness; exclude unknowns."""
    decision_scored = decision_correct = subtype_scored = subtype_correct = 0
    by_type = {kind: {"correct": 0, "total": 0, "scored": 0, "unscorable": 0}
               for kind in ("i", "ii")}
    unscorable = 0
    for item in results:
        allowed = item.get("allowed_to_answer")
        outcome = item.get("actual_outcome")
        if not isinstance(allowed, bool) or outcome not in {"answer", "refusal"}:
            unscorable += 1
            continue
        expected_outcome = "answer" if allowed else "refusal"
        decision_scored += 1
        decision_correct += outcome == expected_outcome
        if not allowed:
            expected_type = item.get("expected_refusal_type")
            actual_type = item.get("actual_refusal_type")
            if expected_type in by_type:
                by_type[expected_type]["total"] += 1
                if actual_type in by_type:
                    subtype_scored += 1
                    by_type[expected_type]["scored"] += 1
                    subtype_ok = actual_type == expected_type and outcome == "refusal"
                    subtype_correct += subtype_ok
                    by_type[expected_type]["correct"] += subtype_ok
                else:
                    by_type[expected_type]["unscorable"] += 1
    return {
        "correct": decision_correct,
        "total": decision_scored,
        "rate": decision_correct / decision_scored if decision_scored else None,
        "subtype_correct": subtype_correct,
        "subtype_total": subtype_scored,
        "subtype_rate": subtype_correct / subtype_scored if subtype_scored else None,
        "by_type": by_type,
        "unscorable": unscorable,
    }
