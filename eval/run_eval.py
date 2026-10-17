"""Validate the testset or evaluate through an explicitly supplied adapter.

Adapter contract: ``module:function``; callable accepts one test-case dict and
returns a dict with `answer`, optional `actual_outcome`, `actual_refusal_type`,
`contexts` (list[str]), `claims` (list[str]), `tool_trace`, and `usage`. Async
callables are supported. The built-in `eval.agent_adapter:run_case` passes
through fields explicitly supplied by the runtime; unavailable metadata remains
unavailable and is never inferred from answer text.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

try:  # package execution: python -m eval.run_eval
    from .metrics import (
        answer_correctness, context_precision, faithfulness, marker_results,
        metadata_filter_usage, refusal_decision_correctness, refusal_rate,
    )
    from .database_isolation import require_isolated_database
    from .redaction import redact_for_log
    from .step_events import append_step_events
    from .decision_events import append_decision_event
    from .provenance import resolve_execution_mode
    from .llm_judge import evaluate_judge, load_judge_prompt
except ImportError:  # direct script execution
    from metrics import (
        answer_correctness, context_precision, faithfulness, marker_results,
        metadata_filter_usage, refusal_decision_correctness, refusal_rate,
    )
    from database_isolation import require_isolated_database
    from redaction import redact_for_log
    from step_events import append_step_events
    from decision_events import append_decision_event
    from provenance import resolve_execution_mode
    from llm_judge import evaluate_judge, load_judge_prompt

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTSET = ROOT / "tests" / "testset.jsonl"
DEFAULT_OUTPUT = ROOT / "logs" / "evaluation.jsonl"
EXPECTED_DISTRIBUTION = {
    "retrieval": 3, "calc": 2, "contradiction": 2,
    "multi_doc": 1, "no_answer": 4,
}
_SAFE_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def load_testset(path: Path = DEFAULT_TESTSET) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Blank line in JSONL at {path}:{line_no}")
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {path}:{line_no}: {exc}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"Expected JSON object at {path}:{line_no}")
        cases.append(item)
    validate_testset(cases)
    return cases


def validate_testset(cases: list[dict[str, Any]]) -> None:
    if len(cases) != 12:
        raise ValueError(f"Expected exactly 12 cases, found {len(cases)}")
    if not all(isinstance(case, dict) for case in cases):
        raise ValueError("Every testset row must be a JSON object")
    ids = [case.get("id") for case in cases]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Every case needs a unique non-empty string id")
    required = {"id", "question", "category", "allowed_to_answer", "expected_outcome", "expected", "source_refs"}
    for index, case in enumerate(cases, 1):
        missing = required - case.keys()
        if missing:
            raise ValueError(f"Case {index} missing fields: {', '.join(sorted(missing))}")
        if not isinstance(case["question"], str) or not case["question"].strip():
            raise ValueError(f"Case {case['id']} has an empty question")
        if not isinstance(case["category"], str) or case["category"] not in EXPECTED_DISTRIBUTION:
            raise ValueError(f"Case {case['id']} has an unsupported category")
        if "scenario" in case and (
            not isinstance(case["scenario"], str)
            or case["scenario"] not in {"freeze", "flag", "refusal"}
        ):
            raise ValueError(f"Case {case['id']} has an unsupported C4 scenario")
        if not isinstance(case["allowed_to_answer"], bool):
            raise ValueError(f"Case {case['id']} allowed_to_answer must be boolean")
        if not isinstance(case["expected_outcome"], str) or case["expected_outcome"] not in {"answer", "refusal"}:
            raise ValueError(f"Case {case['id']} has invalid expected_outcome")
        if case["allowed_to_answer"] != (case["expected_outcome"] == "answer"):
            raise ValueError(f"Case {case['id']} allowed_to_answer conflicts with expected_outcome")
        if not isinstance(case["expected"], dict):
            raise ValueError(f"Case {case['id']} expected must be an object")
        expected = case["expected"]
        expected_values = expected.get("values")
        if (not isinstance(expected.get("criteria_type"), str)
                or not isinstance(expected_values, list) or not expected_values):
            raise ValueError(f"Case {case['id']} expected needs a criteria_type and non-empty values")
        for index, criterion in enumerate(expected_values, 1):
            if isinstance(criterion, str):
                if not criterion.strip():
                    raise ValueError(f"Case {case['id']} expected value {index} is empty")
                continue
            if not isinstance(criterion, dict):
                raise ValueError(
                    f"Case {case['id']} expected value {index} must be a string or a variant object")
            if set(criterion) - {"label", "all", "any"}:
                raise ValueError(
                    f"Case {case['id']} expected value {index} has unsupported keys")
            keys = [key for key in ("all", "any") if key in criterion]
            if len(keys) != 1:
                raise ValueError(
                    f"Case {case['id']} expected value {index} needs exactly one of all/any")
            variants = criterion[keys[0]]
            if (not isinstance(variants, list) or not variants
                    or not all(isinstance(v, str) and v.strip() for v in variants)):
                raise ValueError(
                    f"Case {case['id']} expected value {index} needs non-empty string variants")
        if not isinstance(case["source_refs"], list) or not case["source_refs"] or not all(
            isinstance(ref, str) and re.fullmatch(r"DOC\d{4}", ref, re.IGNORECASE)
            for ref in case["source_refs"]
        ):
            raise ValueError(f"Case {case['id']} source_refs must contain DOCnnnn identifiers")
        if not isinstance(case.get("must_cite"), list) or not all(
            isinstance(ref, str) and re.fullmatch(r"DOC\d{4}", ref, re.IGNORECASE)
            for ref in case["must_cite"]
        ):
            raise ValueError(f"Case {case['id']} must_cite must contain DOCnnnn identifiers")
        if not set(case["must_cite"]).issubset(case["source_refs"]):
            raise ValueError(f"Case {case['id']} must_cite must be included in source_refs")
        if "missing_evidence" in case and (
            not isinstance(case["missing_evidence"], list)
            or not all(isinstance(item, str) and item.strip() for item in case["missing_evidence"])
        ):
            raise ValueError(f"Case {case['id']} missing_evidence must be a list of non-empty strings")
        if "expected_tier" in case and (
            type(case["expected_tier"]) is not int or case["expected_tier"] not in (1, 2, 3)
        ):
            raise ValueError(f"Case {case['id']} expected_tier must be an integer tier 1, 2, or 3")
        if case["category"] == "no_answer":
            if (case["allowed_to_answer"] or case["expected_outcome"] != "refusal"
                    or case.get("refusal_type") not in {"i", "ii"}
                    or expected.get("criteria_type") != "refusal_reason"):
                raise ValueError(f"Case {case['id']} needs refusal outcome and type i or ii")
            if case["refusal_type"] == "ii" and not case.get("missing_evidence"):
                raise ValueError(f"Case {case['id']} refusal type ii needs missing_evidence")
        elif (case.get("refusal_type") is not None or not case["allowed_to_answer"]
              or case["expected_outcome"] != "answer"
              or expected.get("criteria_type") != "contains_all"):
            raise ValueError(f"Answerable case {case['id']} must have answer outcome and contains_all criteria")
    counts = {category: sum(case["category"] == category for case in cases)
              for category in EXPECTED_DISTRIBUTION}
    if counts != EXPECTED_DISTRIBUTION:
        raise ValueError(f"Wrong category distribution: {counts}")
    refusal_counts = {kind: sum(case.get("refusal_type") == kind for case in cases) for kind in ("i", "ii")}
    if refusal_counts != {"i": 2, "ii": 2}:
        raise ValueError(f"Expected 2 refusals of each subtype, got {refusal_counts}")


def _load_adapter(spec: str):
    if ":" not in spec:
        raise ValueError("Adapter must be specified as module:function")
    module_name, function_name = spec.split(":", 1)
    fn = getattr(importlib.import_module(module_name), function_name)
    if not callable(fn):
        raise ValueError(f"Adapter {spec} is not callable")
    return fn


async def _invoke(adapter, case):
    value = adapter(case)
    return await value if inspect.isawaitable(value) else value


def _usage_or_none(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    keys = ("calls", "prompt_tokens", "completion_tokens", "max_prompt")
    if (not all(key in value for key in keys)
            or type(value["calls"]) is not int or value["calls"] < 0
            or any(value[key] is not None and
                   (type(value[key]) is not int or value[key] < 0)
                   for key in keys[1:])
            or (value["prompt_tokens"] is None and value["max_prompt"] is not None)):
        return None
    return {key: value[key] for key in keys}


_JUDGE_ROW_FIELDS = (
    "judge_faithfulness", "judge_outcome", "judge_refusal_type",
    "judge_outcome_correct", "judge_refusal_type_correct", "judge_claims",
    "judge_agreement", "judge_note", "judge_error",
)


def _actual_outcome(result: dict[str, Any]) -> str | None:
    outcome = result.get("actual_outcome")
    if isinstance(outcome, str) and outcome in {"answer", "refusal"}:
        return outcome
    return None


async def evaluate(cases: list[dict[str, Any]], adapter, output_path: Path,
                   case_timeout: float = 180.0, *,
                   step_events_path: Path | None = None,
                   decision_events_path: Path | None = None,
                   execution_mode: str | None = None,
                   judge_request=None,
                   judge_prompt_template: str | None = None) -> dict[str, Any]:
    if case_timeout <= 0:
        raise ValueError("case_timeout must be positive")
    has_event_output = step_events_path is not None or decision_events_path is not None
    if not has_event_output and execution_mode is not None:
        raise ValueError("execution mode requires event output")
    resolved_execution_mode = None
    if has_event_output:
        event_paths = [Path(path).resolve() for path in (step_events_path, decision_events_path) if path is not None]
        if Path(output_path).resolve() in event_paths or len(set(event_paths)) != len(event_paths):
            raise ValueError("case, tool-event, and decision-event outputs must be different files")
        resolved_execution_mode = resolve_execution_mode(adapter, execution_mode)
    # Adapters may invoke the write-capable agent tools. Fail before creating
    # output or calling an adapter unless the isolated DB contract is explicit.
    require_isolated_database()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = failed = unscorable = 0
    judged = judge_skipped = judge_errored = 0
    refusal_rows = []
    event_written = 0
    event_skipped: dict[str, int] = {}
    event_errors = 0
    decision_event_written = 0
    decision_event_skipped: dict[str, int] = {}
    decision_event_errors = 0
    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        for case in cases:
            run_id = uuid4().hex if has_event_output else None
            row: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "question_id": case["id"], "category": case["category"],
                "expected_outcome": case["expected_outcome"],
                "allowed_to_answer": case["allowed_to_answer"],
                "expected_refusal_type": case.get("refusal_type"),
                "expected_tier": case.get("expected_tier"),
                "expected": case["expected"], "source_refs": case["source_refs"],
                "actual_answer": None, "actual_outcome": None,
                "actual_refusal_type": None, "contexts": None, "claims": None,
                "policy_rule_id": None, "decision_source": None,
                "policy_decision_status": None, "policy_reason_code": None,
                "tool_trace": None, "usage": None, "metrics": {}, "marker_results": None,
                "error": None, "status": "failed",
            }
            try:
                result = await asyncio.wait_for(_invoke(adapter, case), timeout=case_timeout)
                if not isinstance(result, dict):
                    raise TypeError("Adapter must return a dict")
                row["actual_answer"] = result.get("answer")
                row["actual_outcome"] = _actual_outcome(result)
                refusal_type = result.get("actual_refusal_type")
                row["actual_refusal_type"] = (
                    refusal_type
                    if row["actual_outcome"] == "refusal" and refusal_type in {"i", "ii"}
                    else None
                )
                policy_rule_id = result.get("policy_rule_id")
                row["policy_rule_id"] = (
                    policy_rule_id
                    if isinstance(policy_rule_id, str) and _SAFE_IDENTIFIER.fullmatch(policy_rule_id)
                    else None
                )
                decision_source = result.get("decision_source")
                row["decision_source"] = (
                    decision_source
                    if isinstance(decision_source, str) and _SAFE_IDENTIFIER.fullmatch(decision_source)
                    else None
                )
                policy_status = result.get("policy_decision_status")
                row["policy_decision_status"] = (
                    policy_status if policy_status in {"decided", "needs_information"} else None
                )
                policy_reason_code = result.get("policy_reason_code")
                row["policy_reason_code"] = (
                    policy_reason_code
                    if isinstance(policy_reason_code, str) and policy_reason_code.strip()
                    else None
                )
                if row["policy_decision_status"] == "needs_information":
                    row["actual_outcome"] = None
                    row["actual_refusal_type"] = None
                    row["policy_rule_id"] = None
                    row["decision_source"] = None
                elif row["policy_decision_status"] == "decided":
                    if row["actual_outcome"] not in {"answer", "refusal"} or row["decision_source"] is None:
                        row["policy_decision_status"] = None
                row["contexts"] = result.get("contexts")
                row["claims"] = result.get("claims")
                row["tool_trace"] = result.get("tool_trace")
                row["usage"] = _usage_or_none(result.get("usage"))
                status = result.get("status")
                if status == "failed":
                    raise RuntimeError(result.get("error") or "Adapter reported a failed runtime execution")
                if status not in (None, "completed", "unscorable"):
                    raise ValueError(f"Adapter returned an invalid execution status: {status!r}")
                if status == "unscorable":
                    row["actual_outcome"] = None
                    row["actual_refusal_type"] = None
                    row["policy_rule_id"] = None
                    row["decision_source"] = None
                    row["policy_decision_status"] = None
                    row["status"] = "unscorable"
                    unscorable += 1
                elif not isinstance(row["actual_outcome"], str) or row["actual_outcome"] not in {"answer", "refusal"}:
                    row["status"] = "unscorable"
                    unscorable += 1
                else:
                    row["status"] = "completed"
                    completed += 1
                row["metrics"] = {
                    "answer_correctness": answer_correctness(
                        row["actual_answer"], case["expected"], case["allowed_to_answer"]),
                    "faithfulness": faithfulness(row["actual_answer"], row["contexts"], row["claims"]),
                    "context_precision": context_precision(
                        case["question"], row["contexts"], case["source_refs"]),
                    "refusal_correctness": refusal_decision_correctness(
                        case["allowed_to_answer"], row["actual_outcome"]),
                    "refusal_subtype_correctness": (
                        row["actual_refusal_type"] == case.get("refusal_type")
                        if case.get("refusal_type") in {"i", "ii"}
                        and isinstance(row["actual_refusal_type"], str)
                        and row["actual_refusal_type"] in {"i", "ii"}
                        and row["actual_outcome"] == "refusal"
                        else None
                    ),
                    "metadata_filter_usage": metadata_filter_usage(
                        row["tool_trace"], case.get("expected_tier")),
                }
                # Recorded before redaction: the stored answer loses money
                # amounts and IDs, so this is the only in-log proof of why
                # answer_correctness got its value.
                row["marker_results"] = marker_results(row["actual_answer"], case["expected"])
                # The judge runs here, on the unredacted row. Once redaction is
                # applied below, the amounts it would need are gone.
                if judge_request is not None:
                    judgement = evaluate_judge(
                        row, judge_request, prompt_template=judge_prompt_template)
                    row.update(judgement.as_row_fields())
                    if judgement.error is None:
                        judged += 1
                    elif "REDACTED" in judgement.error or "not 'completed'" in judgement.error:
                        judge_skipped += 1
                    else:
                        judge_errored += 1
            except Exception as exc:  # continue so a single case cannot abort the set
                row["error"] = f"{type(exc).__name__}: {exc}"
                row["status"] = "failed"
                row["actual_outcome"] = None
                row["actual_refusal_type"] = None
                row["policy_rule_id"] = None
                row["decision_source"] = None
                row["policy_decision_status"] = None
                row["policy_reason_code"] = None
                row["claims"] = None
                row["marker_results"] = None
                if judge_request is not None:
                    row.update({field: None for field in _JUDGE_ROW_FIELDS})
                    row["judge_error"] = "case failed before judging"
                failed += 1
            case_serialization_failed = False
            try:
                encoded_row = json.dumps(redact_for_log(row), ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError):
                case_serialization_failed = True
                if row["status"] == "completed":
                    completed -= 1
                elif row["status"] == "unscorable":
                    unscorable -= 1
                failed += 1
                row["status"] = "failed"
                row["error"] = "SerializationError: adapter result contains non-JSON-serializable data"
                row["actual_answer"] = None
                row["actual_outcome"] = None
                row["actual_refusal_type"] = None
                row["policy_rule_id"] = None
                row["decision_source"] = None
                row["policy_decision_status"] = None
                row["policy_reason_code"] = None
                row["contexts"] = None
                row["claims"] = None
                row["tool_trace"] = None
                row["usage"] = None
                row["metrics"] = {}
                row["marker_results"] = None
                encoded_row = json.dumps(redact_for_log(row), ensure_ascii=False, allow_nan=False)
            stream.write(encoded_row + "\n")
            if not case_serialization_failed and row["status"] != "failed":
                refusal_rows.append({
                    "allowed_to_answer": case["allowed_to_answer"],
                    "actual_outcome": row["actual_outcome"],
                    "expected_refusal_type": case.get("refusal_type"),
                    "actual_refusal_type": row["actual_refusal_type"],
                })
            if step_events_path is not None:
                if case_serialization_failed:
                    reason = "case_serialization_failed"
                    event_skipped[reason] = event_skipped.get(reason, 0) + 1
                else:
                    scenario = case.get("scenario")
                    if scenario is None:
                        reason = "scenario_unavailable"
                        event_skipped[reason] = event_skipped.get(reason, 0) + 1
                    else:
                        try:
                            event_result = append_step_events(
                                step_events_path,
                                tool_trace=row["tool_trace"],
                                usage=row["usage"],
                                run_id=run_id,
                                question_id=case["id"],
                                scenario=scenario,
                                execution_mode=resolved_execution_mode,
                                actual_outcome=row["actual_outcome"],
                                actual_refusal_type=row["actual_refusal_type"],
                            )
                            event_written += event_result.written
                            if event_result.skipped_reason is not None:
                                reason = event_result.skipped_reason
                                event_skipped[reason] = event_skipped.get(reason, 0) + 1
                        except (OSError, TypeError, ValueError):
                            # Do not mislabel the model/tool run as a runtime failure;
                            # report event persistence failure separately and return
                            # a non-success summary to the CLI.
                            event_errors += 1
            if decision_events_path is not None:
                if case_serialization_failed:
                    reason = "case_serialization_failed"
                    decision_event_skipped[reason] = decision_event_skipped.get(reason, 0) + 1
                elif row["status"] != "completed":
                    reason = "runtime_not_completed"
                    decision_event_skipped[reason] = decision_event_skipped.get(reason, 0) + 1
                else:
                    try:
                        reason = append_decision_event(
                            decision_events_path,
                            run_id=run_id,
                            question_id=case["id"],
                            execution_mode=resolved_execution_mode,
                            actual_outcome=row["actual_outcome"],
                            actual_refusal_type=row["actual_refusal_type"],
                            policy_rule_id=row["policy_rule_id"],
                            decision_source=row["decision_source"],
                            tool_trace=row["tool_trace"],
                        )
                        if reason is None:
                            decision_event_written += 1
                        else:
                            decision_event_skipped[reason] = decision_event_skipped.get(reason, 0) + 1
                    except (OSError, TypeError, ValueError):
                        decision_event_errors += 1
    refusal_summary = refusal_rate(refusal_rows)
    summary = {"completed": completed, "failed": failed, "unscorable": unscorable,
               "refusal_summary": refusal_summary}
    if judge_request is not None:
        summary["judge"] = {"judged": judged, "skipped": judge_skipped, "errored": judge_errored}
    if step_events_path is not None:
        summary["step_event_log"] = {
            "written": event_written,
            "skipped": event_skipped,
            "errors": event_errors,
        }
    if decision_events_path is not None:
        summary["decision_event_log"] = {
            "written": decision_event_written,
            "skipped": decision_event_skipped,
            "errors": decision_event_errors,
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-timeout", type=float, default=180.0,
                        help="Maximum seconds for each adapter call (default: 180)")
    parser.add_argument("--dry-run", action="store_true", help="Validate testset only; never imports or calls an agent")
    parser.add_argument("--agent-adapter", help="Explicit module:function adapter implementing the documented contract")
    parser.add_argument("--step-events-output", type=Path,
                        help="Append captured, redacted tool events to this JSONL file")
    parser.add_argument("--decision-events-output", type=Path,
                        help="Append structured runtime decisions to a separate JSONL file")
    parser.add_argument("--execution-mode", choices=("real", "mock", "unit_test", "synthetic"),
                        help="Optional consistency check against the selected adapter's registered provenance")
    parser.add_argument("--judge", action="store_true",
                        help="Also run the LLM judge (prompts/judge.txt) on each unredacted case. "
                             "Judge columns are additive and never replace the deterministic metrics.")
    parser.add_argument("--judge-interval-seconds", type=float, default=2.0,
                        help="Pause between judge requests (default: 2)")
    args = parser.parse_args()
    has_event_output = args.step_events_output is not None or args.decision_events_output is not None
    if args.dry_run and (has_event_output or args.execution_mode is not None):
        parser.error("--dry-run cannot emit events")
    if args.dry_run and args.judge:
        parser.error("--dry-run cannot call the judge")
    if not has_event_output and args.execution_mode is not None:
        parser.error("--execution-mode requires event output")
    try:
        cases = load_testset(args.testset)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(f"VALIDATE ONLY: testset hop le ({len(cases)} cases). Buoc nay khong goi agent/API va khong sinh diem — diem duoc tai lap o buoc 2-3.")
        return 0
    if not args.agent_adapter:
        parser.error("Real evaluation is unavailable: supply --agent-adapter module:function after A/B stabilize the runtime result interface. No dummy answers are used.")
    try:
        require_isolated_database()
    except ValueError as exc:
        parser.error(str(exc))
    try:
        adapter = _load_adapter(args.agent_adapter)
    except Exception as exc:
        parser.error(f"Cannot load agent adapter: {exc}")
    judge_request = None
    judge_template = None
    if args.judge:
        from trfc.agent.llm import call_llm as _judge_call_llm
        from eval.llm_judge import JUDGE_MAX_TOKENS as _judge_max_tokens

        def judge_request(messages):
            return _judge_call_llm(messages, max_tokens=_judge_max_tokens)

        judge_template = load_judge_prompt()
    try:
        summary = asyncio.run(evaluate(
            cases, adapter, args.output, args.case_timeout,
            step_events_path=args.step_events_output,
            decision_events_path=args.decision_events_output,
            execution_mode=args.execution_mode,
            judge_request=judge_request,
            judge_prompt_template=judge_template,
        ))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    event_errors = (
        summary.get("step_event_log", {}).get("errors", 0)
        + summary.get("decision_event_log", {}).get("errors", 0)
    )
    return 1 if summary["failed"] or event_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
