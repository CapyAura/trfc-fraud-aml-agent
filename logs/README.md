# ≥3 lần chạy thật, mỗi lần 1 file jsonl. Chủ sở hữu: C. Mốc: CP4.
# Mỗi dòng 1 bước: timestamp, step, tool, args, result, USAGE.
# 3 lần chạy phải KHÁC NHAU CÓ CHỦ ĐÍCH (1 freeze / 1 flag / 1 từ chối)
# để chứng minh agent quyết định theo dữ liệu, không phải kịch bản cứng.

## Phiên chạy được nghiệm thu (semantic gate PASS)

- `logs/staging_20261017_201308/` — 12/12 case, `overall: PASS`. Đầy đủ freeze (q05), flag (q06),
  từ chối loại i (q09, q10) và loại ii (q11, q12), kèm `step_events.jsonl`,
  `decision_events.jsonl`, `evaluation.jsonl`, `semantic_gate_result.json` và `reports/`.
  Đây là phiên `make eval` và `report.docx` trích số.
- `logs/staging_20261018_035803/` — 12/12 case, `overall: PASS`, cùng đủ bộ artifact + `reports/`.
  Chạy lại độc lập trên DB cách ly mới; `data/state.db` production có SHA256 trước/sau trùng nhau.

Hai phiên PASS **không phải bản sao của nhau**. Cùng 12 câu hỏi nhưng agent chọn truy vấn và
đường suy luận khác nhau, dẫn tới quyết định khác nhau trên cùng dữ liệu:

| Case | `201308` | `035803` |
|---|---|---|
| q01 | `policy_rule_id = None`, 1 tool call | `DOC0007_ART04`, 1 tool call |
| q03 | `DOC0008_ART03` | `DOC0008_ART03` (trùng) |
| q07 | `DOC0003_ART09` | `DOC0003_ART10` |
| q08 | `DOC0006_ART07` | `DOC0006_ART04` |
| q09 | 2 tool call | 1 tool call |
| q11 | 2 tool call, 10 context | 0 tool call, không context |

Đây là bằng chứng "agent quyết định theo dữ liệu, không phải kịch bản cứng" mạnh hơn một lần
đổi config: cùng testset, cùng seed DB, cùng prompt, mà trace và rule id vẫn khác.

## Phiên chạy thất bại — giữ lại làm bằng chứng, KHÔNG xoá

- `logs/staging_20261018_034518/` — 12/12 case chạy xong, 0 lỗi, freeze/flag write+verify đều
  `true`, nhưng **semantic gate FAIL**: `Case q11 missing required citation/evidence for DOC0006`.
  Nguyên nhân: model chọn truy vấn khác cho q11
  (`"thiếu dữ liệu gốc không được kết luận khóa tài khoản Điều 7 Điều 8"` → lấy DOC0005) nên câu
  trả lời loại ii đúng nhưng không trích DOC0006. Đây là phương sai phía model, không phải lỗi
  hạ tầng — cùng phiên `201308` với cùng testset vẫn PASS. Giữ nguyên để đối chiếu.
- `logs/staging_20261018_034302_FAILED_stderr_abort/` — pipeline dừng ngay bước đầu vì
  `$ErrorActionPreference = "Stop"` giết script ở dòng INFO đầu tiên của MCP server (server ghi
  log ra stderr đúng thiết kế). `evaluation.jsonl` rỗng 0 byte. Đã sửa runner sang `"Continue"`;
  giữ thư mục này làm dấu vết của lỗi đã khắc phục.

## Chạy lại một phiên

```powershell
.\scripts\run_c4_staging.ps1
```

Script tạo DB cách ly trong `%TEMP%`, kiểm SHA256 `data/state.db` trước/sau, chạy 12 case thật,
validate schema 3 file log, chạy semantic gate (`--require-events`) và sinh `reports/`.
