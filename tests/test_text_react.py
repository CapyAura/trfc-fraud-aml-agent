"""Chế độ text ReAct (prompts/react_step.txt) — opt-in, đường native không đổi."""

import json

from types import SimpleNamespace as NS

from trfc.agent.loop import load_react_prompt, run_with_session


def _inline(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("fake test coroutine unexpectedly suspended")


def assistant(content=None, calls=None):
    return NS(content=content, tool_calls=calls)


class FakeSession:
    def __init__(self, tools, results=None):
        self.tools, self.results, self.calls = tools, results or {}, []

    async def list_tools(self):
        return NS(tools=self.tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results.get(name, NS(content=[NS(text="tool result")], isError=False))


def mcp_tool(name="lookup", schema=None):
    return NS(name=name, description="test tool", input_schema=schema or {
        "type": "object", "properties": {"key": {"type": "string"}},
        "required": ["key"], "additionalProperties": False,
    })

ACT = 'Thought: tra.\nAction:\n```json\n{"tool": "lookup", "args": {"key": "x"}}\n```'


def _model(replies, seen=None):
    it = iter(replies)

    def request(messages, tools=None):
        if seen is not None:
            seen.append((list(messages), tools))
        return assistant(content=next(it)), None
    return request


def _run(replies, session=None, **kw):
    session = session or FakeSession([mcp_tool()])
    seen = kw.pop("seen", None)
    res = _inline(run_with_session(
        "q", session, model_request=_model(replies, seen), text_react=True, **kw))
    return res, session


def test_react_prompt_loads_and_is_used_without_native_tools():
    seen = []
    res, _ = _run(["Thought: ok\nFinal Answer: Xong."], seen=seen)
    assert res.status == "completed" and res.answer == "Xong."
    messages, tools = seen[0]
    assert tools is None
    assert messages[0]["content"] == load_react_prompt()


def test_action_runs_via_mcp_then_observation_then_final_answer():
    seen = []
    res, session = _run([ACT, "Thought: đủ\nFinal Answer: Kết quả."], seen=seen)
    assert session.calls == [("lookup", {"key": "x"})]
    assert res.status == "completed" and res.answer == "Kết quả."
    assert res.tool_trace[0]["tool_name"] == "lookup" and res.tool_trace[0]["status"] == "completed"
    last_user = seen[1][0][-1]
    assert last_user["role"] == "user" and last_user["content"] == "Observation: tool result"


def test_broken_json_is_fed_back_as_error_not_crash():
    seen = []
    res, session = _run(['Thought: x\nAction:\n```json\n{"tool": "lookup", "args": {\n```',
                         "Final Answer: Thôi."], seen=seen)
    assert session.calls == []
    assert res.status == "completed"
    assert seen[1][0][-1]["content"].startswith("Observation: Error:")


def test_unknown_tool_and_bad_args_are_errors_without_execution():
    bad = 'Action:\n```json\n{"tool": "nope", "args": {}}\n```'
    miss = 'Action:\n```json\n{"tool": "lookup", "args": {}}\n```'
    res, session = _run([bad, miss, "Final Answer: ok"])
    assert session.calls == []
    assert [t["status"] for t in res.tool_trace] == ["error", "error"]
    assert res.tool_trace[0]["result"].startswith("Tool error: Unknown")
    assert "missing required" in res.tool_trace[1]["result"]


def test_tool_error_string_is_observation_not_exception():
    session = FakeSession([mcp_tool()], results={
        "lookup": NS(content=[NS(text=json.dumps("Error: Account X not found."))], isError=False)})
    res, _ = _run([ACT, "Final Answer: Không có tài khoản."], session=session)
    assert res.tool_trace[0]["status"] == "error"
    assert res.status == "completed"


def test_max_steps_is_enforced():
    res, session = _run([ACT, ACT, ACT], max_steps=2)
    assert res.status == "failed"
    assert res.error == "Text ReAct loop exceeded MAX_STEPS (2)"
    assert len(session.calls) == 2 and len(res.tool_trace) == 2


def test_search_policy_is_capped_at_two_calls():
    session = FakeSession([mcp_tool("search_policy", {
        "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]})],
        results={"search_policy": NS(content=[NS(text="[]")], isError=False)})
    act = 'Action:\n```json\n{"tool": "search_policy", "args": {"query": "q"}}\n```'
    res, _ = _run([act, act, act, "Final Answer: ok"], session=session)
    assert len(session.calls) == 2
    assert "tối đa 2 lần" in res.tool_trace[2]["result"]


def test_empty_response_fails_cleanly():
    res, _ = _run(["   "])
    assert res.status == "failed" and "no text content" in res.error
