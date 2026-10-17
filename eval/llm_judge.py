"""LLM judge for evaluation rows — an *additional* measurement, never a replacement.

Design constraints, each of which exists because the opposite choice produced a
wrong number somewhere in this project:

1. **The judge is not the scorer.** It produces claim labels and a segmentation,
   but ``eval/metrics.py`` still recomputes support by literal match. Two
   independent numbers are reported side by side so a disagreement is visible.
2. **The judge never runs on redacted text.** Money amounts and identifiers are
   replaced with ``[REDACTED]`` at the logging boundary; judging that text would
   ask the model whether ``220.000.000 VND`` appears in a context that now says
   ``[REDACTED] VND``. ``evaluate_judge`` therefore refuses rows whose inputs
   contain redaction placeholders rather than inventing a score.
3. **The judge cannot emit a decision.** It returns claims and a label
   comparison. ``actual_outcome`` and ``actual_refusal_type`` in the evaluation
   row stay whatever the runtime decided, so the judge cannot inflate refusal
   accuracy.
4. **Failure is unscorable, not zero.** A malformed or missing judge response
   yields ``None`` for every judge field, with the reason recorded.

The prompt lives in ``prompts/judge.txt`` (requirement 2.4: prompts stay out of
code).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
JUDGE_PROMPT_PATH = ROOT / "prompts" / "judge.txt"

REDACTED = "[REDACTED]"
_JUDGE_PROVIDER_ID = "llm-judge"
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)

# A judge response lists every claim plus metadata. The agent default (650) was
# measured to truncate 8 of 12 responses mid-object on the real staging run, so
# the judge gets its own budget.
JUDGE_MAX_TOKENS = 4096

# Fields the judge may contribute to a row. Kept separate from ``metrics`` so a
# judge number can never be mistaken for a deterministic one.
JUDGE_FIELDS = (
    "judge_faithfulness",
    "judge_outcome",
    "judge_refusal_type",
    "judge_outcome_correct",
    "judge_refusal_type_correct",
    "judge_claims",
    "judge_agreement",
    "judge_note",
    "judge_error",
)


@dataclass(frozen=True)
class JudgeResult:
    """Parsed judge output for one case."""

    faithfulness: float | None = None
    outcome: str | None = None
    refusal_type: str | None = None
    outcome_correct: bool | None = None
    refusal_type_correct: bool | None = None
    claims: list[dict[str, Any]] = field(default_factory=list)
    note: str | None = None
    error: str | None = None

    def as_row_fields(self) -> dict[str, Any]:
        return {
            "judge_faithfulness": self.faithfulness,
            "judge_outcome": self.outcome,
            "judge_refusal_type": self.refusal_type,
            "judge_outcome_correct": self.outcome_correct,
            "judge_refusal_type_correct": self.refusal_type_correct,
            "judge_claims": self.claims or None,
            "judge_note": self.note,
            "judge_error": self.error,
        }


def load_judge_prompt(path: Path = JUDGE_PROMPT_PATH) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required judge prompt not found at {path}")
    return path.read_text(encoding="utf-8")


def build_judge_messages(row: dict[str, Any], prompt_template: str) -> list[dict[str, str]]:
    """Fill prompts/judge.txt placeholders from an unredacted evaluation row.

    ``str.format`` cannot be used here: the prompt ends with a JSON example
    whose braces would be read as format fields. Substitution is therefore done
    on the named placeholders only.
    """
    contexts = row.get("contexts") or []
    values = {
        "question": row.get("question") or "",
        "contexts": "\n\n".join(str(context) for context in contexts),
        "answer": row.get("actual_answer") or "",
        "expected_outcome": row.get("expected_outcome") or "",
        "expected_refusal_type": row.get("expected_refusal_type") or "null",
    }
    prompt = prompt_template
    for name, value in values.items():
        prompt = prompt.replace("{" + name + "}", str(value))
    return [{"role": "user", "content": prompt}]


def _extract_json(text: str) -> dict[str, Any] | None:
    """Parse the judge's JSON, tolerating a code fence or trailing prose."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = _JSON_OBJECT.search(stripped)
        if match is None:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, dict) else None


def parse_judge_response(text: Any, *, expected_outcome: Any,
                         expected_refusal_type: Any) -> JudgeResult:
    """Validate the judge's JSON against the documented shape.

    Anything malformed becomes an error result with no scores. The judge is
    never given the benefit of the doubt.
    """
    if not isinstance(text, str) or not text.strip():
        return JudgeResult(error="judge returned empty output")
    payload = _extract_json(text)
    if payload is None:
        return JudgeResult(error="judge output was not valid JSON")

    claims_raw = payload.get("claims", [])
    if not isinstance(claims_raw, list):
        return JudgeResult(error="judge claims must be a list")
    claims: list[dict[str, Any]] = []
    for item in claims_raw:
        if not isinstance(item, dict):
            return JudgeResult(error="judge claim must be an object")
        span = item.get("text")
        if not isinstance(span, str) or not span.strip():
            return JudgeResult(error="judge claim missing text")
        label = item.get("label")
        if label not in ("supported", "unsupported"):
            return JudgeResult(error="judge claim label must be supported or unsupported")
        evidence = item.get("evidence_doc_id")
        if evidence is not None and not (
                isinstance(evidence, str) and re.fullmatch(r"DOC\d{4}", evidence)):
            return JudgeResult(error="judge claim evidence_doc_id must be DOCnnnn or null")
        claims.append({"text": span, "label": label, "evidence_doc_id": evidence})

    faithfulness = payload.get("faithfulness")
    if faithfulness is not None:
        if isinstance(faithfulness, bool) or not isinstance(faithfulness, (int, float)):
            return JudgeResult(error="judge faithfulness must be a number or null")
        if not 0.0 <= float(faithfulness) <= 1.0:
            return JudgeResult(error="judge faithfulness must be between 0 and 1")
        faithfulness = float(faithfulness)
    elif claims:
        # Recompute from the judge's own labels rather than trusting a missing
        # aggregate that disagrees with its claim list.
        supported = sum(claim["label"] == "supported" for claim in claims)
        faithfulness = round(supported / len(claims), 2)

    outcome = payload.get("actual_outcome")
    if outcome not in ("answer", "refusal"):
        return JudgeResult(error="judge actual_outcome must be answer or refusal")
    refusal_type = payload.get("actual_refusal_type")
    if refusal_type is not None and refusal_type not in ("i", "ii"):
        return JudgeResult(error="judge actual_refusal_type must be i, ii, or null")
    if outcome == "answer":
        refusal_type = None

    expected = expected_outcome if expected_outcome in ("answer", "refusal") else None
    outcome_correct = None if expected is None else (outcome == expected)

    if expected != "refusal" or outcome != "refusal":
        refusal_type_correct = None
    elif expected_refusal_type not in ("i", "ii") or refusal_type not in ("i", "ii"):
        refusal_type_correct = None
    else:
        refusal_type_correct = refusal_type == expected_refusal_type

    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        note = None

    return JudgeResult(
        faithfulness=faithfulness,
        outcome=outcome,
        refusal_type=refusal_type,
        outcome_correct=outcome_correct,
        refusal_type_correct=refusal_type_correct,
        claims=claims,
        note=note,
    )


def _has_redaction(value: Any) -> bool:
    if isinstance(value, str):
        return REDACTED in value
    if isinstance(value, dict):
        return any(_has_redaction(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_redaction(item) for item in value)
    return False


def judge_eligibility(row: dict[str, Any]) -> str | None:
    """Return a reason string when the row cannot be judged honestly."""
    if row.get("status") != "completed":
        return f"case status is {row.get('status')!r}, not 'completed'"
    if not isinstance(row.get("actual_answer"), str) or not row["actual_answer"].strip():
        return "case has no answer to judge"
    contexts = row.get("contexts")
    if not isinstance(contexts, list) or not contexts:
        return "case has no retrieved context to judge against"
    for name in ("actual_answer", "contexts"):
        if _has_redaction(row.get(name)):
            return (
                f"{name} contains [REDACTED]; judging it would ask the model about "
                "placeholders, so no judge score is produced"
            )
    return None


def evaluate_judge(
    row: dict[str, Any],
    request_model: Callable[..., Any],
    *,
    prompt_template: str | None = None,
) -> JudgeResult:
    """Run the judge for one row. Never raises; failures become unscorable."""
    reason = judge_eligibility(row)
    if reason is not None:
        return JudgeResult(error=reason)
    template = prompt_template if prompt_template is not None else load_judge_prompt()
    messages = build_judge_messages(row, template)
    try:
        message, _usage = request_model(messages)
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content")
    except Exception as exc:  # a judge failure must not abort the run
        return JudgeResult(error=f"judge request failed: {type(exc).__name__}: {exc}")
    return parse_judge_response(
        content,
        expected_outcome=row.get("expected_outcome"),
        expected_refusal_type=row.get("expected_refusal_type"),
    )


def judge_model_identifier() -> str:
    """Non-secret description of the judge provider, for the run manifest."""
    return os.getenv("LLM_MODEL") or "(provider default)"


def agreement(deterministic: float | None, judged: float | None) -> str | None:
    """Coarse comparison between the two faithfulness measurements."""
    if deterministic is None or judged is None:
        return None
    if abs(deterministic - judged) < 0.01:
        return "agree"
    return "judge_higher" if judged > deterministic else "judge_lower"


__all__ = [
    "JUDGE_FIELDS",
    "JudgeResult",
    "agreement",
    "build_judge_messages",
    "evaluate_judge",
    "judge_eligibility",
    "judge_model_identifier",
    "load_judge_prompt",
    "parse_judge_response",
]
