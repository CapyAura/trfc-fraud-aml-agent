# ≥3 lần chạy thật, mỗi lần 1 file jsonl. Chủ sở hữu: C. Mốc: CP4.
# Mỗi dòng 1 bước: timestamp, step, tool, args, result, USAGE.
# 3 lần chạy phải KHÁC NHAU CÓ CHỦ ĐÍCH (1 freeze / 1 flag / 1 từ chối)
# để chứng minh agent quyết định theo dữ liệu, không phải kịch bản cứng.

Phiên chạy staging hoàn chỉnh đã nghiệm thu:
- `logs/staging_20261017_201308/`: 12 test cases (đầy đủ freeze q05, flag q06, refusal q09-q12) kèm step_events.jsonl, decision_events.jsonl, evaluation.jsonl và semantic_gate_result.json (PASS).
