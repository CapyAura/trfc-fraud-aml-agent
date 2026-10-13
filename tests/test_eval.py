import csv
import json
from pathlib import Path
import sys

import pytest

from eval.metrics import answer_correctness, context_precision, faithfulness, refusal_rate
from eval.report import CSV_COLUMNS, generate_report
from eval.run_eval import DEFAULT_TESTSET, _usage_or_none, load_testset, main, validate_testset


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


def test_faithfulness_literal_claim_support_and_unscorable_inputs():
    assert faithfulness("Hạn mức là 500.000.000 VND", ["DOC0007 Hạn mức là 500.000.000 VND"],
                        ["Hạn mức là 500.000.000 VND"]) == 1.0
    assert faithfulness("Câu trả lời", ["context"], ["Câu trả lời", "không được nhắc"]) is None
    assert faithfulness("Một câu khác", ["context có claim"], ["claim"]) is None
    assert faithfulness("Giá trị 150 VND", ["Giá trị 50 VND"], ["50 VND"]) is None
    assert faithfulness("", ["context"], ["claim"]) is None
    assert faithfulness("answer", [], ["claim"]) is None
    assert faithfulness("answer", ["context"]) is None


def test_context_precision_uses_explicit_document_references():
    assert context_precision("q", ["[DOC0007] policy", "[DOC0003] old policy"], ["DOC0007"]) == 0.5
    assert context_precision("q", ["no source id"], ["DOC0007"]) is None
    assert context_precision("q", ["[DOC00070] wrong prefix"], ["DOC0007"]) is None
    assert context_precision("q", [], ["DOC0007"]) is None
    assert context_precision("q", ["[DOC0007]"], None) is None


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
        {"allowed_to_answer": False, "actual_outcome": None},
    ])
    assert summary["correct"] == 3
    assert summary["total"] == 4
    assert summary["rate"] == pytest.approx(3 / 4)
    assert summary["subtype_correct"] == 1
    assert summary["subtype_total"] == 2
    assert summary["subtype_rate"] == 0.5
    assert summary["by_type"]["ii"] == {
        "correct": 0, "total": 2, "scored": 1, "unscorable": 1,
    }
    assert summary["unscorable"] == 1


def test_usage_missing_or_invalid_is_not_zero():
    assert _usage_or_none(None) is None
    assert _usage_or_none({"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "max_prompt": 0}) == {
        "calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "max_prompt": 0,
    }
    assert _usage_or_none({"calls": True, "prompt_tokens": 1, "completion_tokens": 0, "max_prompt": 1}) is None


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
    assert rows[0]["faithfulness"] == ""
    assert rows[0]["prompt_tokens"] == ""
    assert rows[0]["refusal_correctness"] == "True"
    assert "Unscored: 1" in faith_chart.read_text(encoding="utf-8")
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
    assert "Question ID" in svg


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
