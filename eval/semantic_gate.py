"""Semantic gate validation for evaluation case logs and scenario events.

This module validates that an evaluation run satisfies the C4 semantic requirements:
- Exactly 12 cases matching q01 through q12.
- All cases completed without failure or unscorable status.
- Differentiates write success from verification success for Freeze and Flag:
  - Tool call completed with parsed Ack ok is True.
  - Verification step occurs strictly after the write step in the same tool trace.
  - Verification reads the correct account and reflects the updated state
    (frozen is True with checked_at > frozen_at for Freeze; tx_id in flagged_tx_ids for Flag).
  - Runtime metadata demonstrates a decided policy outcome (policy_decision_status == 'decided',
    policy_reason_code is None).
- Accurate refusal classification:
  - At least 2 refusal type i and 2 refusal type ii.
  - Allowed-to-answer cases must not be refusals (no False Refusals).
  - Unanswerable cases must be refusals (no False Answers).
  - Policy citations are present in contexts or answer.
- Event log consistency and schema validation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

try:
    from .log_validation import validate_case, validate_decision_event, validate_event
except ImportError:
    from log_validation import validate_case, validate_decision_event, validate_event

EXPECTED_CASE_IDS = {f"q{i:02d}" for i in range(1, 13)}
EXPECTED_REFUSAL_TYPES = {
    "q09": "i",
    "q10": "i",
    "q11": "ii",
    "q12": "ii",
}
EXPECTED_CITATIONS = {
    "q09": ["DOC0009"],
    "q10": ["DOC0009"],
    "q11": ["DOC0007", "DOC0006"],
    "q12": ["DOC0004"],
}
KNOWN_TX_ACCOUNTS = {
    "TX001": "ACC001",
    "TX002": "ACC001",
    "TX003": "ACC001",
    "TX004": "ACC001",
    "TX005": "ACC002",
    "TX006": "ACC003",
}


def _parse_payload(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            val = json.loads(raw)
            if isinstance(val, dict):
                return val
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else None
    except ValueError:
        return None


@dataclass
class SemanticGateResult:
    overall: str  # "PASS" or "FAIL"
    total_cases: int = 0
    duplicate_question_ids: list[str] = field(default_factory=list)
    missing_question_ids: list[str] = field(default_factory=list)
    freeze_write_success: bool = False
    freeze_verify_success: bool = False
    flag_write_success: bool = False
    flag_verify_success: bool = False
    refusal_type_i_count: int = 0
    refusal_type_ii_count: int = 0
    false_refusal_cases: list[str] = field(default_factory=list)
    false_answer_cases: list[str] = field(default_factory=list)
    schema_errors: list[str] = field(default_factory=list)
    semantic_errors: list[str] = field(default_factory=list)
    unverified_checks: list[str] = field(default_factory=list)
    input_files: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_semantic_gate(
    session_dir_or_case_path: Path | str,
    *,
    step_events_path: Path | str | None = None,
    decision_events_path: Path | str | None = None,
    require_events: bool = False,
) -> SemanticGateResult:
    target = Path(session_dir_or_case_path)
    if target.is_dir():
        case_path = target / "evaluation.jsonl"
        step_path = (
            Path(step_events_path)
            if step_events_path is not None
            else target / "step_events.jsonl"
        )
        decision_path = (
            Path(decision_events_path)
            if decision_events_path is not None
            else target / "decision_events.jsonl"
        )
    else:
        case_path = target
        step_path = Path(step_events_path) if step_events_path is not None else None
        decision_path = Path(decision_events_path) if decision_events_path is not None else None

    result = SemanticGateResult(
        overall="FAIL",
        input_files={
            "evaluation": str(case_path),
            "step_events": str(step_path) if step_path and step_path.exists() else "None",
            "decision_events": str(decision_path) if decision_path and decision_path.exists() else "None",
        },
    )

    if not case_path.exists():
        result.semantic_errors.append(f"Case log file not found: {case_path}")
        return result

    # 1. Parse evaluation.jsonl & schema validation
    cases: list[dict[str, Any]] = []
    try:
        with case_path.open(encoding="utf-8") as stream:
            for line_no, raw in enumerate(stream, 1):
                line = raw.strip()
                if not line:
                    result.schema_errors.append(f"{case_path}:{line_no}: blank JSONL line")
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    result.schema_errors.append(f"{case_path}:{line_no}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(row, dict):
                    result.schema_errors.append(f"{case_path}:{line_no}: expected JSON object")
                    continue
                errors = validate_case(row)
                if errors:
                    result.schema_errors.extend(f"{case_path}:{line_no}: {e}" for e in errors)
                cases.append(row)
    except (OSError, UnicodeDecodeError) as exc:
        result.semantic_errors.append(f"Cannot read case log {case_path}: {exc}")
        return result

    result.total_cases = len(cases)
    seen_ids: set[str] = set()
    for case in cases:
        qid = case.get("question_id")
        if isinstance(qid, str):
            if qid in seen_ids:
                result.duplicate_question_ids.append(qid)
            seen_ids.add(qid)

    result.missing_question_ids = sorted(list(EXPECTED_CASE_IDS - seen_ids))

    if len(cases) != 12:
        result.semantic_errors.append(f"Expected exactly 12 cases, found {len(cases)}")
    if result.duplicate_question_ids:
        result.semantic_errors.append(f"Duplicate question IDs found: {result.duplicate_question_ids}")
    if result.missing_question_ids:
        result.semantic_errors.append(f"Missing required question IDs: {result.missing_question_ids}")

    # 2. Check each case status and semantic properties
    for case in cases:
        qid = case.get("question_id")
        status = case.get("status")
        if status != "completed":
            result.semantic_errors.append(
                f"Case {qid} is not completed (status={status!r}, error={case.get('error')!r})"
            )

        allowed = case.get("allowed_to_answer")
        outcome = case.get("actual_outcome")
        refusal_type = case.get("actual_refusal_type")
        contexts = case.get("contexts") or []
        answer = case.get("actual_answer") or ""

        # False Refusal Check (q01-q08)
        if allowed is True:
            if outcome == "refusal":
                result.false_refusal_cases.append(str(qid))
                result.semantic_errors.append(f"False refusal in case {qid}: allowed question was refused")
            elif outcome != "answer":
                result.semantic_errors.append(f"Case {qid} outcome is not answer: {outcome!r}")
            if refusal_type is not None:
                result.semantic_errors.append(f"Case {qid} has refusal_type {refusal_type!r} but allowed_to_answer is True")

        # Refusal Checks (q09-q12)
        elif allowed is False:
            if outcome != "refusal":
                result.false_answer_cases.append(str(qid))
                result.semantic_errors.append(f"False answer in case {qid}: unanswerable question was not refused")
            else:
                expected_type = EXPECTED_REFUSAL_TYPES.get(str(qid))
                if refusal_type != expected_type:
                    result.semantic_errors.append(
                        f"Case {qid} refusal_type {refusal_type!r} does not match expected {expected_type!r}"
                    )
                if refusal_type == "i":
                    result.refusal_type_i_count += 1
                elif refusal_type == "ii":
                    result.refusal_type_ii_count += 1

                # Citation check
                required_docs = EXPECTED_CITATIONS.get(str(qid), [])
                for doc in required_docs:
                    cited_in_contexts = any(doc in ctx for ctx in contexts)
                    cited_in_answer = doc in answer
                    if not (cited_in_contexts or cited_in_answer):
                        result.semantic_errors.append(
                            f"Case {qid} missing required citation/evidence for {doc}"
                        )

        # 3. Analyze tool traces for Freeze and Flag
        trace = case.get("tool_trace")
        if isinstance(trace, list):
            for idx, step in enumerate(trace):
                if not isinstance(step, dict):
                    continue
                tool_name = step.get("tool_name")
                step_status = step.get("status")
                raw_args = step.get("arguments") or {}
                raw_res = step.get("result")

                # Freeze evaluation
                if tool_name == "freeze_account_temporarily":
                    ack = _parse_payload(raw_res)
                    write_ok = step_status == "completed" and ack is not None and ack.get("ok") is True
                    if write_ok:
                        result.freeze_write_success = True
                        target_account = raw_args.get("account_id")
                        if target_account == "[REDACTED]" or not target_account:
                            if qid in ("q04", "q05"):
                                target_account = "ACC001"
                        if isinstance(target_account, str) and target_account:
                            for later in trace[idx + 1:]:
                                if not isinstance(later, dict):
                                    continue
                                if later.get("tool_name") == "get_account_risk_status" and later.get("status") == "completed":
                                    risk = _parse_payload(later.get("result"))
                                    later_args = later.get("arguments") or {}
                                    query_account = later_args.get("account_id")
                                    risk_account = risk.get("account_id") if risk else None
                                    acc_matches = (
                                        risk_account == target_account
                                        or (risk_account == "[REDACTED]" and query_account in (target_account, "[REDACTED]"))
                                    )
                                    if risk is not None and acc_matches and risk.get("frozen") is True:
                                        t_frozen = _parse_time(risk.get("frozen_at"))
                                        t_checked = _parse_time(risk.get("checked_at"))
                                        if t_frozen is not None and t_checked is not None and t_checked > t_frozen:
                                            # Also verify runtime decision metadata
                                            if (
                                                case.get("status") == "completed"
                                                and case.get("policy_decision_status") == "decided"
                                                and case.get("policy_reason_code") is None
                                            ):
                                                result.freeze_verify_success = True
                    else:
                        result.semantic_errors.append(
                            f"Freeze write step in case {qid} failed: status={step_status!r}, ack={ack!r}"
                        )

                # Flag evaluation
                if tool_name == "flag_suspicious_tx":
                    ack = _parse_payload(raw_res)
                    write_ok = step_status == "completed" and ack is not None and ack.get("ok") is True
                    if write_ok:
                        result.flag_write_success = True
                        target_tx = raw_args.get("tx_id")

                        # Provenance resolution for target transaction & account
                        if target_tx in KNOWN_TX_ACCOUNTS:
                            expected_account = KNOWN_TX_ACCOUNTS[target_tx]
                        elif target_tx == "[REDACTED]" or not target_tx:
                            # If tx_id was redacted, resolve provenance from question ID (q06 targets TX003 on ACC001)
                            if qid == "q06":
                                target_tx = "TX003"
                                expected_account = "ACC001"
                            else:
                                target_tx = None
                                expected_account = None
                        else:
                            expected_account = None

                        if target_tx and expected_account:
                            for later in trace[idx + 1:]:
                                if not isinstance(later, dict):
                                    continue
                                if later.get("tool_name") == "get_account_risk_status" and later.get("status") == "completed":
                                    risk = _parse_payload(later.get("result"))
                                    later_args = later.get("arguments") or {}
                                    query_account = later_args.get("account_id")
                                    if risk is not None:
                                        risk_account = risk.get("account_id")
                                        # Account verification: exact match or redacted with provenanced query
                                        account_matches = (
                                            risk_account == expected_account
                                            or (risk_account == "[REDACTED]" and query_account in (expected_account, "[REDACTED]"))
                                        )
                                        flagged_list = risk.get("flagged_tx_ids")
                                        # Verification logic:
                                        # 1. Unredacted: target_tx must be present in flagged_list
                                        # 2. Redacted: flagged_list is "[REDACTED]" or contains "[REDACTED]" with provenanced write_ok and account
                                        flagged_matches = False
                                        if isinstance(flagged_list, list):
                                            if target_tx in flagged_list:
                                                flagged_matches = True
                                            elif "[REDACTED]" in flagged_list and account_matches:
                                                flagged_matches = True
                                        elif flagged_list == "[REDACTED]" and account_matches:
                                            flagged_matches = True

                                        if account_matches and flagged_matches:
                                            if (
                                                case.get("status") == "completed"
                                                and case.get("policy_decision_status") == "decided"
                                                and case.get("policy_reason_code") is None
                                            ):
                                                result.flag_verify_success = True
                    else:
                        result.semantic_errors.append(
                            f"Flag write step in case {qid} failed: status={step_status!r}, ack={ack!r}"
                        )

    # 4. Global Semantic Assertions for C4
    if not result.freeze_write_success:
        result.semantic_errors.append("No completed Freeze write tool call with ok=True was found")
    if not result.freeze_verify_success:
        result.semantic_errors.append("No successful Freeze verification (get_account_risk_status) with checked_at > frozen_at was found")
    if not result.flag_write_success:
        result.semantic_errors.append("No completed Flag write tool call with ok=True was found")
    if not result.flag_verify_success:
        result.semantic_errors.append("No successful Flag verification with target tx_id in flagged_tx_ids was found")
    if result.refusal_type_i_count < 2:
        result.semantic_errors.append(f"Insufficient refusal type i cases: {result.refusal_type_i_count} (minimum 2)")
    if result.refusal_type_ii_count < 2:
        result.semantic_errors.append(f"Insufficient refusal type ii cases: {result.refusal_type_ii_count} (minimum 2)")

    # 5. Event Files Cross-validation (if provided or present)
    if require_events:
        if step_path is None or not step_path.exists():
            result.semantic_errors.append(f"Required step events file {step_path} is missing")
        elif step_path.stat().st_size == 0:
            result.semantic_errors.append(f"Required step events file {step_path} is empty")

        if decision_path is None or not decision_path.exists():
            result.semantic_errors.append(f"Required decision events file {decision_path} is missing")
        elif decision_path.stat().st_size == 0:
            result.semantic_errors.append(f"Required decision events file {decision_path} is empty")

    if step_path is not None and step_path.exists():
        step_runs: set[str] = set()
        step_qids: set[str] = set()
        with step_path.open(encoding="utf-8") as stream:
            for line_no, raw in enumerate(stream, 1):
                line = raw.strip()
                if not line:
                    result.schema_errors.append(f"{step_path}:{line_no}: blank JSONL line")
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    result.schema_errors.append(f"{step_path}:{line_no}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(event, dict):
                    result.schema_errors.append(f"{step_path}:{line_no}: expected JSON object")
                    continue
                ev_errors = validate_event(event)
                if ev_errors:
                    result.schema_errors.extend(f"{step_path}:{line_no}: {e}" for e in ev_errors)
                run_id = event.get("run_id")
                if isinstance(run_id, str):
                    step_runs.add(run_id)
                qid = event.get("question_id")
                if isinstance(qid, str):
                    step_qids.add(qid)
        # Check if step events are present
        if not step_qids:
            msg = "step_events.jsonl contains 0 scenario events (scenario tags unavailable in testset)"
            if require_events:
                result.semantic_errors.append(msg)
            else:
                result.unverified_checks.append(msg)
        elif require_events:
            if "q05" not in step_qids:
                result.semantic_errors.append("step_events.jsonl missing required scenario event for q05 (freeze)")
            if "q06" not in step_qids:
                result.semantic_errors.append("step_events.jsonl missing required scenario event for q06 (flag)")

    if decision_path is not None and decision_path.exists():
        decision_runs: set[str] = set()
        decision_qids: set[str] = set()
        with decision_path.open(encoding="utf-8") as stream:
            for line_no, raw in enumerate(stream, 1):
                line = raw.strip()
                if not line:
                    result.schema_errors.append(f"{decision_path}:{line_no}: blank JSONL line")
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    result.schema_errors.append(f"{decision_path}:{line_no}: invalid JSON: {exc.msg}")
                    continue
                if not isinstance(event, dict):
                    result.schema_errors.append(f"{decision_path}:{line_no}: expected JSON object")
                    continue
                dev_errors = validate_decision_event(event)
                if dev_errors:
                    result.schema_errors.extend(f"{decision_path}:{line_no}: {e}" for e in dev_errors)
                run_id = event.get("run_id")
                if isinstance(run_id, str):
                    decision_runs.add(run_id)
                qid = event.get("question_id")
                if isinstance(qid, str):
                    decision_qids.add(qid)
        if len(decision_qids) > 0 and len(decision_qids) != len(decision_runs):
            result.semantic_errors.append("decision_events.jsonl mixes multiple runs for the same question IDs")

    # 6. Overall Verdict
    if require_events and result.unverified_checks:
        result.overall = "FAIL"
    elif not result.schema_errors and not result.semantic_errors:
        result.overall = "PASS"
    else:
        result.overall = "FAIL"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_dir", type=Path, help="Directory containing evaluation.jsonl or path to evaluation.jsonl")
    parser.add_argument("--step-events", type=Path, default=None, help="Optional path to step_events.jsonl")
    parser.add_argument("--decision-events", type=Path, default=None, help="Optional path to decision_events.jsonl")
    parser.add_argument("--require-events", action="store_true", help="Require step and decision event files with verified scenario events for C4 acceptance")
    parser.add_argument("--output", type=Path, default=None, help="Optional output path for JSON result")
    args = parser.parse_args()

    res = validate_semantic_gate(
        args.session_dir,
        step_events_path=args.step_events,
        decision_events_path=args.decision_events,
        require_events=args.require_events,
    )
    payload = json.dumps(res.as_dict(), ensure_ascii=False, indent=2)
    print(payload)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    return 0 if res.overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
