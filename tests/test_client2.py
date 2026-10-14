"""Focused C6 tests using fake MCP sessions; no server or project data is used."""

from contextlib import asynccontextmanager
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from trfc.mcp_server import client2


def fake_tool(name="lookup", description="Read a value"):
    return SimpleNamespace(
        name=name,
        description=description,
        input_schema={
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    )


class FakeSession:
    def __init__(self, tools=None, result=None, error=None, call_error=None):
        self.tools = tools if tools is not None else [fake_tool()]
        self.result = result or SimpleNamespace(is_error=False, content=[SimpleNamespace(text="ok")])
        self.error = error
        self.call_error = call_error
        self.calls = []
        self.closed = False
        self.initialized = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        self.closed = True

    async def initialize(self):
        self.initialized = True

    async def list_tools(self):
        if self.error:
            raise self.error
        return SimpleNamespace(tools=self.tools)

    async def call_tool(self, name, arguments):
        if self.call_error:
            raise self.call_error
        if self.error:
            raise self.error
        self.calls.append((name, arguments))
        return self.result


def run_immediate(coroutine):
    """Drive fake-session coroutines that perform no event-loop I/O."""
    try:
        coroutine.send(None)
    except StopIteration as completed:
        return completed.value
    raise AssertionError("fake-session coroutine unexpectedly yielded to an event loop")


class Client2Tests(unittest.TestCase):
    def test_successful_discovery_returns_server_tools(self):
        session = FakeSession()
        tools = run_immediate(client2.discover_tools(session))
        self.assertEqual([tool.name for tool in tools], ["lookup"])
        output = StringIO()
        with redirect_stdout(output):
            client2._display_tools(tools)
        self.assertIn("lookup: Read a value", output.getvalue())
        self.assertIn('"required": ["key"]', output.getvalue())

    def test_call_uses_discovered_name_and_arguments(self):
        session = FakeSession()
        tools = run_immediate(client2.discover_tools(session))
        result = run_immediate(client2.call_discovered_tool(session, tools, "lookup", {"key": "x"}))
        self.assertEqual(session.calls, [("lookup", {"key": "x"})])
        self.assertEqual(result.content[0].text, "ok")

    def test_unknown_tool_is_rejected_without_call(self):
        session = FakeSession()
        tools = run_immediate(client2.discover_tools(session))
        with self.assertRaisesRegex(client2.ClientError, "Unknown tool"):
            run_immediate(client2.call_discovered_tool(session, tools, "not-advertised", {"key": "x"}))
        self.assertEqual(session.calls, [])

    def test_missing_required_arguments_are_rejected(self):
        session = FakeSession()
        tools = run_immediate(client2.discover_tools(session))
        with self.assertRaisesRegex(client2.ClientError, "Missing required"):
            run_immediate(client2.call_discovered_tool(session, tools, "lookup", {}))
        self.assertEqual(session.calls, [])

    def test_arguments_must_match_discovered_property_types(self):
        session = FakeSession()
        tools = run_immediate(client2.discover_tools(session))
        with self.assertRaisesRegex(client2.ClientError, "JSON type 'string'"):
            run_immediate(client2.call_discovered_tool(session, tools, "lookup", {"key": 7}))
        self.assertEqual(session.calls, [])

    def test_tool_error_is_not_reported_as_success(self):
        session = FakeSession(result=SimpleNamespace(is_error=True, content=[SimpleNamespace(text="denied")]))
        tools = run_immediate(client2.discover_tools(session))
        with self.assertRaisesRegex(client2.ClientError, "denied"):
            run_immediate(client2.call_discovered_tool(session, tools, "lookup", {"key": "x"}))

    def test_connection_and_discovery_failure_propagates(self):
        session = FakeSession(error=OSError("transport unavailable"))
        with self.assertRaisesRegex(OSError, "transport unavailable"):
            run_immediate(client2.discover_tools(session))

    def test_tool_transport_failure_propagates(self):
        session = FakeSession(call_error=OSError("call transport failed"))
        tools = run_immediate(client2.discover_tools(session))
        with self.assertRaisesRegex(OSError, "call transport failed"):
            run_immediate(client2.call_discovered_tool(session, tools, "lookup", {"key": "x"}))

    def test_stdio_connection_failure_propagates(self):
        @asynccontextmanager
        async def broken_stdio(_params):
            raise OSError("server could not be started")
            yield  # pragma: no cover - make this an async generator context manager

        with patch("mcp.client.stdio.stdio_client", broken_stdio):
            with self.assertRaisesRegex(OSError, "server could not be started"):
                run_immediate(client2.run_client("lookup", {"key": "x"}))

    def test_session_cleanup_on_success_and_discovery_failure(self):
        for error in (None, OSError("discovery failed")):
            session = FakeSession(error=error)

            @asynccontextmanager
            async def fake_stdio(_params):
                try:
                    yield "read", "write"
                finally:
                    session.transport_closed = True

            class FakeClientSession(FakeSession):
                def __init__(self, *_streams):
                    super().__init__(error=error)
                    self.outer = session

                async def __aenter__(self):
                    return self.outer

                async def __aexit__(self, *_exc):
                    self.outer.closed = True

            with (
                patch("mcp.client.stdio.stdio_client", fake_stdio),
                patch("mcp.client.session.ClientSession", FakeClientSession),
                patch.object(client2, "_display_tools"),
                patch.object(client2, "_display_result"),
            ):
                if error is None:
                    run_immediate(client2.run_client("lookup", {"key": "x"}))
                else:
                    with self.assertRaisesRegex(OSError, "discovery failed"):
                        run_immediate(client2.run_client("lookup", {"key": "x"}))
            self.assertTrue(session.closed)
            self.assertTrue(session.transport_closed)

    def test_launcher_receives_isolated_database_environment(self):
        from trfc.tools import state

        database = Path.cwd() / ".test-tmp" / "client-launcher-state.db"
        self.enterContext(patch.dict(os.environ, {
            state.DB_PATH_ENV: str(database),
            state.REQUIRE_ISOLATED_DB_ENV: "1",
        }))
        captured = {}
        @asynccontextmanager
        async def fake_stdio(params):
            captured["params"] = params
            yield "read", "write"

        class FakeClientSession(FakeSession):
            def __init__(self, *_streams):
                super().__init__()

        with (
            patch("mcp.client.stdio.stdio_client", fake_stdio),
            patch("mcp.client.session.ClientSession", FakeClientSession),
            patch.object(client2, "_display_tools"),
            patch.object(client2, "_display_result"),
        ):
            run_immediate(client2.run_client("lookup", {"key": "x"}))

        launched_env = captured["params"].env
        self.assertEqual(launched_env[state.DB_PATH_ENV], str(database.resolve()))
        self.assertEqual(launched_env[state.REQUIRE_ISOLATED_DB_ENV], "1")
        self.assertNotIn("GROQ_API_KEY", launched_env)

    def test_malformed_json_and_non_object_arguments_rejected(self):
        with self.assertRaisesRegex(client2.ClientError, "Invalid JSON"):
            client2._parse_arguments("{")
        with self.assertRaisesRegex(client2.ClientError, "JSON object"):
            client2._parse_arguments("[1, 2]")


if __name__ == "__main__":
    unittest.main()
