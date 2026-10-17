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
| C — testset / eval / log | **xong**: Testset (12 cases), offline & live evaluator qua MCP/agent adapter, metrics RAGAS + refusal rate, xuất CSV/SVG reports, JSONL event logs (phiên staging run `staging_20261017_201308` đạt semantic gate PASS). |

## Chạy

Các lệnh offline có trong Makefile:

```bash
make eval       # validate testset; không chạy agent và không ghi evaluation logs
make test       # pytest, target hiện không bao gồm tests/test_tools.py
```

`make setup` dùng `uv sync --locked --extra dev`. Lệnh `make demo` gọi agent và cần
Groq credentials/network cùng MCP runtime; tools ghi trạng thái chỉ được dùng khi
`TRFC_REQUIRE_ISOLATED_DB=1` và một isolated `TRFC_STATE_DB` được cấu hình. Không
xem demo là offline check.

**Trạng thái xác minh gần nhất của working tree:** full offline pytest suite đã pass
trên Python 3.14.7 bằng `.venv` của dự án: adapter tests **14 passed**, focused
regression suite **118 passed, 1 skipped**, full suite **142 passed, 1 skipped**.
`git diff --check` không có whitespace error; Git chỉ báo LF-to-CRLF working-copy
notices. Các kết quả trên chỉ xác nhận automated test coverage. Người dùng đã
báo cáo riêng MCP subprocess isolation PASS trên DB tạm; lần triển khai policy
offline này không chạy lại verifier. Chưa xác minh live Groq request hoặc
production policy metadata cho outcome/refusal/claims. Deterministic offline
policy tests dùng provenance `synthetic` và không phải genuine scenario evidence.
Không có live evaluation hoặc thao tác trên production database được xác nhận.

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
