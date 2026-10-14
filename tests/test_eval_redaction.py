import json

import pytest

from eval.redaction import REDACTED, redact_for_log
from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset


@pytest.fixture(autouse=True)
def _isolated_eval_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")


def _run_immediate(coroutine):
    """Drive fake adapter coroutines without creating a Windows event loop."""
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("fake adapter unexpectedly suspended")


def test_redacts_credentials_identifiers_and_reason_fields_recursively():
    source = {
        "arguments": {
            "account_id": "ACC001",
            "reason": "Customer reported unusual transfers",
            "query": "transaction limits",
            "metadata": {
                "Authorization": "Bearer private-value",
                "api_key": "service-secret",
                "safe": "DOC0007",
                "amount": 120000000,
                "location": "Hanoi",
            },
        },
        "flagged_tx_ids": ["TX001"],
    }

    redacted = redact_for_log(source)

    assert redacted["arguments"]["account_id"] == REDACTED
    assert redacted["arguments"]["reason"] == REDACTED
    assert redacted["arguments"]["metadata"]["Authorization"] == REDACTED
    assert redacted["arguments"]["metadata"]["api_key"] == REDACTED
    assert redacted["arguments"]["metadata"]["safe"] == "DOC0007"
    assert redacted["arguments"]["metadata"]["amount"] == REDACTED
    assert redacted["arguments"]["metadata"]["location"] == REDACTED
    assert redacted["arguments"]["query"] == "transaction limits"
    assert redacted["flagged_tx_ids"] == REDACTED
    assert source["arguments"]["account_id"] == "ACC001"  # source is not mutated


def test_redacts_nested_json_tool_result_and_free_text_identifiers():
    result = '[{"account_id":"ACC001","text":"Transfer TX001 reviewed"}]'
    redacted = redact_for_log({"result": result})["result"]
    parsed = json.loads(redacted)
    assert parsed[0]["account_id"] == REDACTED
    assert parsed[0]["text"] == f"Transfer {REDACTED} reviewed"


def test_exception_message_keeps_diagnostic_context_but_scrubs_values():
    message = (
        "RuntimeError: request failed for account ACC001; "
        "Authorization: Bearer bearer-secret; GROQ_API_KEY=gsk_12345678901234567890; "
        "contact user@example.com; phone +1 (212) 555-0134; card 4111111111111111"
    )
    redacted = redact_for_log(message)

    assert redacted.startswith("RuntimeError: request failed for account")
    assert "Authorization=[REDACTED]" in redacted
    assert "GROQ_API_KEY=[REDACTED]" in redacted
    assert redact_for_log("account_id=private-account") == "account_id=[REDACTED]"
    assert REDACTED in redacted
    for sensitive in (
        "ACC001", "bearer-secret", "gsk_12345678901234567890", "user@example.com",
        "+1 (212) 555-0134", "4111111111111111",
    ):
        assert sensitive not in redacted


def test_evaluation_jsonl_redacts_trace_and_exception_fields(tmp_path, monkeypatch):
    from eval import run_eval

    case = load_testset(DEFAULT_TESTSET)[0]
    trace = [{
        "tool_name": "freeze_account_temporarily",
        "arguments": {"account_id": "ACC001", "reason": "Sensitive case details"},
        "result": '{"account_id":"ACC001","message":"frozen"}',
    }]
    original_trace = json.loads(json.dumps(trace))

    async def adapter(_case):
        return {
            "answer": None,
            "actual_outcome": None,
            "tool_trace": trace,
            "status": "failed",
            "error": "RuntimeError: authorization Bearer top-secret for account ACC001",
        }

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    output = tmp_path / "redacted-eval.jsonl"
    _run_immediate(evaluate([case], adapter, output, case_timeout=1.0))

    persisted = json.loads(output.read_text(encoding="utf-8"))
    serialized = output.read_text(encoding="utf-8")
    assert persisted["tool_trace"][0]["arguments"]["account_id"] == REDACTED
    assert persisted["tool_trace"][0]["arguments"]["reason"] == REDACTED
    assert json.loads(persisted["tool_trace"][0]["result"])["account_id"] == REDACTED
    assert "top-secret" not in serialized and "ACC001" not in serialized
    assert persisted["error"].startswith("RuntimeError:")
    assert trace == original_trace  # sanitization only applies to persisted copy


def test_evaluation_jsonl_redacts_thrown_adapter_exception(tmp_path, monkeypatch):
    from eval import run_eval

    case = load_testset(DEFAULT_TESTSET)[0]

    async def adapter(_case):
        raise ValueError("password=never-store; account_id=private-account")

    async def immediate_wait_for(awaitable, timeout):
        assert timeout > 0
        return await awaitable

    monkeypatch.setattr(run_eval.asyncio, "wait_for", immediate_wait_for)
    output = tmp_path / "exception.jsonl"
    _run_immediate(evaluate([case], adapter, output, case_timeout=1.0))

    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted["error"].startswith("ValueError:")
    assert "password=[REDACTED]" in persisted["error"]
    assert "account_id=[REDACTED]" in persisted["error"]
    assert "never-store" not in persisted["error"]
    assert "private-account" not in persisted["error"]


def test_preserves_normal_non_sensitive_values():
    data = {
        "tool_name": "search_policy",
        "arguments": {"query": "transaction limits", "k": 5},
        "result": [{"doc_id": "DOC0007", "text": "Daily transfer limit"}],
        "error": "TimeoutError: policy search exceeded the configured timeout",
    }
    assert redact_for_log(data) == data
