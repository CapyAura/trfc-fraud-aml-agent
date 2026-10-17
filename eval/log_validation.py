"""Read-only validation for evaluation case rows and C4 step-event JSONL.

Schema validation does not establish that a record came from a genuine run.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

CASE_REQUIRED = {
    "timestamp", "question_id", "category", "expected_outcome",
    "allowed_to_answer", "expected_refusal_type", "expected",
    "source_refs", "actual_answer", "actual_outcome",
    "actual_refusal_type", "contexts", "claims", "tool_trace", "usage",
    "metrics", "error", "status",
}
USAGE_KEYS = {"calls", "prompt_tokens", "completion_tokens", "max_prompt"}
EXECUTION_MODES = {"real", "mock", "dry_run", "unit_test", "synthetic"}
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z", re.ASCII)
_DOC_ID = re.compile(r"DOC\d{4}\Z", re.ASCII)
_JUDGE_FIELDS = (
    "judge_faithfulness", "judge_outcome", "judge_refusal_type",
    "judge_outcome_correct", "judge_refusal_type_correct", "judge_claims",
    "judge_agreement", "judge_note", "judge_error",
)


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _judge_errors(row: dict[str, Any]) -> list[str]:
    """Validate optional judge columns.

    Judge fields are additive and may be absent on rows produced without
    ``--judge``. When present they must not be mistaken for deterministic
    metrics: a judge score is only meaningful alongside the error field that
    says whether the judge actually ran.
    """
    if not any(field in row for field in _JUDGE_FIELDS):
        return []
    errors = []
    score = row.get("judge_faithfulness")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 1:
            errors.append("judge_faithfulness must be null or a number between 0 and 1")
    outcome = row.get("judge_outcome")
    if outcome is not None and outcome not in {"answer", "refusal"}:
        errors.append("judge_outcome must be answer, refusal, or null")
    refusal_type = row.get("judge_refusal_type")
    if refusal_type is not None and refusal_type not in {"i", "ii"}:
        errors.append("judge_refusal_type must be i, ii, or null")
    if outcome == "answer" and refusal_type is not None:
        errors.append("judge_refusal_type must be null when judge_outcome is answer")
    for field in ("judge_outcome_correct", "judge_refusal_type_correct"):
        value = row.get(field)
        if value is not None and not isinstance(value, bool):
            errors.append(f"{field} must be a boolean or null")
    claims = row.get("judge_claims")
    if claims is not None:
        if not isinstance(claims, list):
            errors.append("judge_claims must be null or a list")
        else:
            for index, item in enumerate(claims):
                if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                    errors.append(f"judge_claims[{index}] must be an object with a text field")
                    continue
                if item.get("label") not in {"supported", "unsupported"}:
                    errors.append(f"judge_claims[{index}].label must be supported or unsupported")
    agreement = row.get("judge_agreement")
    if agreement is not None and agreement not in {"agree", "judge_higher", "judge_lower"}:
        errors.append("judge_agreement must be agree, judge_higher, judge_lower, or null")
    error = row.get("judge_error")
    if error is not None and not isinstance(error, str):
        errors.append("judge_error must be a string or null")
    if error is None and outcome is None and score is None and claims is None:
        errors.append("judge columns present but no judge result or judge_error recorded")
    return errors


def _valid_usage(value: Any, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    return (
        isinstance(value, dict)
        and USAGE_KEYS == value.keys()
        and type(value["calls"]) is int
        and value["calls"] >= 0
        and all(value[key] is None or (type(value[key]) is int and value[key] >= 0)
                for key in USAGE_KEYS - {"calls"})
        and (value["prompt_tokens"] is not None or value["max_prompt"] is None)
    )


def _valid_tool_trace(value: Any) -> bool:
    """Accept unavailable traces or lists of records emitted by the runtime."""
    if value is None:
        return True
    if not isinstance(value, list):
        return False
    required = {
        "step", "tool_call_id", "tool_name", "arguments",
        "result", "status", "error",
    }
    for event in value:
        if not isinstance(event, dict) or not required.issubset(event):
            return False
        if type(event["step"]) is not int or event["step"] < 1:
            return False
        if (not isinstance(event["tool_call_id"], str)
                or not event["tool_call_id"].strip()
                or not isinstance(event["tool_name"], str)
                or not event["tool_name"].strip()):
            return False
        if event["arguments"] is not None and not isinstance(event["arguments"], dict):
            return False
        if not isinstance(event["result"], str):
            return False
        if event["status"] not in ("completed", "error"):
            return False
        if event["error"] is not None and not isinstance(event["error"], str):
            return False
        if event["status"] == "error" and not event["error"]:
            return False
        if event["status"] == "completed" and event["error"] is not None:
            return False
    return True


def validate_case(row: dict[str, Any]) -> list[str]:
    errors = []
    missing = CASE_REQUIRED - row.keys()
    if missing:
        errors.append(f"missing fields: {', '.join(sorted(missing))}")
    if not _timestamp(row.get("timestamp")):
        errors.append("timestamp must be ISO-8601 with timezone")
    if not isinstance(row.get("question_id"), str) or not row["question_id"].strip():
        errors.append("question_id must be a non-empty string")
    if not isinstance(row.get("category"), str):
        errors.append("category must be a string")
    if row.get("expected_outcome") not in ("answer", "refusal"):
        errors.append("expected_outcome must be answer or refusal")
    if type(row.get("allowed_to_answer")) is not bool:
        errors.append("allowed_to_answer must be boolean")
    if row.get("expected_refusal_type") not in (None, "i", "ii"):
        errors.append("expected_refusal_type must be null, i, or ii")
    if row.get("status") not in ("completed", "failed", "unscorable"):
        errors.append("status must be completed, failed, or unscorable")
    if row.get("status") == "completed" and row.get("actual_outcome") not in ("answer", "refusal"):
        errors.append("completed row needs actual_outcome answer or refusal")
    if row.get("status") == "unscorable" and row.get("actual_outcome") is not None:
        errors.append("unscorable row must have unavailable actual_outcome")
    if row.get("status") == "failed" and (
        not isinstance(row.get("error"), str) or not row["error"].strip()
    ):
        errors.append("failed row needs a non-empty runtime error")
    if not isinstance(row.get("expected"), dict):
        errors.append("expected must be an object")
    if not isinstance(row.get("source_refs"), list):
        errors.append("source_refs must be a list")
    for field in ("actual_answer", "error"):
        if row.get(field) is not None and not isinstance(row[field], str):
            errors.append(f"{field} must be a string or null")
    if row.get("actual_outcome") not in (None, "answer", "refusal"):
        errors.append("actual_outcome must be null, answer, or refusal")
    if row.get("actual_refusal_type") not in (None, "i", "ii"):
        errors.append("actual_refusal_type must be null, i, or ii")
    if row.get("actual_refusal_type") is not None and row.get("actual_outcome") != "refusal":
        errors.append("actual_refusal_type is only applicable to a refusal outcome")
    policy_status = row.get("policy_decision_status")
    if ("policy_decision_status" in row
            and policy_status not in (None, "decided", "needs_information")):
        errors.append("policy_decision_status must be null, decided, or needs_information")
    if ("policy_reason_code" in row and row["policy_reason_code"] is not None
            and not isinstance(row["policy_reason_code"], str)):
        errors.append("policy_reason_code must be a string or null")
    decision_fields = ("actual_outcome", "actual_refusal_type", "policy_rule_id", "decision_source")
    if policy_status == "needs_information" and any(row.get(field) is not None for field in decision_fields):
        errors.append("needs_information policy status cannot contain decision metadata")
    if policy_status == "decided":
        if row.get("status") != "completed" or row.get("actual_outcome") not in ("answer", "refusal"):
            errors.append("decided policy status needs a completed row with an actual outcome")
        source = row.get("decision_source")
        if not isinstance(source, str) or not _SAFE_IDENTIFIER.fullmatch(source):
            errors.append("decided policy status needs a structured decision_source")
    for field in ("contexts", "claims"):
        value = row.get(field)
        if value is None:
            continue
        if not isinstance(value, list):
            errors.append(f"{field} must be null or a list")
            continue
        if field == "claims":
            # Accept both encodings documented in eval/metrics.py: a bare span
            # string, or the record object requested by prompts/judge.txt.
            for index, item in enumerate(value):
                if isinstance(item, str):
                    continue
                if not isinstance(item, dict):
                    errors.append(f"claims[{index}] must be a string or a claim object")
                    continue
                if not isinstance(item.get("text"), str):
                    errors.append(f"claims[{index}].text must be a string")
                label = item.get("label")
                if label is not None and label not in {"supported", "unsupported"}:
                    errors.append(f"claims[{index}].label must be supported or unsupported")
                evidence = item.get("evidence_doc_id")
                if evidence is not None and not (
                        isinstance(evidence, str) and _DOC_ID.fullmatch(evidence)):
                    errors.append(f"claims[{index}].evidence_doc_id must be a DOCnnnn id or null")
        elif not all(isinstance(item, str) for item in value):
            errors.append("contexts must be null or a list of strings")
    if not isinstance(row.get("metrics"), dict):
        errors.append("metrics must be an object")
    if "marker_results" in row and row["marker_results"] is not None:
        markers = row["marker_results"]
        if not isinstance(markers, list):
            errors.append("marker_results must be null or a list")
        else:
            for index, item in enumerate(markers):
                if not isinstance(item, dict):
                    errors.append(f"marker_results[{index}] must be an object")
                    continue
                if type(item.get("index")) is not int or item["index"] < 1:
                    errors.append(f"marker_results[{index}].index must be a positive integer")
                if item.get("kind") not in {"literal", "variants", "invalid"}:
                    errors.append(
                        f"marker_results[{index}].kind must be literal, variants, or invalid")
                if item.get("satisfied") is not None and not isinstance(item.get("satisfied"), bool):
                    errors.append(f"marker_results[{index}].satisfied must be a boolean or null")
    errors.extend(_judge_errors(row))
    if not _valid_usage(row.get("usage"), nullable=True):
        errors.append("usage must be null or contain calls and non-negative/unknown token counters")
    trace = row.get("tool_trace")
    if not _valid_tool_trace(trace):
        errors.append("tool_trace must be null or a list of valid captured tool-call records")
    if row.get("status") == "failed" and trace == []:
        errors.append("failed row cannot claim an empty completed tool trace")
    return errors


def validate_event(row: dict[str, Any]) -> list[str]:
    """Validate the C4 tool-call event contract emitted by the evaluator."""
    required = {"record_type", "timestamp", "run_id", "question_id", "scenario",
                "execution_mode", "step", "tool", "args", "result", "usage"}
    errors = []
    missing = required - row.keys()
    if missing:
        errors.append(f"missing fields: {', '.join(sorted(missing))}")
    if row.get("record_type") != "step_event":
        errors.append("record_type must be step_event")
    if not _timestamp(row.get("timestamp")):
        errors.append("timestamp must be ISO-8601 with timezone")
    for field in ("run_id", "question_id"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if row.get("scenario") not in ("freeze", "flag", "refusal"):
        errors.append("scenario must be freeze, flag, or refusal")
    if row.get("execution_mode") not in tuple(EXECUTION_MODES):
        errors.append("execution_mode must identify real, mock, dry_run, unit_test, or synthetic")
    if type(row.get("step")) is not int or row["step"] < 1:
        errors.append("step must be a positive integer")
    if not isinstance(row.get("tool"), str) or not row["tool"].strip():
        errors.append("tool must be a non-empty tool/step name")
    if not isinstance(row.get("args"), dict):
        errors.append("args must be an object")
    if row.get("result") is None:
        errors.append("result must not be null")
    if not _valid_usage(row.get("usage")):
        errors.append("usage must contain calls and non-negative/unknown token counters")
    return errors


def validate_decision_event(row: dict[str, Any]) -> list[str]:
    """Validate a separate structured decision record, not a tool-call event."""
    required = {
        "record_type", "timestamp", "run_id", "question_id", "execution_mode",
        "actual_outcome", "actual_refusal_type", "policy_rule_id", "decision_source",
        "tool_trace_status", "tool_call_count", "business_outcome_verified",
    }
    errors = []
    missing = required - row.keys()
    if missing:
        errors.append(f"missing fields: {', '.join(sorted(missing))}")
    if row.get("record_type") != "decision_event":
        errors.append("record_type must be decision_event")
    if not _timestamp(row.get("timestamp")):
        errors.append("timestamp must be ISO-8601 with timezone")
    for field in ("run_id", "question_id"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            errors.append(f"{field} must be a non-empty string")
    if row.get("execution_mode") not in tuple(EXECUTION_MODES):
        errors.append("execution_mode must identify real, mock, dry_run, unit_test, or synthetic")
    if row.get("actual_outcome") not in ("answer", "refusal"):
        errors.append("actual_outcome must be answer or refusal")
    refusal_type = row.get("actual_refusal_type")
    if refusal_type not in (None, "i", "ii"):
        errors.append("actual_refusal_type must be null, i, or ii")
    if row.get("actual_outcome") == "refusal" and refusal_type not in ("i", "ii"):
        errors.append("refusal decision needs actual_refusal_type i or ii")
    if row.get("actual_outcome") == "answer" and refusal_type is not None:
        errors.append("answer decision cannot have actual_refusal_type")
    rule_id = row.get("policy_rule_id")
    if rule_id is not None and (
        not isinstance(rule_id, str) or _SAFE_IDENTIFIER.fullmatch(rule_id) is None
    ):
        errors.append("policy_rule_id must be null or a non-empty identifier")
    source = row.get("decision_source")
    if not isinstance(source, str) or _SAFE_IDENTIFIER.fullmatch(source) is None:
        errors.append("decision_source must be a safe structured identifier")
    trace_status = row.get("tool_trace_status")
    count = row.get("tool_call_count")
    if trace_status not in ("complete", "unavailable"):
        errors.append("tool_trace_status must be complete or unavailable")
    if trace_status == "complete" and (type(count) is not int or count < 0):
        errors.append("complete tool trace needs a non-negative tool_call_count")
    if trace_status == "unavailable" and count is not None:
        errors.append("unavailable tool trace must have null tool_call_count")
    if row.get("business_outcome_verified") is not False:
        errors.append("decision event cannot claim a verified business outcome")
    return errors


def validate_file(path: Path, kind: str) -> list[str]:
    validators = {
        "case": validate_case,
        "event": validate_event,
        "decision": validate_decision_event,
    }
    validator = validators[kind]
    errors: list[str] = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_no, raw in enumerate(stream, 1):
                if not raw.strip():
                    errors.append(f"{path}:{line_no}: blank JSONL line")
                    continue
                try:
                    row = json.loads(raw)
                except json.JSONDecodeError as exc:
                    errors.append(f"{path}:{line_no}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(row, dict):
                    errors.append(f"{path}:{line_no}: expected JSON object")
                    continue
                errors.extend(f"{path}:{line_no}: {message}" for message in validator(row))
    except (OSError, UnicodeError) as exc:
        errors.append(f"{path}: cannot read: {exc}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("case", "event", "decision"), required=True)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    files = []
    for path in args.paths:
        files.extend(sorted(path.glob("*.jsonl")) if path.is_dir() else [path])
    if not files:
        print("No JSONL files found; no records validated.")
        return 2
    errors = [issue for path in files for issue in validate_file(path, args.kind)]
    if errors:
        print("\n".join(errors))
        return 1
    print(f"Schema valid: {len(files)} file(s), kind={args.kind}. Provenance/authenticity not verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
