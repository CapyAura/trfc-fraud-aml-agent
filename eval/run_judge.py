"""Apply the LLM judge to an evaluation run and write judge columns.

The judge is a second, independent measurement. It never overwrites the
deterministic metrics; it adds ``judge_*`` columns beside them so the two can be
compared and a disagreement can be explained.

It also never runs on redacted text. ``eval/llm_judge.py`` refuses any row whose
answer or context still contains ``[REDACTED]``, because asking a model whether
an amount appears in a passage that no longer contains it produces a confident
wrong answer.

Usage::

    python -m eval.run_judge --input <run>/evaluation.jsonl \
        --output <run>/judge.jsonl

The output is a separate file. The evaluation JSONL is evidence and is never
rewritten.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .llm_judge import (
    JUDGE_MAX_TOKENS,
    JudgeResult,
    agreement,
    evaluate_judge,
    judge_eligibility,
    judge_model_identifier,
    load_judge_prompt,
)

ROOT = Path(__file__).resolve().parent.parent


def _default_model_request(messages: list[dict[str, Any]]):
    """Judge request with a budget large enough to finish the JSON object.

    The agent default is 650 completion tokens, which truncates a judge
    response mid-object and makes it unparseable. This is a separate,
    explicit budget rather than a change to agent behaviour.
    """
    from trfc.agent.llm import call_llm

    return call_llm(messages, max_tokens=JUDGE_MAX_TOKENS)


async def judge_run(
    input_path: Path,
    output_path: Path,
    *,
    request_model=_default_model_request,
    prompt_template: str | None = None,
    case_interval_seconds: float = 0.0,
) -> dict[str, Any]:
    """Judge every eligible row and write one JSON object per case."""
    rows = []
    for line_no, line in enumerate(input_path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Blank line in {input_path}:{line_no}")
        rows.append(json.loads(line))

    template = prompt_template if prompt_template is not None else load_judge_prompt()
    results: list[dict[str, Any]] = []
    judged = skipped = errored = 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as stream:
        for index, row in enumerate(rows):
            reason = judge_eligibility(row)
            if reason is not None:
                skipped += 1
                result = JudgeResult(error=reason)
            else:
                if index and case_interval_seconds:
                    await asyncio.sleep(case_interval_seconds)
                result = await asyncio.to_thread(
                    evaluate_judge, row, request_model, prompt_template=template
                )
                if result.error is not None:
                    errored += 1
                else:
                    judged += 1

            metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
            deterministic = metrics.get("faithfulness")
            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "question_id": row.get("question_id"),
                "category": row.get("category"),
                "judge_model": judge_model_identifier(),
                **result.as_row_fields(),
                "deterministic_faithfulness": deterministic,
                "faithfulness_agreement": agreement(
                    deterministic if isinstance(deterministic, (int, float)) else None,
                    result.faithfulness,
                ),
            }
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            results.append(record)

    return {
        "input": str(input_path),
        "output": str(output_path),
        "total": len(rows),
        "judged": judged,
        "skipped": skipped,
        "errored": errored,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="Evaluation JSONL from a real run (never modified)")
    parser.add_argument("--output", type=Path, required=True,
                        help="Where to write judge records (separate file)")
    parser.add_argument("--case-interval-seconds", type=float, default=2.0,
                        help="Pause between judge requests (default: 2)")
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"No evaluation data at {args.input}")
    if args.input.resolve() == args.output.resolve():
        parser.error("Refusing to overwrite the evaluation JSONL; choose a separate --output")
    try:
        summary = asyncio.run(judge_run(
            args.input, args.output,
            case_interval_seconds=args.case_interval_seconds,
        ))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))

    counts = {key: summary[key] for key in ("total", "judged", "skipped", "errored")}
    print(json.dumps(counts, indent=2))
    return 0 if summary["errored"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
