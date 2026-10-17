# Khung `report.docx` — chia việc 3 người

> Mục tiêu: **8–9 trang**, đúng 9 mục theo `Ref/02-Yeu-cau-Thuc-hien.pdf` §5 và `CLAUDE.md` §7.
> Mỗi mục dưới đây ghi rõ: **ai viết**, **viết gì**, **số liệu lấy ở đâu**. Chỗ đánh dấu `[[TODO: ...]]` là **chưa có bằng chứng thật — không được bịa số**.
> Quy ước: A = Dữ liệu & Truy hồi · B = Agent & Tool/MCP · C = Đo lường & Tái lập.
> Người ghép & format `.docx`: **C** (`PHAN_CONG.md` §5).

---

## Bảng phân trang & người phụ trách

| Mục | Tên mục | Trang | Người viết chính | Người review |
|---|---|---|---|---|
| 1 | Vấn đề, phạm vi, giả định | 0.5–1 | **A** | B |
| 2 | Kiến trúc tổng thể | 1 | **B** (vẽ sơ đồ) | A, C |
| 3 | Thiết kế RAG | 1.5 | **A** | B |
| 4 | Thiết kế Agent & tool | 2 | **B** | A |
| 5 | MCP server | 1 | **B** | C |
| 6 | Đánh giá | 1.5 | **C** | A, B |
| 7 | Hạn chế & hướng phát triển | 0.5 | **A** | C |
| 8 | Phân công & đóng góp | 0.5 | **C** | cả 3 |
| 9 | Phụ lục | — | **B** | C |
| — | Ghép, format, mục lục | — | **C** | — |
| **Tổng** | | **≈ 8.5** | | |

**Deadline nội bộ:** A/B gửi bản nháp Markdown cho C trước **CP5** (ngày 10); C ghép + format trong 1 buổi.

---

## §1 — Vấn đề, phạm vi, giả định · 0.5–1 trang · **A**

**Phải có**

1. **Bài toán** (3–4 câu): chuyên viên Risk & Compliance phải tra quy định + đối chiếu hạn mức + khoá tài khoản nghi vấn; hiện làm thủ công, không truy được nguồn, không có log quyết định.
2. **Người dùng**: chuyên viên Risk/Compliance (không phải khách hàng cuối).
3. **Hệ thống LÀM gì**: tra cứu có trích dẫn `doc_id` + `version` → tính/so sánh → gọi tool ghi (freeze/flag) → đọc lại verify.
4. **Hệ thống KHÔNG làm gì** (bắt buộc theo yêu cầu §1 — "và hệ thống **KHÔNG làm gì**"):
   - Không phải hệ thống phát hiện gian lận thời gian thực; không có streaming.
   - Không kết nối core banking thật — dữ liệu giao dịch là SQLite mô phỏng (`data/state.db`).
   - Không tự động khoá tài khoản không có người duyệt trong production; mọi write đều qua guard cô lập DB.
   - Không tư vấn pháp lý; không thay thế quyết định của con người.
5. **Giả định** (3 gạch đầu dòng): corpus 9 tài liệu là bản hiện hành trừ DOC0003 (bản cũ đã bị thay thế); `tier` eKYC lấy từ hồ sơ tài khoản; một tài khoản chỉ thuộc một tầng.

**Lấy từ**: `DE_TAI_TRFC_Agent.md` §1–§2 · `data/docs/DOC0003.md` (bản 2025.2 đã bị thay thế).

---

## §2 — Kiến trúc tổng thể · 1 trang · **B** (vẽ), A+C review

**Phải có**

1. **Sơ đồ khối** (1 hình, in sẵn — GV yêu cầu "sơ đồ in sẵn", không đọc slide). Vẽ 4 ranh giới:

```
┌──────────────┐   prompt .txt   ┌──────────────────┐
│  CLI / User  │ ──────────────▶ │  ReAct loop (B)  │
└──────────────┘                 │  MAX_STEPS = 8   │
                                 └───┬──────────┬───┘
                        tool call    │          │  tool call
                     ┌───────────────┘          └──────────────┐
                     ▼                                         ▼
            ┌─────────────────┐                    ┌──────────────────────┐
            │ tools/impl.py   │                    │ MCP server (stdio)   │
            │ 5 tool          │◀── cùng impl ─────▶│ 5 tool, stdout sạch  │
            └───┬────────┬────┘                    └──────────┬───────────┘
                │        │                                    │
        ┌───────▼──┐  ┌──▼────────┐                   ┌───────▼────────┐
        │ RAG      │  │ SQLite    │                   │ client2.py     │
        │ dense +  │  │ state.db  │                   │ (host thứ hai) │
        │ hybrid   │  │ (write)   │                   └────────────────┘
        └───────┬──┘  └───────────┘
                ▼
        ┌───────────────┐
        │ data/docs/    │
        │ DOC0001–0009  │
        └───────────────┘
```

2. **Luồng 1 câu hỏi mẫu** (dùng trace §4, không lặp lại toàn bộ): `search_policy → get_transactions → freeze_account_temporarily → get_account_risk_status (verify)`.
3. **Bảng ranh giới trách nhiệm** — 1 bảng 3 dòng: RAG (A) · Agent+Tool+MCP (B) · Eval+Log (C). Nêu rõ **MCP server và agent dùng chung `tools/impl.py`**, nên hành vi tool giống nhau ở cả 2 đường.

**Lấy từ**: `src/trfc/agent/loop.py`, `src/trfc/tools/impl.py`, `src/trfc/mcp_server/server.py`, `src/trfc/rag/search.py`.

---

## §3 — Thiết kế RAG · 1.5 trang · **A**

**Phải có**

1. **Corpus** — bảng 9 dòng: `doc_id` · tiêu đề · `version` · `owner`. Ghi rõ 16.920 token (tiktoken cl100k_base), vượt mốc 10.000 của syllabus.
2. **Chunking + lý do (3–5 dòng bắt buộc)** — copy từ `DE_TAI_TRFC_Agent.md:59-66`, rút còn 4 ý:
   - cắt theo Chương → Điều → Khoản vì văn bản quy định có cấu trúc phân cấp sẵn;
   - `chunk_size=400` đủ 1 Điều trung bình, giữ 3–5 chunk trong context;
   - `overlap=50` chỉ bắc cầu đoạn dài qua ranh giới Điều;
   - **bảng markdown atomic** — không cắt vỡ bảng hạn mức (rủi ro gán sai tầng eKYC).
   - 3 tham số nằm trong `config.toml`, không hard-code.
3. **Embedding + vector store**: backend nào (hashing offline hay API), chiều vector, similarity = cosine, top-K kèm `score`.
4. **Dense vs Hybrid**: công thức fuse `0.3*BM25_norm + 0.7*cosine`; giải thích **vì sao hybrid** (truy vấn có mã/từ chính xác như "eKYC", "DOC0007" thì BM25 thắng; câu diễn đạt tự nhiên thì dense thắng).
5. **Metadata filter `tier`** — đoạn quan trọng nhất, GV sẽ hỏi:
   - Vì sao không lọc được ở mức chunk: một chunk chứa **cả 3 tầng** trong bảng atomic.
   - Cách làm: mỗi dòng `| Tầng N | ...` sinh một **view** cùng `doc_id`/`chunk_index`, chỉ giữ dòng tầng N (`store._tier_views`).
   - Pre-filter **trước** rank → chunk sai tầng không bao giờ chiếm slot top-K.
   - ⚠️ `[[TODO: C bổ sung số ca testset có tier thật]]` — hiện testset **chưa có** câu nào truyền `tier`; nếu không thêm thì **không được claim điểm cộng +1**, chỉ mô tả như năng lực của tool.
6. **Bảng so sánh dense vs hybrid** (nếu C chạy được) `[[TODO: số từ make eval]]`; nếu không có, ghi rõ "chưa đo, xem §7".

**Lấy từ**: `data/docs/*.md`, `src/trfc/rag/chunking.py`, `embed.py`, `store.py:53-112`, `search.py:55-76`, `config.toml`.

**Câu GV chắc chắn hỏi** (chuẩn bị trước): `chunk_size=400` chọn thế nào? Thử 200 thì hỏng ở đâu? · Filter trước hay sau rank, vì sao? · Chỉ dòng code giữ bảng atomic.

---

## §4 — Thiết kế Agent & tool · 2 trang · **B**

**Phải có**

1. **Tool schema bằng `@dataclass`** (yêu cầu 2.3) — dán `Chunk`, `RiskStatus` (rút gọn `Transaction`, `Ack`), kèm 1 câu: *không dùng dict thô vì GV `grep -n "@dataclass"`*.
2. **Bảng 5 tool**: tên · đọc/ghi · chữ ký · trả về. Đánh dấu rõ 2 tool ghi.
3. **Mô tả tool viết như prompt** — dán docstring thật của `freeze_account_temporarily` và `flag_suspicious_tx`; giải thích agent chỉ chọn đúng tool khi mô tả nêu rõ *khi nào dùng / khi nào không*.
4. **Vòng lặp ReAct** (yêu cầu 2.2): sơ đồ 1 dòng `LLM → parse action → gọi tool → quan sát → lặp`; nói rõ **tự viết**, không LangChain.
5. **`MAX_STEPS = 8`** — lý do: trace điển hình ~5 bước, 8 đủ headroom; hết bước thì trả lỗi có kiểm soát (`loop.py:671`).
6. **Xử lý lỗi** (yêu cầu 2.6):
   - tool lỗi trả `"Error: ..."`, **không raise** (`loop.py:251`, `:716`) — kèm **1 ví dụ trace thật** nếu có;
   - parse action an toàn: JSON hỏng/thiếu ngoặc → trả `"Error: No valid action JSON block found..."`, run không chết (`parse.py`).
7. **`call_llm`** (yêu cầu 2.4): retry có backoff, timeout 30s, log lỗi HTTP kèm `status_code`, xử lý riêng 429; prompt nằm trong `prompts/*.txt`.
8. **Side effect + verify** (yêu cầu 2.7) — **mục ăn điểm nhất**:
   - ghi SQLite thật vào `state.db`, không mock `"OK"`;
   - verify gọi `get_account_risk_status`, chứng minh `checked_at > frozen_at` (freeze) hoặc `tx_id ∈ flagged_tx_ids` (flag);
   - **dán trace thật 1 câu hỏi** (dạng bảng: step · thought · action · args · observe). `[[TODO: trace từ logs/ thật]]`.
9. **Guard an toàn**: write tool chỉ chạy khi `TRFC_REQUIRE_ISOLATED_DB=1` + `TRFC_STATE_DB` trỏ ra ngoài repo.

**Lấy từ**: `src/trfc/tools/schemas.py`, `impl.py`, `src/trfc/agent/loop.py`, `parse.py`, `llm.py`, `prompts/*.txt`, `.env.example` §4.

**Câu GV chắc chắn hỏi**: hết `MAX_STEPS` thì sao? · Vì sao trả chuỗi thay vì raise — cho ví dụ cứu cả run? · Chứng minh agent dùng kết quả tool chứ không tự diễn.

---

## §5 — MCP server · 1 trang · **B**

**Phải có**

1. **Bảng tool + contract**: 5 tool, ≥1 ghi (thực tế 2 ghi); transport **stdio**.
2. **stdout sạch**: log handler gắn `sys.stderr` (`server.py:23`); giải thích *nếu `print()` ra stdout thì JSON-RPC frame bị hỏng → client parse fail*.
3. **Discover động**: client gọi `session.list_tools()` (`client2.py:39`), không hard-code tên tool; thêm tool mới thì client **không phải sửa**. Dán đoạn `validate_arguments` kiểm tra `input_schema` lấy từ server.
4. **Host thứ hai** (điểm cộng +1): `client2.py` độc lập với agent, do **C viết** (không phải người viết server) → chứng minh interop thật.
5. **Giới hạn trung thực**: nếu chưa chạy live Groq qua MCP, ghi đúng mức đã xác minh (offline/subprocess trên DB tạm).

**Lấy từ**: `src/trfc/mcp_server/server.py:45-110`, `client2.py`, `tests/test_client2.py`.

---

## §6 — Đánh giá · 1.5 trang · **C**

**Phải có**

1. **Testset** — bảng phân bố 12 câu: `retrieval` 3 · `calc` 2 · `contradiction` 2 · `multi_doc` 1 · `no_answer` 4 (loại i = 2, loại ii = 2). Nêu **vì sao phải đo cặp** faithfulness + tỉ lệ từ chối đúng (nếu chỉ đo faithfulness, hệ thống luôn từ chối sẽ được điểm cao giả).
2. **Cách đo**: faithfulness (claim có được context hỗ trợ), context precision (theo `doc_id` gold), refusal correctness **tách i/ii**. Ghi rõ là so khớp chuỗi xác định, không phải LLM-judge — và hệ quả (rẻ, tái lập được, nhưng bỏ sót paraphrase).
3. **Kết quả**: bảng từng câu (id · category · faithfulness · context precision · refusal đúng · calls · prompt_tokens · completion_tokens · max_prompt). `[[TODO: chỉ điền từ logs/ thật]]`.
4. **Chi phí token từng câu** + tổng cả testset (bắt buộc theo §6).
5. **≥1 ca thất bại + phân tích** — chọn câu điểm thấp nhất, nêu nguyên nhân (retrieval sai / reasoning sai / thiếu dữ liệu) và đề xuất sửa.
6. **Trạng thái bằng chứng**: nếu `logs/` chưa có, **ghi rõ "chưa có lần chạy thật"**, không điền số. Xem `FIX_C.md` F1–F2.

**Lấy từ**: `tests/testset.jsonl`, `eval/metrics.py`, `eval/run_eval.py`, `eval/report.py`, `logs/staging_*/`.

---

## §7 — Hạn chế & hướng phát triển · 0.5 trang · **A**

**Phải có ≥2 hạn chế TRUNG THỰC** — không viết "chưa có thời gian". Gợi ý (chọn 3):

1. **Embedding offline bằng hashing** — không nắm ngữ nghĩa tiếng Việt; chuyển sang `sentence-transformers` hoặc API embedding sẽ cải thiện recall.
2. **Faithfulness đo bằng so khớp chuỗi** — bỏ sót câu diễn đạt lại; RAGAS/LLM-judge chính xác hơn nhưng đắt và khó tái lập.
3. **Corpus chỉ 9 tài liệu, 1 domain** — chưa kiểm chứng khi corpus lớn (hàng trăm doc) hoặc có nhiều version chồng lấn.
4. **Metadata filter `tier` chưa dùng trong testset** — năng lực có nhưng chưa có bằng chứng eval.
5. **Chưa có live verification đầy đủ** với provider/MCP trong môi trường production.

**Hướng phát triển**: 1 đoạn ngắn — rerank, streaming, human-in-the-loop cho write tool, audit trail bất biến.

---

## §8 — Phân công & đóng góp · 0.5 trang · **C**

**Phải có bảng** (GV đối chiếu khi vấn đáp):

| Thành viên | Vai trò | File phụ trách | Commit hash | Điểm |
|---|---|---|---|---|

Lấy hash bằng:

```bash
git log --author="<tên>" --format="%h %s" | head -5
```

Hiện có 4 tài khoản commit (Do Ngo 21 · CapyCoder 10 · Penguin-cell34 9 · Do Coding 7); ghi chú 2 bạn Do Ngo/Do Coding dùng chung phần B. `[[TODO: hash cuối cùng — lấy sau khi mọi người commit xong]]`.

---

## §9 — Phụ lục · không tính trang · **B**

1. **Prompt gốc**: dán nguyên văn `prompts/system.txt`, `react_step.txt`, `judge.txt`, `decision.txt` (hoặc đường dẫn nếu quá dài).
2. **Trace dài**: 1 trace đầy đủ dạng JSONL từ `logs/`.
3. **`ai-usage.md`**: dán nguyên file.
4. **`.env.example`** (rút gọn, không có key thật).

---

## Checklist trước khi ghép `.docx`

- [ ] Đủ 9 mục, đúng thứ tự, **8–9 trang** (đếm trang sau khi format)
- [ ] §2 có **1 hình sơ đồ in sẵn**
- [ ] §3 có **3–5 dòng lý do chunking**
- [ ] §4 có **trace thật** + `MAX_STEPS` + `"Error: ..."` + verify
- [ ] §5 có bảng tool + stdout + discover
- [ ] §6 có **bảng token từng câu** + **≥1 ca thất bại**
- [ ] §7 có **≥2 hạn chế trung thực**, không có "chưa có thời gian"
- [ ] §8 có **commit hash** từng người
- [ ] Không có `[[TODO:` nào còn sót
- [ ] Không có số liệu nào không truy được về `logs/` hoặc `make eval`
