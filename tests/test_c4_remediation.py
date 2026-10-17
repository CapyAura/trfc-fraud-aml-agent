"""Tests covering C4 failure remediation: tool argument error handling,
step event serialization of failed tool calls, and structured decision validation.
"""

from __future__ import annotations

import asyncio
from typing import Any
from types import SimpleNamespace as NS

import pytest

from eval.log_validation import validate_event
from eval.step_events import _validate_trace_record, build_step_events
from trfc.agent.loop import (
    MODEL_DECISION_SOURCE,
    resolve_decision,
    run_with_session,
)


def _inline(awaitable):
    return asyncio.run(awaitable)


class FakeSession:
    def __init__(self, tools: list[Any] | None = None) -> None:
        self._tools = tools or []
        self.calls: list[tuple[str, Any]] = []

    async def list_tools(self) -> dict[str, Any]:
        return {"tools": list(self._tools)}

    async def call_tool(self, name: str, arguments: Any) -> Any:
        self.calls.append((name, arguments))
        return NS(is_error=False, content=[NS(text='{"ok": true}')])


def mcp_tool(name: str = "flag_suspicious_tx") -> NS:
    return NS(
        name=name,
        description="Flag a transaction",
        inputSchema={
            "type": "object",
            "properties": {
                "tx_id": {"type": "string"},
                "reason": {"type": "string"},
            },
            "required": ["tx_id", "reason"],
        },
    )


def test_malformed_json_arguments_captured_as_empty_dict_in_tool_trace():
    """When a model emits malformed JSON arguments, the runtime records arguments as {}."""
    session = FakeSession([mcp_tool()])
    responses = [
        NS(
            content=None,
            tool_calls=[
                NS(
                    id="call-malformed",
                    type="function",
                    function=NS(name="flag_suspicious_tx", arguments='{"tx_id": "TX003", "reason":'),
                )
            ],
        ),
        NS(content="Recovered after malformed tool call.", tool_calls=[]),
    ]

    def mock_model(*_args, **_kwargs):
        return responses.pop(0), {"calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "max_prompt": 10}

    result = _inline(run_with_session(
        "flag TX003", session, model_request=mock_model, system_prompt="test",
    ))

    assert result.status == "completed"
    assert session.calls == []
    assert len(result.tool_trace) == 1
    trace = result.tool_trace[0]
    assert trace["status"] == "error"
    assert "Malformed JSON arguments" in trace["error"]
    assert trace["arguments"] == {}
    assert isinstance(trace["arguments"], dict)


def test_non_dict_json_arguments_captured_as_empty_dict_in_tool_trace():
    """When a model emits JSON that parses to a non-dict (e.g. a string), arguments defaults to {}."""
    session = FakeSession([mcp_tool()])
    responses = [
        NS(
            content=None,
            tool_calls=[
                NS(
                    id="call-str-json",
                    type="function",
                    function=NS(name="flag_suspicious_tx", arguments='"not an object"'),
                )
            ],
        ),
        NS(content="Done.", tool_calls=[]),
    ]

    def mock_model(*_args, **_kwargs):
        return responses.pop(0), {"calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "max_prompt": 10}

    result = _inline(run_with_session(
        "flag TX003", session, model_request=mock_model, system_prompt="test",
    ))

    assert result.status == "completed"
    assert session.calls == []
    assert len(result.tool_trace) == 1
    trace = result.tool_trace[0]
    assert trace["status"] == "error"
    assert "expected JSON object" in trace["error"]
    assert trace["arguments"] == {}
    assert isinstance(trace["arguments"], dict)


def test_step_events_handles_malformed_arguments_trace_record():
    """build_step_events validates and emits a step_event for failed tool calls with arguments={}."""
    tool_trace = [{
        "step": 1,
        "tool_call_id": "call-1",
        "tool_name": "flag_suspicious_tx",
        "arguments": {},
        "result": "Tool error: Malformed JSON arguments: Unterminated string",
        "status": "error",
        "error": "Malformed JSON arguments: Unterminated string",
    }]
    usage = {"calls": 1, "prompt_tokens": 10, "completion_tokens": 5, "max_prompt": 10}

    events, skipped = build_step_events(
        tool_trace=tool_trace,
        usage=usage,
        run_id="run-test",
        question_id="q06",
        scenario="flag",
        execution_mode="unit_test",
    )

    assert skipped is None
    assert len(events) == 1
    event = events[0]
    assert event["scenario_evidence_status"] == "tool_call_failed"
    assert event["args"] == {}
    assert event["status"] == "error"
    assert event["business_outcome_verified"] is False
    assert validate_event(event) == []


def test_validate_trace_record_coerces_none_arguments_on_error():
    """_validate_trace_record defensively converts arguments=None to {} if status is error."""
    record = {
        "step": 1,
        "tool_call_id": "call-1",
        "tool_name": "flag_suspicious_tx",
        "arguments": None,
        "result": "Tool error: Malformed JSON arguments",
        "status": "error",
        "error": "Malformed JSON arguments",
    }
    _validate_trace_record(record)
    assert record["arguments"] == {}


def test_resolve_decision_without_policy_rule_id_leaves_reason_code_none():
    """When submit_decision has no policy_rule_id, policy_reason_code remains None."""
    raw = {
        "outcome": "answer",
        "decision_source": MODEL_DECISION_SOURCE,
    }
    result = resolve_decision(raw, contexts=[], tool_trace=[])
    assert result["actual_outcome"] == "answer"
    assert result["actual_refusal_type"] is None
    assert result["policy_rule_id"] is None
    assert result["policy_decision_status"] == "decided"
    assert result["policy_reason_code"] is None


def test_resolve_decision_with_evidenced_rule_id():
    """When policy_rule_id matches a retrieved context, it is accepted with policy_reason_code=None."""
    raw = {
        "outcome": "answer",
        "policy_rule_id": "DOC0004_ART05",
        "decision_source": MODEL_DECISION_SOURCE,
    }
    contexts = ["[Source: DOC0004] Điều 05. Bất khả thi địa lý đối với giao dịch đa quốc gia."]
    result = resolve_decision(raw, contexts=contexts, tool_trace=[])
    assert result["actual_outcome"] == "answer"
    assert result["policy_rule_id"] == "DOC0004_ART05"
    assert result["policy_decision_status"] == "decided"
    assert result["policy_reason_code"] is None


def test_resolve_decision_refusal_type_ii():
    """submit_decision with refusal type ii produces decided status with no error code."""
    raw = {
        "outcome": "refusal",
        "refusal_type": "ii",
        "decision_source": MODEL_DECISION_SOURCE,
    }
    result = resolve_decision(raw, contexts=[], tool_trace=[])
    assert result["actual_outcome"] == "refusal"
    assert result["actual_refusal_type"] == "ii"
    assert result["policy_decision_status"] == "decided"
    assert result["policy_reason_code"] is None
