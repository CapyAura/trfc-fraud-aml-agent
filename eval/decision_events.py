"""Append decision records only when structured runtime metadata is available."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from .log_validation import _valid_tool_trace, validate_decision_event
    from .redaction import redact_for_log
except ImportError:  # direct module-path execution
    from log_validation import _valid_tool_trace, validate_decision_event
    from redaction import redact_for_log


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def build_decision_event(
    *,
    run_id: str,
    question_id: str,
    execution_mode: str,
    actual_outcome: str | None,
    actual_refusal_type: str | None,
    policy_rule_id: str | None,
    decision_source: str | None,
    tool_trace: list[dict[str, Any]] | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Build one decision event, preserving unavailable data without guessing."""
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id must be non-empty")
    if not isinstance(question_id, str) or not question_id.strip():
        raise ValueError("question_id must be non-empty")
    if not isinstance(actual_outcome, str) or actual_outcome not in {"answer", "refusal"}:
        return None, "actual_outcome_unavailable"
    if actual_outcome == "refusal":
        if not isinstance(actual_refusal_type, str) or actual_refusal_type not in {"i", "ii"}:
            return None, "actual_refusal_type_unavailable"
    elif actual_refusal_type is not None:
        return None, "refusal_type_on_answer_outcome"
    if decision_source is None:
        return None, "decision_source_unavailable"
    if not isinstance(decision_source, str) or not _IDENTIFIER.fullmatch(decision_source):
        raise ValueError("decision_source must be a safe structured identifier")
    if policy_rule_id is not None and (
        not isinstance(policy_rule_id, str) or not _IDENTIFIER.fullmatch(policy_rule_id)
    ):
        raise ValueError("policy_rule_id must be null or a safe identifier")
    if not _valid_tool_trace(tool_trace):
        return None, "tool_trace_invalid"

    event = {
        "record_type": "decision_event",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "question_id": question_id,
        "execution_mode": execution_mode,
        "actual_outcome": actual_outcome,
        "actual_refusal_type": actual_refusal_type,
        "policy_rule_id": policy_rule_id,
        "decision_source": decision_source,
        "tool_trace_status": "unavailable" if tool_trace is None else "complete",
        "tool_call_count": None if tool_trace is None else len(tool_trace),
        "business_outcome_verified": False,
    }
    errors = validate_decision_event(event)
    if errors:
        raise ValueError("Generated decision event is invalid: " + "; ".join(errors))
    return redact_for_log(event), None


def append_decision_event(
    path: Path,
    **event_fields: Any,
) -> str | None:
    """Append a validated decision event; return a skip reason if unavailable."""
    event, reason = build_decision_event(**event_fields)
    if event is None:
        return reason

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size:
        with path.open("r", encoding="utf-8") as stream:
            for line_number, raw in enumerate(stream, 1):
                try:
                    prior = json.loads(raw)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Existing decision-event file has invalid JSON at line {line_number}"
                    ) from exc
                if not isinstance(prior, dict) or validate_decision_event(prior):
                    raise ValueError(
                        f"Existing decision-event file has an invalid record at line {line_number}"
                    )

    payload = json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
    needs_separator = False
    if path.exists() and path.stat().st_size:
        with path.open("rb") as stream:
            stream.seek(-1, 2)
            needs_separator = stream.read(1) not in (b"\n", b"\r")
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(("\n" if needs_separator else "") + payload)
    return None
