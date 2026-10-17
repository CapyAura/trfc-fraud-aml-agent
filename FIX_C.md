# FIX_C — Việc còn lại của Thành viên C

> Cập nhật **2026-10-18** sau khi A/B đã sửa xong phần report.
> **Không còn TODO nào về số liệu trong 3 file báo cáo** — T4a/T4b/T4d/T6 đã xong, đừng làm lại.
>
> **Thứ tự: T1 → T2 → T3b → T5 → F4b.** Chỉ **T1** chặn nộp.

| # | Việc | Chặn nộp? | Trạng thái |
|---|---|:---:|---|
| **T1** | Ghép 3 file `.md` → `report.docx` (8–9 trang, 9 mục) | 🔴 **CÓ** | ❌ `report.docx` chưa tồn tại |
| **T2** | `make eval` chỉ `--dry-run`; `ai-usage.md:16-17` claim sai | 🟡 Không | ❌ |
| **T3b** | `eval/README.md` còn bộ số cũ + câu "No genuine run logs" | 🟡 Không | ❌ |
| **T5** | Testset chưa có câu dùng `tier` → không claim được bonus +1 | ➖ Không | ❌ |
| **F4b** | `test_native_tool_calling.py:411` còn nhánh `or` làm assert vô nghĩa | ➖ Không | ❌ |

---

## T1 🔴 Ghép `report.docx` — **CHẶN NỘP**

`report.docx` **không có trong repo** (`ls report.docx` → không tồn tại). Đây là deliverable #1 của
[CLAUDE.md §4](CLAUDE.md#4-sản-phẩm-phải-nộp).

### T1a — Bản đồ ghép (đã cập nhật, đừng dùng bản cũ)

| Mục | Lấy từ | Dòng | Ghi chú |
|---|---|---|---|
| §1 Vấn đề, phạm vi, giả định | `REPORT.md` | 30–78 | A viết xong |
| §2 Kiến trúc tổng thể | **`REPORT_B_.md`** | 3–27 | Sơ đồ ASCII thật + bốn ranh giới + luồng q05 |
| §3 Thiết kế RAG | `REPORT.md` | 117–225 | **§3.5 đã có số đo thật** (dense vs hybrid), không còn TODO |
| §4 Agent & tool | **`REPORT_B_.md`** | 28–99 | Trace q05 thật, bảng 3 bước |
| §5 MCP server | **`REPORT_B_.md`** | 100–119 | **dòng 118 đã sửa** — provider/model ghi đúng "log không lưu" |
| §6 Đánh giá | `REPORT_PERSON_C.md` | 9–119 | C; **6 lỗi số liệu đã sửa**, số khớp `evaluation.csv` |
| §7 Hạn chế | `REPORT.md` | 355–392 | A viết xong, 4 hạn chế trung thực |
| §8 Phân công | `REPORT_PERSON_C.md` | 121–141 | C; **đã xoá cột `Tỷ lệ đóng góp`**, 68 commits đúng |
| §9 Phụ lục | **`REPORT_B_.md`** | 120–227 | Prompt nguyên văn; **dòng 122 đã sửa** (`react_step.txt` được nạp thật) |

**Bỏ hẳn — KHÔNG chép sang `.docx`:**

| Vùng | Lý do |
|---|---|
| `REPORT.md:1-28` | Tiêu đề khung + 4 blockquote nội bộ + bảng phân trang + deadline CP5 |
| `REPORT.md:79-116` | Khung §2 cũ — sơ đồ còn ghi 4 tool, **sai**: trace thật q05 chỉ 3 tool, không có `get_transactions`. Đã thay bằng `REPORT_B_.md:3-27` |
| `REPORT.md:222-225` | `> **Ghi chú cho A — KHÔNG đưa vào `.docx**` — 4 dòng, tuyệt đối không được lọt vào bản nộp |
| `REPORT.md:227-265` | Khung §4/§5 (đã thay bằng B) |
| `REPORT.md:266-354` | Khung §6 (đã thay bằng `REPORT_PERSON_C.md`) |
| `REPORT.md:393-410` | Khung §8 (đã thay bằng `REPORT_PERSON_C.md`) |
| `REPORT.md:411-419` | Khung §9 (đã thay bằng `REPORT_B_.md`) |
| `REPORT.md:420-431` | Checklist trước khi ghép `.docx` — ghi chú nội bộ |
| `REPORT_PERSON_C.md:3-5` | 3 blockquote nội bộ ở đầu ("Tài liệu nguồn căn cứ…") |
| `REPORT_PERSON_C.md:145-156` | "Bảng Checklist hoàn tất của Thành viên C" — ghi chú nội bộ |

**Kiểm tra trước khi convert:**

```bash
# 1. Không còn ghi chú nội bộ
grep -n "KHÔNG đưa vào\|Ghi chú cho A\|Checklist hoàn tất\|Checklist trước khi ghép\|Bảng phân trang" <file-ghép>
# 2. Không còn TODO
grep -n "\[\[TODO" <file-ghép>
# 3. Đúng 9 mục, đúng thứ tự §1→§9
grep -n "^#\{1,2\} §" <file-ghép>
```

**`REPORT_PERSON_C.md` CHƯA ĐƯỢC TRACK GIT** — `git ls-files REPORT_PERSON_C.md` → rỗng.
Phải `git add REPORT_PERSON_C.md` trước khi nộp, nếu không phần §6/§8 mất khỏi repo.

**Đếm trang sau khi format** — yêu cầu 8–9 trang. §9 Phụ lục không tính trang.

---

## T2 🟡 `make eval` không tái lập được số liệu

[Makefile:19-20](Makefile#L19) chỉ chạy `--dry-run`:

```
$ make eval
.venv/Scripts/python.exe -m eval.run_eval --dry-run
DRY RUN: valid testset (12 cases); no agent/API called and no evaluation scores produced.
```

Nhưng [CLAUDE.md §5](CLAUDE.md#5-yêu-cầu-kỹ-thuật-bắt-buộc) và §12 ghi *"`make eval` tái lập mọi số liệu"*,
và [PHAN_CONG.md:79](PHAN_CONG.md#L79) ghi *"`make eval` in ra bảng khớp số trong report"*.
Số trong report đến từ lần chạy thật cần `--agent-adapter` + LLM sống — **không tái lập offline được**.

**Câu sai:** [ai-usage.md:16-17](ai-usage.md#L16) — *"Mọi số trong `eval/reports/` đều lấy từ lần chạy thật,
tái lập bằng `make eval`."* Vế sau sai.

**Chọn một (khuyên làm cả hai):**

- **(a) Thêm target `eval-live`** vào Makefile (~3 dòng, không có `--dry-run`, có `--agent-adapter`),
  giữ `eval` là validate offline. Rồi sửa `ai-usage.md` thành *"tái lập bằng `make eval-live` (cần LLM key + network)"*.
- **(b) Chỉ sửa câu chữ** — nói đúng: số lấy từ `logs/staging_20261017_201308/`, không tái lập offline.

**Lưu ý cold start:** máy dev **không có GNU `make`** (chỉ `mingw32-make`). Nếu GV cũng dùng Windows
không có GNU make thì `make setup && make demo` chết ngay ở [CLAUDE.md §9](CLAUDE.md#9-liêm-chính-học-thuật--buổi-bảo-vệ) TT1.
README cần ghi rõ yêu cầu GNU make + lệnh thay thế.

---

## T3b 🟡 `eval/README.md` còn bộ số cũ

**`eval/README.md:241-245`** — sửa thành:

| Đang viết | Sự thật (đo lại 2026-10-18) |
|---|---|
| `Python 3.14.7` | **Python 3.13.5** |
| Adapter tests: `14 passed` | **19 passed** |
| Focused regression: `118 passed, 1 skipped` | **76 passed** |
| Full suite: `142 passed, 1 skipped` | **368 passed, 0 skipped** |

**`eval/README.md:235-237`** — *"No genuine run logs are included, so do not treat … report values as
verified until the A/B integration and real scenarios have run."* — **sai**: `logs/staging_20261017_201308/`
đã có log thật và **đã track git** (`git ls-files logs/` → 7 file). Câu này viết từ trước commit `8c77866`.

---

## T5 ➖ Bonus +1 metadata filter

Code đã sẵn (`tier` pre-filter ở [search.py:55](src/trfc/rag/search.py#L55), `search_policy(query, k, tier, mode)`
ở [impl.py:190](src/trfc/tools/impl.py#L190)), nhưng:

```
grep -rn "tier" eval/*.py src/trfc/agent/loop.py   →  0 hit
grep -c '"tier"' tests/testset.jsonl               →  0
```

Không có câu testset nào dùng `tier` → **không claim được** bonus +1.

**Cách lấy (+1):** thêm 1 câu testset có `tier` (vd. hỏi policy chỉ áp cho `tier: "high"`), chạy lại eval,
thêm 1 dòng vào bảng §6. **Testset thuộc C — A/B không được sửa.**

> Đã có 2/4 bonus: CSV + SVG graph (+1), `client2.py` client MCP thứ hai (+1).
> Bonus thứ 3 (dense-vs-hybrid) **đã có số** ở `REPORT.md` §3.5 — nhưng số đó đo bằng script ngoài,
> chưa nối vào `make eval`; muốn claim chắc thì thêm target như T2a.

---

## F4b ➖ Assert có nhánh `or` làm test vô nghĩa

[tests/test_native_tool_calling.py:411](tests/test_native_tool_calling.py#L411):

```python
assert ("No valid LLM provider configured" in str(exc)) or ("Missing GROQ_API_KEY" in str(exc))
```

`llm.py:101` raise `"No valid LLM provider configured…"` khi không có provider nào; `llm.py:110/129` raise
`"Missing GROQ_API_KEY…"`. Test này xoá **cả** `LLM_PROVIDER` nên phải đi nhánh 101 — nhánh `or` thứ hai
chỉ làm assert đúng với **hai** hành vi khác nhau. Bỏ nhánh `or`, chỉ giữ `"No valid LLM provider configured"`,
để test bắt được hồi quy thật.

> File này do C viết (`git log` → 2 commit của `Penguin-cell34`).

---

## Đã xong — KHÔNG làm lại

A/B đã sửa trong lượt này, đừng chạm vào:

- ✅ **T4a** — `REPORT_B_.md:118` provider/model: đã ghi đúng "log không lưu", không suy từ `llm.py:24`.
- ✅ **T4b** — `REPORT.md` §3.5 dense-vs-hybrid: đã có bảng số đo thật + phân tích `q01`/`q09`.
- ✅ **T4d** — `REPORT_B_.md:122`: `react_step.txt` được nạp thật qua `load_react_prompt()`, `judge.txt` không có code nạp.
- ✅ **T6** — `REPORT_PERSON_C.md`: model claim, `get_account_risk_status`, `368 passed`/`Python 3.13.5`,
  đường dẫn DB, cột `Tỷ lệ đóng góp` (đã xoá), `68 commits` (38/12/11/7), câu "không còn TODO", 7 link `file:///D:/Work/...`.
- ✅ **`REPORT_PERSON_C.md:74`** — câu đổ lỗi "cơ chế ẩn danh hóa dữ liệu (redaction)" cho `q05`/`q08` là **sai**, đã sửa
  thành **paraphrase**: `run_eval.py:284-300` tính `answer_correctness` **trước** `redact_for_log()` ở `:314`; log thật
  cho thấy `q05` có `44%` nhưng thiếu `220.000.000 VND`, `q08` viết "không **thể** ra quyết định khóa" thay vì
  "không **được** ra quyết định khóa". **Đừng đổ lỗi redaction ở bất kỳ đâu khác.**
- ✅ **README.md** số liệu — đã sửa (Python 3.13.5, 19 / 76 / 368 passed).

### Còn là hạn chế đã biết (ghi trong report, không sửa)

- **`faithfulness` = `Unscorable` 12/12** — adapter chưa sinh trường `claims`; đã giải thích đúng ở `REPORT.md` §6.2. **Giữ nguyên, đây là điểm trung thực.**
- **`context_precision` chỉ chấm được 1–2/12** — `metrics.py:73` trả `None` khi một context chứa nhiều mã `DOCnnnn`. Đã ghi ở §3.5 và §6.2.
- **`expected_refusal_type` thiếu trong `tests/testset.jsonl`** — loại (i)/(ii) chỉ suy ra lúc chấm gate. Không bắt buộc.
- **`reports/verification/c4_final_report.md` còn số cũ** (`359 passed, 1 skipped`, `CPython 3.14.7`). File này là
  báo cáo nội bộ, không phải deliverable — nhưng nếu GV đọc thì nên sửa hoặc ghi rõ "snapshot 2026-10-17".
