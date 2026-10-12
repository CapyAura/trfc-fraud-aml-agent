# TRFC Agent — Trợ lý Kiểm soát Rủi ro & Gian lận Giao dịch

Final project môn AIPR. Trợ lý cho chuyên viên Risk & Compliance: tra cứu quy định có trích dẫn,
tính toán / đối chiếu hạn mức giao dịch, khóa tạm thời tài khoản nghi vấn — kèm bước verify đọc lại
trạng thái để chứng minh hành động đã có hiệu lực.

## Trạng thái

Đang dựng. Lát cắt của A (corpus + chunking) đã xong; tool/agent/MCP và eval còn là khung rỗng
có docstring, chưa cài đặt.

| Lát cắt | Trạng thái |
|---|---|
| A — corpus | **xong**: 9 tài liệu, 16.293 token (tiktoken cl100k_base) |
| A — chunking | **xong**: cắt theo Chương→Điều→Khoản, bảng markdown atomic; 4 test pass |
| A — embed / store / search | khung rỗng — `search_policy` còn `raise NotImplementedError` |
| B — tool / agent loop / MCP | khung rỗng, mốc CP2 |
| C — testset / eval / log | khung rỗng, mốc CP4 |

## Chạy

```bash
make setup && make demo      # CHƯA chạy được — demo cần agent loop của B (CP3)
```

Phần đã xong kiểm tra được ngay:

```bash
python -m pytest tests/test_chunking.py
```

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
