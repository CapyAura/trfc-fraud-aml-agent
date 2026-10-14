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
| B — tool / agent loop / MCP | Có native Groq tool-call loop, MCP client/server và fail-closed guard cho write tools. Live Groq/MCP interoperability và subprocess database isolation **chưa xác minh**; runtime files cần Person B review. |
| C — testset / eval / log | Testset, offline evaluator, metrics, reports, JSONL validation và best-effort log redaction đã có. C4 **chưa hoàn tất**: không có genuine scenario logs, metadata authoritative còn thiếu, và MCP subprocess isolation chưa được xác minh. |

## Chạy

Các lệnh offline có trong Makefile:

```bash
make eval       # validate testset; không chạy agent và không ghi evaluation logs
make test       # pytest, target hiện không bao gồm tests/test_tools.py
```

`make setup` dùng `uv sync --locked --group dev`. Lệnh `make demo` gọi agent và cần
Groq credentials/network cùng MCP runtime; tools ghi trạng thái chỉ được dùng khi
`TRFC_REQUIRE_ISOLATED_DB=1` và một isolated `TRFC_STATE_DB` được cấu hình. Không
xem demo là offline check.

**Trạng thái xác minh gần nhất của working tree:** test chạy bằng Python hệ thống bị
blocked vì môi trường đó không có `pytest`. Python trong `.venv` trỏ tới interpreter
uv-managed không còn ở vị trí ghi trong `pyvenv.cfg`; lần thử targeted test không đạt
assertion và bị dừng. AST syntax check cho timeout changes và `git diff --check` đã
pass. `python -m eval.run_eval --dry-run` hiện pass với 12 cases và không gọi
agent/API hay ghi score. Một lượt trước đó từng báo 22 passed và 4 deselected; kết quả đó có trước
timeout change mới nhất và không xác minh working tree hiện tại. `make test` chủ
động loại `tests/test_tools.py` bằng `--ignore`, nên module đó không được chạy bởi
target này. Không có test nào bị tính pass chỉ vì đã bị deselect hoặc không chạy được.

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
