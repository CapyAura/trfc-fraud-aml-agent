"""Evaluation adapter for the agent's detailed runtime result.

Importing this module does not start the agent, load credentials, or open the
database. A real call requires the configured Groq service and local MCP server.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from trfc.agent.loop import run_detailed


_RESULT_FIELDS = (
    "answer",
    "actual_outcome",
    "actual_refusal_type",
    "contexts",
    "claims",
    "tool_trace",
    "usage",
    "status",
    "error",
)


async def run_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run one case and pass through only fields explicitly supplied at runtime.

    The runtime reports ``None`` until MCP discovery activates trace capture,
    ``[]`` after a completed run with no tool events, and captured events (even
    partial ones) when a failure occurs after tool execution starts. Trace
    values are passed through unchanged; ``None`` is never converted to ``[]``.
    """
    if not isinstance(case, dict):
        raise TypeError("Evaluation case must be a dict")
    question = case.get("question")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Evaluation case needs a non-empty question")

    result = await run_detailed(question)
    if is_dataclass(result) and not isinstance(result, type):
        payload = asdict(result)
    elif isinstance(result, dict):
        payload = result
    else:
        raise TypeError("run_detailed() must return a dataclass or dict")

    mapped = {name: payload.get(name) for name in _RESULT_FIELDS}
    return mapped
