"""Offline tests for the optional LLM judge.

Every test uses a fake model callable; none contacts a provider. The behaviours
covered are the ones that decide whether a reported number is trustworthy:
the judge must refuse redacted input, must never overwrite deterministic
metrics, must degrade to unscorable on malformed output, and must not be able to
change a case's decision.
"""

from __future__ import annotations

import json

import pytest

from eval.llm_judge import (
    agreement,
    build_judge_messages,
    evaluate_judge,
    judge_eligibility,
    load_judge_prompt,
    parse_judge_response,
)
from eval.run_judge import judge_run


def row(**overrides):
    base = {
        "question_id": "q01",
        "category": "retrieval",
        "expected_outcome": "answer",
        "expected_refusal_type": None,
        "actual_answer": "Hạn mức mỗi ngày là 500.000.000 VND.",
        "contexts": ["[Source: DOC0007] Hạn mức mỗi ngày là 500.000.000 VND."],
        "actual_outcome": "answer",
        "actual_refusal_type": None,
        "metrics": {"faithfulness": None},
        "status": "completed",
    }
    base.update(overrides)
    return base


GOOD_PAYLOAD = {
    "claims": [
        {"text": "Hạn mức mỗi ngày là 500.000.000 VND",
         "label": "supported", "evidence_doc_id": "DOC0007"},
    ],
    "faithfulness": 1.0,
    "actual_outcome": "answer",
    "actual_refusal_type": None,
    "outcome_correct": True,
    "refusal_type_correct": None,
    "note": "",
}


class Message:
    def __init__(self, content):
        self.content = content


def fake_model(content):
    def request(messages):
        request.seen = messages
        return Message(content), None
    request.seen = None
    return request


def test_judge_prompt_is_loaded_from_the_prompt_directory():
    template = load_judge_prompt()
    assert "{question}" in template and "{contexts}" in template and "{answer}" in template


def test_messages_fill_every_placeholder():
    messages = build_judge_messages(row(), load_judge_prompt())
    content = messages[0]["content"]
    assert "Hạn mức mỗi ngày là 500.000.000 VND." in content
    assert "[Source: DOC0007]" in content
    assert "{question}" not in content and "{answer}" not in content


def test_redacted_input_is_refused_instead_of_judged():
    redacted = row(actual_answer="Hạn mức là [REDACTED] VND.")
    assert "actual_answer contains [REDACTED]" in judge_eligibility(redacted)
    result = evaluate_judge(redacted, fake_model(json.dumps(GOOD_PAYLOAD)))
    assert result.faithfulness is None
    assert "REDACTED" in result.error

    redacted_context = row(contexts=["[Source: DOC0007] Hạn mức [REDACTED] VND."])
    assert "contexts contains [REDACTED]" in judge_eligibility(redacted_context)


def test_non_completed_or_empty_cases_are_skipped():
    assert "not 'completed'" in judge_eligibility(row(status="failed"))
    assert "no answer" in judge_eligibility(row(actual_answer="   "))
    assert "no retrieved context" in judge_eligibility(row(contexts=[]))
    assert judge_eligibility(row()) is None


def test_parses_a_well_formed_response():
    result = parse_judge_response(json.dumps(GOOD_PAYLOAD), expected_outcome="answer",
                                  expected_refusal_type=None)
    assert result.error is None
    assert result.faithfulness == 1.0
    assert result.outcome == "answer"
    assert result.outcome_correct is True
    assert result.refusal_type_correct is None
    assert result.claims[0]["evidence_doc_id"] == "DOC0007"


def test_tolerates_code_fence_and_surrounding_prose():
    fenced = "```json\n" + json.dumps(GOOD_PAYLOAD) + "\n```"
    assert parse_judge_response(fenced, expected_outcome="answer",
                                expected_refusal_type=None).error is None
    chatty = "Đây là kết quả: " + json.dumps(GOOD_PAYLOAD)
    assert parse_judge_response(chatty, expected_outcome="answer",
                                expected_refusal_type=None).error is None


@pytest.mark.parametrize("payload,expected_error", [
    ("not json at all", "not valid JSON"),
    ("[]", "not valid JSON"),
    (json.dumps({"claims": "nope"}), "claims must be a list"),
    (json.dumps({"claims": [{"label": "supported"}]}), "missing text"),
    (json.dumps({"claims": [{"text": "x", "label": "maybe"}]}), "label must be"),
    (json.dumps({"claims": [{"text": "x", "label": "supported",
                             "evidence_doc_id": "DOC1"}]}), "evidence_doc_id"),
    (json.dumps({"claims": [], "faithfulness": 1.5, "actual_outcome": "answer"}),
     "between 0 and 1"),
    (json.dumps({"claims": [], "actual_outcome": "maybe"}), "actual_outcome"),
    (json.dumps({"claims": [], "actual_outcome": "answer", "actual_refusal_type": "iii"}),
     "refusal_type"),
])
def test_malformed_judge_output_becomes_an_error_not_a_score(payload, expected_error):
    result = parse_judge_response(payload, expected_outcome="answer", expected_refusal_type=None)
    assert result.error is not None
    assert expected_error in result.error
    assert result.faithfulness is None
    assert result.outcome is None


def test_missing_aggregate_is_recomputed_from_claim_labels():
    payload = {
        "claims": [
            {"text": "a", "label": "supported"},
            {"text": "b", "label": "unsupported"},
        ],
        "actual_outcome": "answer",
    }
    result = parse_judge_response(json.dumps(payload), expected_outcome="answer",
                                  expected_refusal_type=None)
    assert result.faithfulness == 0.5


def test_answer_outcome_cannot_carry_a_refusal_subtype():
    payload = {**GOOD_PAYLOAD, "actual_outcome": "answer", "actual_refusal_type": "i"}
    result = parse_judge_response(json.dumps(payload), expected_outcome="answer",
                                  expected_refusal_type=None)
    assert result.refusal_type is None
    assert result.refusal_type_correct is None


def test_refusal_subtype_comparison_only_when_both_sides_have_one():
    payload = {**GOOD_PAYLOAD, "actual_outcome": "refusal", "actual_refusal_type": "ii",
               "outcome_correct": True, "refusal_type_correct": True}
    ok = parse_judge_response(json.dumps(payload), expected_outcome="refusal",
                              expected_refusal_type="ii")
    assert ok.outcome_correct is True and ok.refusal_type_correct is True

    wrong = parse_judge_response(json.dumps(payload), expected_outcome="refusal",
                                 expected_refusal_type="i")
    assert wrong.refusal_type_correct is False

    no_expected = parse_judge_response(json.dumps(payload), expected_outcome="refusal",
                                       expected_refusal_type=None)
    assert no_expected.refusal_type_correct is None


def test_provider_failure_is_captured_not_raised():
    def boom(_messages):
        raise RuntimeError("provider down")

    result = evaluate_judge(row(), boom)
    assert result.faithfulness is None
    assert "judge request failed" in result.error


def test_judge_run_writes_a_separate_file_and_keeps_metrics_intact(tmp_path):
    source = tmp_path / "evaluation.jsonl"
    source.write_text(json.dumps(row()) + "\n", encoding="utf-8")
    before = source.read_text(encoding="utf-8")

    output = tmp_path / "judge.jsonl"
    summary = asyncio_run(judge_run(source, output, request_model=fake_model(json.dumps(GOOD_PAYLOAD))))

    assert summary["judged"] == 1
    assert source.read_text(encoding="utf-8") == before
    record = json.loads(output.read_text(encoding="utf-8").strip())
    assert record["judge_faithfulness"] == 1.0
    assert record["deterministic_faithfulness"] is None
    assert "metrics" not in record


def test_judge_run_records_redaction_skips_without_calling_the_model(tmp_path):
    source = tmp_path / "evaluation.jsonl"
    source.write_text(json.dumps(row(actual_answer="[REDACTED] VND")) + "\n", encoding="utf-8")

    def must_not_run(_messages):
        raise AssertionError("the judge must not be called on redacted rows")

    summary = asyncio_run(judge_run(source, tmp_path / "judge.jsonl", request_model=must_not_run))
    assert summary["skipped"] == 1
    assert summary["judged"] == 0
    record = json.loads((tmp_path / "judge.jsonl").read_text(encoding="utf-8").strip())
    assert record["judge_faithfulness"] is None
    assert "REDACTED" in record["judge_error"]


def test_agreement_labels():
    assert agreement(0.5, 0.5) == "agree"
    assert agreement(0.5, 0.9) == "judge_higher"
    assert agreement(0.9, 0.5) == "judge_lower"
    assert agreement(None, 0.5) is None


def test_truncated_response_is_reported_not_half_parsed():
    """A response cut off at max_tokens must not yield a partial claim set.

    This was a real failure: a 650-token completion budget truncated 8 of 12
    judge responses mid-object, and a lenient parser would have scored the
    fragment that happened to close.
    """
    full = json.dumps(GOOD_PAYLOAD)
    truncated = full[: len(full) // 2]
    result = parse_judge_response(truncated, expected_outcome="answer",
                                  expected_refusal_type=None)
    assert result.error is not None
    assert result.faithfulness is None and result.claims == []


def test_judge_has_its_own_token_budget_above_the_agent_default():
    from eval.llm_judge import JUDGE_MAX_TOKENS

    # A judge response carries every claim, so it needs more room than an
    # ordinary agent turn.
    from trfc.agent.llm import LLMConfig

    assert JUDGE_MAX_TOKENS > LLMConfig("groq", "m", "k", None).max_tokens


def test_judge_hook_runs_before_redaction_inside_evaluate(tmp_path, monkeypatch):
    """The judge must see the real amounts; the log must not keep them."""
    import asyncio

    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")

    from eval.run_eval import evaluate
    from eval.run_eval import load_testset, DEFAULT_TESTSET

    case = next(c for c in load_testset(DEFAULT_TESTSET) if c["id"] == "q05")
    seen_prompts = []

    class Message:
        content = json.dumps({
            "claims": [{"text": "44%", "label": "supported", "evidence_doc_id": "DOC0007"}],
            "faithfulness": 1.0, "actual_outcome": "answer",
            "actual_refusal_type": None, "note": "",
        })

    def judge_request(messages):
        seen_prompts.append(messages[0]["content"])
        return Message(), None

    async def adapter(_case):
        return {
            "answer": "Tỷ lệ vượt hạn mức là 44% với 220.000.000 VND.",
            "actual_outcome": "answer",
            "contexts": ["[Source: DOC0007] ví dụ 220.000.000 VND cho ra 44%"],
            "claims": None, "usage": None,
        }

    output = tmp_path / "results.jsonl"
    summary = asyncio.run(evaluate([case], adapter, output, judge_request=judge_request))
    row = json.loads(output.read_text(encoding="utf-8"))

    # The judge saw the unredacted amount...
    assert "220.000.000 VND" in seen_prompts[0]
    # ...but the persisted row did not keep it.
    assert "[REDACTED]" in row["actual_answer"]
    assert row["judge_faithfulness"] == 1.0
    assert row["judge_outcome"] == "answer"
    assert summary["judge"] == {"judged": 1, "skipped": 0, "errored": 0}


def test_judge_failure_does_not_change_deterministic_metrics(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")

    from eval.run_eval import DEFAULT_TESTSET, evaluate, load_testset

    case = next(c for c in load_testset(DEFAULT_TESTSET) if c["id"] == "q01")

    def broken_judge(_messages):
        raise RuntimeError("judge offline")

    async def adapter(_case):
        return {
            "answer": "500.000.000 VND và 100.000.000 VND",
            "actual_outcome": "answer",
            "contexts": ["[Source: DOC0007] hạn mức 500.000.000 VND"],
            "claims": None, "usage": None,
        }

    output = tmp_path / "results.jsonl"
    summary = asyncio.run(evaluate([case], adapter, output, judge_request=broken_judge))
    row = json.loads(output.read_text(encoding="utf-8"))
    assert row["judge_faithfulness"] is None
    assert "judge offline" in row["judge_error"]
    assert row["metrics"]["answer_correctness"] is True
    assert summary["judge"]["errored"] == 1
    assert summary["completed"] == 1


def asyncio_run(coroutine):
    import asyncio
    return asyncio.run(coroutine)
