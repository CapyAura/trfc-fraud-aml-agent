"""Independent MCP stdio client for discovering and invoking server tools.

Run ``python -m trfc.mcp_server.client2 --tool search_policy --arguments
'{"query":"transaction limits"}'`` from the project root. Tool names and
schemas are discovered from the server at runtime; no tool is invoked unless
``--tool`` is supplied.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]


class ClientError(Exception):
    """An input, discovery, connection, or MCP tool-call error."""


def _field(value: Any, name: str, fallback: str | None = None, default: Any = None) -> Any:
    """Read fields from MCP models and mapping-based test doubles."""
    if isinstance(value, dict):
        if name in value:
            return value[name]
        return value.get(fallback, default) if fallback else default
    result = getattr(value, name, None)
    return result if result is not None else getattr(value, fallback, default) if fallback else default


async def discover_tools(session: Any) -> list[Any]:
    """Return tools advertised by the connected MCP server."""
    response = await session.list_tools()
    tools = _field(response, "tools")
    if not isinstance(tools, list):
        raise ClientError("MCP server returned a malformed tools/list response.")
    return tools


def validate_arguments(tool: Any, arguments: Any) -> dict[str, Any]:
    """Check JSON object arguments against the discovered input schema."""
    if not isinstance(arguments, dict):
        raise ClientError("Tool arguments must be a JSON object.")
    schema = _field(tool, "input_schema", "inputSchema", {}) or {}
    if not isinstance(schema, dict):
        raise ClientError("Discovered tool has a malformed input schema.")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        raise ClientError("Discovered tool has a malformed input schema.")
    required = schema.get("required", [])
    if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
        raise ClientError("Discovered tool has a malformed required-arguments list.")
    missing = [key for key in required if key not in arguments]
    if missing:
        raise ClientError(f"Missing required tool argument(s): {', '.join(missing)}.")
    unknown = [key for key in arguments if key not in properties]
    if unknown and schema.get("additionalProperties") is False:
        raise ClientError(f"Unknown tool argument(s): {', '.join(unknown)}.")
    json_types = {
        "object": dict,
        "array": list,
        "string": str,
        "boolean": bool,
        "null": type(None),
    }
    for key, value in arguments.items():
        property_schema = properties.get(key)
        if not isinstance(property_schema, dict):
            continue
        expected_type = property_schema.get("type")
        actual_type = json_types.get(expected_type)
        if expected_type == "integer":
            valid_type = isinstance(value, int) and not isinstance(value, bool)
        elif expected_type == "number":
            valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            valid_type = actual_type is None or isinstance(value, actual_type)
        if not valid_type:
            raise ClientError(f"Tool argument '{key}' must have JSON type '{expected_type}'.")
        enum = property_schema.get("enum")
        if isinstance(enum, list) and value not in enum:
            raise ClientError(f"Tool argument '{key}' must be one of the discovered enum values.")
    return arguments


async def call_discovered_tool(session: Any, tools: list[Any], name: str, arguments: Any) -> Any:
    """Call only a tool confirmed by the current discovery response."""
    selected = next((tool for tool in tools if _field(tool, "name") == name), None)
    if selected is None:
        raise ClientError(f"Unknown tool '{name}'. Choose a name returned by tools/list.")
    checked_arguments = validate_arguments(selected, arguments)
    result = await session.call_tool(name, checked_arguments)
    if _field(result, "is_error", "isError", False):
        details = []
        for item in _field(result, "content", default=[]) or []:
            text = _field(item, "text")
            if isinstance(text, str):
                details.append(text)
        message = "; ".join(details) or "server reported an MCP tool error"
        raise ClientError(f"Tool '{name}' failed: {message}")
    return result


def _display_tools(tools: list[Any]) -> None:
    print("Discovered MCP tools:")
    for tool in tools:
        name = _field(tool, "name", default="<unnamed>")
        description = _field(tool, "description", default="") or "(no description)"
        schema = _field(tool, "input_schema", "inputSchema", {}) or {}
        print(f"- {name}: {description}")
        print(f"  input schema: {json.dumps(schema, ensure_ascii=False, sort_keys=True)}")


def _display_result(result: Any) -> None:
    structured = _field(result, "structured_content", "structuredContent")
    if structured is not None:
        print(json.dumps(structured, ensure_ascii=False, default=str))
        return
    content = _field(result, "content", default=[]) or []
    text_items = [_field(item, "text") for item in content if isinstance(_field(item, "text"), str)]
    if text_items:
        print("\n".join(text_items))
    else:
        print("Tool completed with no text content.")


def _server_parameters(command: str, server_args: list[str] | None) -> Any:
    """Build parameters using the same MCP stdio SDK used by the agent."""
    from mcp.client.stdio import StdioServerParameters

    env = {"PYTHONPATH": str(ROOT_DIR / "src")}
    existing_pythonpath = os.environ.get("PYTHONPATH")
    if existing_pythonpath:
        env["PYTHONPATH"] += os.pathsep + existing_pythonpath
    return StdioServerParameters(
        command=command,
        args=server_args if server_args is not None else ["-m", "trfc.mcp_server.server"],
        env=env,
        cwd=str(ROOT_DIR),
    )


async def run_client(
    tool_name: str,
    arguments: dict[str, Any],
    *,
    command: str | None = None,
    server_args: list[str] | None = None,
) -> None:
    """Connect, initialize, discover, invoke the selected tool, and clean up."""
    try:
        from mcp.client.session import ClientSession
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise ClientError("The MCP SDK is unavailable; install the project's declared dependencies.") from exc

    params = _server_parameters(command or sys.executable, server_args)
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await discover_tools(session)
            _display_tools(tools)
            result = await call_discovered_tool(session, tools, tool_name, arguments)
            _display_result(result)


def _parse_arguments(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ClientError(f"Invalid JSON for --arguments: {exc.msg} at character {exc.pos}.") from exc
    if not isinstance(parsed, dict):
        raise ClientError("--arguments must decode to a JSON object.")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Discover and call a tool on the TRFC MCP stdio server.")
    parser.add_argument("--tool", required=True, help="Tool name (validated against runtime discovery).")
    parser.add_argument("--arguments", default="{}", help="Tool arguments as a JSON object.")
    parser.add_argument("--command", default=sys.executable, help="Server executable (defaults to this Python).")
    parser.add_argument(
        "--server-arg", action="append", dest="server_args",
        help="Server command argument; repeat as needed. Defaults to -m trfc.mcp_server.server.",
    )
    options = parser.parse_args(argv)
    try:
        arguments = _parse_arguments(options.arguments)
        asyncio.run(run_client(options.tool, arguments, command=options.command, server_args=options.server_args))
    except (ClientError, OSError, RuntimeError, ValueError) as exc:
        print(f"MCP client failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        # MCP session and transport exceptions vary by SDK version; surface the failure.
        print(f"MCP client failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
