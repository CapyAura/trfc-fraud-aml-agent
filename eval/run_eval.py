"""Validate the testset or evaluate through an explicitly supplied adapter.

Adapter contract: ``module:function``; callable accepts one test-case dict and
returns a dict with `answer`, optional `actual_outcome`, `actual_refusal_type`,
`contexts` (list[str]), `claims` (list[str]), `tool_trace`, and `usage`. Async
callables are supported. No built-in adapter is provided until A/B stabilize
the runtime result contract.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # package execution: python -m eval.run_eval
    from .metrics import answer_correctness, context_precision, faithfulness, refusal_rate
except ImportError:  # direct script execution
    from metrics import answer_correctness, context_precision, faithfulness, refusal_rate

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTSET = ROOT / "tests" / "testset.jsonl"
DEFAULT_OUTPUT = ROOT / "logs" / "evaluation.jsonl"
EXPECTED_DISTRIBUTION = {
    "retrieval": 3, "calc": 2, "contradiction": 2,
    "multi_doc": 1, "no_answer": 4,
}


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
        if case["category"] not in {*EXPECTED_DISTRIBUTION}:
            raise ValueError(f"Case {case['id']} has an unsupported category")
        if not isinstance(case["allowed_to_answer"], bool):
            raise ValueError(f"Case {case['id']} allowed_to_answer must be boolean")
        if case["expected_outcome"] not in {"answer", "refusal"}:
            raise ValueError(f"Case {case['id']} has invalid expected_outcome")
        if case["allowed_to_answer"] != (case["expected_outcome"] == "answer"):
            raise ValueError(f"Case {case['id']} allowed_to_answer conflicts with expected_outcome")
        if not isinstance(case["expected"], dict):
            raise ValueError(f"Case {case['id']} expected must be an object")
        if not isinstance(case["source_refs"], list) or not all(
            isinstance(ref, str) for ref in case["source_refs"]
        ):
            raise ValueError(f"Case {case['id']} source_refs must be a list of strings")
        if case["category"] == "no_answer":
            if case["allowed_to_answer"] or case.get("refusal_type") not in {"i", "ii"}:
                raise ValueError(f"Case {case['id']} needs refusal outcome and type i or ii")
        elif case.get("refusal_type") is not None:
            raise ValueError(f"Answerable case {case['id']} must not declare refusal_type")
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
    if not all(key in value and type(value[key]) is int and value[key] >= 0 for key in keys):
        return None
    return {key: value[key] for key in keys}


async def evaluate(cases: list[dict[str, Any]], adapter, output_path: Path,
                   case_timeout: float = 180.0) -> dict[str, Any]:
    if case_timeout <= 0:
        raise ValueError("case_timeout must be positive")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    completed = failed = unscorable = 0
    refusal_rows = []
    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        for case in cases:
            row: dict[str, Any] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "question_id": case["id"], "category": case["category"],
                "expected_outcome": case["expected_outcome"],
                "allowed_to_answer": case["allowed_to_answer"],
                "expected_refusal_type": case.get("refusal_type"),
                "expected": case["expected"], "source_refs": case["source_refs"],
                "actual_answer": None, "actual_outcome": None,
                "actual_refusal_type": None, "contexts": None, "claims": None,
                "tool_trace": None, "usage": None, "metrics": {},
                "error": None, "status": "failed",
            }
            try:
                result = await asyncio.wait_for(_invoke(adapter, case), timeout=case_timeout)
                if not isinstance(result, dict):
                    raise TypeError("Adapter must return a dict")
                row["actual_answer"] = result.get("answer")
                row["actual_outcome"] = result.get("actual_outcome")
                row["actual_refusal_type"] = result.get("actual_refusal_type")
                row["contexts"] = result.get("contexts")
                row["claims"] = result.get("claims")
                row["tool_trace"] = result.get("tool_trace")
                row["usage"] = _usage_or_none(result.get("usage"))
                if row["actual_outcome"] is None:
                    row["actual_outcome"] = "refusal" if result.get("refused") is True else (
                        "answer" if row["actual_answer"] else None)
                if row["actual_outcome"] not in {"answer", "refusal"}:
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
                    "refusal_correctness": row["actual_outcome"] == case["expected_outcome"],
                    "refusal_subtype_correctness": (
                        row["actual_refusal_type"] == case.get("refusal_type")
                        if case.get("refusal_type") in {"i", "ii"}
                        and row["actual_refusal_type"] in {"i", "ii"}
                        and row["actual_outcome"] == "refusal"
                        else None
                    ),
                }
                refusal_rows.append({
                    "allowed_to_answer": case["allowed_to_answer"],
                    "actual_outcome": row["actual_outcome"],
                    "expected_refusal_type": case.get("refusal_type"),
                    "actual_refusal_type": row["actual_refusal_type"],
                })
            except Exception as exc:  # continue so a single case cannot abort the set
                row["error"] = f"{type(exc).__name__}: {exc}"
                failed += 1
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    refusal_summary = refusal_rate(refusal_rows)
    return {"completed": completed, "failed": failed, "unscorable": unscorable,
            "refusal_summary": refusal_summary}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--case-timeout", type=float, default=180.0,
                        help="Maximum seconds for each adapter call (default: 180)")
    parser.add_argument("--dry-run", action="store_true", help="Validate testset only; never imports or calls an agent")
    parser.add_argument("--agent-adapter", help="Explicit module:function adapter implementing the documented contract")
    args = parser.parse_args()
    try:
        cases = load_testset(args.testset)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.dry_run:
        print(f"DRY RUN: valid testset ({len(cases)} cases); no agent/API called and no evaluation scores produced.")
        return 0
    if not args.agent_adapter:
        parser.error("Real evaluation is unavailable: supply --agent-adapter module:function after A/B stabilize the runtime result interface. No dummy answers are used.")
    try:
        adapter = _load_adapter(args.agent_adapter)
    except Exception as exc:
        parser.error(f"Cannot load agent adapter: {exc}")
    try:
        summary = asyncio.run(evaluate(cases, adapter, args.output, args.case_timeout))
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
