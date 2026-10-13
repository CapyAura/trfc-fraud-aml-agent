"""Create per-question CSV and dependency-free SVG charts from real eval JSONL."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

CSV_COLUMNS = [
    "question_id", "category", "expected_outcome", "actual_outcome",
    "answer_correctness", "faithfulness", "context_precision",
    "refusal_correctness", "refusal_subtype_correctness", "calls",
    "prompt_tokens", "completion_tokens", "max_prompt", "status", "error",
]


def load_results(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"Blank line in evaluation JSONL at {path}:{line_no}")
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON at {path}:{line_no}: {exc.msg}") from exc
        if not isinstance(row, dict):
            raise ValueError(f"Expected an object at {path}:{line_no}")
        rows.append(row)
    return rows


def _refusal_fields(row: dict[str, Any]) -> tuple[bool | None, bool | None]:
    allowed, actual = row.get("allowed_to_answer"), row.get("actual_outcome")
    if not isinstance(allowed, bool) or not isinstance(actual, str) or actual not in {"answer", "refusal"}:
        return None, None
    correct = actual == ("answer" if allowed else "refusal")
    if allowed:
        return correct, None
    if actual != "refusal":
        return correct, None
    expected_type = row.get("expected_refusal_type")
    actual_type = row.get("actual_refusal_type")
    return correct, (actual_type == expected_type) if (
        isinstance(actual_type, str) and actual_type in {"i", "ii"}
        and isinstance(expected_type, str) and expected_type in {"i", "ii"}
    ) else None


def csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flattened = []
    for row in rows:
        metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
        usage = row.get("usage") if isinstance(row.get("usage"), dict) else {}
        refusal_correct, subtype_correct = _refusal_fields(row)

        def metric_cell(name: str, kind: str) -> Any:
            if name not in metrics:
                return "Unscorable" if row.get("status") in {"failed", "unscorable"} else "Missing"
            value = metrics[name]
            if value is None:
                return "Unscorable"
            if kind == "boolean":
                return value if isinstance(value, bool) else "Unscorable"
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or not 0 <= value <= 1):
                return "Unscorable"
            return value

        flattened.append({
            "question_id": row.get("question_id"), "category": row.get("category"),
            "expected_outcome": row.get("expected_outcome"), "actual_outcome": row.get("actual_outcome"),
            "answer_correctness": metric_cell("answer_correctness", "boolean"),
            "faithfulness": metric_cell("faithfulness", "fraction"),
            "context_precision": metric_cell("context_precision", "fraction"),
            "refusal_correctness": refusal_correct if refusal_correct is not None else "Unscorable",
            "refusal_subtype_correctness": (
                subtype_correct if subtype_correct is not None else
                ("N/A" if row.get("allowed_to_answer") is True else "Unscorable")
            ),
            "calls": usage.get("calls"), "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"), "max_prompt": usage.get("max_prompt"),
            "status": row.get("status", "unscorable"), "error": row.get("error"),
        })
    return flattened


def write_csv(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(csv_rows(rows))


def _bar_chart(title: str, metric: str, values: list[tuple[str, Any]], path: Path) -> None:
    width, height, left, top, plot_w, plot_h = 760, 420, 190, 80, 510, 270
    scored = [(label, value) for label, value in values
              if not isinstance(value, bool) and isinstance(value, (int, float))
              and math.isfinite(value) and 0 <= value <= 1]
    missing = sum(value == "Missing" for _, value in values)
    unscorable = sum(value == "Unscorable" for _, value in values)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
             '<rect width="100%" height="100%" fill="white"/>',
             f'<text x="{width/2}" y="35" text-anchor="middle" font-family="sans-serif" font-size="20">{escape(title)}</text>',
             f'<line x1="{left}" y1="{top+plot_h}" x2="{left+plot_w}" y2="{top+plot_h}" stroke="#333"/>',
             f'<line x1="{left}" y1="{top}" x2="{left}" y2="{top+plot_h}" stroke="#333"/>']
    for tick in range(0, 101, 20):
        y = top + plot_h - plot_h * tick / 100
        parts += [f'<line x1="{left-5}" y1="{y:.1f}" x2="{left+plot_w}" y2="{y:.1f}" stroke="#ddd"/>',
                  f'<text x="{left-12}" y="{y+4:.1f}" text-anchor="end" font-family="sans-serif" font-size="12">{tick}%</text>']
    parts.append(f'<text transform="translate(25 {top+plot_h/2}) rotate(-90)" text-anchor="middle" font-family="sans-serif" font-size="14">{escape(metric)} (%)</text>')
    if not scored:
        message = "No evaluation data" if not values else "No metric scores available"
        parts.append(f'<text x="{left+plot_w/2}" y="{top+plot_h/2}" text-anchor="middle" font-family="sans-serif" font-size="16">{message}</text>')
        count_label = f"Scored: 0 · Missing: {missing} · Unscorable: {unscorable}"
        if values:
            slot = plot_w / len(values)
            for index, (label, value) in enumerate(values):
                x = left + index * slot + slot / 2
                state = value if value in {"Missing", "Unscorable", "N/A"} else "Unscorable"
                parts.append(f'<text x="{x:.1f}" y="{top+plot_h-6}" text-anchor="middle" font-family="sans-serif" font-size="10">{state}</text>')
                parts.append(f'<text x="{x:.1f}" y="{top+plot_h+20}" text-anchor="middle" font-family="sans-serif" font-size="10">{escape(str(label))}</text>')
    else:
        slot = plot_w / len(values)
        bar_w = min(34, slot * 0.65)
        for index, (label, value) in enumerate(values):
            x = left + index * slot + (slot - bar_w) / 2
            if (not isinstance(value, bool) and isinstance(value, (int, float))
                    and math.isfinite(value) and 0 <= value <= 1):
                h = plot_h * max(0, min(float(value), 1))
                y = top + plot_h - h
                parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="#3976a8"/>')
                parts.append(f'<text x="{x+bar_w/2:.1f}" y="{y-6:.1f}" text-anchor="middle" font-family="sans-serif" font-size="11">{value:.0%}</text>')
            else:
                state = value if value in {"Missing", "Unscorable", "N/A"} else "Unscorable"
                parts.append(f'<text x="{x+bar_w/2:.1f}" y="{top+plot_h-6}" text-anchor="middle" font-family="sans-serif" font-size="10">{state}</text>')
            parts.append(f'<text x="{x+bar_w/2:.1f}" y="{top+plot_h+20}" text-anchor="middle" font-family="sans-serif" font-size="10">{escape(str(label))}</text>')
        count_label = f"Scored: {len(scored)} · Missing: {missing} · Unscorable: {unscorable}"
    parts.append(f'<text x="{width/2}" y="390" text-anchor="middle" font-family="sans-serif" font-size="13">{count_label}</text>')
    parts.append(f'<text x="{left+plot_w/2}" y="412" text-anchor="middle" font-family="sans-serif" font-size="13">Question ID</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def generate_report(input_path: Path, output_dir: Path) -> tuple[Path, Path, Path]:
    rows = load_results(input_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "evaluation.csv"
    faith_path = output_dir / "faithfulness.svg"
    refusal_path = output_dir / "refusal_correctness.svg"
    write_csv(rows, csv_path)
    flat = csv_rows(rows)
    _bar_chart("Faithfulness by question", "Faithfulness", [(r["question_id"] or "?", r["faithfulness"]) for r in flat], faith_path)
    _bar_chart("Refusal decision correctness by question", "Refusal correctness", [(r["question_id"] or "?", r["refusal_correctness"]) for r in flat], refusal_path)
    return csv_path, faith_path, refusal_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path(__file__).resolve().parents[1] / "logs" / "evaluation.jsonl")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "reports")
    args = parser.parse_args()
    if not args.input.exists():
        parser.error(f"No evaluation data at {args.input}; run a real evaluation first. No scores were generated.")
    try:
        outputs = generate_report(args.input, args.output_dir)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
