import csv
import json
from pathlib import Path
import sys

import pytest

from eval.metrics import (
    answer_correctness, claim_support_detail, context_precision, faithfulness,
    marker_results, metadata_filter_usage, refusal_decision_correctness, refusal_rate,
)
from eval.report import CSV_COLUMNS, csv_rows, generate_report, load_results, rescore_row
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


def test_testset_declares_a_metadata_tier_filter_case():
    cases = load_testset(DEFAULT_TESTSET)
    tiered = [case for case in cases if "expected_tier" in case]
    assert tiered, "no case exercises the tier metadata pre-filter"
    assert all(case["expected_tier"] in (1, 2, 3) for case in tiered)

    malformed = [dict(case) for case in cases]
    malformed[0] = {**cases[0], "expected_tier": "2"}
    with pytest.raises(ValueError, match="expected_tier"):
        validate_testset(malformed)


def test_metadata_filter_usage_requires_the_requested_tier_argument():
    trace = [
        {"tool_name": "search_policy", "arguments": {"query": "han muc"}},
        {"tool_name": "search_policy", "arguments": {"query": "han muc", "tier": 2}},
    ]
    assert metadata_filter_usage(trace, 2) is True
    assert metadata_filter_usage(trace, 3) is False
    # A trace that could not be captured must not read as a successful filter.
    assert metadata_filter_usage(None, 2) is None
    assert metadata_filter_usage([], 2) is False
    # Cases without a declared tier are not scored on this metric.
    assert metadata_filter_usage(trace, None) is None
    assert metadata_filter_usage(trace, "2") is None


def test_testset_rejects_malformed_expected_values_and_document_ids():
    cases = load_testset(DEFAULT_TESTSET)
    malformed_expected = [dict(case) for case in cases]
    malformed_expected[0] = {**cases[0], "expected": {"criteria_type": "contains_all", "values": [7]}}
    with pytest.raises(ValueError, match="expected value 1"):
        validate_testset(malformed_expected)

    bad_variant = [dict(case) for case in cases]
    bad_variant[0] = {**cases[0], "expected": {
        "criteria_type": "contains_all",
        "values": [{"any": [], "label": "x"}],
    }}
    with pytest.raises(ValueError, match="non-empty string variants"):
        validate_testset(bad_variant)

    both_keys = [dict(case) for case in cases]
    both_keys[0] = {**cases[0], "expected": {
        "criteria_type": "contains_all",
        "values": [{"any": ["a"], "all": ["b"]}],
    }}
    with pytest.raises(ValueError, match="exactly one of all/any"):
        validate_testset(both_keys)

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
    assert context_precision("q", ["[DOC0007]"] , [None]) is None
    # A context citing several documents is judged by its own citations instead
    # of voiding the whole case; unscorable contexts are excluded, not counted
    # as irrelevant.
    assert context_precision("q", ["[DOC0007] and [DOC0008]"], ["DOC0007"]) == 1.0
    assert context_precision("q", ["[DOC0003] old", "[DOC0007] and [DOC0008]"], ["DOC0007"]) == 0.5
    assert context_precision("q", ["no source id", "[DOC0007] x"], ["DOC0007"]) == 1.0


def test_faithfulness_accepts_judge_claim_records_without_trusting_labels():
    answer = "Hạn mức là 500.000.000 VND"
    context = ["[Source: DOC0007] Hạn mức là 500.000.000 VND"]
    judge_claims = [{"text": "Hạn mức là 500.000.000 VND", "label": "supported",
                     "evidence_doc_id": "DOC0007"}]
    assert faithfulness(answer, context, judge_claims) == 1.0
    # The judge's own label must never move the score; only the literal match.
    assert faithfulness(answer, ["no supporting text"], judge_claims) == 0.0
    assert faithfulness(answer, context,
                        [{"text": answer, "label": "unsupported"}]) == 1.0
    assert faithfulness("A B", ["A"], [{"text": "A"}, {"text": "B"}]) == 0.5
    # A claim record without a usable span invalidates the list.
    assert faithfulness(answer, context, [{"label": "supported"}]) is None
    assert faithfulness(answer, context, [{"text": None}]) is None
    assert faithfulness(answer, context, [{"text": "  "}]) is None


def test_claim_support_detail_reports_judge_agreement():
    claims = [
        {"text": "present", "label": "supported"},
        {"text": "absent", "label": "supported"},
        "bare span",
    ]
    detail = claim_support_detail(claims, ["present"])
    assert detail[0] == {"text": "present", "supported": True,
                         "label": "supported", "agrees": True}
    assert detail[1]["supported"] is False and detail[1]["agrees"] is False
    assert detail[2]["label"] is None and detail[2]["agrees"] is None


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


def test_rescore_recomputes_context_precision_without_touching_evidence(tmp_path):
    row = {
        "question_id": "q1", "category": "retrieval", "expected_outcome": "answer",
        "actual_outcome": "answer", "allowed_to_answer": True,
        "expected": {"criteria_type": "contains_all", "values": ["44%"]},
        "source_refs": ["DOC0007"], "actual_answer": "ket qua 44%",
        "contexts": ["[Source: DOC0007] a", "[Source: DOC0003] b"],
        "claims": None, "metrics": {"context_precision": None, "answer_correctness": True},
        "usage": None, "status": "completed",
    }
    rescored = rescore_row(row)
    # Derived metric is recomputed; the evidence fields are untouched.
    assert rescored["metrics"]["context_precision"] == 0.5
    assert rescored["actual_answer"] == row["actual_answer"]
    assert rescored["contexts"] == row["contexts"]
    assert row["metrics"]["context_precision"] is None


def test_rescore_refuses_to_score_answer_correctness_against_redacted_evidence():
    # A stored row whose expected marker and answer were both redacted would
    # match trivially and flip a genuine failure into a pass.
    row = {
        "question_id": "q05", "category": "calc", "expected_outcome": "answer",
        "actual_outcome": "answer", "allowed_to_answer": True,
        "expected": {"criteria_type": "contains_all", "values": ["44%", "[REDACTED] VND"]},
        "source_refs": ["DOC0007"],
        "actual_answer": "ty le 44% voi [REDACTED] VND",
        "contexts": ["[Source: DOC0007] a"], "claims": None,
        "metrics": {"answer_correctness": False, "context_precision": None},
        "usage": None, "status": "completed",
    }
    rescored = rescore_row(row)
    assert rescored["metrics"]["answer_correctness"] is False


def test_rescore_scores_answer_correctness_when_evidence_is_intact():
    row = {
        "question_id": "q1", "category": "calc", "expected_outcome": "answer",
        "actual_outcome": "answer", "allowed_to_answer": True,
        "expected": {"criteria_type": "contains_all", "values": ["44%"]},
        "source_refs": ["DOC0007"], "actual_answer": "ty le 44%",
        "contexts": ["[Source: DOC0007] a"], "claims": None,
        "metrics": {"answer_correctness": False}, "usage": None, "status": "completed",
    }
    assert rescore_row(row)["metrics"]["answer_correctness"] is True


def test_marker_results_record_outcomes_without_leaking_amounts():
    """The in-log proof of a score must survive redaction.

    Recording the marker text would put money amounts in the log, where they are
    redacted — leaving a criterion recorded as "[REDACTED] VND" that proves
    nothing. Index + kind is enough, because the reader pairs it with the
    testset.
    """
    expected = {"criteria_type": "contains_all",
                "values": ["44%", "220.000.000 VND",
                           {"label": "k", "any": ["a", "b"]}]}
    answer = "44% với 220.000.000 VND và a"
    results = marker_results(answer, expected)
    assert [item["index"] for item in results] == [1, 2, 3]
    assert [item["kind"] for item in results] == ["literal", "literal", "variants"]
    assert all(item["satisfied"] is True for item in results)
    assert not any("220.000.000" in str(item) for item in results)

    assert marker_results("44%", expected)[1]["satisfied"] is False
    assert marker_results(None, expected) is None


def test_answer_correctness_supports_variant_criteria():
    expected = {"criteria_type": "contains_all", "values": [
        {"label": "no freeze", "any": ["không được ra quyết định khóa",
                                       "không thể ra quyết định khóa"]},
        "5 năm",
    ]}
    assert answer_correctness("Không thể ra quyết định khóa. Lưu 5 năm.", expected, True) is True
    assert answer_correctness("Lưu 5 năm.", expected, True) is False
    assert answer_correctness("x", {"criteria_type": "contains_all",
                                    "values": [{"any": []}]}, True) is None


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
    assert _actual_outcome({"refused": False, "answer": "some text"}) is None
    assert _actual_outcome({"refused": True, "answer": "I cannot help"}) is None
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


def test_report_charts_boolean_metrics_instead_of_dropping_them(tmp_path):
    """refusal_correctness is a boolean; it must still be plotted.

    Treating a bool as "not a number" silently produced an empty chart for a
    metric that was measured on every case, so a reader saw "No metric scores
    available" for 12/12 correct decisions.
    """
    source = tmp_path / "eval.jsonl"
    rows = [
        {"question_id": "q1", "category": "retrieval", "status": "completed",
         "allowed_to_answer": True, "actual_outcome": "answer",
         "metrics": {"refusal_correctness": True}, "usage": None},
        {"question_id": "q2", "category": "no_answer", "status": "completed",
         "allowed_to_answer": False, "actual_outcome": "answer",
         "metrics": {"refusal_correctness": False}, "usage": None},
    ]
    source.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    _, _, refusal_chart = generate_report(source, tmp_path / "out")
    svg = refusal_chart.read_text(encoding="utf-8")
    assert "No metric scores available" not in svg
    assert "Scored: 2" in svg
    # True plots as a full bar, False as an empty one; both labels are present.
    assert svg.count('fill="#3976a8"') == 2
    assert "100%" in svg and "0%" in svg


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
