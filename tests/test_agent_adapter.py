"""Offline tests for mapping the agent's provisional detailed result."""

import json

import pytest

from eval import agent_adapter
from trfc.agent.loop import AgentRunResult


@pytest.fixture(autouse=True)
def _isolated_eval_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")


def _run_immediate(coroutine):
    """Run a fake-only coroutine without initializing an OS event loop."""
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("Fake coroutine unexpectedly suspended")


def test_adapter_passes_through_runtime_metadata_and_unavailable_fields(monkeypatch):
    calls = []
    runtime = AgentRunResult(
        answer="An answer that begins Error: but is still an answer",
        contexts=["[Source: DOC0012] passage"],
        tool_trace=[],
        usage={"calls": 1, "prompt_tokens": None, "completion_tokens": None, "max_prompt": None},
        status="completed",
    )

    async def fake_run_detailed(question):
        calls.append(question)
        return runtime

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))

    assert calls == ["case question"]
    assert agent_adapter.run_case.provenance.execution_mode == "real"
    assert agent_adapter.run_case.provenance.provider_id == "groq-default"
    assert result == {
        "answer": runtime.answer,
        "actual_outcome": None,
        "actual_refusal_type": None,
        "policy_rule_id": None,
        "decision_source": None,
        "contexts": runtime.contexts,
        "claims": None,
        "tool_trace": [],
        "usage": runtime.usage,
        "status": "completed",
        "error": None,
        "policy_decision_status": None,
        "policy_reason_code": None,
    }


@pytest.mark.parametrize(
    "answer",
    ["Tôi không đủ dữ liệu để kết luận.", "Không tìm thấy thông tin trong tài liệu."],
)
def test_adapter_does_not_infer_refusal_metadata_from_final_text(monkeypatch, answer):
    runtime = AgentRunResult(answer=answer, status="completed")

    async def fake_run_detailed(_question):
        return runtime

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "offline case"}))

    assert result["actual_outcome"] is None
    assert result["actual_refusal_type"] is None
    assert result["policy_rule_id"] is None
    assert result["decision_source"] is None
    assert result["claims"] is None


def test_injected_provider_flows_through_evaluator_and_detailed_runtime(tmp_path, monkeypatch):
    from eval import run_eval
    from eval.run_eval import DEFAULT_TESTSET, load_testset

    provider_calls = []

    def fake_provider(*, messages, tools):
        provider_calls.append((messages, tools))
        return "fake model response"

    async def fake_run_detailed(question, *, model_request):
        response = model_request(messages=[{"role": "user", "content": question}], tools=[])
        assert response == "fake model response"
        return AgentRunResult(answer="offline answer", actual_outcome="answer", status="completed")

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    adapter = agent_adapter.build_adapter(
        fake_provider, mode="mock", provider_id="fake-provider",
    )
    case = load_testset(DEFAULT_TESTSET)[0]
    output = tmp_path / "injected-adapter-case.jsonl"

    summary = _run_immediate(run_eval.evaluate([case], adapter, output, case_timeout=1))

    assert provider_calls == [([{"role": "user", "content": case["question"]}], [])]
    assert summary["completed"] == 1
    assert json.loads(output.read_text(encoding="utf-8"))["actual_answer"] == "offline answer"
    assert adapter.provenance.execution_mode == "mock"


def test_injected_provider_cannot_register_as_real():
    def fake_provider(**_kwargs):
        return "fake"

    with pytest.raises(ValueError, match="only use mock, unit_test, or synthetic"):
        agent_adapter.build_adapter(fake_provider, mode="real", provider_id="fake-provider")


def test_step_event_mode_comes_from_registered_adapter_and_rejects_conflict(tmp_path):
    from eval import run_eval
    from eval.run_eval import DEFAULT_TESTSET, load_testset

    async def fake_adapter(_case):
        return {"answer": "offline", "actual_outcome": "answer", "status": "completed"}

    registered = agent_adapter.build_adapter(
        lambda **_kwargs: "unused", mode="mock", provider_id="fake-provider",
    )
    from eval.provenance import resolve_execution_mode
    assert resolve_execution_mode(registered, None) == "mock"
    # The event-mode resolver rejects a caller label that conflicts with the
    # adapter's immutable non-real registration before invoking the adapter.
    case = load_testset(DEFAULT_TESTSET)[0]
    coroutine = run_eval.evaluate(
        [case], registered, tmp_path / "cases.jsonl", step_events_path=tmp_path / "events.jsonl",
        execution_mode="real",
    )
    with pytest.raises(ValueError, match="conflicts with registered"):
        _run_immediate(coroutine)

    raw_coroutine = run_eval.evaluate(
        [case], fake_adapter, tmp_path / "raw-cases.jsonl",
        step_events_path=tmp_path / "raw-events.jsonl", execution_mode="real",
    )
    with pytest.raises(ValueError, match="requires a registered adapter provenance"):
        _run_immediate(raw_coroutine)


def test_adapter_preserves_null_and_partial_trace_on_failure(monkeypatch):
    runtime = AgentRunResult(
        answer="partial answer",
        tool_trace=[{"step": 1, "tool_name": "search_policy", "status": "ok"}],
        usage={"calls": 1, "prompt_tokens": None, "completion_tokens": None, "max_prompt": None},
        status="failed",
        error="runtime failed",
    )

    async def fake_run_detailed(_question):
        return runtime

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))

    assert result["status"] == "failed"
    assert result["answer"] == "partial answer"
    assert result["tool_trace"] == runtime.tool_trace
    assert result["error"] == "runtime failed"

    runtime.tool_trace = None
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))
    assert result["tool_trace"] is None


def test_adapter_preserves_completed_unavailable_trace_and_runtime_supplied_labels(monkeypatch):
    runtime = AgentRunResult(
        answer="A structured refusal",
        actual_outcome="refusal",
        actual_refusal_type="ii",
        policy_rule_id="policy.rule.ii",
        decision_source="policy_branch.v1",
        contexts=["[Source: DOC0012] evidence"],
        claims=["A claim from the answer"],
        tool_trace=None,
        usage=None,
        status="completed",
    )

    async def fake_run_detailed(_question):
        return runtime

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))

    assert result["actual_outcome"] == "refusal"
    assert result["actual_refusal_type"] == "ii"
    assert result["policy_rule_id"] == "policy.rule.ii"
    assert result["decision_source"] == "policy_branch.v1"
    assert result["claims"] == runtime.claims
    assert result["tool_trace"] is None
    assert result["usage"] is None


def test_adapter_does_not_call_public_string_api(monkeypatch):
    from trfc.agent import loop as agent_loop

    async def unexpected_run(_question):
        pytest.fail("adapter must call run_detailed exactly once")

    async def fake_run_detailed(_question):
        return AgentRunResult(answer="Error: legitimate answer", status="completed")

    monkeypatch.setattr(agent_loop, "run", unexpected_run)
    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))
    assert result["status"] == "completed"
    assert result["answer"] == "Error: legitimate answer"


def test_adapter_propagates_unexpected_runtime_exception(monkeypatch):
    async def fake_run_detailed(_question):
        raise RuntimeError("runtime exception")

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    with pytest.raises(RuntimeError, match="runtime exception"):
        _run_immediate(agent_adapter.run_case({"question": "case question"}))


@pytest.mark.parametrize("value", [None, {}, 1])
def test_adapter_rejects_non_result(monkeypatch, value):
    async def fake_run_detailed(_question):
        return value

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    with pytest.raises(TypeError, match="AgentRunResult"):
        _run_immediate(agent_adapter.run_case({"question": "case question"}))


def test_adapter_rejects_invalid_status(monkeypatch):
    async def fake_run_detailed(_question):
        return AgentRunResult(answer="answer", status="maybe")

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    with pytest.raises(ValueError, match="invalid execution status"):
        _run_immediate(agent_adapter.run_case({"question": "case question"}))


def test_public_string_api_remains_backward_compatible(monkeypatch):
    from trfc.agent import loop as agent_loop

    async def successful_detailed(_question):
        return AgentRunResult(answer="answer", status="completed")

    async def failed_detailed(_question):
        return AgentRunResult(status="failed", error="MCP unavailable")

    monkeypatch.setattr(agent_loop, "run_detailed", successful_detailed)
    assert _run_immediate(agent_loop.run("question")) == "answer"

    monkeypatch.setattr(agent_loop, "run_detailed", failed_detailed)
    assert _run_immediate(agent_loop.run("question")) == "Error: MCP unavailable"


def test_evaluator_records_runtime_failure_and_continues_to_next_case(tmp_path, monkeypatch):
    from eval import run_eval
    from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset

    calls = []

    async def fake_run_detailed(question):
        calls.append(question)
        if question == "first question":
            return AgentRunResult(
                answer="partial response",
                tool_trace=[{
                    "step": 1, "tool_call_id": "call-1", "tool_name": "search_policy",
                    "arguments": {"query": "policy"}, "result": "partial result",
                    "status": "completed", "error": None,
                }],
                usage={"calls": 1, "prompt_tokens": None,
                       "completion_tokens": None, "max_prompt": None},
                status="failed", error="MCP connection failed",
            )
        return AgentRunResult(answer="answer", status="completed", tool_trace=[])

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    cases = load_testset(DEFAULT_TESTSET)[:2]
    cases[0] = {**cases[0], "question": "first question"}
    cases[1] = {**cases[1], "question": "second question"}
    output = tmp_path / "adapter-results.jsonl"

    summary = _run_immediate(evaluate(cases, agent_adapter.run_case, output, case_timeout=1.0))
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert calls == ["first question", "second question"]
    assert summary["failed"] == 1 and summary["unscorable"] == 1
    assert [row["status"] for row in rows] == ["failed", "unscorable"]
    assert rows[0]["tool_trace"][0]["tool_name"] == "search_policy"
    assert rows[0]["usage"] == {
        "calls": 1, "prompt_tokens": None,
        "completion_tokens": None, "max_prompt": None,
    }
    assert rows[1]["tool_trace"] == []
    assert rows[1]["actual_outcome"] is None


def test_sync_adapter_exception_is_recorded_and_later_case_continues(tmp_path, monkeypatch):
    from eval import run_eval
    from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset

    calls = []

    def sync_adapter(case):
        calls.append(case["id"])
        if len(calls) == 1:
            raise RuntimeError("first case failed")
        return {"answer": "answer", "actual_outcome": None, "status": "unscorable"}

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    cases = load_testset(DEFAULT_TESTSET)[:2]
    output = tmp_path / "sync-exception.jsonl"
    summary = _run_immediate(evaluate(cases, sync_adapter, output, case_timeout=1.0))
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert calls == ["q01", "q02"]
    assert summary["failed"] == 1 and summary["unscorable"] == 1
    assert [row["status"] for row in rows] == ["failed", "unscorable"]
    assert rows[0]["actual_outcome"] is None
    assert rows[0]["error"].startswith("RuntimeError:")


def test_evaluator_distinguishes_missing_metadata_from_not_applicable(tmp_path, monkeypatch):
    from eval import run_eval
    from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset

    answer_case = load_testset(DEFAULT_TESTSET)[0]
    refusal_case = load_testset(DEFAULT_TESTSET)[8]
    cases = [answer_case, {**refusal_case, "id": "missing-outcome"},
             {**refusal_case, "id": "missing-subtype"}]

    async def adapter(case):
        if case["id"] == answer_case["id"]:
            return {
                "answer": "Answer without claim segmentation",
                "actual_outcome": "answer",
                "actual_refusal_type": None,
                "contexts": ["[Source: DOC0007] Retrieved passage."],
                "claims": None,
                "status": "completed",
            }
        if case["id"] == "missing-outcome":
            return {"answer": "Unclassified response", "actual_outcome": None,
                    "actual_refusal_type": None, "contexts": None, "claims": None,
                    "status": "completed"}
        return {"answer": "Classified refusal", "actual_outcome": "refusal",
                "actual_refusal_type": None, "contexts": None, "claims": None,
                "status": "completed"}

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    output = tmp_path / "metadata-states.jsonl"
    summary = _run_immediate(evaluate(cases, adapter, output, case_timeout=1.0))
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert [row["status"] for row in rows] == ["completed", "unscorable", "completed"]
    assert rows[0]["metrics"]["faithfulness"] is None
    assert rows[0]["metrics"]["refusal_subtype_correctness"] is None
    assert rows[1]["actual_outcome"] is None and rows[1]["error"] is None
    assert rows[1]["metrics"]["refusal_correctness"] is None
    assert rows[2]["metrics"]["refusal_subtype_correctness"] is None
    assert summary["unscorable"] == 1
    refusal_type = refusal_case["refusal_type"]
    assert summary["refusal_summary"]["by_type"][refusal_type]["unscorable"] == 1


def test_adapter_rejects_malformed_case_before_runtime_call(monkeypatch):
    def unexpected_run(_question):
        pytest.fail("runtime must not be called for malformed case")

    monkeypatch.setattr(agent_adapter, "run_detailed", unexpected_run)
    with pytest.raises(ValueError, match="non-empty question"):
        _run_immediate(agent_adapter.run_case({}))
