"""Comprehensive offline unit tests for eval.semantic_gate covering all 20 required checks.

These tests use in-memory synthetic fixtures written to a temporary directory.
No external network, no LLMs, and no database operations are performed.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import pytest

from eval.semantic_gate import validate_semantic_gate, SemanticGateResult


def make_valid_cases() -> list[dict]:
    """Generate a fully valid synthetic 12-case evaluation record list."""
    base_cases = []
    # q01 - q03: retrieval
    for i in range(1, 4):
        base_cases.append({
            "timestamp": "2026-10-17T10:00:00+00:00",
            "question_id": f"q{i:02d}",
            "category": "retrieval",
            "expected_outcome": "answer",
            "allowed_to_answer": True,
            "expected_refusal_type": None,
            "expected": {"criteria_type": "contains_all", "values": ["v1"]},
            "source_refs": ["DOC0007"],
            "actual_answer": "Trả lời đầy đủ theo quy định DOC0007.",
            "actual_outcome": "answer",
            "actual_refusal_type": None,
            "contexts": ["[DOC0007] Nội dung điều khoản quy định..."],
            "claims": ["Claim 1"],
            "policy_rule_id": "DOC0007_D1",
            "decision_source": "runtime_policy_resolution",
            "policy_decision_status": "decided",
            "policy_reason_code": None,
            "tool_trace": [],
            "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
            "metrics": {},
            "error": None,
            "status": "completed",
        })

    # q04: calc with Freeze write and verify
    base_cases.append({
        "timestamp": "2026-10-17T10:01:00+00:00",
        "question_id": "q04",
        "category": "calc",
        "expected_outcome": "answer",
        "allowed_to_answer": True,
        "expected_refusal_type": None,
        "expected": {"criteria_type": "contains_all", "values": ["v1"]},
        "source_refs": ["DOC0007"],
        "actual_answer": "Tính toán vượt hạn mức và tạm khóa.",
        "actual_outcome": "answer",
        "actual_refusal_type": None,
        "contexts": ["[DOC0007] Hạn mức..."],
        "claims": ["Claim calc"],
        "policy_rule_id": "DOC0007_D4",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [
            {
                "step": 1,
                "tool_call_id": "call_1",
                "tool_name": "freeze_account_temporarily",
                "arguments": {"account_id": "ACC001", "reason": "Exceeded daily limit"},
                "result": json.dumps({"ok": True, "message": "Frozen successfully", "tx_id": None}),
                "status": "completed",
                "error": None,
            },
            {
                "step": 2,
                "tool_call_id": "call_2",
                "tool_name": "get_account_risk_status",
                "arguments": {"account_id": "ACC001"},
                "result": json.dumps({
                    "account_id": "ACC001",
                    "frozen": True,
                    "freeze_reason": "Exceeded daily limit",
                    "frozen_at": "2026-10-17T10:01:05+00:00",
                    "flagged_tx_ids": [],
                    "checked_at": "2026-10-17T10:01:10+00:00",
                }),
                "status": "completed",
                "error": None,
            },
        ],
        "usage": {"calls": 2, "prompt_tokens": 20, "completion_tokens": 20, "max_prompt": 20},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q05: calc
    base_cases.append({
        "timestamp": "2026-10-17T10:02:00+00:00",
        "question_id": "q05",
        "category": "calc",
        "expected_outcome": "answer",
        "allowed_to_answer": True,
        "expected_refusal_type": None,
        "expected": {"criteria_type": "contains_all", "values": ["44%"]},
        "source_refs": ["DOC0007"],
        "actual_answer": "Tỷ lệ vượt hạn mức 44%.",
        "actual_outcome": "answer",
        "actual_refusal_type": None,
        "contexts": ["[DOC0007] Hạn mức..."],
        "claims": ["Claim 44%"],
        "policy_rule_id": "DOC0007_D5",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [],
        "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q06: contradiction with Flag write and verify
    base_cases.append({
        "timestamp": "2026-10-17T10:03:00+00:00",
        "question_id": "q06",
        "category": "contradiction",
        "expected_outcome": "answer",
        "allowed_to_answer": True,
        "expected_refusal_type": None,
        "expected": {"criteria_type": "contains_all", "values": ["khớp"]},
        "source_refs": ["DOC0004"],
        "actual_answer": "Khớp quy tắc bất khả thi địa lý và đã gắn cờ TX003.",
        "actual_outcome": "answer",
        "actual_refusal_type": None,
        "contexts": ["[DOC0004] Bất khả thi địa lý..."],
        "claims": ["Claim geo"],
        "policy_rule_id": "DOC0004_D1",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [
            {
                "step": 1,
                "tool_call_id": "call_1",
                "tool_name": "flag_suspicious_tx",
                "arguments": {"tx_id": "TX003", "reason": "Geographic impossibility"},
                "result": json.dumps({"ok": True, "message": "Flagged", "tx_id": "TX003"}),
                "status": "completed",
                "error": None,
            },
            {
                "step": 2,
                "tool_call_id": "call_2",
                "tool_name": "get_account_risk_status",
                "arguments": {"account_id": "ACC001"},
                "result": json.dumps({
                    "account_id": "ACC001",
                    "frozen": False,
                    "freeze_reason": None,
                    "frozen_at": None,
                    "flagged_tx_ids": ["TX003"],
                    "checked_at": "2026-10-17T10:03:05+00:00",
                }),
                "status": "completed",
                "error": None,
            },
        ],
        "usage": {"calls": 2, "prompt_tokens": 20, "completion_tokens": 20, "max_prompt": 20},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q07: contradiction
    base_cases.append({
        "timestamp": "2026-10-17T10:04:00+00:00",
        "question_id": "q07",
        "category": "contradiction",
        "expected_outcome": "answer",
        "allowed_to_answer": True,
        "expected_refusal_type": None,
        "expected": {"criteria_type": "contains_all", "values": ["DOC0007"]},
        "source_refs": ["DOC0003", "DOC0007"],
        "actual_answer": "Áp dụng DOC0007 phiên bản 2026.1.",
        "actual_outcome": "answer",
        "actual_refusal_type": None,
        "contexts": ["[DOC0007] Ngày hiệu lực..."],
        "claims": ["Claim version"],
        "policy_rule_id": "DOC0007_D1",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [],
        "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q08: multi_doc
    base_cases.append({
        "timestamp": "2026-10-17T10:05:00+00:00",
        "question_id": "q08",
        "category": "multi_doc",
        "expected_outcome": "answer",
        "allowed_to_answer": True,
        "expected_refusal_type": None,
        "expected": {"criteria_type": "contains_all", "values": ["5 năm"]},
        "source_refs": ["DOC0006", "DOC0008"],
        "actual_answer": "Không được khóa và lưu trữ 5 năm theo DOC0006 và DOC0008.",
        "actual_outcome": "answer",
        "actual_refusal_type": None,
        "contexts": ["[DOC0006] Lưu trữ 5 năm...", "[DOC0008] Thẩm quyền kiểm soát viên..."],
        "claims": ["Claim multi"],
        "policy_rule_id": "DOC0006_D4",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [],
        "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q09: no_answer (refusal type i)
    base_cases.append({
        "timestamp": "2026-10-17T10:06:00+00:00",
        "question_id": "q09",
        "category": "no_answer",
        "expected_outcome": "refusal",
        "allowed_to_answer": False,
        "expected_refusal_type": "i",
        "expected": {"criteria_type": "refusal_reason", "values": ["ngoài phạm vi"]},
        "source_refs": ["DOC0009"],
        "actual_answer": "Từ chối trả lời: Ví điện tử bên thứ ba nằm ngoài phạm vi quy định tại DOC0009.",
        "actual_outcome": "refusal",
        "actual_refusal_type": "i",
        "contexts": ["[DOC0009] Điều 4 danh mục phương thức thanh toán hỗ trợ..."],
        "claims": [],
        "policy_rule_id": "DOC0009_D4",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [],
        "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q10: no_answer (refusal type i)
    base_cases.append({
        "timestamp": "2026-10-17T10:07:00+00:00",
        "question_id": "q10",
        "category": "no_answer",
        "expected_outcome": "refusal",
        "allowed_to_answer": False,
        "expected_refusal_type": "i",
        "expected": {"criteria_type": "refusal_reason", "values": ["ngoài phạm vi"]},
        "source_refs": ["DOC0009"],
        "actual_answer": "Từ chối trả lời: Tiền mã hóa không thuộc danh mục hỗ trợ của DOC0009.",
        "actual_outcome": "refusal",
        "actual_refusal_type": "i",
        "contexts": ["[DOC0009] Điều 1 phạm vi áp dụng..."],
        "claims": [],
        "policy_rule_id": "DOC0009_D1",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [],
        "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q11: no_answer (refusal type ii)
    base_cases.append({
        "timestamp": "2026-10-17T10:08:00+00:00",
        "question_id": "q11",
        "category": "no_answer",
        "expected_outcome": "refusal",
        "allowed_to_answer": False,
        "expected_refusal_type": "ii",
        "expected": {"criteria_type": "refusal_reason", "values": ["không đủ dữ liệu"]},
        "source_refs": ["DOC0007", "DOC0006"],
        "actual_answer": "Từ chối trả lời: Thiếu nhật ký giao dịch gốc theo DOC0007 và DOC0006.",
        "actual_outcome": "refusal",
        "actual_refusal_type": "ii",
        "contexts": ["[DOC0007] Điều 12 nhật ký...", "[DOC0006] Điều 7 lưu trữ..."],
        "claims": [],
        "policy_rule_id": "DOC0007_D12",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [],
        "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    # q12: no_answer (refusal type ii)
    base_cases.append({
        "timestamp": "2026-10-17T10:09:00+00:00",
        "question_id": "q12",
        "category": "no_answer",
        "expected_outcome": "refusal",
        "allowed_to_answer": False,
        "expected_refusal_type": "ii",
        "expected": {"criteria_type": "refusal_reason", "values": ["không đủ dữ liệu"]},
        "source_refs": ["DOC0004"],
        "actual_answer": "Từ chối trả lời: Thiếu thông tin quốc gia theo DOC0004.",
        "actual_outcome": "refusal",
        "actual_refusal_type": "ii",
        "contexts": ["[DOC0004] Điều 3 quy định thông tin quốc gia..."],
        "claims": [],
        "policy_rule_id": "DOC0004_D3",
        "decision_source": "runtime_policy_resolution",
        "policy_decision_status": "decided",
        "policy_reason_code": None,
        "tool_trace": [],
        "usage": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 10, "max_prompt": 10},
        "metrics": {},
        "error": None,
        "status": "completed",
    })

    return base_cases


def write_cases(path: Path, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for case in cases:
            stream.write(json.dumps(case, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------------------
# Test 1: Valid 12 cases pass all gates
# ------------------------------------------------------------------------------
def test_check_1_valid_cases_pass_all_gates(tmp_path: Path):
    cases = make_valid_cases()
    log_dir = tmp_path / "valid_session"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "PASS"
    assert res.total_cases == 12
    assert res.freeze_write_success is True
    assert res.freeze_verify_success is True
    assert res.flag_write_success is True
    assert res.flag_verify_success is True
    assert res.refusal_type_i_count == 2
    assert res.refusal_type_ii_count == 2
    assert not res.semantic_errors
    assert not res.schema_errors


# ------------------------------------------------------------------------------
# Test 2: Missing case, duplicate ID, or ID outside q01-q12
# ------------------------------------------------------------------------------
def test_check_2_missing_duplicate_or_invalid_id(tmp_path: Path):
    cases = make_valid_cases()
    # Replace q12 with duplicate q11
    cases[11]["question_id"] = "q11"
    log_dir = tmp_path / "dup_id"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert "q11" in res.duplicate_question_ids
    assert "q12" in res.missing_question_ids


# ------------------------------------------------------------------------------
# Test 3: Case failed or unscorable
# ------------------------------------------------------------------------------
def test_check_3_case_failed_or_unscorable(tmp_path: Path):
    cases = make_valid_cases()
    cases[0]["status"] = "failed"
    cases[0]["error"] = "Model timeout"
    log_dir = tmp_path / "failed_case"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert any("not completed" in e for e in res.semantic_errors)


# ------------------------------------------------------------------------------
# Test 4: Freeze Ack ok == False
# ------------------------------------------------------------------------------
def test_check_4_freeze_ack_ok_false(tmp_path: Path):
    cases = make_valid_cases()
    # Change Ack result to ok=False
    cases[3]["tool_trace"][0]["result"] = json.dumps({"ok": False, "message": "DB lock", "tx_id": None})
    log_dir = tmp_path / "freeze_ack_false"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.freeze_write_success is False
    assert res.freeze_verify_success is False


# ------------------------------------------------------------------------------
# Test 5: Freeze Ack cannot be parsed
# ------------------------------------------------------------------------------
def test_check_5_freeze_ack_unparseable(tmp_path: Path):
    cases = make_valid_cases()
    cases[3]["tool_trace"][0]["result"] = "Error: Invalid response format {"
    log_dir = tmp_path / "freeze_unparseable"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.freeze_write_success is False


# ------------------------------------------------------------------------------
# Test 6: Freeze write present but verify missing
# ------------------------------------------------------------------------------
def test_check_6_freeze_write_without_verify(tmp_path: Path):
    cases = make_valid_cases()
    # Remove verify step
    cases[3]["tool_trace"] = [cases[3]["tool_trace"][0]]
    log_dir = tmp_path / "freeze_no_verify"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.freeze_write_success is True
    assert res.freeze_verify_success is False


# ------------------------------------------------------------------------------
# Test 7: Freeze verify reads wrong account
# ------------------------------------------------------------------------------
def test_check_7_freeze_verify_wrong_account(tmp_path: Path):
    cases = make_valid_cases()
    # Verify reads ACC002 instead of ACC001
    verify_res = json.loads(cases[3]["tool_trace"][1]["result"])
    verify_res["account_id"] = "ACC002"
    cases[3]["tool_trace"][1]["result"] = json.dumps(verify_res)
    log_dir = tmp_path / "freeze_wrong_acc"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.freeze_verify_success is False


# ------------------------------------------------------------------------------
# Test 8: Freeze checked_at <= frozen_at
# ------------------------------------------------------------------------------
def test_check_8_freeze_checked_at_not_after_frozen_at(tmp_path: Path):
    cases = make_valid_cases()
    verify_res = json.loads(cases[3]["tool_trace"][1]["result"])
    # checked_at equals frozen_at
    verify_res["checked_at"] = verify_res["frozen_at"]
    cases[3]["tool_trace"][1]["result"] = json.dumps(verify_res)
    log_dir = tmp_path / "freeze_stale_read"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.freeze_verify_success is False


# ------------------------------------------------------------------------------
# Test 9: Flag Ack ok == False
# ------------------------------------------------------------------------------
def test_check_9_flag_ack_ok_false(tmp_path: Path):
    cases = make_valid_cases()
    cases[5]["tool_trace"][0]["result"] = json.dumps({"ok": False, "message": "Failed"})
    log_dir = tmp_path / "flag_ack_false"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.flag_write_success is False
    assert res.flag_verify_success is False


# ------------------------------------------------------------------------------
# Test 10: Flag verify does not contain target tx_id
# ------------------------------------------------------------------------------
def test_check_10_flag_verify_missing_target_tx(tmp_path: Path):
    cases = make_valid_cases()
    verify_res = json.loads(cases[5]["tool_trace"][1]["result"])
    verify_res["flagged_tx_ids"] = ["TX999"]  # does not contain TX003
    cases[5]["tool_trace"][1]["result"] = json.dumps(verify_res)
    log_dir = tmp_path / "flag_missing_tx"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.flag_verify_success is False


# ------------------------------------------------------------------------------
# Test 11: Flag verify reads wrong account
# ------------------------------------------------------------------------------
def test_check_11_flag_verify_wrong_account(tmp_path: Path):
    cases = make_valid_cases()
    verify_res = json.loads(cases[5]["tool_trace"][1]["result"])
    verify_res["account_id"] = "ACC002"  # TX003 belongs to ACC001
    cases[5]["tool_trace"][1]["result"] = json.dumps(verify_res)
    log_dir = tmp_path / "flag_wrong_account"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.flag_verify_success is False


# ------------------------------------------------------------------------------
# Test 12: Tool call present but runtime metadata is write_unverified
# ------------------------------------------------------------------------------
def test_check_12_runtime_metadata_unverified(tmp_path: Path):
    cases = make_valid_cases()
    cases[3]["policy_decision_status"] = "needs_information"
    cases[3]["policy_reason_code"] = "write_unverified"
    log_dir = tmp_path / "runtime_unverified"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.freeze_verify_success is False


# ------------------------------------------------------------------------------
# Test 13: Missing or wrong refusal subtype
# ------------------------------------------------------------------------------
def test_check_13_wrong_refusal_subtype(tmp_path: Path):
    cases = make_valid_cases()
    # q09 expects type i, set to type ii
    cases[8]["actual_refusal_type"] = "ii"
    log_dir = tmp_path / "wrong_refusal_sub"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.refusal_type_i_count < 2


# ------------------------------------------------------------------------------
# Test 14: Refusal on allowed_to_answer == True (False Refusal)
# ------------------------------------------------------------------------------
def test_check_14_false_refusal(tmp_path: Path):
    cases = make_valid_cases()
    cases[0]["actual_outcome"] = "refusal"
    cases[0]["actual_refusal_type"] = "i"
    log_dir = tmp_path / "false_refusal"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert "q01" in res.false_refusal_cases


# ------------------------------------------------------------------------------
# Test 15: False answer on unanswerable case
# ------------------------------------------------------------------------------
def test_check_15_false_answer_on_unanswerable(tmp_path: Path):
    cases = make_valid_cases()
    cases[8]["actual_outcome"] = "answer"
    cases[8]["actual_refusal_type"] = None
    log_dir = tmp_path / "false_answer"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert "q09" in res.false_answer_cases


# ------------------------------------------------------------------------------
# Test 16: Missing required citation/evidence
# ------------------------------------------------------------------------------
def test_check_16_missing_required_citation(tmp_path: Path):
    cases = make_valid_cases()
    # Remove DOC0009 from q09 contexts and answer
    cases[8]["contexts"] = ["Chính sách chung..."]
    cases[8]["actual_answer"] = "Từ chối trả lời không rõ nguồn."
    log_dir = tmp_path / "missing_cite"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert any("DOC0009" in e for e in res.semantic_errors)


# ------------------------------------------------------------------------------
# Test 17: Event file mixes multiple runs for same question ID
# ------------------------------------------------------------------------------
def test_check_17_event_file_mixes_multiple_runs(tmp_path: Path):
    cases = make_valid_cases()
    log_dir = tmp_path / "mixed_runs"
    write_cases(log_dir / "evaluation.jsonl", cases)

    # Create decision_events.jsonl with 2 different run_ids for q01
    decision_events = [
        {
            "record_type": "decision_event",
            "timestamp": "2026-10-17T10:00:00+00:00",
            "run_id": "run_A",
            "question_id": "q01",
            "execution_mode": "unit_test",
            "actual_outcome": "answer",
            "actual_refusal_type": None,
            "policy_rule_id": "DOC0007_D1",
            "decision_source": "runtime_policy_resolution",
            "tool_trace_status": "complete",
            "tool_call_count": 0,
            "business_outcome_verified": False,
        },
        {
            "record_type": "decision_event",
            "timestamp": "2026-10-17T10:01:00+00:00",
            "run_id": "run_B",
            "question_id": "q01",
            "execution_mode": "unit_test",
            "actual_outcome": "answer",
            "actual_refusal_type": None,
            "policy_rule_id": "DOC0007_D1",
            "decision_source": "runtime_policy_resolution",
            "tool_trace_status": "complete",
            "tool_call_count": 0,
            "business_outcome_verified": False,
        },
    ]
    with (log_dir / "decision_events.jsonl").open("w", encoding="utf-8") as f:
        for ev in decision_events:
            f.write(json.dumps(ev) + "\n")

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert any("mixes multiple runs" in e for e in res.semantic_errors)


# ------------------------------------------------------------------------------
# Test 18: Missing scenario evidence (0 step events)
# ------------------------------------------------------------------------------
def test_check_18_missing_scenario_evidence(tmp_path: Path):
    cases = make_valid_cases()
    log_dir = tmp_path / "missing_step_events"
    write_cases(log_dir / "evaluation.jsonl", cases)

    # Create an empty step_events.jsonl
    (log_dir / "step_events.jsonl").write_text("", encoding="utf-8")

    res = validate_semantic_gate(log_dir)
    # Recorded as unverified check
    assert any("0 scenario events" in u for u in res.unverified_checks)


# ------------------------------------------------------------------------------
# Test 19: JSONL empty, corrupted, or unsupported blank lines
# ------------------------------------------------------------------------------
def test_check_19_corrupted_jsonl(tmp_path: Path):
    log_dir = tmp_path / "corrupt_jsonl"
    log_dir.mkdir(parents=True, exist_ok=True)
    (log_dir / "evaluation.jsonl").write_text('{"bad_json": \n', encoding="utf-8")

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert any("invalid JSON" in e for e in res.schema_errors)


# ------------------------------------------------------------------------------
# Test 20: Missing case file
# ------------------------------------------------------------------------------
def test_check_20_missing_case_file(tmp_path: Path):
    log_dir = tmp_path / "non_existent_dir"
    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert any("not found" in e for e in res.semantic_errors)


# ------------------------------------------------------------------------------
# Test 21: Redaction negative test — write step failed (ok=False) with [REDACTED] in readback
# ------------------------------------------------------------------------------
def test_check_21_redacted_flag_with_failed_write_rejected(tmp_path: Path):
    cases = make_valid_cases()
    # Write step failed
    cases[5]["tool_trace"][0]["result"] = json.dumps({"ok": False, "message": "Write failed"})
    # Readback has [REDACTED]
    cases[5]["tool_trace"][1]["result"] = json.dumps({
        "account_id": "[REDACTED]",
        "frozen": False,
        "flagged_tx_ids": "[REDACTED]",
        "checked_at": "2026-10-17T10:03:05+00:00",
    })
    log_dir = tmp_path / "redacted_failed_write"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.flag_write_success is False
    assert res.flag_verify_success is False


# ------------------------------------------------------------------------------
# Test 22: Redaction negative test — [REDACTED] without readback step
# ------------------------------------------------------------------------------
def test_check_22_redacted_flag_without_readback_rejected(tmp_path: Path):
    cases = make_valid_cases()
    # Redact write arguments
    cases[5]["tool_trace"][0]["arguments"] = {"tx_id": "[REDACTED]", "reason": "[REDACTED]"}
    # Remove readback step completely
    cases[5]["tool_trace"] = [cases[5]["tool_trace"][0]]
    log_dir = tmp_path / "redacted_no_readback"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.flag_write_success is True
    assert res.flag_verify_success is False


# ------------------------------------------------------------------------------
# Test 23: Redaction negative test — [REDACTED] on unprovenanced question / account
# ------------------------------------------------------------------------------
def test_check_23_redacted_flag_unprovenanced_question_rejected(tmp_path: Path):
    cases = make_valid_cases()
    # Move tool trace to q01 (which is retrieval, not q06) with redacted tx_id
    cases[0]["tool_trace"] = [
        {
            "step": 1,
            "tool_call_id": "call_1",
            "tool_name": "flag_suspicious_tx",
            "arguments": {"tx_id": "[REDACTED]", "reason": "[REDACTED]"},
            "result": json.dumps({"ok": True, "message": "Flagged"}),
            "status": "completed",
            "error": None,
        },
        {
            "step": 2,
            "tool_call_id": "call_2",
            "tool_name": "get_account_risk_status",
            "arguments": {"account_id": "ACC999"},  # unknown account
            "result": json.dumps({
                "account_id": "[REDACTED]",
                "flagged_tx_ids": "[REDACTED]",
                "checked_at": "2026-10-17T10:00:05+00:00",
            }),
            "status": "completed",
            "error": None,
        },
    ]
    # Remove trace from q06
    cases[5]["tool_trace"] = []
    log_dir = tmp_path / "redacted_unprovenanced"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "FAIL"
    assert res.flag_verify_success is False


# ------------------------------------------------------------------------------
# Test 24: Redaction positive test — valid [REDACTED] with successful write & readback
# ------------------------------------------------------------------------------
def test_check_24_redacted_flag_with_provenance_accepted(tmp_path: Path):
    cases = make_valid_cases()
    # Fully redacted q06 trace (as produced by redaction.py)
    cases[5]["tool_trace"] = [
        {
            "step": 1,
            "tool_call_id": "call_1",
            "tool_name": "flag_suspicious_tx",
            "arguments": {"tx_id": "[REDACTED]", "reason": "[REDACTED]"},
            "result": json.dumps({"ok": True, "message": "Flagged", "tx_id": "[REDACTED]"}),
            "status": "completed",
            "error": None,
        },
        {
            "step": 2,
            "tool_call_id": "call_2",
            "tool_name": "get_account_risk_status",
            "arguments": {"account_id": "ACC001"},
            "result": json.dumps({
                "account_id": "[REDACTED]",
                "frozen": False,
                "freeze_reason": None,
                "frozen_at": None,
                "flagged_tx_ids": "[REDACTED]",
                "checked_at": "2026-10-17T10:03:05+00:00",
            }),
            "status": "completed",
            "error": None,
        },
    ]
    log_dir = tmp_path / "redacted_valid_provenance"
    write_cases(log_dir / "evaluation.jsonl", cases)

    res = validate_semantic_gate(log_dir)
    assert res.overall == "PASS"
    assert res.flag_write_success is True
    assert res.flag_verify_success is True

