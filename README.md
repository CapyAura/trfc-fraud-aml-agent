# TRFC Agent — Trợ lý Kiểm soát Rủi ro & Gian lận Giao dịch

Final project môn AIPR. Trợ lý cho chuyên viên Risk & Compliance: tra cứu quy định có trích dẫn,
tính toán / đối chiếu hạn mức giao dịch, khóa tạm thời tài khoản nghi vấn — kèm bước verify đọc lại
trạng thái để chứng minh hành động đã có hiệu lực.

## Trạng thái

Đang dựng. Lát cắt của A (corpus → chunking → retrieval) đã xong; tool/agent/MCP và eval còn là
khung rỗng có docstring, chưa cài đặt.

| Lát cắt | Trạng thái |
|---|---|
| A — corpus | **xong**: 9 tài liệu, 16.293 token (tiktoken cl100k_base) |
| A — chunking | **xong**: cắt theo Chương→Điều→Khoản, bảng markdown atomic |
| A — embed / store / search | **xong**: dense + hybrid BM25 (`0.3*BM25_norm + 0.7*cosine`), top-K kèm score, pre-filter `tier` |
| B — tool / agent loop / MCP | **xong** |
| C — testset / eval / log | khung rỗng, mốc CP4 |

## Chạy

```bash
make setup && make demo      # CHƯA chạy được — demo cần agent loop của B (CP3)
```

Phần đã xong kiểm tra được ngay (chưa cần API key — `embed.py` tự rơi về offline-hashing):

```bash
python -m pytest tests/test_chunking.py
python -m trfc.rag.embed                              # self-check embedding
python -m trfc.rag.search "hạn mức giao dịch tầng eKYC 2" --tier 2
python -m trfc.rag.search "giao dịch bất thường cần báo cáo" --mode dense   # so sánh dense vs hybrid
```

Chạy trực tiếp từ gốc repo cần `PYTHONPATH=src` nếu chưa `pip install -e .`.

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
