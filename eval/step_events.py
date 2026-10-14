"""Append redacted C4 step events derived from captured runtime tool traces.

This module records only events present in a structured trace. It does not
classify answers, invent tool calls, or authenticate the declared execution mode.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:
    from .log_validation import EXECUTION_MODES, validate_event
    from .redaction import redact_for_log
except ImportError:  # direct script/module-path execution
    from log_validation import EXECUTION_MODES, validate_event
    from redaction import redact_for_log

SCENARIOS = {"freeze", "flag", "refusal"}
SCENARIO_TOOLS = {
    "freeze": "freeze_account_temporarily",
    "flag": "flag_suspicious_tx",
}
REFUSAL_TYPES = {"i", "ii"}


@dataclass(frozen=True)
class AppendResult:
    written: int
    skipped_reason: str | None = None


def _validate_trace_record(record: Any) -> None:
    required = {
        "step", "tool_call_id", "tool_name", "arguments", "result", "status", "error",
    }
    if not isinstance(record, dict) or not required.issubset(record):
        raise ValueError("Captured tool trace contains a malformed event")
    if type(record["step"]) is not int or record["step"] < 1:
        raise ValueError("Captured tool trace has an invalid step number")
    if not isinstance(record["tool_name"], str) or not record["tool_name"].strip():
        raise ValueError("Captured tool trace has no tool name")
    if not isinstance(record["arguments"], dict):
        raise ValueError("Captured tool arguments are unavailable or malformed")
    if not isinstance(record["result"], str):
        raise ValueError("Captured tool result is unavailable or malformed")
    if not isinstance(record["status"], str) or record["status"] not in {"completed", "error"}:
        raise ValueError("Captured tool trace has an invalid result status")
    if record["status"] == "error":
        if not isinstance(record["error"], str) or not record["error"].strip():
            raise ValueError("Failed tool trace needs an error classification")
    elif record["error"] is not None:
        raise ValueError("Successful tool trace cannot contain an error")


def build_step_events(
    *,
    tool_trace: list[dict[str, Any]] | None,
    usage: dict[str, Any] | None,
    run_id: str,
    question_id: str,
    scenario: str,
    execution_mode: str,
    actual_outcome: str | None = None,
    actual_refusal_type: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Build validated records; unavailable data produces no fabricated event."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be a non-empty string")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("question_id must be a non-empty string")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise ValueError("scenario must be freeze, flag, or refusal")
    if not isinstance(execution_mode, str) or execution_mode not in EXECUTION_MODES:
        raise ValueError("execution_mode is not supported by the event schema")
    if execution_mode == "dry_run":
        return [], "dry_run_has_no_runtime_events"
    if tool_trace is None:
        return [], "tool_trace_unavailable"
    if scenario == "refusal":
        if actual_outcome != "refusal" or actual_refusal_type not in REFUSAL_TYPES:
            return [], "authoritative_refusal_metadata_unavailable"
    if not isinstance(tool_trace, list):
        raise ValueError("tool_trace must be null or a list")
    if not tool_trace:
        if scenario == "refusal":
            return [], "refusal_event_not_supported_without_tool_trace"
        return [], "empty_tool_trace"
    if not isinstance(usage, dict):
        return [], "usage_unavailable"

    for record in tool_trace:
        _validate_trace_record(record)

    scenario_tool = SCENARIO_TOOLS.get(scenario)
    matching_records = [
        record for record in tool_trace
        if isinstance(record, dict) and record.get("tool_name") == scenario_tool
    ] if scenario_tool is not None else []
    if scenario_tool is not None and not matching_records:
        return [], "scenario_write_tool_not_observed"

    events = []
    for record in tool_trace:
        is_scenario_action = scenario_tool is not None and record["tool_name"] == scenario_tool
        # The event schema has no error field. Keep the failure classification,
        # but omit free-form exception/result text for failed calls.
        result: Any = (
            {"status": "error", "detail": "Tool call failed; diagnostic details omitted."}
            if record["status"] == "error"
            else redact_for_log(record["result"])
        )
        event = {
            "record_type": "step_event",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": run_id,
            "question_id": question_id,
            "scenario": scenario,
            "execution_mode": execution_mode,
            "step": record["step"],
            "tool": record["tool_name"],
            "args": redact_for_log(record["arguments"]),
            "result": result,
            "usage": redact_for_log(usage),
            # Optional schema extension: preserve captured completion/failure
            # state without persisting the raw exception message.
            "status": record["status"],
        }
        if scenario_tool is not None:
            event["scenario_evidence_status"] = (
                "tool_call_failed" if is_scenario_action and record["status"] == "error"
                else "tool_call_completed_outcome_unverified" if is_scenario_action
                else "context_only"
            )
            # MCP completion or an acknowledgement does not prove the business
            # state changed. The current runtime has no authoritative read-back
            # contract, so this must never be represented as verified success.
            event["business_outcome_verified"] = False
        elif scenario == "refusal":
            event["actual_outcome"] = actual_outcome
            event["actual_refusal_type"] = actual_refusal_type
            event["scenario_evidence_status"] = "structured_runtime_refusal_metadata"
        errors = validate_event(event)
        if errors:
            raise ValueError("Generated step event is invalid: " + "; ".join(errors))
        events.append(event)
    return events, None


def append_step_events(
    path: Path,
    *,
    tool_trace: list[dict[str, Any]] | None,
    usage: dict[str, Any] | None,
    run_id: str,
    question_id: str,
    scenario: str,
    execution_mode: str,
    actual_outcome: str | None = None,
    actual_refusal_type: str | None = None,
) -> AppendResult:
    """Append schema-valid redacted events without replacing existing records."""
    events, skipped_reason = build_step_events(
        tool_trace=tool_trace,
        usage=usage,
        run_id=run_id,
        question_id=question_id,
        scenario=scenario,
        execution_mode=execution_mode,
        actual_outcome=actual_outcome,
        actual_refusal_type=actual_refusal_type,
    )
    if not events:
        return AppendResult(written=0, skipped_reason=skipped_reason)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        # Do not mix step events into an existing case log or append after a
        # malformed/partial record. Existing records remain untouched.
        with path.open("r", encoding="utf-8") as existing:
            for line_number, raw in enumerate(existing, 1):
                try:
                    previous = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Existing step-event file has invalid JSON at line {line_number}"
                    ) from exc
                if not isinstance(previous, dict) or validate_event(previous):
                    raise ValueError(
                        f"Existing step-event file has a non-event or invalid record at line {line_number}"
                    )
    payload = "".join(
        json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
        for event in events
    )
    # Append mode preserves any existing C4 evidence; never truncate it.
    needs_separator = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as existing:
            existing.seek(-1, 2)
            needs_separator = existing.read(1) not in (b"\n", b"\r")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(("\n" if needs_separator else "") + payload)
    return AppendResult(written=len(events))
