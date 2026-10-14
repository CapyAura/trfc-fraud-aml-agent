from dataclasses import dataclass
import json

import pytest

from eval import agent_adapter


@pytest.fixture(autouse=True)
def _isolated_eval_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")


@dataclass
class FakeRuntimeResult:
    answer: str | None = None
    actual_outcome: str | None = None
    actual_refusal_type: str | None = None
    contexts: list[str] | None = None
    claims: list[str] | None = None
    tool_trace: list[dict] | None = None
    usage: dict | None = None
    status: str = "completed"
    error: str | None = None


def _run_immediate(coroutine):
    """Run fake-only coroutines that must complete without event-loop I/O."""
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("Fake coroutine unexpectedly suspended")


def test_adapter_import_and_mapping_preserve_unavailable_fields(monkeypatch):
    from eval.run_eval import _load_adapter

    assert _load_adapter("eval.agent_adapter:run_case") is agent_adapter.run_case
    calls = []

    async def fake_run_detailed(question):
        calls.append(question)
        return FakeRuntimeResult(
            answer="Observed answer",
            tool_trace=[],
            usage={
                "calls": 1, "prompt_tokens": None,
                "completion_tokens": None, "max_prompt": None,
            },
        )

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))

    assert calls == ["case question"]
    assert result["answer"] == "Observed answer"
    assert result["actual_outcome"] is None
    assert result["actual_refusal_type"] is None
    assert result["contexts"] is None
    assert result["claims"] is None
    assert result["tool_trace"] == []
    assert result["usage"]["prompt_tokens"] is None
    assert result["usage"]["completion_tokens"] is None


def test_adapter_passes_through_only_runtime_supplied_contexts_and_labels(monkeypatch):
    runtime = FakeRuntimeResult(
        answer="Observed response",
        actual_outcome=None,
        actual_refusal_type=None,
        contexts=["[Source: DOC0012] Retrieved passage."],
        claims=None,
        status="completed",
    )

    async def fake_run_detailed(_question):
        return runtime

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))
    assert result["contexts"] == runtime.contexts
    assert result["actual_outcome"] is None
    assert result["actual_refusal_type"] is None
    assert result["claims"] is None


def test_adapter_keeps_completed_but_unavailable_trace_as_null(monkeypatch):
    runtime = FakeRuntimeResult(
        answer="Classified answer",
        actual_outcome="answer",
        tool_trace=None,
        status="completed",
    )

    async def fake_run_detailed(_question):
        return runtime

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))
    assert result["status"] == "completed"
    assert result["tool_trace"] is None


@pytest.mark.parametrize("status", ["failed", None])
def test_adapter_preserves_runtime_unavailable_trace(monkeypatch, status):
    async def fake_run_detailed(_question):
        return FakeRuntimeResult(
            tool_trace=None, status=status, error="MCP discovery was not established",
        )

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))
    assert result["tool_trace"] is None
    assert result["status"] == status
    assert result["error"] == "MCP discovery was not established"


def test_adapter_keeps_partial_trace_when_runtime_fails(monkeypatch):
    partial_trace = [{"step": 1, "tool_name": "lookup", "status": "completed"}]

    async def fake_run_detailed(_question):
        return FakeRuntimeResult(
            tool_trace=partial_trace, status="failed", error="later model failure",
        )

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    result = _run_immediate(agent_adapter.run_case({"question": "case question"}))
    assert result["tool_trace"] == partial_trace


def test_legacy_run_returns_string_for_success_and_failure(monkeypatch):
    from trfc.agent import loop as agent_loop

    async def successful_run(_question):
        return FakeRuntimeResult(answer="final answer", status="completed")

    monkeypatch.setattr(agent_loop, "run_detailed", successful_run)
    assert _run_immediate(agent_loop.run("question")) == "final answer"

    async def failed_run(_question):
        return FakeRuntimeResult(status="failed", error="MCP unavailable")

    monkeypatch.setattr(agent_loop, "run_detailed", failed_run)
    assert _run_immediate(agent_loop.run("question")) == "Error: MCP unavailable"


def test_evaluator_records_runtime_failure_and_continues_to_next_case(tmp_path, monkeypatch):
    from eval import run_eval
    from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset

    calls = []

    async def fake_run_detailed(question):
        calls.append(question)
        if question == "first question":
            return FakeRuntimeResult(
                status="failed", error="MCP connection failed: OSError", tool_trace=None,
            )
        return FakeRuntimeResult(answer="answer", status="completed", tool_trace=[])

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(agent_adapter, "run_detailed", fake_run_detailed)
    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    cases = load_testset(DEFAULT_TESTSET)[:2]
    cases[0] = {**cases[0], "question": "first question"}
    cases[1] = {**cases[1], "question": "second question"}
    output = tmp_path / "adapter-results.jsonl"

    summary = _run_immediate(
        evaluate(cases, agent_adapter.run_case, output, case_timeout=1.0)
    )
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert calls == ["first question", "second question"]
    assert summary["failed"] == 1
    assert summary["unscorable"] == 1
    assert [row["status"] for row in rows] == ["failed", "unscorable"]
    assert rows[0]["tool_trace"] is None
    assert rows[1]["tool_trace"] == []
    assert rows[1]["actual_outcome"] is None


def test_evaluator_distinguishes_missing_metadata_from_not_applicable(tmp_path, monkeypatch):
    from eval import run_eval
    from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset

    answer_case = load_testset(DEFAULT_TESTSET)[0]
    refusal_case = load_testset(DEFAULT_TESTSET)[8]
    cases = [
        answer_case,
        {**refusal_case, "id": "missing-outcome"},
        {**refusal_case, "id": "missing-subtype"},
    ]

    async def adapter(case):
        if case["id"] == answer_case["id"]:
            return {
                "answer": "Answer without claim segmentation",
                "actual_outcome": "answer",
                "actual_refusal_type": None,  # Refusal subtype is not applicable to an answer.
                "contexts": ["[Source: DOC0007] Retrieved passage."],
                "claims": None,
                "status": "completed",
            }
        if case["id"] == "missing-outcome":
            return {
                "answer": "An unclassified final response",
                "actual_outcome": None,
                "actual_refusal_type": None,
                "contexts": None,
                "claims": None,
                "status": "completed",
            }
        return {
            "answer": "Explicitly classified refusal",
            "actual_outcome": "refusal",
            "actual_refusal_type": None,
            "contexts": None,
            "claims": None,
            "status": "completed",
        }

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    output = tmp_path / "metadata-states.jsonl"
    summary = _run_immediate(evaluate(cases, adapter, output, case_timeout=1.0))
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]

    assert [row["status"] for row in rows] == ["completed", "unscorable", "completed"]
    assert rows[0]["metrics"]["faithfulness"] is None  # claims unavailable
    assert rows[0]["metrics"]["refusal_subtype_correctness"] is None  # N/A
    assert rows[1]["actual_outcome"] is None and rows[1]["error"] is None
    assert rows[1]["metrics"]["refusal_correctness"] is None
    assert rows[2]["metrics"]["refusal_subtype_correctness"] is None  # missing subtype
    assert summary["unscorable"] == 1
    refusal_type = refusal_case["refusal_type"]
    assert summary["refusal_summary"]["by_type"][refusal_type]["unscorable"] == 1


def test_adapter_rejects_missing_question_without_runtime_call(monkeypatch):
    def should_not_run(_question):
        pytest.fail("runtime should not be called for malformed case")

    monkeypatch.setattr(agent_adapter, "run_detailed", should_not_run)
    with pytest.raises(ValueError, match="non-empty question"):
        _run_immediate(agent_adapter.run_case({}))
