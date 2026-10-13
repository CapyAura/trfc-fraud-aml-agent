"""Read-only validation for evaluation case rows and C4 step-event JSONL.

Schema validation does not establish that a record came from a genuine run.
"""

from __future__ import annotations

import argparse
import json
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


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None and parsed.utcoffset() is not None
    except ValueError:
        return False


def _valid_usage(value: Any, nullable: bool = False) -> bool:
    if value is None:
        return nullable
    return (isinstance(value, dict) and USAGE_KEYS == value.keys()
            and all(type(value[key]) is int and value[key] >= 0 for key in USAGE_KEYS))


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
    for field in ("contexts", "claims"):
        value = row.get(field)
        if value is not None and (not isinstance(value, list)
                                  or not all(isinstance(item, str) for item in value)):
            errors.append(f"{field} must be null or a list of strings")
    if not isinstance(row.get("metrics"), dict):
        errors.append("metrics must be an object")
    if not _valid_usage(row.get("usage"), nullable=True):
        errors.append("usage must be null or contain non-negative integer counters")
    trace = row.get("tool_trace")
    if trace is not None and not isinstance(trace, list):
        errors.append("tool_trace must be null or a list")
    return errors


def validate_event(row: dict[str, Any]) -> list[str]:
    """Validate the C4 per-step record contract; it is not emitted by run_eval."""
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
        errors.append("usage must contain non-negative integer counters")
    return errors


def validate_file(path: Path, kind: str) -> list[str]:
    validator = validate_event if kind == "event" else validate_case
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
    parser.add_argument("--kind", choices=("case", "event"), required=True)
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
