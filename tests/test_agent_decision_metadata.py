"""Offline tests for runtime decision metadata (C4). No Groq/API, MCP or staging.

Every model, session and decision provider here is a local fake.
"""

import json
from types import SimpleNamespace as NS

import pytest

import trfc.agent.loop as agent_loop
from trfc.agent.llm import Usage
from trfc.agent.loop import resolve_decision, run_with_session, write_verification_status

DECISION_FIELDS = (
    "actual_outcome", "actual_refusal_type", "policy_rule_id", "decision_source",
)


def _inline(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as finished:
        return finished.value
    raise AssertionError("fake test coroutine unexpectedly suspended")


def _tool(name):
    return NS(name=name, description="fake", input_schema={"type": "object", "properties": {}})


def _call(call_id, name, arguments):
    return NS(id=call_id, type="function", function=NS(name=name, arguments=json.dumps(arguments)))


def _tool_result(payload):
    return NS(content=[NS(text=json.dumps(payload))], isError=False)


class FakeSession:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def list_tools(self):
        return NS(tools=[_tool(n) for n in (
            "search_policy", "get_transactions", "get_account_risk_status",
            "freeze_account_temporarily", "flag_suspicious_tx")])

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return self.results[name]


def _run(session, script, provider=None, final="Câu trả lời."):
    """Replay `script` (list of (id, tool, args)) one call per model turn, then answer."""
    turns = [NS(content=None, tool_calls=[_call(*step)]) for step in script]
    turns.append(NS(content=final, tool_calls=None))

    def model(messages, *, tools):
        return turns.pop(0), Usage(calls=1, prompt_tokens=1, completion_tokens=1, max_prompt=1)

    return _inline(run_with_session(
        "q", session, model_request=model, system_prompt="s", decision_provider=provider))


def _trace(*events):
    return list(events)


def _event(tool, arguments, payload, status="completed"):
    return {"step": 1, "tool_call_id": "c", "tool_name": tool, "arguments": arguments,
            "result": json.dumps(payload), "status": status, "error": None}


CONTEXTS = [
    "[Source: DOC0007] ### Điều 12. Trường hợp không đủ dữ liệu để kết luận ...",
    "[Source: DOC0009] ### Điều 5. Phương thức ngoài danh mục ...",
]


# ---------------------------------------------------------------- no provider
def test_without_provider_all_decision_fields_stay_null_even_if_text_says_refusal():
    result = _run(FakeSession({}), [], final="Tôi từ chối: không có trong tài liệu.")
    assert result.status == "completed"
    for name in DECISION_FIELDS + ("policy_decision_status", "policy_reason_code"):
        assert getattr(result, name) is None, name
    assert result.claims is None


# ---------------------------------------------------------------- answer
def test_answer_decision_is_decided_and_has_no_refusal_type():
    fields = resolve_decision(
        {"outcome": "answer", "decision_source": "test.provider"}, contexts=None, tool_trace=None)
    assert fields["actual_outcome"] == "answer"
    assert fields["actual_refusal_type"] is None
    assert fields["policy_rule_id"] is None
    assert fields["decision_source"] == "test.provider"
    assert fields["policy_decision_status"] == "decided"
    assert fields["policy_reason_code"] is None


def test_refusal_type_on_answer_is_contradictory_and_clears_everything():
    fields = resolve_decision(
        {"outcome": "answer", "refusal_type": "i", "decision_source": "test.provider"},
        contexts=None, tool_trace=None)
    assert fields["policy_decision_status"] == "needs_information"
    assert all(fields[name] is None for name in DECISION_FIELDS)


# ---------------------------------------------------------------- refusal
@pytest.mark.parametrize("kind", ["i", "ii"])
def test_refusal_with_explicit_type_is_passed_through(kind):
    fields = resolve_decision(
        {"outcome": "refusal", "refusal_type": kind, "decision_source": "test.provider"},
        contexts=None, tool_trace=None)
    assert fields["actual_outcome"] == "refusal"
    assert fields["actual_refusal_type"] == kind
    assert fields["policy_decision_status"] == "decided"


@pytest.mark.parametrize("bad_type", [None, "", "iii", "I", 1, ["i"]])
def test_refusal_with_unknown_type_keeps_outcome_but_type_stays_null(bad_type):
    raw = {"outcome": "refusal", "decision_source": "test.provider"}
    if bad_type is not None:
        raw["refusal_type"] = bad_type
    fields = resolve_decision(raw, contexts=None, tool_trace=None)
    assert fields["actual_outcome"] == "refusal"
    assert fields["actual_refusal_type"] is None
    assert fields["policy_decision_status"] == "decided"
    assert fields["policy_reason_code"] == "refusal_type_unavailable"


# ---------------------------------------------------------------- policy rule
def test_policy_rule_kept_only_when_that_article_was_retrieved():
    fields = resolve_decision(
        {"outcome": "refusal", "refusal_type": "ii", "decision_source": "s",
         "policy_rule_id": "DOC0007_ART12"}, contexts=CONTEXTS, tool_trace=None)
    assert fields["policy_rule_id"] == "DOC0007_ART12"
    assert fields["policy_reason_code"] is None


@pytest.mark.parametrize("rule", [
    "DOC0007_ART05",   # doc retrieved, article text not retrieved
    "DOC0001_ART01",   # doc never retrieved
    "RULE-1", "DOC0007", "doc0007_art12", "DOC0007_ART12; DROP", "", 12, ["DOC0007_ART12"],
])
def test_invalid_or_unevidenced_policy_rule_is_dropped_not_defaulted(rule):
    fields = resolve_decision(
        {"outcome": "refusal", "refusal_type": "ii", "decision_source": "s",
         "policy_rule_id": rule}, contexts=CONTEXTS, tool_trace=None)
    assert fields["policy_rule_id"] is None
    assert fields["actual_outcome"] == "refusal" and fields["actual_refusal_type"] == "ii"
    assert fields["policy_reason_code"] == "policy_rule_id_unverified"


def test_policy_rule_is_dropped_when_no_contexts_were_captured():
    fields = resolve_decision(
        {"outcome": "answer", "decision_source": "s", "policy_rule_id": "DOC0007_ART12"},
        contexts=None, tool_trace=None)
    assert fields["policy_rule_id"] is None


# ---------------------------------------------------------------- malformed
@pytest.mark.parametrize("raw", [
    None, "answer", ["answer"], {},
    {"outcome": "ANSWER", "decision_source": "s"},
    {"outcome": "maybe", "decision_source": "s"},
    {"outcome": "answer"},                                   # no decision_source
    {"outcome": "answer", "decision_source": ""},
    {"outcome": "answer", "decision_source": "bad source!"},
    {"outcome": "answer", "decision_source": "s", "claims": ["x"]},   # unsupported key
])
def test_malformed_decisions_fail_closed(raw):
    fields = resolve_decision(raw, contexts=CONTEXTS, tool_trace=None)
    assert fields["policy_decision_status"] == "needs_information"
    assert fields["policy_reason_code"]
    assert all(fields[name] is None for name in DECISION_FIELDS)


# ---------------------------------------------------------------- provider wiring
def test_provider_decision_reaches_result_and_sees_captured_contexts():
    seen = {}

    def provider(snapshot):
        seen.update(snapshot)
        return {"outcome": "refusal", "refusal_type": "ii", "decision_source": "test.provider",
                "policy_rule_id": "DOC0007_ART12"}

    chunks = [{"doc_id": "DOC0007", "text": "### Điều 12. Không đủ dữ liệu"}]
    session = FakeSession({"search_policy": _tool_result(chunks)})
    result = _run(session, [("c1", "search_policy", {"query": "x"})], provider)

    assert result.status == "completed"
    assert (result.actual_outcome, result.actual_refusal_type) == ("refusal", "ii")
    assert result.policy_rule_id == "DOC0007_ART12"
    assert result.decision_source == "test.provider"
    assert result.policy_decision_status == "decided"
    assert seen["answer"] == "Câu trả lời." and seen["contexts"] == result.contexts
    assert result.claims is None
    assert session.calls == [("search_policy", {"query": "x"})]   # no extra tool calls


def test_async_provider_is_supported():
    async def provider(_snapshot):
        return {"outcome": "answer", "decision_source": "test.async"}

    result = _run(FakeSession({}), [], provider)
    assert result.actual_outcome == "answer" and result.policy_decision_status == "decided"


def test_provider_exception_is_fail_closed_and_not_leaked():
    def provider(_snapshot):
        raise RuntimeError("customer ACC123456 secret body")

    result = _run(FakeSession({}), [], provider)
    assert result.status == "completed"
    assert result.policy_decision_status == "needs_information"
    assert result.policy_reason_code == "decision_provider_failed"
    assert all(getattr(result, name) is None for name in DECISION_FIELDS)
    assert "ACC123456" not in json.dumps(result.__dict__, default=str)


def test_provider_is_not_called_when_the_run_fails():
    calls = []

    def model(messages, *, tools):
        raise RuntimeError("boom")

    result = _inline(run_with_session(
        "q", FakeSession({}), model_request=model, system_prompt="s",
        decision_provider=lambda s: calls.append(s)))
    assert result.status == "failed" and calls == []
    assert result.actual_outcome is None and result.policy_decision_status is None


def test_provider_cannot_mutate_the_recorded_trace():
    def provider(snapshot):
        snapshot["tool_trace"].append({"tool_name": "forged"})
        return {"outcome": "answer", "decision_source": "s"}

    session = FakeSession({"get_transactions": _tool_result([])})
    result = _run(session, [("c1", "get_transactions", {})], provider)
    assert [event["tool_name"] for event in result.tool_trace] == ["get_transactions"]


# ---------------------------------------------------------------- write-verify
FROZEN = {"account_id": "ACC001", "frozen": True, "frozen_at": "2026-10-01T10:00:00+00:00",
          "checked_at": "2026-10-01T10:00:05+00:00", "flagged_tx_ids": []}
FREEZE = _event("freeze_account_temporarily", {"account_id": "ACC001", "reason": "r"}, {"ok": True})
FLAG = _event("flag_suspicious_tx", {"tx_id": "TX9", "reason": "r"}, {"ok": True, "tx_id": "TX9"})


def test_no_write_means_not_applicable():
    assert write_verification_status(None) == "not_applicable"
    assert write_verification_status([_event("get_transactions", {}, [])]) == "not_applicable"


def test_freeze_is_verified_only_by_a_later_independent_read():
    read = _event("get_account_risk_status", {"account_id": "ACC001"}, FROZEN)
    assert write_verification_status([FREEZE, read]) == "verified"
    assert write_verification_status([read, FREEZE]) == "unverified"      # read came first
    assert write_verification_status([FREEZE]) == "unverified"


@pytest.mark.parametrize("change", [
    {"frozen": False},
    {"account_id": "ACC999"},
    {"checked_at": "2026-10-01T10:00:00+00:00"},   # not newer than frozen_at
    {"checked_at": "2026-10-01T09:00:00+00:00"},
    {"frozen_at": None},
    {"checked_at": "not-a-time"},
    {"checked_at": "2026-10-01T10:00:05"},          # naive timestamp rejected
])
def test_freeze_verification_rejects_stale_or_mismatched_reads(change):
    read = _event("get_account_risk_status", {"account_id": "ACC001"}, {**FROZEN, **change})
    assert write_verification_status([FREEZE, read]) == "unverified"


def test_failed_verify_read_does_not_count():
    read = _event("get_account_risk_status", {"account_id": "ACC001"}, FROZEN, status="error")
    assert write_verification_status([FREEZE, read]) == "unverified"


def test_flag_is_verified_by_flagged_tx_ids_on_a_later_read():
    ok = _event("get_account_risk_status", {"account_id": "ACC001"},
                {**FROZEN, "frozen": False, "flagged_tx_ids": ["TX9"]})
    missing = _event("get_account_risk_status", {"account_id": "ACC001"},
                     {**FROZEN, "frozen": False, "flagged_tx_ids": ["TX1"]})
    assert write_verification_status([FLAG, ok]) == "verified"
    assert write_verification_status([FLAG, missing]) == "unverified"


def test_failed_write_is_not_treated_as_a_write():
    failed = {**FREEZE, "status": "error"}
    assert write_verification_status([failed]) == "not_applicable"


def test_every_write_needs_its_own_verification():
    read = _event("get_account_risk_status", {"account_id": "ACC001"}, FROZEN)
    assert write_verification_status([FREEZE, read, FLAG]) == "unverified"


def test_unverified_write_blocks_the_decision_without_adding_tool_calls():
    provider = lambda _s: {"outcome": "answer", "decision_source": "test.provider"}
    results = {"freeze_account_temporarily": _tool_result({"ok": True, "message": "frozen"})}
    session = FakeSession(results)
    result = _run(session, [("c1", "freeze_account_temporarily",
                             {"account_id": "ACC001", "reason": "r"})], provider)
    assert result.status == "completed"
    assert result.policy_decision_status == "needs_information"
    assert result.policy_reason_code == "write_verification_missing"
    assert all(getattr(result, name) is None for name in DECISION_FIELDS)
    assert [name for name, _ in session.calls] == ["freeze_account_temporarily"]


def test_verified_freeze_end_to_end_is_decided():
    provider = lambda _s: {"outcome": "answer", "decision_source": "test.provider"}
    session = FakeSession({
        "freeze_account_temporarily": _tool_result({"ok": True, "message": "frozen"}),
        "get_account_risk_status": _tool_result(FROZEN),
    })
    result = _run(session, [
        ("c1", "freeze_account_temporarily", {"account_id": "ACC001", "reason": "r"}),
        ("c2", "get_account_risk_status", {"account_id": "ACC001"}),
    ], provider)
    assert result.policy_decision_status == "decided"
    assert result.actual_outcome == "answer"


# ---------------------------------------------------------------- CLI regression
def test_main_prints_structured_json_and_exit_code(monkeypatch, capsys):
    """main() used to be defined inside itself, so it silently did nothing."""
    async def fake_run_detailed(question):
        return agent_loop.AgentRunResult(
            answer="ok", status="completed", actual_outcome="answer",
            decision_source="test.provider", policy_decision_status="decided")

    monkeypatch.setattr(agent_loop, "run_detailed", fake_run_detailed)
    monkeypatch.setattr(agent_loop.sys, "argv", ["loop", "câu", "hỏi"])
    assert agent_loop.main() == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed" and payload["actual_outcome"] == "answer"
    assert payload["decision_source"] == "test.provider"
    assert "policy_rule_id" in payload and "policy_decision_status" in payload


def test_main_without_question_returns_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(agent_loop.sys, "argv", ["loop"])
    assert agent_loop.main() == 2
    assert "Usage" in capsys.readouterr().err


# ---------------------------------------------------------------- submit_decision tool
def _run_with_tool(session, script, final="Câu trả lời.", **kwargs):
    turns = [NS(content=None, tool_calls=[_call(*step)]) for step in script]
    turns.append(NS(content=final, tool_calls=None))
    seen = {"tools": None, "messages": None}

    def model(messages, *, tools):
        seen["tools"], seen["messages"] = tools, [dict(m) for m in messages]
        return turns.pop(0), Usage(calls=1, prompt_tokens=1, completion_tokens=1, max_prompt=1)

    result = _inline(run_with_session(
        "q", session, model_request=model, enable_decision_tool=True, **kwargs))
    return result, seen


def test_decision_tool_is_offered_with_prompt_only_when_enabled():
    _, seen = _run_with_tool(FakeSession({}), [])
    assert "submit_decision" in [t["function"]["name"] for t in seen["tools"]]
    assert "submit_decision" in seen["messages"][0]["content"]

    def model(messages, *, tools):
        seen["off"] = ([t["function"]["name"] for t in tools], messages[0]["content"])
        return NS(content="x", tool_calls=None), Usage(calls=1)

    _inline(run_with_session("q", FakeSession({}), model_request=model))
    assert "submit_decision" not in seen["off"][0]
    assert "submit_decision" not in seen["off"][1]


def test_model_declared_refusal_is_recorded_with_honest_unauthenticated_source():
    chunks = [{"doc_id": "DOC0007", "text": "### Điều 12. Không đủ dữ liệu"}]
    session = FakeSession({"search_policy": _tool_result(chunks)})
    result, _ = _run_with_tool(session, [
        ("c1", "search_policy", {"query": "x"}),
        ("c2", "submit_decision", {"outcome": "refusal", "refusal_type": "ii",
                                   "policy_rule_id": "DOC0007_ART12"}),
    ])
    assert (result.actual_outcome, result.actual_refusal_type) == ("refusal", "ii")
    assert result.policy_rule_id == "DOC0007_ART12"
    assert result.decision_source == "llm.structured_tool_call"
    assert result.policy_decision_status == "decided"
    # internal tool never reaches the MCP session nor the trace
    assert [name for name, _ in session.calls] == ["search_policy"]
    assert [e["tool_name"] for e in result.tool_trace] == ["search_policy"]


def test_model_declared_answer_has_no_refusal_type():
    result, _ = _run_with_tool(FakeSession({}), [("c1", "submit_decision", {"outcome": "answer"})])
    assert result.actual_outcome == "answer" and result.actual_refusal_type is None
    assert result.policy_rule_id is None


def test_refusal_without_type_leaves_type_null():
    result, _ = _run_with_tool(FakeSession({}), [("c1", "submit_decision", {"outcome": "refusal"})])
    assert result.actual_outcome == "refusal" and result.actual_refusal_type is None
    assert result.policy_reason_code == "refusal_type_unavailable"


def test_no_declaration_means_no_metadata_even_if_text_says_refusal():
    result, _ = _run_with_tool(FakeSession({}), [], final="Tôi từ chối vì không có trong tài liệu.")
    assert result.actual_outcome is None and result.policy_decision_status is None


def test_invalid_declaration_is_rejected_to_the_model_and_not_recorded():
    bad = [
        ("c1", "submit_decision", {"outcome": "maybe"}),
        ("c2", "submit_decision", {"outcome": "answer", "refusal_type": "i"}),
        ("c3", "submit_decision", {"outcome": "refusal", "refusal_type": "iii"}),
        ("c4", "submit_decision", {"outcome": "answer", "decision_source": "forged"}),
    ]
    result, seen = _run_with_tool(FakeSession({}), bad)
    assert result.actual_outcome is None and result.decision_source is None
    tool_msgs = [m["content"] for m in seen["messages"] if m.get("role") == "tool"]
    assert len(tool_msgs) == 4 and all(m.startswith("Tool error:") for m in tool_msgs)


def test_model_cannot_supply_its_own_decision_source():
    result, _ = _run_with_tool(FakeSession({}), [
        ("c1", "submit_decision", {"outcome": "answer", "decision_source": "upstream.core_journal"})])
    assert result.decision_source is None


def test_hallucinated_rule_is_dropped_but_decision_kept():
    result, _ = _run_with_tool(FakeSession({}), [
        ("c1", "submit_decision", {"outcome": "refusal", "refusal_type": "i",
                                   "policy_rule_id": "DOC0009_ART05"})])
    assert result.actual_refusal_type == "i" and result.policy_rule_id is None
    assert result.policy_reason_code == "policy_rule_id_unverified"


def test_last_valid_declaration_wins():
    result, _ = _run_with_tool(FakeSession({}), [
        ("c1", "submit_decision", {"outcome": "answer"}),
        ("c2", "submit_decision", {"outcome": "refusal", "refusal_type": "i"}),
    ])
    assert (result.actual_outcome, result.actual_refusal_type) == ("refusal", "i")


def test_explicit_provider_takes_precedence_over_model_declaration():
    result, _ = _run_with_tool(
        FakeSession({}), [("c1", "submit_decision", {"outcome": "answer"})],
        decision_provider=lambda _s: {"outcome": "refusal", "refusal_type": "ii",
                                      "decision_source": "test.provider"})
    assert result.actual_outcome == "refusal" and result.decision_source == "test.provider"


def test_unverified_freeze_blocks_model_declared_decision():
    session = FakeSession({"freeze_account_temporarily": _tool_result({"ok": True})})
    result, _ = _run_with_tool(session, [
        ("c1", "freeze_account_temporarily", {"account_id": "ACC001", "reason": "r"}),
        ("c2", "submit_decision", {"outcome": "answer"}),
    ])
    assert result.policy_reason_code == "write_verification_missing"
    assert result.actual_outcome is None


def test_mcp_tool_may_not_shadow_the_reserved_name():
    class Shadow(FakeSession):
        async def list_tools(self):
            return NS(tools=[_tool("submit_decision")])

    result, _ = _run_with_tool(Shadow({}), [])
    assert result.status == "failed" and "reserved" in result.error
