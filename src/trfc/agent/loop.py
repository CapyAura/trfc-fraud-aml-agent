"""Groq native tool-calling loop over the dynamically discovered MCP tools."""

from dataclasses import dataclass
import asyncio
import json
import inspect
import logging
import os
from pathlib import Path
import re
import sys
import tomllib
from typing import Any

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from trfc.agent.llm import LLMRequestError, call_llm_async
from trfc.tools.state import DB_PATH_ENV, REQUIRE_ISOLATED_DB_ENV, resolve_db_path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
CONFIG_PATH = ROOT_DIR / "config.toml"
PROMPT_PATH = ROOT_DIR / "prompts" / "system.txt"

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="[REACT ENGINE] %(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("react_loop")


@dataclass
class AgentRunResult:
    """Provisional detailed result; unknown evaluation fields remain unavailable."""

    answer: str | None = None
    actual_outcome: str | None = None
    actual_refusal_type: str | None = None
    policy_rule_id: str | None = None
    decision_source: str | None = None
    contexts: list[str] | None = None
    claims: list[str] | None = None
    tool_trace: list[dict[str, Any]] | None = None
    usage: dict[str, int | None] | None = None
    status: str = "failed"
    error: str | None = None
    policy_decision_status: str | None = None
    policy_reason_code: str | None = None


class _UsageTotals:
    def __init__(self):
        self.calls = 0
        self.prompt_total = 0
        self.completion_total = 0
        self.max_prompt = 0
        self.prompt_complete = True
        self.completion_complete = True
        self.max_prompt_complete = True

    def add(self, usage: Any, fallback_calls: int = 1) -> None:
        calls = getattr(usage, "calls", None)
        if isinstance(usage, dict):
            calls = usage.get("calls")
        self.calls += max(1, calls) if type(calls) is int and calls >= 0 else fallback_calls

        def add_counter(name: str, total_name: str, complete_name: str, *, maximum: bool = False):
            value = getattr(usage, name, None)
            if isinstance(usage, dict):
                value = usage.get(name)
            if type(value) is not int or value < 0:
                setattr(self, complete_name, False)
                return
            if maximum:
                self.max_prompt = max(self.max_prompt, value)
            else:
                setattr(self, total_name, getattr(self, total_name) + value)

        add_counter("prompt_tokens", "prompt_total", "prompt_complete")
        add_counter("completion_tokens", "completion_total", "completion_complete")
        add_counter("max_prompt", "max_prompt", "max_prompt_complete", maximum=True)

    def add_failed_request(self, calls: int) -> None:
        self.calls += max(0, calls)
        self.prompt_complete = False
        self.completion_complete = False
        self.max_prompt_complete = False

    def as_dict(self) -> dict[str, int | None] | None:
        if self.calls == 0:
            return None
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_total if self.prompt_complete else None,
            "completion_tokens": self.completion_total if self.completion_complete else None,
            "max_prompt": self.max_prompt if self.max_prompt_complete else None,
        }


def load_max_steps() -> int:
    """Read MAX_STEPS from config.toml (default 8)."""
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open("rb") as stream:
                value = tomllib.load(stream).get("agent", {}).get("max_steps", 8)
            if type(value) is int and value > 0:
                return value
            logger.warning("Invalid agent.max_steps; using 8")
        except Exception as exc:
            logger.warning("Could not read config.toml; using 8: %s", exc)
    return 8


def load_system_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Required system prompt not found at {PROMPT_PATH}")


def mcp_server_environment() -> dict[str, str]:
    """Pass project path settings, but never copy or print credentials."""
    environment = {"PYTHONPATH": str(ROOT_DIR / "src")}
    # The stdio SDK launches a fresh process with this mapping. Retain only
    # operating-system variables needed to start Python, not unrelated secrets.
    for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"):
        if name in os.environ:
            environment[name] = os.environ[name]
    if DB_PATH_ENV in os.environ:
        configured_path = os.environ[DB_PATH_ENV]
        environment[DB_PATH_ENV] = (
            str(resolve_db_path()) if configured_path.strip() else configured_path
        )
    if REQUIRE_ISOLATED_DB_ENV in os.environ:
        environment[REQUIRE_ISOLATED_DB_ENV] = os.environ[REQUIRE_ISOLATED_DB_ENV]
    return environment


def _field(value: Any, name: str, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _tool_schema(tool: Any) -> dict[str, Any]:
    name = _field(tool, "name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("MCP discovery returned a tool without a valid name")
    function: dict[str, Any] = {
        "name": name,
        "description": _field(tool, "description") or "",
    }
    input_schema = _field(tool, "input_schema")
    if input_schema is None:
        input_schema = _field(tool, "inputSchema")
    if input_schema is not None:
        if not isinstance(input_schema, dict):
            raise ValueError(f"MCP input schema for {name!r} must be an object")
        function["parameters"] = input_schema
    return {"type": "function", "function": function}


def _json_type_matches(value: Any, expected: str) -> bool:
    checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: type(item) is int,
        "number": lambda item: type(item) in {int, float},
        "boolean": lambda item: type(item) is bool,
        "null": lambda item: item is None,
    }
    return expected not in checks or checks[expected](value)


def _validate_arguments(arguments: Any, schema: Any) -> str | None:
    if not isinstance(arguments, dict):
        return "arguments must be a JSON object"
    if schema is None:
        return None
    if not isinstance(schema, dict):
        return "tool input schema is malformed"
    if schema.get("type") not in (None, "object"):
        return "tool input schema must have object type"
    required = schema.get("required", [])
    properties = schema.get("properties", {})
    if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
        return "tool input schema has malformed required fields"
    if not isinstance(properties, dict):
        return "tool input schema has malformed properties"
    missing = [key for key in required if key not in arguments]
    if missing:
        return f"missing required argument(s): {', '.join(missing)}"
    if schema.get("additionalProperties") is False:
        extra = sorted(set(arguments) - set(properties))
        if extra:
            return f"unexpected argument(s): {', '.join(extra)}"
    for key, value in arguments.items():
        property_schema = properties.get(key)
        if not isinstance(property_schema, dict):
            continue
        expected_type = property_schema.get("type")
        accepted = expected_type if isinstance(expected_type, list) else [expected_type]
        known_types = {"object", "array", "string", "integer", "number", "boolean", "null"}
        if expected_type is not None and (
            not all(isinstance(kind, str) and kind in known_types for kind in accepted)
        ):
            return f"tool input schema has an invalid type for argument {key!r}"
        if expected_type is not None and not any(_json_type_matches(value, kind) for kind in accepted):
            return f"argument {key!r} has an invalid type"
        if "enum" in property_schema and value not in property_schema["enum"]:
            return f"argument {key!r} is outside the allowed values"
    return None


def _tool_calls(message: Any) -> list[Any]:
    calls = _field(message, "tool_calls")
    if calls is None:
        return []
    if not isinstance(calls, (list, tuple)):
        raise ValueError("assistant tool_calls must be a list")
    return list(calls)


def _tool_output(result: Any) -> tuple[str, str]:
    is_error = bool(_field(result, "isError", _field(result, "is_error", False)))
    content = _field(result, "content", []) or []
    texts = []
    for item in content:
        value = item if isinstance(item, str) else _field(item, "text")
        if isinstance(value, str):
            texts.append(value)
    if not texts:
        structured = _field(result, "structuredContent", _field(result, "structured_content"))
        if structured is not None:
            texts.append(json.dumps(structured, ensure_ascii=False, default=str))
    output = "\n".join(texts)
    if output:
        try:
            decoded = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        if isinstance(decoded, str) and decoded.startswith("Error:"):
            output = decoded
            is_error = True
    if is_error or output.startswith("Error:"):
        return output or "Tool reported an error without details", "error"
    return output, "completed"


def _retrieved_contexts(tool_name: str, tool_result: str) -> list[str] | None:
    """Return only source text explicitly returned by the policy retrieval tool."""
    if tool_name != "search_policy":
        return None
    try:
        chunks = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(chunks, list):
        return None
    contexts = []
    for chunk in chunks:
        if (not isinstance(chunk, dict)
                or not isinstance(chunk.get("doc_id"), str)
                or re.fullmatch(r"DOC\d{4}", chunk["doc_id"], re.IGNORECASE) is None
                or not isinstance(chunk.get("text"), str)
                or not chunk["text"].strip()):
            return None
        contexts.append(f"[Source: {chunk['doc_id']}] {chunk['text']}")
    return contexts


async def run_with_session(
    question: str,
    session: Any,
    *,
    model_request=call_llm_async,
    max_steps: int | None = None,
    system_prompt: str | None = None,
) -> AgentRunResult:
    """Run the tool loop with injectable model/session collaborators."""
    # Trace capture is unavailable until MCP discovery completes. Once it does,
    # every tool call is appended below; failed runs retain partial events.
    result = AgentRunResult()
    usage_totals = _UsageTotals()
    contexts_capture_complete = True
    try:
        if max_steps is None:
            max_steps = load_max_steps()
        if type(max_steps) is not int or max_steps < 1:
            raise ValueError("max_steps must be a positive integer")
        discovered = _field(await session.list_tools(), "tools", [])
        by_name = {}
        schemas = []
        for tool in discovered:
            schema = _tool_schema(tool)
            name = schema["function"]["name"]
            if name in by_name:
                raise ValueError(f"MCP discovery returned duplicate tool {name!r}")
            by_name[name] = tool
            schemas.append(schema)

        # Discovery succeeded and the trace hook is now active. A successful
        # no-tool run will retain this empty list; failures with no events are
        # converted back to unavailable in the finalization block below.
        result.tool_trace = []

        messages = [
            {"role": "system", "content": system_prompt if system_prompt is not None else load_system_prompt()},
            {"role": "user", "content": question},
        ]
        for step in range(1, max_steps + 1):
            try:
                response = model_request(messages, tools=schemas)
                if inspect.isawaitable(response):
                    response = await response
                assistant, usage = response
                usage_totals.add(usage)
            except LLMRequestError as exc:
                usage_totals.add_failed_request(exc.calls)
                result.error = str(exc)
                result.usage = usage_totals.as_dict()
                return result
            except Exception as exc:
                usage_totals.prompt_complete = False
                usage_totals.completion_complete = False
                usage_totals.max_prompt_complete = False
                result.error = f"Model request failed: {type(exc).__name__}: {exc}"
                result.usage = usage_totals.as_dict()
                return result

            content = _field(assistant, "content")
            calls = _tool_calls(assistant)
            if not calls:
                if not isinstance(content, str) or not content.strip():
                    result.error = "Assistant response has no final content or tool calls"
                    result.usage = usage_totals.as_dict()
                    return result
                result.answer = content
                result.status = "completed"
                result.usage = usage_totals.as_dict()
                return result

            assistant_entry: dict[str, Any] = {"role": "assistant", "tool_calls": []}
            if isinstance(content, str):
                assistant_entry["content"] = content
            normalized_calls = []
            seen_ids = set()
            for call in calls:
                call_id = _field(call, "id")
                call_type = _field(call, "type", "function")
                function = _field(call, "function")
                name = _field(function, "name")
                raw_arguments = _field(function, "arguments")
                if not isinstance(call_id, str) or not call_id.strip() or call_id in seen_ids:
                    result.error = "Assistant tool call has a missing or duplicate call ID"
                    result.usage = usage_totals.as_dict()
                    return result
                seen_ids.add(call_id)
                if (call_type != "function" or not isinstance(name, str) or not name.strip()
                        or not isinstance(raw_arguments, str)):
                    result.error = f"Assistant tool call {call_id!r} has malformed function fields"
                    result.usage = usage_totals.as_dict()
                    return result
                normalized_calls.append((call_id, name, raw_arguments, function))
                assistant_entry["tool_calls"].append({
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": raw_arguments},
                })
            messages.append(assistant_entry)

            for call_id, name, raw_arguments, function in normalized_calls:
                error = None
                tool_result_text = ""
                status = "error"
                arguments = None
                tool = by_name.get(name)
                if tool is None:
                    error = f"Unknown or undiscovered tool {name!r}"
                else:
                    try:
                        arguments = json.loads(raw_arguments)
                    except (json.JSONDecodeError, TypeError) as exc:
                        error = f"Malformed JSON arguments: {exc}"
                    if error is None:
                        input_schema = _field(tool, "input_schema", _field(tool, "inputSchema"))
                        error = _validate_arguments(arguments, input_schema)
                    if error is None:
                        try:
                            tool_result = await session.call_tool(name, arguments)
                            tool_result_text, status = _tool_output(tool_result)
                            if status == "error":
                                error = tool_result_text
                            elif name == "search_policy":
                                retrieved = _retrieved_contexts(name, tool_result_text)
                                if retrieved is None:
                                    contexts_capture_complete = False
                                else:
                                    if result.contexts is None:
                                        result.contexts = []
                                    result.contexts.extend(retrieved)
                        except Exception as exc:
                            error = f"Tool execution failed: {type(exc).__name__}: {exc}"
                if error is not None:
                    status = "error"
                    tool_result_text = f"Tool error: {error}"
                result.tool_trace.append({
                    "step": step, "tool_call_id": call_id, "tool_name": name,
                    "arguments": arguments, "result": tool_result_text,
                    "status": status, "error": error,
                })
                messages.append({
                    "role": "tool", "tool_call_id": call_id, "content": tool_result_text,
                })

        result.error = f"Native tool loop exceeded MAX_STEPS ({max_steps})"
        result.usage = usage_totals.as_dict()
        return result
    except Exception as exc:
        result.error = f"Agent run failed: {type(exc).__name__}: {exc}"
        result.usage = usage_totals.as_dict()
        return result
    finally:
        if result.status != "completed" and result.tool_trace == []:
            result.tool_trace = None
        if not contexts_capture_complete:
            result.contexts = None


async def run_detailed(question: str, *, model_request=call_llm_async) -> AgentRunResult:
    """Run against the project's stdio MCP server and return structured status."""
    try:
        server_params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "trfc.mcp_server.server"],
            env=mcp_server_environment(),
            cwd=ROOT_DIR,
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                return await run_with_session(question, session, model_request=model_request)
    except Exception as exc:
        return AgentRunResult(
            tool_trace=None, error=f"MCP connection failed: {type(exc).__name__}: {exc}"
        )


async def run(question: str) -> str:
    """Backward-compatible string API; detailed callers can use run_detailed()."""
    result = await run_detailed(question)

    if result.status == "failed":
        return f"Error: {result.error or 'Unknown error'}"

    return result.answer or ""


def main() -> int:
   def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) < 2:
        print('Usage: python -m trfc.agent.loop "question"', file=sys.stderr)
        return 2

    # Chạy hàm lấy chi tiết result
    result = asyncio.run(run_detailed(" ".join(sys.argv[1:])))
    
    # In toàn bộ JSON kết quả ra stdout
    output_dict = {
        "status": result.status,
        "answer": result.answer,
        "actual_outcome": result.actual_outcome,
        "actual_refusal_type": result.actual_refusal_type,
        "contexts": result.contexts,
        "claims": result.claims,
        "tool_trace": result.tool_trace,
        "usage": result.usage,
        "error": result.error,
    }
    print(json.dumps(output_dict, ensure_ascii=False, indent=2))
    return 0 if result.status == "completed" else 1

if __name__ == "__main__":
    raise SystemExit(main())
