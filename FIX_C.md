# Việc cần fix — Person C

> Lập ngày 2026-10-17. Đối chiếu [PHAN_CONG.md](PHAN_CONG.md) §4 (C1–C8), [CLAUDE.md](CLAUDE.md) §4–§5, §12.
> A1–A6 và B1–B7 đều ✅ và code chạy đúng. Toàn bộ việc còn lại thuộc C.
>
> **Ưu tiên: F1 → F2 → F3 → F4 → F5.** F1 và F2 là điều kiện chặn nộp.

---

## F1 🔴 `logs/` không có lần chạy thật nào

**Hiện trạng**

```
logs/
└── README.md          # chỉ có hướng dẫn, không có .jsonl
```

`git ls-files logs` → chỉ ra `logs/README.md`. Không nhánh nào (`main`, `origin/main`, `origin/master`) từng chứa file log. `logs/staging*` **không** nằm trong [.gitignore](.gitignore), nên nếu có thật thì đã hiện untracked — tức là chưa từng được tạo trên máy này.

**Yêu cầu học phần** ([CLAUDE.md](CLAUDE.md) §4 mục 3, C4):

> `logs/` — ≥3 lần chạy thật, mỗi lần 1 file `jsonl` có timestamp, các bước, tool args/kết quả, `USAGE` từng câu (calls, prompt/completion tokens)

[logs/README.md](logs/README.md) cũng tự ghi: *"3 lần chạy phải KHÁC NHAU CÓ CHỦ ĐÍCH (1 freeze / 1 flag / 1 từ chối)"*.

**Cách fix**

```powershell
# 1. Kiểm tra provider đã cấu hình (không dán key vào đây)
$env:LLM_PROVIDER   # groq | deepseek | custom
$env:GROQ_API_KEY   # hoặc LLM_API_KEY

# 2. Chạy staging thật — script đã có sẵn
pwsh -File scripts/run_c4_staging.ps1
```

Script tạo `logs/staging_<STAMP>/` gồm `evaluation.jsonl`, `step_events.jsonl`, `decision_events.jsonl`, `semantic_gate_result.json`, `reports/`. Nó đã có sẵn: seed DB cô lập ngoài repo, đối soát SHA256 `data/state.db` trước/sau, assert 12 case `status=completed`, validate 3 schema, chạy semantic gate.

**Sau khi chạy xong**

```powershell
git add logs/staging_<STAMP>
git commit -m "chore(logs): add real C4 staging run"
```

**Lưu ý**
- Chạy lại 3 lần nếu lần đầu chưa phủ đủ 3 kịch bản. Testset đã có: `q05` freeze, `q06` flag, `q09–q12` refusal — một lần chạy đủ 12 case là phủ cả 3.
- Nếu staging fail vì hết quota / 429: **không** giả log. Ghi lại lỗi và báo, đừng commit log rỗng.
- Log đã qua `eval/redaction.py` (best-effort). Đọc lại 1 lần trước khi commit.

---

## F2 🔴 `c4_final_report.md` tuyên bố PASS trên bằng chứng không tồn tại

**Hiện trạng**

[reports/verification/c4_final_report.md:3](reports/verification/c4_final_report.md#L3):

> **Current Verified Status (2026-10-17): PASS — ALL ACCEPTANCE GATES SATISFIED.**

Report dẫn `logs/staging_20261017_201308/` ở 6 dòng khác nhau (L4, L15, L17, L18, L19, L20, L22), kèm:
- DB cô lập `D:\Work\AIPR\staging_c4_20261017_201308\state.db` — không kiểm chứng được từ repo
- "359 passed, 1 skipped" (L21) — **suite hiện tại chạy ra 327 passed, 1 failed**
- `eval/reports/` chứa `evaluation.csv`, `faithfulness.svg`, `refusal_correctness.svg` — không có trong repo

**Mâu thuẫn nội bộ:** [README.md:19](README.md#L19) và [eval/README.md:168](eval/README.md#L168) đều ghi *"C4 **chưa hoàn tất**"* / *"No genuine run logs are included. C4 remains pending"*.

**Cách fix**

Không sửa chữ. Chỉ có 2 đường:

1. **Nếu log có thật ở máy khác** → copy vào `logs/staging_20261017_201308/`, commit, rồi chạy lại suite để lấy con số đúng. Sửa L21 thành số thực tế.
2. **Nếu log chưa từng tồn tại** → hạ L3 xuống `INCOMPLETE — evidence missing`, đổi các ô `PASS` ở cột "Verified" thành `NOT VERIFIED`, rồi làm F1. Sau khi có log thật mới nâng lại.

Đường 2 là mặc định cho tới khi chứng minh được đường 1.

---

## F3 🔴 `make setup` hỏng → cold-start trên máy GV fail

**Hiện trạng**

[Makefile:11](Makefile#L11):

```make
setup:
	uv sync --locked --group dev
```

Lỗi thật:

```
error: Group `dev` is not defined in the project's `dependency-groups` table
```

[pyproject.toml:16-18](pyproject.toml#L16-L18) khai báo `dev` trong `[project.optional-dependencies]`, không phải `[dependency-groups]`. Đúng phải là `--extra dev`.

**Cách fix**

```make
setup:
	uv sync --locked --extra dev
```

Sửa luôn 2 chỗ đang lặp lại lệnh sai:
- [README.md:30](README.md#L30)
- [Makefile.txt:13](Makefile.txt#L13)

**Test:** xoá `.venv/`, chạy `make setup`, phải thấy `pytest` cài được.

**Lỗi thứ hai cùng file** — `make test` ([Makefile:22](Makefile#L22)) dùng `--basetemp .test-tmp/pytest` nhưng pytest **không tạo thư mục cha**. Trên máy sạch sẽ ra 151 lỗi `FileNotFoundError: [WinError 3] ... '.test-tmp\pytest2'`. Fix:

```make
test:
	mkdir -p .test-tmp
	$(PY) -m pytest --ignore=tests/test_tools.py --basetemp .test-tmp/pytest
```

(PowerShell: `if (-not (Test-Path .test-tmp)) { New-Item -ItemType Directory .test-tmp }` — hoặc đơn giản bỏ `--basetemp`, pytest tự dùng temp của OS.)

---

## F4 🟠 1 test fail — assert cũ, không phải bug code

**Hiện trạng**

```
tests/test_native_tool_calling.py::test_missing_provider_key_fails_before_constructing_or_calling_a_client
AssertionError
```

[test_native_tool_calling.py:408](tests/test_native_tool_calling.py#L408) còn assert chuỗi cũ:

```python
assert "Missing GROQ_API_KEY" in str(exc)
```

Trong khi [llm.py](src/trfc/agent/llm.py) đã đổi sang thông báo multi-provider:

> `No valid LLM provider configured. Please set GROQ_API_KEY for Groq, or LLM_BASE_URL and LLM_API_KEY for DeepSeek/custom OpenAI-compatible gateway, or specify LLM_PROVIDER.`

**Cách fix**

```python
assert "No valid LLM provider configured" in str(exc)
```

Test này do C viết ([ai-usage.md:117](ai-usage.md#L117)), nên C sửa. **Không** sửa `llm.py` cho khớp test — thông báo mới đúng hơn vì code hỗ trợ 4 provider.

Sau khi fix: `327 passed` → `328 passed, 0 failed`.

---

## F5 🟠 Các mục còn lại

| # | Việc | File | Ghi chú |
|---|---|---|---|
| F5a | Sinh `eval/reports/` (CSV + SVG) | `eval/reports/` | `make report` — cần `logs/evaluation.jsonl` từ F1 trước. Đây là điểm cộng **+1** (đồ thị + CSV) |
| F5b | Cân nhắc đưa `tests/test_tools.py` vào `make test` | [Makefile:22](Makefile#L22) | Test pass 4/4 khi chạy riêng. Lý do loại trừ là file này `reset()` `data/state.db` — nếu giữ loại trừ thì ghi rõ lý do trong README (đã có ở `Makefile.txt`), không thì để nguyên |
| F5c | Tick C1–C8 trong [PHAN_CONG.md](PHAN_CONG.md) §4 | `PHAN_CONG.md` | C1–C8 hiện **0 ô tick** dù code đã có. GV nhìn checklist đầu tiên |
| F5d | Commit `ai-usage.md` | `ai-usage.md` | Đang `M` chưa commit, +74/−35. Nội dung đã merge xong |
| F5e | `report.docx` 8–9 trang, 9 mục | gốc repo | Việc của C theo [PHAN_CONG.md:114](PHAN_CONG.md#L114). Cần §8 có **commit hash** — lấy từ `git log --author` sau khi mọi người commit xong |

---

## Không cần làm

- **A** — `src/trfc/rag/`, `data/docs/`, `config.toml`: A1–A6 ✅, không đụng.
- **B** — `src/trfc/tools/`, `src/trfc/mcp_server/`, `src/trfc/agent/`, `prompts/`: B1–B7 ✅. 5 tool có thật, MCP client discover động qua `list_tools()`, `MAX_STEPS` + `"Error: ..."` + verify đều có.
- **Testset** — 12 câu, 4 `no_answer` (`q09–q12`), có `scenario` (`freeze`/`flag`/`refusal`) và `refusal_type`. Đạt yêu cầu, đừng sửa.

---

## Thứ tự chạy

```powershell
# 1. Fix Makefile + test assert  (F3, F4)
# 2. Xác minh trên máy sạch
Remove-Item -Recurse -Force .venv
make setup
make test                     # kỳ vọng: 328 passed

# 3. Chạy staging thật  (F1)
pwsh -File scripts/run_c4_staging.ps1

# 4. Sinh report + chart  (F5a)
make report

# 5. Commit
git add logs/ eval/reports/ Makefile README.md Makefile.txt tests/test_native_tool_calling.py ai-usage.md PHAN_CONG.md
git commit -m "fix(eval): repair make setup, stale test assert, and add real C4 staging logs"

# 6. Sửa c4_final_report.md theo bằng chứng thật  (F2)
```

---

## Câu hỏi cần C trả lời trước khi ai sửa gì

1. `logs/staging_20261017_201308/` — có thật ở máy nào không? Nếu có, sao chưa push?
2. Report ghi "359 passed" — suite đó chạy ở commit nào? Hiện tại là 327 passed / 1 failed.
3. DB cô lập `D:\Work\AIPR\staging_c4_20261017_201308\state.db` còn tồn tại không? Nếu còn, log của nó ở đâu?
