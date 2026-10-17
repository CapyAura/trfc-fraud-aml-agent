# FIX_C — Việc còn lại của Thành viên C

> Cập nhật **2026-10-18**, sau khi A rà lại toàn bộ repo đối chiếu với `logs/` thật.
> **T1, T2, T3b, T5, F4b đều đã xong — bảng cũ trong file này đã lỗi thời và được thay bằng bảng dưới.**
> Việc còn lại: **C tự đọc lại §6/§8 của mình** và **kiểm tra số trang `report.docx`** trước khi nộp.

## Trạng thái thật (A đã tự chạy kiểm chứng từng dòng)

| # | Việc cũ | Sự thật đo được | Trạng thái |
|---|---|---|:---:|
| **T1** | Ghép 3 `.md` → `report.docx` | `report.docx` tồn tại, 214.760 bytes, sinh bởi `scripts/build_report_docx.py` | ✅ |
| **T2** | `make eval` chỉ `--dry-run` | `Makefile:46-52` có target `eval-live`; `ai-usage.md:16-18` đã ghi đúng ("`make eval` chỉ validate… lần chạy thật tái lập bằng `make eval-live`") | ✅ |
| **T3b** | `eval/README.md` số cũ | Đã sửa: Python 3.13.5, 19 / 76 / 403 passed, 0 skipped | ✅ |
| **T5** | Testset chưa có câu dùng `tier` | `tests/testset.jsonl:4` (q04) có `"expected_tier": 2` | ✅ |
| **F4b** | `test_native_tool_calling.py:411` còn nhánh `or` | Nhánh `or` đã bỏ, assert chỉ còn `"No valid LLM provider configured"` | ✅ |

---

## Việc còn lại của C

### C1 — Đọc lại §6 và §8 trước khi nộp

A đã sửa các chỗ **sai số / dẫn nguồn không tồn tại** trong `REPORT_PERSON_C.md`. C phải đọc lại và
giải thích được từng dòng (luật bảo vệ: "SV phải giải thích được MỌI DÒNG trong phần mình nhận"):

- **`:98-103`** — bảng metadata filter. Hai phiên `logs/staging_20261018_014623/` và `.../015357/`
  **không tồn tại** trong working tree lẫn lịch sử Git (`git log --all -- 'logs/staging_20261018*'` → rỗng).
  Đã thay bằng phiên thật duy nhất `logs/staging_20261017_201308/`: trace q04 bước 1 gọi
  `search_policy({"query": "hạn mức giao dịch ngày chuyển khoản trong nước theo tầng eKYC", "tier": 2})`,
  và `metadata_filter_usage(tool_trace, 2)` → `True` khi chấm lại trên đúng row đó.
- **`:115`** — đoạn q05 từng dẫn phiên `staging_20261018_012603` và trường `marker_results` với giá trị
  `[{index:1, satisfied:true}, {index:2, satisfied:false}]`. Phiên đó không tồn tại; trường
  `marker_results` chỉ được thêm ở commit `68a7a22`, **sau** phiên `201308`, nên log đã commit không có.
  Đã viết lại thành **giới hạn bằng chứng** trung thực.
- **`:140`** — test count: **407 passed, 0 skipped** (`pytest -q` đầy đủ), Python **3.13.5**;
  `make test` loại `tests/test_tools.py` nên báo **403**.
- **`:159-167`** — bảng commit: **72** tổng; Do Ngo 38 / CapyCoder 15 / Penguin-cell34 12 / Do Coding 7.
- **`:185`** — bullet bonus metadata filter: đã dẫn đúng `logs/staging_20261017_201308/`.

### C2 — Đếm số trang `report.docx`

Yêu cầu 8–9 trang, **§9 Phụ lục không tính trang**. `report.docx` hiện tại sinh từ
`scripts/build_report_docx.py` (không phải convert từ `report_merged.md`). Mở bằng Word, xem số trang
thực tế; nếu lệch thì sửa trong builder rồi chạy lại:

```bash
.venv/Scripts/python.exe scripts/build_report_docx.py
```

### C3 — Kiểm tra hình kiến trúc đã nhúng

`reports/architecture.png` phải nằm trong §2 của `report.docx`. Sinh lại hình nếu cần:

```bash
.venv/Scripts/python.exe scripts/make_arch_figure.py
```

---

## Đã xong — KHÔNG làm lại

- ✅ **T4a** — `REPORT_B_.md:118` provider/model: ghi đúng "log không lưu", không suy từ `llm.py:24`.
- ✅ **T4b** — `REPORT.md` §3.5 dense-vs-hybrid: có bảng số đo thật + phân tích `q01`/`q09`.
- ✅ **T4d** — `REPORT_B_.md:122`: `react_step.txt` được nạp thật qua `load_react_prompt()`.
- ✅ **T6** — `REPORT_PERSON_C.md`: model claim, `get_account_risk_status`, đường dẫn DB, cột
  `Tỷ lệ đóng góp` (đã xoá), số commit, 7 link `file:///D:/Work/...`.
- ✅ **q05/q08** — không đổ lỗi redaction cho `q08`; `q05` là giới hạn bằng chứng (điểm tính trước redaction).
- ✅ **README.md** — Python 3.13.5, 19 / 76 / 403 passed, 0 skipped.
- ✅ **`eval/README.md`** — bộ số mới + bỏ mọi dẫn `logs/staging_20261018_*`.
- ✅ **`scripts/build_report_docx.py`** — bỏ đoạn judge bịa (`staging_20261018_005400`, "11/12 câu",
  "0.63–1.00"). Log `201308` không có trường `judge_*` nào, nên mục "Đối chiếu với LLM judge" chỉ còn
  một đoạn văn nói rõ đó là giới hạn bằng chứng, không còn bảng rỗng. Đánh số bảng đã sửa lại tuần
  tự (0–5, trước đó có hai "Bảng 4").

### Còn là hạn chế đã biết (ghi trong report, không sửa)

- **`faithfulness` = `Unscorable` 12/12** — adapter chưa sinh trường `claims`. Đây là điểm trung thực.
- **`context_precision` chỉ chấm được 1–2/12** — `metrics.py:73` trả `None` khi một context chứa nhiều mã `DOCnnnn`.
- **`expected_refusal_type` thiếu trong `tests/testset.jsonl`** — loại (i)/(ii) chỉ suy ra lúc chấm gate.
- **`reports/verification/c4_final_report.md` còn số cũ** (`359 passed, 1 skipped`, `CPython 3.14.7`).
  File nội bộ, không phải deliverable — nếu GV đọc thì nên sửa hoặc ghi rõ "snapshot 2026-10-17".
