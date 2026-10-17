"""Deterministic evaluation helpers.

Faithfulness is intentionally conservative: it scores only explicit claims that
are exact substrings (case-insensitive) of retrieved context. This is not a
semantic judge; paraphrases and unsupported claims are unscorable/unsupported.

Two claim encodings are accepted, both produced outside this module:

* ``str`` — a bare claim span (the original contract in
  ``eval/PERSON_B_C4_METADATA_CONTRACT.md``).
* ``{"text": ..., "label": "supported"|"unsupported", "evidence_doc_id": ...}`` —
  the record shape requested by ``prompts/judge.txt``.

The dict form carries the judge's own label, but that label is **not trusted**.
The score is always recomputed by literal matching against the retrieved
context, so a caller cannot raise faithfulness by asserting ``"supported"``.
The label is kept only to expose disagreement between the judge and the
deterministic check (see ``claim_support_detail``).
"""

from __future__ import annotations

import re
from typing import Any

CLAIM_LABELS = ("supported", "unsupported")


def _norm(value: str) -> str:
    return " ".join(value.casefold().split())


def _contains_literal(text: str, literal: str) -> bool:
    """Match a normalized phrase without accepting a substring of a token."""
    phrase = _norm(literal)
    if not phrase:
        return False
    return re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", _norm(text)) is not None


def claim_text(claim: Any) -> str | None:
    """Return the claim span from either accepted claim encoding.

    Returns ``None`` for anything else, so a malformed claim makes the metric
    unscorable instead of silently scoring a subset.
    """
    if isinstance(claim, str):
        return claim
    if isinstance(claim, dict):
        text = claim.get("text")
        return text if isinstance(text, str) else None
    return None


def claim_label(claim: Any) -> str | None:
    """Return the judge-supplied label for a dict claim, else ``None``."""
    if isinstance(claim, dict):
        label = claim.get("label")
        if isinstance(label, str) and label in CLAIM_LABELS:
            return label
    return None


def normalize_claims(claims: Any) -> list[Any] | None:
    """Validate and pass through a claims list in either accepted encoding.

    Returns ``None`` when the value is not a usable claim list. Empty strings
    and whitespace-only claims are dropped; a claim without a usable text span
    invalidates the whole list rather than being skipped.
    """
    if not isinstance(claims, list):
        return None
    normalized: list[Any] = []
    for claim in claims:
        text = claim_text(claim)
        if text is None:
            return None
        if not text.strip():
            continue
        normalized.append(claim)
    return normalized


def claim_support_detail(claims: Any, contexts: list[str] | None) -> list[dict[str, Any]]:
    """Per-claim literal support, including judge/deterministic disagreement.

    ``agrees`` is ``None`` for bare-string claims (no judge label to compare).
    """
    normalized = normalize_claims(claims)
    if normalized is None:
        return []
    joined = _norm("\n".join(contexts)) if isinstance(contexts, list) else ""
    detail = []
    for claim in normalized:
        text = claim_text(claim) or ""
        supported = bool(joined) and _contains_literal(joined, text)
        label = claim_label(claim)
        detail.append({
            "text": text,
            "supported": supported,
            "label": label,
            "agrees": None if label is None else (label == "supported") == supported,
        })
    return detail


def faithfulness(answer: str | None, contexts: list[str] | None,
                 claims: list[Any] | None = None) -> float | None:
    """Fraction of supplied factual claims literally supported by context.

    Accepts both claim encodings documented in the module docstring. A
    judge-supplied ``label`` never contributes to the score; only the literal
    match does. Returns None when answer/context/claim segmentation is
    unavailable. The function never treats an empty answer as a perfect score.
    """
    if (not isinstance(answer, str) or not answer.strip()
            or not isinstance(contexts, list) or not contexts
            or not all(isinstance(context, str) and context for context in contexts)):
        return None
    factual_claims = normalize_claims(claims)
    if not factual_claims:
        return None
    answer_norm = _norm(answer)
    # Reject malformed adapter claims instead of allowing a caller to provide
    # claims unrelated to the response and obtain an artificially high score.
    if any(not _contains_literal(answer_norm, claim_text(claim) or "")
           for claim in factual_claims):
        return None
    joined_context = _norm("\n".join(contexts))
    return sum(
        _contains_literal(joined_context, claim_text(claim) or "")
        for claim in factual_claims
    ) / len(factual_claims)


def context_precision(question: str | None, contexts: list[str] | None,
                      relevant_sources: list[str] | None = None) -> float | None:
    """Precision of retrieved contexts by explicit source ID relevance.

    A context is relevant when any ``DOCnnnn`` identifier it carries is in the
    gold ``relevant_sources``. Contexts that carry no identifier are unknown and
    are excluded from the denominator rather than counted as irrelevant, so a
    chunk spanning two documents is judged by its own citations instead of
    voiding the whole case. Returns ``None`` only when nothing is scorable.
    """
    if (not isinstance(question, str) or not question.strip()
            or not isinstance(contexts, list) or not contexts
            or not all(isinstance(context, str) and context for context in contexts)
            or not isinstance(relevant_sources, list) or not relevant_sources):
        return None
    document_id = re.compile(r"(?<![A-Z0-9])DOC\d{4}(?![A-Z0-9])", re.IGNORECASE)
    if not all(isinstance(source, str) and re.fullmatch(r"DOC\d{4}", source, re.IGNORECASE)
               for source in relevant_sources):
        return None
    relevant = {source.upper() for source in relevant_sources}
    scored = 0
    hits = 0
    for context in contexts:
        cited = {source.upper() for source in document_id.findall(context)}
        if not cited:
            # No usable source metadata: unknown, not irrelevant.
            continue
        scored += 1
        hits += bool(cited & relevant)
    if not scored:
        return None
    return hits / scored


def marker_satisfied(answer: str, criterion: Any) -> bool | None:
    """Evaluate one expected criterion against the answer.

    Accepts either a plain string (exact normalized substring) or a criterion
    object with ``all`` (every variant must appear) or ``any`` (at least one
    variant must appear). Variant lists let the testset accept equivalent
    phrasing without loosening the check to a fuzzy match.

    Returns ``None`` for a malformed criterion, so a broken testset entry makes
    the metric unscorable instead of silently passing.
    """
    if isinstance(criterion, str):
        return _contains_literal(answer, criterion)
    if not isinstance(criterion, dict):
        return None
    for key in ("all", "any"):
        variants = criterion.get(key)
        if variants is None:
            continue
        if not isinstance(variants, list) or not variants:
            return None
        if not all(isinstance(v, str) and v.strip() for v in variants):
            return None
        hits = [_contains_literal(answer, v) for v in variants]
        return all(hits) if key == "all" else any(hits)
    return None


def marker_results(answer: str | None, expected: dict[str, Any] | None) -> list[dict[str, Any]] | None:
    """Per-criterion outcome, recorded before redaction so logs stay auditable.

    The criterion *label* is deliberately not the raw marker text: money amounts
    and IDs in it would be redacted on the way to the log, leaving a criterion
    recorded as ``[REDACTED] VND`` that proves nothing. Each entry therefore
    carries its index and a kind, and the reader pairs it with the testset.
    """
    if not isinstance(answer, str) or not isinstance(expected, dict):
        return None
    values = expected.get("values")
    if not isinstance(values, list) or not values:
        return None
    results = []
    for index, criterion in enumerate(values, 1):
        if isinstance(criterion, str):
            kind = "literal"
        elif isinstance(criterion, dict):
            kind = "variants"
        else:
            kind = "invalid"
        results.append({
            "index": index,
            "kind": kind,
            "satisfied": marker_satisfied(answer, criterion),
        })
    return results


def answer_correctness(answer: str | None, expected: dict[str, Any] | None,
                       allowed_to_answer: bool) -> bool | None:
    """Check objective `contains_all` criteria for answerable questions.

    ``values`` entries may be plain strings or variant objects (see
    ``marker_satisfied``). Every entry must be satisfied.
    """
    if (not isinstance(allowed_to_answer, bool) or not allowed_to_answer
            or not isinstance(answer, str) or not answer.strip() or not isinstance(expected, dict)):
        return None
    values = expected.get("values")
    if (expected.get("criteria_type") != "contains_all" or not isinstance(values, list)
            or not values):
        return None
    outcomes = [marker_satisfied(answer, criterion) for criterion in values]
    if any(outcome is None for outcome in outcomes):
        return None
    return all(outcomes)


def refusal_decision_correctness(allowed_to_answer: Any, actual_outcome: Any) -> bool | None:
    """Compare a valid runtime decision with the expected allow/refuse decision."""
    if not isinstance(allowed_to_answer, bool) or actual_outcome not in ("answer", "refusal"):
        return None
    return actual_outcome == ("answer" if allowed_to_answer else "refusal")


def metadata_filter_usage(tool_trace: Any, expected_tier: Any) -> bool | None:
    """Did the run actually apply the ``tier`` metadata pre-filter it was asked for?

    This scores *pipeline behaviour*, not answer text: a case declaring
    ``expected_tier`` is only satisfied when at least one ``search_policy`` call
    passed exactly that ``tier`` argument to the retrieval tool. ``None`` when
    the case declares no tier, when the trace is unavailable, or when the
    expected tier is not a valid tier number — an unavailable trace must never
    read as success.
    """
    if type(expected_tier) is not int or expected_tier not in (1, 2, 3):
        return None
    if not isinstance(tool_trace, list):
        return None
    for step in tool_trace:
        if not isinstance(step, dict) or step.get("tool_name") != "search_policy":
            continue
        arguments = step.get("arguments")
        if isinstance(arguments, dict) and arguments.get("tier") == expected_tier:
            return True
    return False


def refusal_rate(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Score answer/refusal decisions and subtype correctness; exclude unknowns."""
    decision_scored = decision_correct = subtype_scored = subtype_correct = 0
    by_type = {kind: {"correct": 0, "total": 0, "scored": 0, "unscorable": 0}
               for kind in ("i", "ii")}
    unscorable = 0
    for item in results:
        allowed = item.get("allowed_to_answer")
        outcome = item.get("actual_outcome")
        if not isinstance(allowed, bool) or not isinstance(outcome, str) or outcome not in {"answer", "refusal"}:
            unscorable += 1
            continue
        expected_outcome = "answer" if allowed else "refusal"
        decision_scored += 1
        decision_correct += outcome == expected_outcome
        if not allowed:
            expected_type = item.get("expected_refusal_type")
            actual_type = item.get("actual_refusal_type")
            if isinstance(expected_type, str) and expected_type in by_type:
                by_type[expected_type]["total"] += 1
                if outcome == "refusal" and isinstance(actual_type, str) and actual_type in by_type:
                    subtype_scored += 1
                    by_type[expected_type]["scored"] += 1
                    subtype_ok = actual_type == expected_type
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
