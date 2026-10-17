# Việc cần fix — Person C

> Lập ngày 2026-10-17, cập nhật sau commit [`8c77866`](https://github.com/) (C phản hồi lần 1).
> Đối chiếu [PHAN_CONG.md](PHAN_CONG.md) §4 (C1–C8), [CLAUDE.md](CLAUDE.md) §4–§5, §12.
>
> **Ưu tiên còn lại: F2 → F5e → F4b → F6.** F2 là điều kiện chặn nộp — GV đọc file này là mất điểm trung thực.

---

## Trạng thái sau commit `8c77866`

| # | Việc | Trạng thái |
|---|---|---|
| F1 | `logs/` có lần chạy thật | ✅ **Xong** — `logs/staging_20261017_201308/` đủ 5 file |
| F2 | `c4_final_report.md` khai PASS khống | ❌ **Chưa đụng** — còn 3 chỗ sai, xem dưới |
| F3 | `make setup` hỏng | ✅ **Xong** — `--extra dev` (L12) + `MKDIR` (L3/6) |
| F4 | Test assert cũ | ⚠️ **Pass nhưng sửa sai cách** — xem F4 |
| F5a | `eval/reports/` | ✅ Có `evaluation.csv` + 2 SVG |
| F5b | `tests/test_tools.py` | ➖ Không đụng — lý do đã ghi ở [Makefile.txt:18-19](Makefile.txt#L18-L19), chấp nhận được |
| F5c | Tick C1–C8 | ✅ |
| F5d | Commit `ai-usage.md` | ✅ |
| F5e | `report.docx` | ❌ **Chưa có** |

**Câu hỏi ở mục cuối vẫn chưa được trả lời.** C push log lên nhưng không giải thích nguồn "359 passed" và DB `D:\Work\AIPR\...`.

---

## F1 ✅ `logs/` — đã xong

```
logs/staging_20261017_201308/
├── evaluation.jsonl              (12 dòng, timestamp thật 2026-10-17T13:13Z)
├── step_events.jsonl             (13 dòng)
├── decision_events.jsonl         (12 dòng)
├── semantic_gate_result.json     (overall: PASS)
└── reports/
    ├── evaluation.csv
    ├── faithfulness.svg
    └── refusal_correctness.svg
```

Không cần làm gì thêm. **Lưu ý:** [logs/README.md](logs/README.md) yêu cầu *"3 lần chạy KHÁC NHAU CÓ CHỦ ĐÍCH (1 freeze / 1 flag / 1 từ chối)"*. Hiện có **1 lần chạy** phủ cả 3 kịch bản (q05 freeze, q06 flag, q09–q12 refusal). Nếu GV hiểu là 3 **lần chạy** riêng biệt thì phải chạy thêm 2 lần nữa — hỏi lại cho chắc, hoặc chạy thêm cho an toàn.

---

## F2 🔴 `c4_final_report.md` vẫn tuyên bố PASS trên số liệu sai — **CHẶN NỘP**

Log bây giờ là thật, nên đường 1 của lần trước đã đúng. Nhưng file report **chưa được sửa theo bằng chứng thật**. Còn đúng 3 chỗ sai:

### F2a — [c4_final_report.md:3](reports/verification/c4_final_report.md#L3)

```
**Current Verified Status (2026-10-17): PASS — ALL ACCEPTANCE GATES SATISFIED.**
```

Không sai về mặt log, nhưng câu ngay dưới (L4) mới là chỗ sai — xem F2b. Nếu sửa F2b thì L3 giữ nguyên được.

### F2b — [c4_final_report.md:4](reports/verification/c4_final_report.md#L4): "0 unscorable cases"

**Sai sự thật.** `eval/reports/evaluation.csv` cột `faithfulness` = `Unscorable` ở **cả 12/12 câu**:

```
faithfulness Counter({'Unscorable': 12})
```

Nghĩa là metric faithfulness **không chấm được claim nào**, không phải "0 case không chấm được". Đây là loại sai nguy hiểm nhất: con số nghe tốt nhưng ngược nghĩa.

**Sửa L4 thành:**

```markdown
Real staging pipeline executed across all 12 test cases (`logs/staging_20261017_201308/`), achieving 100% case completion, 0 errors, 0 HTTP 429/503 errors, 100% refusal accuracy (2/2 type i, 2/2 type ii), successful Freeze write & verification (`q05`), successful Flag write & verification (`q06`), and full semantic gate PASS with `--require-events`. **Faithfulness is `Unscorable` on all 12 cases** — the string-match metric produced no scorable claims; this is a metric limitation, not a pass. `answer_correctness` is False on `q05` (calc) and `q08` (multi_doc).
```

### F2c — [c4_final_report.md:21](reports/verification/c4_final_report.md#L21): "359 passed, 1 skipped"

**Sai.** Chạy lại trên HEAD `8c77866`:

```
.venv/Scripts/python.exe -m pytest -q --ignore=tests/test_tools.py
→ 356 passed in 13.14s
```

Sửa thành đúng số đo được trên máy này **sau khi chạy lại**, kèm commit hash:

```markdown
| Focused offline tests and dry-run | **PASS** | PASS (offline only) | Full test suite: 356 passed in 13.14s at commit `8c77866` (`pytest -q --ignore=tests/test_tools.py`). `python -m eval.run_eval --dry-run` exit code 0. |
```

Nếu chạy lại ra số khác thì **ghi số mới**, đừng giữ 359.

### F2d — [c4_final_report.md:18](reports/verification/c4_final_report.md#L18): DB ngoài repo

```
D:\Work\AIPR\staging_c4_20261017_201308\state.db
```

Đường dẫn này **không tồn tại trong repo và không ai khác kiểm chứng được**. Thay bằng bằng chứng đọc được từ log đã commit — `step_events.jsonl` của q05/q06 có `freeze_account_temporarily` → `get_account_risk_status` và `flag_suspicious_tx` → `get_account_risk_status`. Dẫn file + số dòng, bỏ đường dẫn tuyệt đối đi.

### F2e — `eval/README.md` nói ngược lại

[eval/README.md:235](eval/README.md#L235) vẫn ghi:

> No genuine run logs are included, so do not treat `make demo`, a real evaluation, or report values as verified until the A/B integration and real scenarios have run.

Trong khi [README.md:19](README.md#L19) đã khai C "**xong**" với log thật. Hai file trong cùng repo nói ngược nhau — GV đọc là thấy ngay. Sửa `eval/README.md:235` thành: log thật nằm ở `logs/staging_20261017_201308/`, tái lập bằng `scripts/run_c4_staging.ps1`.

---

## F3 ✅ `make setup` — đã xong

[Makefile:12](Makefile#L12) `uv sync --locked --extra dev`; [Makefile:3,6](Makefile#L3) tạo `.test-tmp` trước pytest. `Makefile.txt:13` và `README.md` cũng đã sửa.

**Chưa ai verify cold-start thật** (xoá `.venv` → `make setup`). Nếu chưa làm thì làm trước buổi bảo vệ — đây là bài "Cold start" GV chạy tại chỗ.

---

## F4 ⚠️ Test assert — pass, nhưng sửa ngược chỉ dẫn

FIX_C lần trước ghi rõ: *"**Không** sửa `llm.py` cho khớp test"*. C vẫn sửa `llm.py` (đổi `Missing GROQ_API_KEY` → `Please set GROQ_API_KEY`), **và** đổi assert thành:

```python
assert ("No valid LLM provider configured" in str(exc)) or ("Missing GROQ_API_KEY" in str(exc))
```

### F4b — bỏ vế `or`

Cái `or` làm assert **luôn pass** với cả chuỗi cũ, tức là test không còn bảo vệ gì. Sửa về một vế:

```python
assert "No valid LLM provider configured" in str(exc)
```

Việc sửa `llm.py` thì chấp nhận được — chuỗi mới vẫn đúng và vẫn multi-provider, không cần revert.

---

## F5e 🔴 `report.docx` chưa có — **CHẶN NỘP**

`ls report.docx` → không có file. Đây là sản phẩm nộp chính theo [CLAUDE.md](CLAUDE.md) §4 mục 1: **8–9 trang, đúng 9 mục**.

**Việc của C** ([PHAN_CONG.md:114](PHAN_CONG.md#L114)). Nguồn nội dung: [REPORT.md](REPORT.md) — A viết xong §1/§3/§7, B viết §2/§4/§5/§9, C viết §6/§8.

**Trước khi ghép:**
1. Chờ A commit `REPORT.md` (hiện đang `M`, chưa commit).
2. Xoá mọi khối `> **Ghi chú cho A — KHÔNG đưa vào `.docx`**` trong `REPORT.md` — đó là ghi chú nội bộ, không phải nội dung báo cáo.
3. Điền hết `[[TODO: ...]]` hoặc xoá câu đó đi. Hiện còn:
   - §3.4 — `[[TODO: C bổ sung số ca testset có tier thật]]` → testset hiện **0 câu** có `tier`, xoá TODO và giữ nguyên câu "không claim điểm cộng +1" đã viết.
   - §3.5 — `[[TODO: số từ make eval]]` → **không điền được**: `make eval` chỉ chạy `--dry-run`, không eval thật; và faithfulness `Unscorable` ở cả 12 câu. Thay bằng câu fallback đã viết sẵn: "chưa đo được, chuyển sang §7".
   - §4 — `[[TODO: trace từ logs/ thật]]` → giờ có `logs/staging_20261017_201308/step_events.jsonl`, điền được (việc của B).
   - §8 — `[[TODO: hash cuối cùng]]` → lấy sau khi mọi người commit xong.
4. Đếm trang sau khi format, phải nằm trong **8–9 trang**.

---

## F6 🟠 `faithfulness` không chấm được câu nào — cần nói rõ trong §6

`eval/reports/evaluation.csv`: `faithfulness = Unscorable` ở **12/12 câu**. Đây không phải bug chặn nộp, nhưng **§6 bắt buộc phải nêu** vì [CLAUDE.md](CLAUDE.md) §7 mục 6 yêu cầu *"kết quả (kèm chi phí token từng câu), ≥1 ca thất bại + phân tích"*.

C có sẵn 3 thứ dùng được cho §6:

| Thứ | Nguồn |
|---|---|
| Bảng token từng câu | `evaluation.csv` — `calls`, `prompt_tokens`, `completion_tokens`, `max_prompt` (đủ 12 dòng) |
| Ca thất bại | `q05` (calc) và `q08` (multi_doc) — `answer_correctness = False` |
| Tỉ lệ từ chối đúng | `refusal_correctness = True` cả 12; `refusal_subtype_correctness = True` ở q09–q12 |

Phải viết đúng 1 câu giải thích vì sao faithfulness vô dụng ở đây: metric so khớp chuỗi claim với context, mà agent trả lời tổng hợp/diễn đạt lại nên không claim nào khớp nguyên văn → `Unscorable`. Đây là **hạn chế của metric**, không phải hệ thống đúng.

---

## Thứ tự chạy còn lại

```powershell
# 1. Sửa c4_final_report.md (F2a–F2d) + eval/README.md:235 (F2e)
# 2. Chạy lại suite để lấy số đúng cho F2c
.venv\Scripts\python.exe -m pytest -q --ignore=tests/test_tools.py

# 3. Sửa assert (F4b)
# 4. Cold-start verify (F3)
Remove-Item -Recurse -Force .venv
make setup
make test

# 5. Viết §6 + §8 vào REPORT.md (F6), rồi ghép report.docx (F5e)

# 6. Commit
git add reports/verification/c4_final_report.md eval/README.md tests/test_native_tool_calling.py REPORT.md report.docx
git commit -m "fix(report): correct C4 verification claims and add report.docx"
```

---

## Câu hỏi vẫn chưa được trả lời

1. **"359 passed" chạy ở commit nào?** Trên HEAD `8c77866` suite ra **356 passed**. Con số 359 không tái lập được từ repo.
2. **DB `D:\Work\AIPR\staging_c4_20261017_201308\state.db` còn tồn tại không?** Nếu còn, bằng chứng nào trong repo chứng minh được nó? Nếu không, xoá mọi dẫn chiếu tới đường dẫn đó.
3. **Log staging chạy bằng provider nào?** Không ghi ở đâu trong `logs/`. §6 cần biết để mô tả đúng (Groq / DeepSeek / custom).

---

## F7 🟠 Redaction che cả `expected` — làm yếu bằng chứng log

Đã tự kiểm tra: `[REDACTED]` trong `evaluation.jsonl` là do [eval/redaction.py:27-31](eval/redaction.py#L27-L31) đưa `amount` vào `_IDENTIFIER_KEYS`. Hệ quả — cả **đáp án kỳ vọng** cũng bị che:

```json
"expected": {"criteria_type": "contains_all", "values": ["[REDACTED] VND", "[REDACTED] VND"]}
```

`answer_correctness` vẫn đúng vì metric chạy **trước** redaction, nhưng người đọc log (GV) **không kiểm chứng được** câu trả lời có đúng hay không. Đây là đánh đổi hợp lý về bảo mật nhưng phải nói rõ.

**Không cần sửa code.** Chỉ cần **1 câu trong §6**: log đã qua redaction ở `eval/redaction.py`, số tiền/tài khoản/tx_id bị che; số liệu chấm điểm trong `evaluation.csv` tính trên dữ liệu **chưa** redaction nên vẫn đúng.
