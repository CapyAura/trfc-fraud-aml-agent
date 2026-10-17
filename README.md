# TRFC Agent — Trợ lý Kiểm soát Rủi ro & Gian lận Giao dịch

Final project môn AIPR. Trợ lý cho chuyên viên Risk & Compliance: tra cứu quy định có trích dẫn,
tính toán / đối chiếu hạn mức giao dịch, khóa tạm thời tài khoản nghi vấn — kèm bước verify đọc lại
trạng thái để chứng minh hành động đã có hiệu lực.

## Trạng thái

Các thành phần A, B và C đã có implementation trong working tree. Việc có code và fake-based
unit tests không đồng nghĩa tích hợp live đã được xác minh; xem [evaluation status](eval/README.md)
để biết các giới hạn và blocker hiện tại.

| Lát cắt | Trạng thái |
|---|---|
| A — corpus | **xong**: 9 tài liệu, 16.293 token (tiktoken cl100k_base) |
| A — chunking | **xong**: cắt theo Chương→Điều→Khoản, bảng markdown atomic |
| A — embed / store / search | **xong**: dense + hybrid BM25 (`0.3*BM25_norm + 0.7*cosine`), top-K kèm score, pre-filter `tier` |
| B — tool / agent loop / MCP | Có native Groq tool-call loop, MCP client/server và fail-closed guard cho write tools. MCP subprocess isolation đã được người dùng xác minh trên DB tạm; live Groq/MCP interoperability chưa xác minh. |
| C — testset / eval / log | **xong**: Testset (12 cases), offline & live evaluator qua MCP/agent adapter, metrics RAGAS + refusal rate, xuất CSV/SVG reports, JSONL event logs. Hai phiên staging độc lập đạt semantic gate PASS: `staging_20261017_201308` và `staging_20261018_035803`. |

## Chạy

Cần **GNU make**. Trên Windows không có sẵn `make` (chỉ có `mingw32-make`), nên dùng
Git Bash/WSL hoặc chạy trực tiếp lệnh Python tương đương bên dưới.

```bash
make eval       # tái lập số liệu report: chấm lại log thật, so từng byte với eval/reports, chạy lại semantic gate
make test       # pytest, target hiện không bao gồm tests/test_tools.py
make eval-live  # chạy lại agent + LLM thật để sinh log mới; cần key + network + DB cách ly
```

Lệnh tương đương khi không có `make`:

```powershell
.\.venv\Scripts\python.exe -m eval.run_eval --dry-run                       # = make eval (bước 1)
.\.venv\Scripts\python.exe -m eval.report --input logs/staging_20261017_201308/evaluation.jsonl `
    --output-dir .test-tmp/eval-repro --rescore                             # = make eval (bước 2)
.\.venv\Scripts\python.exe -m pytest --ignore=tests/test_tools.py           # = make test
.\.venv\Scripts\python.exe -m eval.run_eval --agent-adapter eval.agent_adapter:run_case `
    --output logs/evaluation.jsonl                                          # = make eval-live
.\.venv\Scripts\python.exe -m eval.report --input logs/evaluation.jsonl `
    --output-dir eval/reports --rescore
```

`make setup` dùng `uv sync --locked --extra dev`. Lệnh `make demo` gọi agent và cần
LLM credentials/network cùng MCP runtime. Target này **tự** đặt
`TRFC_REQUIRE_ISOLATED_DB=1` và trỏ `TRFC_STATE_DB` vào một file DB dùng-một-lần ngoài
repo (rồi `reset()` seed lại mỗi lần), nên `data/state.db` production không bị đụng —
không cần cấu hình tay. Không xem demo là offline check.

**Trạng thái xác minh gần nhất của working tree:** full offline pytest suite đã pass
trên Python 3.13.5 bằng `.venv` của dự án: adapter tests **19 passed**, focused
regression suite (`test_tools` + `test_native_tool_calling` + `test_client2` +
`test_db_isolation`) **76 passed**, full suite (`pytest -q`, gồm cả `test_tools.py`) **407 passed,
0 skipped** — `make test` loại `tests/test_tools.py` nên báo **403 passed**.
`git diff --check` không có whitespace error; Git chỉ báo LF-to-CRLF working-copy
notices. Các kết quả trên chỉ xác nhận automated test coverage. Người dùng đã
báo cáo riêng MCP subprocess isolation PASS trên DB tạm; lần triển khai policy
offline này không chạy lại verifier. Có live evaluation thật (agent + LLM + MCP,
DB tạm ngoài repo) ở `logs/staging_20261017_201308/` và `logs/staging_20261018_035803/`
— report trích số từ phiên `201308`.
`claims` vẫn không được runtime sinh ra nên `faithfulness` chưa chấm được.
Deterministic offline policy tests dùng provenance `synthetic` và không phải
genuine scenario evidence. Không có thao tác nào trên production database.

## Tài liệu

| File | Nội dung |
|---|---|
| [DE_TAI_TRFC_Agent.md](DE_TAI_TRFC_Agent.md) | Thiết kế đề tài: 3 tầng, corpus & chunking, retrieval, tool contract, agent loop, testset, đánh giá |
| [CLAUDE.md](CLAUDE.md) | Tổng hợp yêu cầu học phần: deliverables, yêu cầu kỹ thuật 2.1–2.8, thang điểm, checklist nộp |
| [PHAN_CONG.md](PHAN_CONG.md) | Phân công 3 thành viên, mốc thời gian, hợp đồng giao diện |
| [data/docs/README.md](data/docs/README.md) | Corpus: 9 tài liệu, lý do không tái dùng DOC0001–0006 của lớp |
| [ai-usage.md](ai-usage.md) | Khai báo dùng AI (bắt buộc nộp) |

Tham số pipeline nằm ở [config.toml](config.toml) — `chunk_size`, `overlap`, trọng số hybrid,
`max_steps`. Không hard-code trong code.
