# Việc cần fix — còn lại trước khi nộp

> Lập **2026-10-18**, audit toàn repo so với `Ref/01-De-tai-upload-for-student.pdf` + `Ref/02-Yeu-cau-Thuc-hien.pdf`
> (đối chiếu [CLAUDE.md](CLAUDE.md) §4–§5, §12).
>
> **Việc còn lại của C đã tách sang [FIX_C.md](FIX_C.md)** — file này giữ phần đối chiếu chung.

---

## Bảng tổng hợp

| # | Việc | Ai | Chặn nộp? | Trạng thái |
|---|---|---|:---:|---|
| T1 | Gộp 3 report → `report.docx` (8–9 trang, 9 mục) | **C** chủ trì | 🔴 **CÓ** | ❌ → [FIX_C.md](FIX_C.md#t1--ghép-reportdocx--chặn-nộp) |
| T2 | `make eval` chỉ `--dry-run`, không tái lập số liệu | **C** | 🟡 Không | ❌ → [FIX_C.md](FIX_C.md#t2--make-eval-không-tái-lập-được-số-liệu) |
| T3b | `eval/README.md` còn bộ số cũ + câu "No genuine run logs" | **C** | 🟡 Không | ❌ → [FIX_C.md](FIX_C.md#t3b--evalreadmemd-còn-bộ-số-cũ) |
| T5 | Testset chưa có câu dùng `tier` → không claim được bonus +1 | **C** | ➖ Không | ❌ → [FIX_C.md](FIX_C.md#t5--bonus-1-metadata-filter) |
| F4b | Assert còn nhánh `or` làm test vô nghĩa | **C** | ➖ Không | ❌ → [FIX_C.md](FIX_C.md#f4b--assert-có-nhánh-or-làm-test-vô-nghĩa) |
| ~~T4a~~ | ~~`REPORT_B_.md:118` TODO provider/model~~ | ~~B~~ | — | ✅ xong |
| ~~T4b~~ | ~~`REPORT.md:194` TODO dense-vs-hybrid~~ | ~~A~~ | — | ✅ xong |
| ~~T4d~~ | ~~`REPORT_B_.md:122` sai về `react_step.txt`~~ | ~~B~~ | — | ✅ xong |
| ~~T6~~ | ~~`REPORT_PERSON_C.md` 6 lỗi số liệu~~ | ~~C~~ | — | ✅ xong |

---

## Đã kiểm — đạt, không phải task

Giữ lại để đối chiếu lúc bảo vệ:

- **3 tầng (a)(b)(c)** — đủ, có bằng chứng thật.
- **Yêu cầu 2.1–2.8** — đạt cả 8.
- **Corpus** — 9 doc, 16.293 token (min 10.000).
- **Testset** — 12 câu, 4 `no_answer` (loại i=2, ii=2).
- **Logs** — 3 lần chạy thật: `logs/staging_20261017_201308/` và `logs/staging_20261018_035803/` (gate PASS), `logs/staging_20261018_034518/` (gate FAIL q11, giữ làm bằng chứng). Đều `execution_mode: "real"`, có `USAGE` từng câu.
- **Side effect + verify** — `semantic_gate_result.json` → `freeze_write_success` / `freeze_verify_success` / `flag_write_success` / `flag_verify_success` đều `true`. Trace thật đã dán ở `REPORT_B_.md:86-94`.
- **MCP** — 5 tool (2 ghi), stdio, log ra stderr, client discover động.
- **Bảo mật** — `.env` ignored, `Ref/` untracked, không có key trong repo.
- **Tests** — 368 passed, 0 skipped (Python 3.13.5).
- **README số liệu** — đã sửa (Python 3.13.5, 19 / 76 / 368 passed).
- **Commit hash §8** — 12 hash đã đối chiếu `git log -1`, đều tồn tại và đúng người.

```
ed531d9 CapyCoder        69dd5d8 CapyCoder        b975579 CapyCoder        0e0f6fc CapyCoder
6ccbdf1 Do Ngo           84a69e7 Do Ngo           d12f5cc Do Ngo           aae71ca Do Ngo
8c77866 Penguin-cell34   2a6cffb Penguin-cell34   86b144e Penguin-cell34   b9f09ba Penguin-cell34
```

Số commit đổi sau mỗi lần pull B — **đếm lại ngay trước khi chốt `report.docx`**:
`git rev-list --count HEAD` và `git shortlog -sn HEAD`.

### Còn là hạn chế đã biết (ghi trong report, không sửa)

- **`faithfulness` = `Unscorable` 12/12** — adapter chưa sinh trường `claims`. Rubric [CLAUDE.md §11](CLAUDE.md#11-phần-bổ-sung-từ-syllabus-mục-final-project-specification) (RAGAS) chỉ đạt một phần. Đã ghi đúng ở `REPORT.md` §6.2 — **giữ nguyên, đây là điểm trung thực**.
- **`context_precision` chỉ chấm được 1–2/12** — `eval/metrics.py:73` trả `None` khi một context chứa nhiều mã `DOCnnnn`.
- **`expected_refusal_type` thiếu trong `tests/testset.jsonl`** — loại (i)/(ii) chỉ suy ra lúc chấm gate. Không bắt buộc.
