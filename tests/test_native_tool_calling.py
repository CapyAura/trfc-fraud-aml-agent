"""Deterministic native tool-call tests with fake Groq responses and MCP sessions."""

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace as NS

import trfc.agent.loop as agent_loop
import trfc.agent.llm as agent_llm
from trfc.agent.llm import LLMRequestError, Usage, call_llm
from trfc.agent.loop import run_with_session


def _inline(coroutine):
    """Drive fake-only coroutines without initializing a platform event loop."""
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("fake test coroutine unexpectedly suspended")


def tool_call(call_id, name, arguments):
    return NS(id=call_id, type="function", function=NS(name=name, arguments=arguments))


def assistant(content=None, calls=None):
    return NS(content=content, tool_calls=calls)


class FakeSession:
    def __init__(self, tools, results=None, errors=None, initialize_error=None, discovery_error=None):
        self.tools = tools
        self.results = results or {}
        self.errors = errors or {}
        self.initialize_error = initialize_error
        self.discovery_error = discovery_error
        self.calls = []

    async def list_tools(self):
        if self.discovery_error:
            raise self.discovery_error
        return NS(tools=self.tools)

    async def initialize(self):
        if self.initialize_error:
            raise self.initialize_error
        return None

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        if name in self.errors:
            raise self.errors[name]
        return self.results.get(name, NS(content=[NS(text="tool result")], isError=False))


def mcp_tool(name="lookup", schema=None):
    return NS(name=name, description="test tool", input_schema=schema or {
        "type": "object", "properties": {"key": {"type": "string"}},
        "required": ["key"], "additionalProperties": False,
    })


def test_native_tool_call_followed_by_final_answer_and_matching_tool_result_id():
    session = FakeSession([mcp_tool()])
    requests = []
    responses = [
        assistant(calls=[tool_call("call-1", "lookup", '{"key":"x"}')]),
        assistant(content="Found it."),
    ]

    def model(messages, *, tools):
        requests.append((list(messages), tools))
        return responses.pop(0), Usage(calls=1, prompt_tokens=10, completion_tokens=2, max_prompt=10)

    result = _inline(run_with_session("find", session, model_request=model, system_prompt="system"))

    assert result.status == "completed" and result.answer == "Found it."
    assert result.actual_outcome is None and result.actual_refusal_type is None
    assert result.contexts is None and result.claims is None
    assert result.usage == {"calls": 2, "prompt_tokens": 20, "completion_tokens": 4, "max_prompt": 10}
    assert session.calls == [("lookup", {"key": "x"})]
    sent_tools = requests[0][1]
    assert sent_tools[0]["function"]["name"] == "lookup"
    second_turn = requests[1][0]
    assert second_turn[-2]["role"] == "assistant"
    assert second_turn[-2]["tool_calls"][0]["id"] == "call-1"
    assert second_turn[-1] == {"role": "tool", "tool_call_id": "call-1", "content": "tool result"}


def test_multiple_discovered_tool_calls_execute_in_order():
    session = FakeSession([mcp_tool("first"), mcp_tool("second")])
    responses = [
        assistant(calls=[
            tool_call("call-a", "first", '{"key":"a"}'),
            tool_call("call-b", "second", '{"key":"b"}'),
        ]),
        assistant(content="Done."),
    ]

    result = _inline(run_with_session(
        "do both", session, model_request=lambda *_args, **_kwargs: (responses.pop(0), None),
        system_prompt="system",
    ))

    assert result.status == "completed"
    assert session.calls == [("first", {"key": "a"}), ("second", {"key": "b"})]
    assert [event["tool_call_id"] for event in result.tool_trace] == ["call-a", "call-b"]


def test_malformed_arguments_and_unknown_tool_are_returned_as_errors_without_execution():
    session = FakeSession([mcp_tool()])
    requests = []
    responses = [
        assistant(calls=[
            tool_call("bad-json", "lookup", '{"key":'),
            tool_call("unknown", "not_discovered", '{"key":"x"}'),
        ]),
        assistant(content="I could not use those tools."),
    ]

    def model(messages, **_kwargs):
        requests.append(list(messages))
        return responses.pop(0), None

    result = _inline(run_with_session("query", session, model_request=model, system_prompt="system"))

    assert result.status == "completed"
    assert session.calls == []
    assert [event["status"] for event in result.tool_trace] == ["error", "error"]
    tool_messages = [message for message in requests[1] if message.get("role") == "tool"]
    assert [message["tool_call_id"] for message in tool_messages] == ["bad-json", "unknown"]
    assert "Malformed JSON" in tool_messages[0]["content"]
    assert "Unknown or undiscovered" in tool_messages[1]["content"]


def test_schema_validation_and_tool_execution_errors_are_not_silent_successes():
    session = FakeSession([mcp_tool()], errors={"lookup": RuntimeError("tool broke")})
    responses = [
        assistant(calls=[
            tool_call("wrong-type", "lookup", '{"key":7}'),
            tool_call("runtime-error", "lookup", '{"key":"x"}'),
        ]),
        assistant(content="The tool failed."),
    ]

    result = _inline(run_with_session(
        "query", session,
        model_request=lambda *_args, **_kwargs: (responses.pop(0), None),
        system_prompt="system",
    ))

    assert result.status == "completed"
    assert len(session.calls) == 1
    assert result.tool_trace[0]["error"].startswith("argument 'key'")
    assert result.tool_trace[1]["error"].startswith("Tool execution failed: RuntimeError")


def test_json_encoded_tool_error_is_still_classified_as_tool_failure():
    session = FakeSession([mcp_tool()], results={
        "lookup": NS(content=[NS(text='"Error: database unavailable"')], isError=False),
    })
    responses = [
        assistant(calls=[tool_call("failed-call", "lookup", '{"key":"x"}')]),
        assistant(content="The lookup failed."),
    ]
    result = _inline(run_with_session(
        "query", session,
        model_request=lambda *_args, **_kwargs: (responses.pop(0), None),
        system_prompt="system",
    ))
    assert result.status == "completed"
    assert result.tool_trace[0]["status"] == "error"
    assert result.tool_trace[0]["error"] == "Error: database unavailable"
    assert "Tool error:" in result.tool_trace[0]["result"]


def test_empty_assistant_content_without_tool_calls_fails():
    result = _inline(run_with_session(
        "query", FakeSession([mcp_tool()]),
        model_request=lambda *_args, **_kwargs: (assistant(content=None), None),
        system_prompt="system",
    ))
    assert result.status == "failed"
    assert "no final content" in result.error
    assert result.answer is None
    assert result.tool_trace is None


def test_discovery_failure_leaves_trace_unavailable():
    result = _inline(run_with_session(
        "query", FakeSession([], discovery_error=RuntimeError("discovery failed")),
        model_request=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("model must not be called before discovery")
        ),
        system_prompt="system",
    ))
    assert result.status == "failed"
    assert result.tool_trace is None
    assert "discovery failed" in result.error


def test_successful_execution_without_tool_calls_has_completed_empty_trace():
    result = _inline(run_with_session(
        "query", FakeSession([]),
        model_request=lambda *_args, **_kwargs: (assistant(content="answer"), None),
        system_prompt="system",
    ))
    assert result.status == "completed"
    assert result.tool_trace == []


def test_failure_after_tool_event_preserves_partial_trace():
    session = FakeSession([mcp_tool()])
    responses = [assistant(calls=[tool_call("call-1", "lookup", '{"key":"x"}')])]

    def model(*_args, **_kwargs):
        if responses:
            return responses.pop(0), None
        raise RuntimeError("later model failure")

    result = _inline(run_with_session(
        "query", session, model_request=model, system_prompt="system",
    ))
    assert result.status == "failed"
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0]["tool_name"] == "lookup"


def test_search_policy_contexts_are_captured_only_from_returned_chunks():
    retrieved = [{"doc_id": "DOC0012", "text": "Verified policy passage."}]
    session = FakeSession(
        [mcp_tool("search_policy")],
        results={"search_policy": NS(content=[NS(text=json.dumps(retrieved))], isError=False)},
    )
    responses = [
        assistant(calls=[tool_call("search-1", "search_policy", '{"key":"query"}')]),
        assistant(content="A response."),
    ]
    result = _inline(run_with_session(
        "query", session,
        model_request=lambda *_args, **_kwargs: (responses.pop(0), None),
        system_prompt="system",
    ))
    assert result.status == "completed"
    assert result.contexts == ["[Source: DOC0012] Verified policy passage."]
    assert result.actual_outcome is None
    assert result.actual_refusal_type is None
    assert result.claims is None


def test_malformed_search_result_keeps_contexts_unavailable():
    session = FakeSession(
        [mcp_tool("search_policy")],
        results={"search_policy": NS(content=[NS(text="not JSON")], isError=False)},
    )
    responses = [
        assistant(calls=[tool_call("search-1", "search_policy", '{"key":"query"}')]),
        assistant(content="A response."),
    ]
    result = _inline(run_with_session(
        "query", session,
        model_request=lambda *_args, **_kwargs: (responses.pop(0), None),
        system_prompt="system",
    ))
    assert result.status == "completed"
    assert result.contexts is None


def test_search_context_parser_rejects_invalid_chunk_fields_and_accepts_empty_results():
    from trfc.agent.loop import _retrieved_contexts

    assert _retrieved_contexts("search_policy", "[]") == []
    assert _retrieved_contexts("search_policy", '{"doc_id":"DOC0001"}') is None
    assert _retrieved_contexts(
        "search_policy", '[{"doc_id":"not-a-doc-id","text":"passage"}]'
    ) is None
    assert _retrieved_contexts(
        "search_policy", '[{"doc_id":"DOC0001","text":"  "}]'
    ) is None
    assert _retrieved_contexts("get_transactions", "[]") is None


def test_mcp_launcher_receives_resolved_isolated_database_environment(monkeypatch, tmp_path):
    from trfc.tools import state

    expected_db = (tmp_path / "runner-state.db").resolve()
    monkeypatch.setenv(state.DB_PATH_ENV, str(expected_db))
    monkeypatch.setenv(state.REQUIRE_ISOLATED_DB_ENV, "1")
    captured = {}

    @asynccontextmanager
    async def fake_stdio(params):
        captured["params"] = params
        yield "read", "write"

    class SuccessfulSession(FakeSession):
        async def initialize(self):
            return None

    session = SuccessfulSession([])

    class FakeClientSession:
        def __init__(self, *_streams):
            pass

        async def __aenter__(self):
            return session

        async def __aexit__(self, *_exc):
            return None

    monkeypatch.setattr(agent_loop, "stdio_client", fake_stdio)
    monkeypatch.setattr(agent_loop, "ClientSession", FakeClientSession)
    result = _inline(agent_loop.run_detailed(
        "query", model_request=lambda *_args, **_kwargs: (assistant(content="answer"), None),
    ))

    assert result.status == "completed"
    assert captured["params"].env[state.DB_PATH_ENV] == str(expected_db)
    assert captured["params"].env[state.REQUIRE_ISOLATED_DB_ENV] == "1"


def test_maximum_model_turns_is_enforced():
    session = FakeSession([mcp_tool()])
    result = _inline(run_with_session(
        "query", session,
        model_request=lambda *_args, **_kwargs: (
            assistant(calls=[tool_call("again", "lookup", '{"key":"x"}')]), None
        ),
        max_steps=2,
        system_prompt="system",
    ))
    assert result.status == "failed"
    assert result.error == "Native tool loop exceeded MAX_STEPS (2)"
    assert len(session.calls) == 2


def test_json_text_in_assistant_content_is_never_executed_as_a_tool_call():
    session = FakeSession([mcp_tool()])
    result = _inline(run_with_session(
        "query", session,
        model_request=lambda *_args, **_kwargs: (
            assistant(content='{"tool":"lookup","args":{"key":"x"}}'), None
        ),
        system_prompt="system",
    ))
    assert result.status == "completed"
    assert result.answer == '{"tool":"lookup","args":{"key":"x"}}'
    assert session.calls == []


def test_llm_wrapper_returns_structured_message_and_preserves_missing_usage():
    message = assistant(calls=[tool_call("call-1", "lookup", '{"key":"x"}')])
    response = NS(choices=[NS(message=message)], usage=None)

    class FakeCompletions:
        def create(self, **kwargs):
            self.kwargs = kwargs
            return response

    completions = FakeCompletions()
    client = NS(chat=NS(completions=completions))
    returned, usage = call_llm(
        [{"role": "user", "content": "query"}],
        tools=[{"type": "function", "function": {"name": "lookup", "parameters": {}}}],
        request_client=client,
    )

    assert returned is message and returned.tool_calls[0].id == "call-1"
    assert usage == Usage(calls=1, prompt_tokens=None, completion_tokens=None, max_prompt=None)
    assert completions.kwargs["tool_choice"] == "auto"


def test_model_usage_zeroes_are_preserved_when_provider_reports_them():
    response = NS(choices=[NS(message=assistant(content="ok"))],
                  usage=NS(prompt_tokens=0, completion_tokens=0))

    class FakeCompletions:
        def create(self, **_kwargs):
            return response

    _, usage = call_llm([], request_client=NS(chat=NS(completions=FakeCompletions())))
    assert usage == Usage(calls=1, prompt_tokens=0, completion_tokens=0, max_prompt=0)


def test_failed_model_requests_do_not_report_token_usage_as_zero():
    result = _inline(run_with_session(
        "query", FakeSession([mcp_tool()]),
        model_request=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            LLMRequestError("provider unavailable", calls=2)
        ),
        system_prompt="system",
    ))
    assert result.status == "failed"
    assert result.usage == {
        "calls": 2, "prompt_tokens": None, "completion_tokens": None, "max_prompt": None,
    }


def test_missing_provider_key_fails_before_constructing_or_calling_a_client(monkeypatch):
    monkeypatch.setattr(agent_llm, "load_dotenv", lambda: None)
    monkeypatch.setattr(agent_llm, "client", None)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    try:
        call_llm([])
    except RuntimeError as exc:
        assert "Missing GROQ_API_KEY" in str(exc)
    else:
        raise AssertionError("missing credentials should fail before a request")


def test_run_detailed_closes_fake_session_and_transport_on_success_and_failure(monkeypatch):
    states = []

    for failure in (None, RuntimeError("initialize failed")):
        session = FakeSession([mcp_tool()], initialize_error=failure)

        @asynccontextmanager
        async def fake_stdio(_params):
            try:
                yield "read", "write"
            finally:
                states.append("transport closed")

        class FakeClientSession:
            def __init__(self, *_streams):
                pass

            async def __aenter__(self):
                return session

            async def __aexit__(self, *_exc):
                states.append("session closed")

        monkeypatch.setattr(agent_loop, "stdio_client", fake_stdio)
        monkeypatch.setattr(agent_loop, "ClientSession", FakeClientSession)
        result = _inline(agent_loop.run_detailed(
            "query", model_request=lambda *_args, **_kwargs: (assistant(content="answer"), None)
        ))

        if failure:
            assert result.status == "failed"
            assert "MCP connection failed" in result.error
            assert result.tool_trace is None
        else:
            assert result.status == "completed", result.error
        assert states[-2:] == ["session closed", "transport closed"]
