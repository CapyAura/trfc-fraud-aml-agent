import csv
import json
from pathlib import Path
import sys

import pytest

from eval.metrics import (
    answer_correctness, context_precision, faithfulness, refusal_decision_correctness, refusal_rate,
)
from eval.report import CSV_COLUMNS, csv_rows, generate_report, load_results
from eval.run_eval import DEFAULT_TESTSET, _actual_outcome, _usage_or_none, load_testset, main, validate_testset


@pytest.fixture(autouse=True)
def _isolated_eval_database(tmp_path, monkeypatch):
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "eval-state.db"))
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")


def test_testset_is_valid_with_required_distribution():
    cases = load_testset(DEFAULT_TESTSET)
    assert len(cases) == 12
    assert sum(case["category"] == "no_answer" for case in cases) == 4
    assert sum(case.get("refusal_type") == "i" for case in cases) == 2
    assert sum(case.get("refusal_type") == "ii" for case in cases) == 2


def test_testset_rejects_invalid_distribution():
    cases = load_testset(DEFAULT_TESTSET)
    with pytest.raises(ValueError, match="exactly 12"):
        validate_testset(cases[:-1])


def test_testset_rejects_malformed_expected_values_and_document_ids():
    cases = load_testset(DEFAULT_TESTSET)
    malformed_expected = [dict(case) for case in cases]
    malformed_expected[0] = {**cases[0], "expected": {"criteria_type": "contains_all", "values": [7]}}
    with pytest.raises(ValueError, match="expected needs"):
        validate_testset(malformed_expected)

    malformed_source = [dict(case) for case in cases]
    malformed_source[0] = {**cases[0], "source_refs": ["DOC00070"]}
    with pytest.raises(ValueError, match="source_refs"):
        validate_testset(malformed_source)

    misplaced_citation = [dict(case) for case in cases]
    misplaced_citation[0] = {**cases[0], "must_cite": ["DOC0008"]}
    with pytest.raises(ValueError, match="must_cite must be included"):
        validate_testset(misplaced_citation)


def test_faithfulness_literal_claim_support_and_unscorable_inputs():
    assert faithfulness("Hạn mức là 500.000.000 VND", ["DOC0007 Hạn mức là 500.000.000 VND"],
                        ["Hạn mức là 500.000.000 VND"]) == 1.0
    assert faithfulness("Câu trả lời", ["context"], ["Câu trả lời", "không được nhắc"]) is None
    assert faithfulness("Một câu khác", ["context có claim"], ["claim"]) is None
    assert faithfulness("Giá trị 150 VND", ["Giá trị 50 VND"], ["50 VND"]) is None
    assert faithfulness("", ["context"], ["claim"]) is None
    assert faithfulness("answer", [], ["claim"]) is None
    assert faithfulness("answer", ["context"]) is None
    assert faithfulness("answer", ["context"], [None]) is None
    assert faithfulness("answer", "context", ["answer"]) is None


def test_context_precision_uses_explicit_document_references():
    assert context_precision("q", ["[DOC0007] policy", "[DOC0003] old policy"], ["DOC0007"]) == 0.5
    assert context_precision("q", ["no source id"], ["DOC0007"]) is None
    assert context_precision("q", ["[DOC00070] wrong prefix"], ["DOC0007"]) is None
    assert context_precision("q", [], ["DOC0007"]) is None
    assert context_precision("q", ["[DOC0007]"], None) is None
    assert context_precision("q", ["[DOC0007]"], ["DOC00070"]) is None
    assert context_precision("q", ["[DOC0007] and [DOC0008]"], ["DOC0007"]) is None
    assert context_precision("q", ["[DOC0007]"] , [None]) is None


def test_answer_correctness_and_missing_values():
    expected = {"criteria_type": "contains_all", "values": ["44%", "220.000.000 VND"]}
    assert answer_correctness("Vượt 44%, tức 220.000.000 VND", expected, True) is True
    assert answer_correctness("Vượt 44%", expected, True) is False
    assert answer_correctness("150.000.000 VND", {"criteria_type": "contains_all", "values": ["50.000.000 VND"]}, True) is False
    assert answer_correctness(None, expected, True) is None
    assert answer_correctness("answer", expected, False) is None


def test_refusal_decision_and_subtype_metrics():
    summary = refusal_rate([
        {"allowed_to_answer": False, "actual_outcome": "refusal", "expected_refusal_type": "i", "actual_refusal_type": "i"},
        {"allowed_to_answer": False, "actual_outcome": "refusal", "expected_refusal_type": "ii", "actual_refusal_type": "i"},
        {"allowed_to_answer": True, "actual_outcome": "refusal"},
        {"allowed_to_answer": False, "actual_outcome": "refusal", "expected_refusal_type": "ii", "actual_refusal_type": None},
        {"allowed_to_answer": False, "actual_outcome": "answer", "expected_refusal_type": "i", "actual_refusal_type": "i"},
        {"allowed_to_answer": False, "actual_outcome": None},
    ])
    assert summary["correct"] == 3
    assert summary["total"] == 5
    assert summary["rate"] == pytest.approx(3 / 5)
    assert summary["subtype_correct"] == 1
    assert summary["subtype_total"] == 2
    assert summary["subtype_rate"] == 0.5
    assert summary["by_type"]["ii"] == {
        "correct": 0, "total": 2, "scored": 1, "unscorable": 1,
    }
    assert summary["by_type"]["i"] == {
        "correct": 1, "total": 2, "scored": 1, "unscorable": 1,
    }
    assert summary["unscorable"] == 1
    assert refusal_decision_correctness(False, None) is None
    assert refusal_decision_correctness(False, "answer") is False


def test_report_does_not_score_refusal_subtype_when_no_refusal_occurred():
    row = {
        "allowed_to_answer": False, "actual_outcome": "answer",
        "expected_refusal_type": "i", "actual_refusal_type": "i",
        "metrics": {"refusal_correctness": False, "refusal_subtype_correctness": None},
    }
    flattened = csv_rows([row])[0]
    assert flattened["refusal_correctness"] is False
    assert flattened["refusal_subtype_correctness"] == "Unscorable"


def test_usage_missing_or_invalid_is_not_zero():
    assert _usage_or_none(None) is None
    assert _usage_or_none({"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "max_prompt": 0}) == {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "max_prompt": 0,
    }
    assert _usage_or_none({"calls": True, "prompt_tokens": 1, "completion_tokens": 0, "max_prompt": 1}) is None


def test_usage_preserves_actual_call_count_when_provider_tokens_are_unavailable():
    partial = {"calls": 2, "prompt_tokens": None, "completion_tokens": None, "max_prompt": None}
    assert _usage_or_none(partial) == partial
    assert _usage_or_none({**partial, "calls": True}) is None
    assert _usage_or_none({**partial, "max_prompt": 1}) is None


def test_actual_outcome_is_not_guessed_from_answer_text():
    assert _actual_outcome({"answer": "some text"}) is None
    assert _actual_outcome({"refused": False, "answer": "some text"}) == "answer"
    assert _actual_outcome({"actual_outcome": "refusal", "answer": "some text"}) == "refusal"


def test_csv_report_columns_and_missing_scores_not_zero(tmp_path):
    source = tmp_path / "eval.jsonl"
    source.write_text(json.dumps({
        "question_id": "q1", "category": "retrieval", "expected_outcome": "answer",
        "actual_outcome": "answer", "allowed_to_answer": True,
        "metrics": {"faithfulness": None, "context_precision": 0.5, "answer_correctness": True},
        "usage": None, "status": "completed",
    }) + "\n", encoding="utf-8")
    csv_path, faith_chart, refusal_chart = generate_report(source, tmp_path / "out")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert list(rows[0]) == CSV_COLUMNS
    assert rows[0]["faithfulness"] == "Unscorable"
    assert rows[0]["prompt_tokens"] == ""
    assert rows[0]["refusal_correctness"] == "True"
    assert "Unscorable: 1" in faith_chart.read_text(encoding="utf-8")
    assert "No evaluation data" not in refusal_chart.read_text(encoding="utf-8")


def test_report_supports_empty_evaluation_file(tmp_path):
    source = tmp_path / "empty.jsonl"
    source.write_text("", encoding="utf-8")
    csv_path, faith_chart, _ = generate_report(source, tmp_path / "out")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        assert list(csv.reader(stream)) == [CSV_COLUMNS]
    assert "No evaluation data" in faith_chart.read_text(encoding="utf-8")


def test_report_distinguishes_rows_with_no_scores_from_empty_data(tmp_path):
    source = tmp_path / "unscored.jsonl"
    source.write_text(json.dumps({
        "question_id": "q1", "category": "retrieval", "status": "unscorable",
        "metrics": {}, "usage": None,
    }) + "\n", encoding="utf-8")
    _, faith_chart, _ = generate_report(source, tmp_path / "out")
    svg = faith_chart.read_text(encoding="utf-8")
    assert "No metric scores available" in svg
    assert "Unscorable: 1" in svg
    assert "Question ID" in svg


def test_report_labels_missing_and_unscorable_values_and_escapes_csv_svg(tmp_path):
    source = tmp_path / "evaluation.jsonl"
    source.write_text("\n".join([
        json.dumps({
            "question_id": 'q<&,"1', "category": "retrieval", "status": "completed",
            "metrics": {}, "usage": None,
        }),
        json.dumps({
            "question_id": "q2", "category": "retrieval", "status": "completed",
            "metrics": {"faithfulness": None}, "usage": None,
        }),
    ]) + "\n", encoding="utf-8")
    csv_path, faith_chart, _ = generate_report(source, tmp_path / "out")
    with csv_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["question_id"] == 'q<&,"1'
    assert rows[0]["faithfulness"] == "Missing"
    assert rows[1]["faithfulness"] == "Unscorable"
    svg = faith_chart.read_text(encoding="utf-8")
    assert "Missing: 1" in svg and "Unscorable: 1" in svg
    assert 'q&lt;&amp;,"1' in svg


def test_report_rejects_invalid_jsonl_with_path_and_line(tmp_path):
    source = tmp_path / "bad.jsonl"
    source.write_text('{}\n{bad json}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"Invalid JSON at .*bad.jsonl:2"):
        load_results(source)


def test_dry_run_does_not_load_adapter_or_write_evaluation(tmp_path, monkeypatch, capsys):
    output = tmp_path / "must_not_exist.jsonl"
    monkeypatch.setattr(sys, "argv", [
        "run_eval", "--dry-run", "--agent-adapter", "module_that_does_not_exist:run",
        "--output", str(output),
    ])
    assert main() == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert not output.exists()


def test_adapter_evaluation_records_missing_usage_and_errors(tmp_path):
    cases = load_testset(DEFAULT_TESTSET)[:2]
    calls = []

    async def adapter(case):
        calls.append(case["id"])
        if case["id"] == "q01":
            return {"answer": "500.000.000 VND and 100.000.000 VND", "actual_outcome": "answer",
                    "contexts": ["[DOC0007] limits"], "claims": None, "usage": None}
        raise RuntimeError("sample adapter error")

    from eval.run_eval import evaluate
    summary = __import__("asyncio").run(evaluate(cases, adapter, tmp_path / "results.jsonl"))
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert calls == ["q01", "q02"]
    assert summary["completed"] == 1 and summary["failed"] == 1
    assert rows[0]["usage"] is None
    assert rows[1]["error"].startswith("RuntimeError:")


def test_unknown_decision_is_unscorable_not_incorrect(tmp_path):
    import asyncio
    from eval.run_eval import evaluate

    case = load_testset(DEFAULT_TESTSET)[8]

    async def adapter(_case):
        return {"answer": None, "actual_outcome": None}

    summary = asyncio.run(evaluate([case], adapter, tmp_path / "results.jsonl"))
    row = json.loads((tmp_path / "results.jsonl").read_text(encoding="utf-8"))
    assert summary["unscorable"] == 1
    assert row["metrics"]["refusal_correctness"] is None


def test_nonserializable_case_fails_without_dropping_later_case(tmp_path):
    import asyncio
    from eval.run_eval import evaluate

    cases = load_testset(DEFAULT_TESTSET)[:2]

    async def adapter(case):
        if case["id"] == "q01":
            return {"answer": "x", "actual_outcome": "answer", "tool_trace": object()}
        return {"answer": "x", "actual_outcome": "answer"}

    output = tmp_path / "results.jsonl"
    summary = asyncio.run(evaluate(cases, adapter, output))
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert summary["failed"] == 1 and summary["completed"] == 1
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"].startswith("SerializationError:")
    assert rows[1]["question_id"] == "q02"


def test_async_adapter_timeout_is_recorded_and_later_case_continues(tmp_path):
    import asyncio
    from eval.run_eval import evaluate

    cases = load_testset(DEFAULT_TESTSET)[:2]

    async def adapter(case):
        if case["id"] == "q01":
            await asyncio.sleep(1)
        return {"answer": "answer", "actual_outcome": "answer"}

    summary = asyncio.run(evaluate(cases, adapter, tmp_path / "results.jsonl", case_timeout=0.01))
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["failed"] == 1 and summary["completed"] == 1
    assert rows[0]["error"].startswith("TimeoutError:")
    assert rows[1]["status"] == "completed"


def test_blocking_provider_worker_does_not_block_timeout_or_later_case(tmp_path, monkeypatch):
    import asyncio
    import threading

    from eval.run_eval import evaluate
    from trfc.agent import llm

    cases = load_testset(DEFAULT_TESTSET)[:2]
    release_worker = threading.Event()

    def blocking_provider(_messages, _tools=None):
        release_worker.wait(timeout=2)
        return object(), None

    monkeypatch.setattr(llm, "call_llm", blocking_provider)
    monkeypatch.setenv("TRFC_REQUIRE_ISOLATED_DB", "1")
    monkeypatch.setenv("TRFC_STATE_DB", str(tmp_path / "isolated.db"))

    async def adapter(case):
        if case["id"] == "q01":
            await llm.call_llm_async([])
        return {"answer": "answer", "actual_outcome": "answer"}

    async def run():
        # Let the provider worker finish after the first timeout. This also
        # prevents asyncio's executor shutdown from waiting for its full bound.
        asyncio.get_running_loop().call_later(0.1, release_worker.set)
        return await evaluate(cases, adapter, tmp_path / "results.jsonl", case_timeout=0.01)

    summary = asyncio.run(run())
    rows = [json.loads(line) for line in (tmp_path / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert summary["failed"] == 1 and summary["completed"] == 1
    assert rows[0]["error"].startswith("TimeoutError:")
    assert rows[1]["status"] == "completed"
