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

### 1.1 Bài toán

Chuyên viên Risk & Compliance phải trả lời liên tục hai câu: *giao dịch này có vi phạm quy định
không*, và *nếu có thì làm gì ngay*. Hiện làm thủ công: mở file quy định, đối chiếu hạn mức theo
tầng eKYC, cộng dồn giá trị trong ngày, rồi quyết định khoá tài khoản hay đánh dấu giao dịch. Ba
điểm yếu: (1) không truy được câu trả lời về **đúng điều khoản và đúng phiên bản**; (2) cộng dồn
theo ngày dễ sai, không lặp lại được; (3) quyết định không để lại dấu vết nên không kiểm toán được.

TRFC Agent biến quy trình đó thành vòng lặp có bằng chứng: **tra cứu → tính/so sánh → hành động →
tự kiểm chứng**. Mọi kết luận truy được về `doc_id`, mọi hành động có bước đọc lại chứng minh.
Người dùng là **chuyên viên Risk & Compliance nội bộ** đã biết nghiệp vụ, cần công cụ tăng tốc và
tạo dấu vết — **không phải** khách hàng cuối hay chatbot tư vấn chung.

### 1.2 Hệ thống làm gì

1. **Tra cứu có trích dẫn** — `[Source: <doc_id>, chunk <n>]`; `Chunk` mang `version` và `tier`
   nên phân biệt được DOC0003 (2025.2) với DOC0007 (2026.1).
2. **Biến đổi** — cộng dồn giao dịch trong ngày, tính % vượt hạn mức theo tầng, đối chiếu quy tắc
   bất khả thi địa lý, phát hiện mâu thuẫn giữa hai phiên bản tài liệu.
3. **Hành động + verify** — gọi tool ghi (`freeze_account_temporarily`, `flag_suspicious_tx`) rồi
   **bắt buộc** đọc lại bằng `get_account_risk_status` để chứng minh trạng thái đã đổi.
4. **Từ chối có phân loại** — (i) ngoài phạm vi tài liệu; (ii) có quy định nhưng thiếu dữ liệu để
   suy luận.

### 1.3 Hệ thống KHÔNG làm gì

- **Không chạy thời gian thực, không nối core banking thật.** Không streaming hay job nền; mỗi câu
  hỏi là một lượt chạy độc lập do người dùng khởi phát, dữ liệu giao dịch là SQLite mô phỏng
  (`data/state.db`).
- **Không tự động khoá tài khoản trong production.** Tool ghi chỉ chạy khi
  `TRFC_REQUIRE_ISOLATED_DB=1` và `TRFC_STATE_DB` trỏ ra ngoài repo; DB production đối soát SHA256
  trước/sau mỗi lần chạy.
- **Không phong toả vĩnh viễn, không ra quyết định pháp lý, không thay người ký duyệt** — hành
  động tối đa là *khoá tạm thời* và *đánh dấu giao dịch*. Câu hỏi ngoài 9 tài liệu phải bị từ chối.

### 1.4 Giả định

- 9 tài liệu trong `data/docs/` là bản hiện hành, trừ DOC0003 (2025.2) đã bị DOC0007 (2026.1) thay
  thế. Hệ thống **không** tự loại DOC0003 khỏi index — để tầng suy luận chọn bản mới hơn theo
  `version`/`date` (hệ quả xem §7.1).
- `tier` eKYC lấy từ `accounts.ekyc_tier`, không suy ra từ lịch sử giao dịch; một tài khoản thuộc
  đúng một tầng tại một thời điểm. Câu hỏi là tiếng Việt hoặc tiếng Anh.

**Lấy từ**: `DE_TAI_TRFC_Agent.md` §1–§2 · `data/docs/DOC0003.md` · `src/trfc/tools/state.py`.

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

### 3.1 Corpus

9 tài liệu tự soạn trong `data/docs/`, frontmatter `doc_id` / `title` / `version` / `date` /
`owner`. **Tổng 16.293 token** (`tiktoken`, `cl100k_base`) — vượt mốc 10.000 của syllabus.

| `doc_id` | Tiêu đề | `version` | `date` | `owner` |
|---|---|---|---|---|
| DOC0003 | Hạn mức giao dịch theo tầng eKYC (**bản cũ, đã bị thay thế**) | 2025.2 | 2025-08-01 | Risk |
| DOC0004 | Quy tắc phát hiện giao dịch bất thường | 2026.1 | 2026-01-10 | Risk |
| DOC0007 | Hạn mức giao dịch theo tầng eKYC | 2026.1 | 2026-01-15 | Risk |
| DOC0008 | Quy trình xử lý và khoá tài khoản rủi ro | 2026.1 | 2026-01-20 | Compliance |
| DOC0009 | Danh mục phương thức thanh toán trong phạm vi kiểm soát | 2026.1 | 2026-02-01 | Risk |

Bốn tài liệu còn lại (DOC0001, 0002, 0005, 0006) cùng khuôn metadata, `owner` là Risk hoặc
Operations.

### 3.2 Chunking — và lý do

**Structural**: cắt theo Chương → Điều → Khoản; `chunk_size=400`, `overlap=50` đọc từ
`config.toml` (`chunking.py:142-144`). Kết quả **61 chunk gốc** (trung bình 305 token, trung vị
320, lớn nhất 421) + 6 view tầng (§3.4) = 67 vector.

1. **Cấu trúc phân cấp sẵn** — cắt theo `Điều`/`Khoản` giữ nguyên đơn vị ngữ nghĩa; fixed-size cắt
   giữa câu và làm mất chủ thể điều khoản.
2. **Bảng hạn mức phải nguyên khối** — bảng cắt vỡ có thể giữ "hạn mức 500 triệu/ngày" mà mất dòng
   "áp dụng cho tầng eKYC 2": số đúng nhưng gán sai tầng, **lỗi im lặng** không crash.
   `chunking.py:169` giữ khối atomic kể cả khi vượt `chunk_size` (chunk bảng DOC0007 = 421 token —
   cố ý).
3. **`overlap=50`** bắc cầu đoạn văn dài qua ranh giới Điều; carry theo *segment* trọn vẹn nên
   bảng atomic không bị hỏng. **`chunk_size=400`** đủ chứa 1 Điều trung bình, giữ 3–5 chunk trong
   context.

Mỗi chunk mang **heading path prefix** (`"Điều 5 > Khoản 2"`) để đứng một mình vẫn có ngữ cảnh vị
trí; **dòng giới thiệu ngay trên bảng gộp vào khối bảng** (`chunking.py:75-79`).

### 3.3 Embedding và hai chế độ truy vấn

- **Backend**: `OPENAI_API_KEY` → `text-embedding-3-small`; `JINA_API_KEY` → `jina-embeddings-v3`;
  không có key → **offline hashing** (`embed.py:124`, md5 token vào 1024 chiều, L2-normalize).
  Backend chốt một lần cho cả run (`_probe()`); probe lỗi thì hạ xuống offline kèm cảnh báo stderr
  thay vì chết giữa demo.
- **Ngưỡng và hợp đồng trả về**: cosine, `MIN_SCORE=0.45` (API) / `MIN_SCORE_OFFLINE=0.10`
  (hashing) — hai backend hai thang điểm. Top-K = 5; không đạt ngưỡng trả `[]`, **không bao giờ**
  `None`, để agent phân biệt "không tìm thấy" với "lỗi tool".
- **Hai chế độ** (`retrieval.mode`, mặc định `hybrid`): `dense` xếp theo `cosine`; `hybrid` theo
  `0.3 × BM25_norm + 0.7 × cosine`. Truy vấn chứa **mã định danh** ("DOC0007", "PM03") thì BM25
  thắng vì embedding làm mờ token hiếm; câu **diễn đạt tự nhiên** thì dense thắng vì không trùng
  mặt chữ. Trọng số nghiêng dense nhưng vẫn giữ BM25 để bắt mã tài liệu.
- **Ngưỡng chỉ áp lên cosine**, không áp lên điểm fuse (`search.py:61-65`): fuse là thang **tương
  đối** phụ thuộc phân bố BM25 từng truy vấn — ngưỡng để **chặn**, fuse để **xếp hạng**.

### 3.4 Metadata filter `tier`

`tier` là metadata **mức dòng**, đơn vị index là **chunk**, mà chunk bảng DOC0007 chứa cả 3 tầng —
gắn `tier` lên chunk thì không giá trị nào đúng, còn lọc sau rank thì `tier=2` vẫn trả nguyên bảng
kèm hạn mức tầng 1 và 3.

**Cách giải — "view một tầng".** Mỗi dòng `| Tầng N | ... |` sinh một view (`store.py:53`): cùng
`doc_id`/`chunk_index`, text chỉ giữ dòng tiêu đề bảng và dòng tầng N. View được embed và đánh BM25
cùng lúc với chunk gốc (`store.py:83`) nên hai chế độ dùng chung thứ tự index. DOC0003 + DOC0007 →
6 view, mỗi tầng đúng **2 ứng viên**.

Ghi chú: `tier` không có trong frontmatter doc nào — nó là metadata **sinh ra lúc index**.

**Pre-filter, không phải post-filter** (`search.py:55`): `store.rank_candidates(tier)` trả index
của toàn bộ chunk gốc khi `tier=None`, hoặc chỉ view tầng N khi có `tier`; `dense_scores` chỉ tính
trên tập đó. Chunk sai tầng **không bao giờ** vào top-K kể cả khi khớp từ khoá tốt hơn, trong khi
post-filter để chunk sai tầng chiếm slot top-5 và đẩy chunk đúng ra ngoài.

**Bằng chứng đo lường thực tế:** Testset có câu `q04` khai báo `expected_tier: 2`. Evaluator ghi nhận metric `metadata_filter_usage` từ tool trace thực tế: trong phiên staging thật `logs/staging_20261017_201308/`, bước 1 của `q04` gọi `search_policy(query="hạn mức giao dịch ngày chuyển khoản trong nước theo tầng eKYC", tier=2)` và metric đạt `True` khi chấm lại trên đúng row đó. Điều này chứng minh filter hoạt động thực sự trong pipeline chứ không chỉ tồn tại trong mã nguồn (xem thêm chi tiết tại §6.4).

### 3.5 Dense vs hybrid — số đo

Đo bằng cách gọi thẳng `search_policy(question, k, mode=...)` trên 12 câu của `tests/testset.jsonl`
và so với trường `must_cite` của từng câu. Không đi qua LLM — đây là **số của tầng truy vấn**, không
phải số của toàn pipeline.

| Cấu hình | recall@1 | recall@3 | recall@5 | context precision |
|---|---|---|---|---|
| `mode="dense"` | 11/12 | 11/12 | 11/12 | 0.40 (chấm được 2/12 câu) |
| `mode="hybrid"` (`0.3*BM25 + 0.7*cosine`) | 10/12 | 12/12 | 12/12 | 0.80 (chấm được 1/12 câu) |

Đọc bảng này cho đúng:

- **Hybrid thắng ở recall@3 và @5** (12/12 so với 11/12): câu duy nhất dense trượt là `q09` — gold
  `DOC0009`, dense trả `DOC0007` bốn lần rồi `DOC0003`, tức là BM25 kéo đúng tài liệu vào top-3.
  Ở top-1 thì ngược lại, hybrid trượt `q01` (gold `DOC0007`, trả `DOC0003`) và `q09`, dense chỉ trượt
  `q09` — nên **không kết luận được hybrid tốt hơn ở top-1** với 12 câu.
- **`context precision` chỉ chấm được 1–2/12 câu**, nên 0.40 và 0.80 là trung bình của 2 và 1 điểm dữ
  liệu — **không đủ để so sánh hai cấu hình**. Lý do: `eval/metrics.py:73` trả `None` (không chấm) khi
  một context chứa nhiều hơn một mã `DOCnnnn`; phần lớn chunk trích dẫn chéo tài liệu khác nên bị loại.
- **`faithfulness` = `Unscorable` cho cả hai cấu hình** — nó cần câu trả lời của LLM và trường `claims`,
  mà phép đo này không gọi LLM (§6.2).
- **Cả hai cấu hình chạy trên backend embedding `offline-hashing`** (md5 theo token, 1024 chiều), vì
  lần đo không có API key trong môi trường. Đây **không phải** số của lần chạy staging
  `staging_20261017_201308`. Log staging **không ghi** backend embedding nào đã dùng, nên không đối
  chiếu được hai lần chạy; muốn số của cấu hình API thật thì phải chạy lại với key.

**Lấy từ**: `data/docs/*.md`, `src/trfc/rag/chunking.py:75-79,169`, `embed.py:25-34,124`,
`store.py:53,83,108`, `search.py:55-76`, `config.toml`.

> **Ghi chú cho A — KHÔNG đưa vào `.docx`**: câu GV chắc chắn hỏi là `chunk_size=400` chọn thế
> nào, thử 200 thì hỏng ở đâu; filter trước hay sau rank, vì sao; chỉ dòng code giữ bảng atomic.

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

### 6.1 Testset

12 câu trong `tests/testset.jsonl`, chia theo đúng ba tầng của đề bài:

| `category` | Số câu | ID | Đo cái gì |
|---|:---:|---|---|
| `retrieval` | 3 | q01–q03 | Trích đúng `doc_id` + đúng phiên bản |
| `calc` | 2 | q04, q05 | Cộng dồn giao dịch, tính % vượt hạn mức |
| `contradiction` | 2 | q06, q07 | Chọn bản policy còn hiệu lực giữa DOC0003/DOC0007 |
| `multi_doc` | 1 | q08 | Phải trích ≥2 tài liệu mới trả lời được |
| `no_answer` loại (i) | 2 | q09, q10 | Ngoài phạm vi 9 tài liệu → lỗi ở khâu **truy vấn** |
| `no_answer` loại (ii) | 2 | q11, q12 | Có quy định nhưng thiếu dữ liệu → lỗi ở khâu **suy luận** |

Hai loại `no_answer` tách riêng vì cách sửa khác nhau. Chúng cũng là **đối trọng của `faithfulness`**:
hệ thống luôn từ chối có faithfulness hoàn hảo mà vô dụng, hệ thống luôn bịa có tỉ lệ từ chối đúng
cao giả — chỉ khi hai metric ràng buộc nhau thì con số mới có nghĩa.

### 6.2 Cách đo

Toàn bộ metric chính thức được công bố là **so khớp chuỗi xác định** (`eval/metrics.py`), không dùng LLM-as-a-judge:
`answer_correctness` kiểm tra `expected.values` xuất hiện nguyên văn trong câu trả lời
(`_contains_literal`); `context_precision` đếm tỉ lệ `doc_id` gold có trong context truy hồi;
`refusal_decision_correctness` + `refusal_subtype_correctness` kiểm tra quyết định từ chối và đúng
loại (i)/(ii). Đánh đổi: rẻ, 0 token, tái lập 100%, nhưng bỏ sót câu đúng diễn đạt khác (ca `q08`). Để khắc phục, hệ thống đã bổ sung: (1) hỗ trợ biến thể từ đồng nghĩa `{"label": ..., "any": [...]}` trong `tests/testset.jsonl`; (2) module **LLM Judge độc lập** (`eval/llm_judge.py`, cờ `--judge`) chạy song song trích xuất claims và chấm semantic entailment mà không ghi đè metric tất định. Bộ judge bị cấm chạy trên log redacted để tránh sai số.

**`faithfulness` không chấm được câu nào.** Cột này `Unscorable` ở **cả 12/12 câu**: metric chỉ chấm
khi câu trả lời kèm danh sách `claims` tách rời, mà adapter chưa bao giờ sinh trường đó
(`loop.py:47`, `policy.py:39` đều để `None`) nên `faithfulness()` trả `None` ngay ở guard đầu vào.
Đây là **hạn chế của metric/plumbing, không phải hệ thống đúng**.

**Redaction:** log đã qua `eval/redaction.py` nên số tiền/tài khoản/`tx_id` — kể cả trong `expected` —
hiện thành `[REDACTED]`. Điểm trong `evaluation.csv` tính **trước** redaction (`run_eval.py:285-288`
so với `:314`) nên vẫn đúng, nhưng người đọc log không kiểm chứng lại được bằng mắt.

### 6.3 Kết quả — lần chạy thật `logs/staging_20261017_201308/`

| ID | `category` | Đúng | Faith. | Ctx prec. | Từ chối đúng | Calls | Prompt | Compl. |
|---|---|:---:|:---:|:---:|:---:|:---:|---:|---:|
| q01 | retrieval | ✅ | Unscorable | 0.60 | ✅ | 2 | 7.627 | 448 |
| q02 | retrieval | ✅ | Unscorable | 0.75 | ✅ | 3 | 16.904 | 896 |
| q03 | retrieval | ✅ | Unscorable | Unscorable | ✅ | 3 | 13.188 | 568 |
| q04 | calc | ✅ | Unscorable | Unscorable | ✅ | 4 | 16.671 | 897 |
| q05 | calc | ❌ | Unscorable | Unscorable | ✅ | 5 | 23.557 | 982 |
| q06 | contradiction | ✅ | Unscorable | Unscorable | ✅ | 5 | 22.637 | 987 |
| q07 | contradiction | ✅ | Unscorable | Unscorable | ✅ | 3 | 17.086 | 875 |
| q08 | multi_doc | ❌ | Unscorable | Unscorable | ✅ | 3 | 15.960 | 842 |
| q09 | no_answer (i) | — | Unscorable | Unscorable | ✅ (i) | 3 | 15.364 | 854 |
| q10 | no_answer (i) | — | Unscorable | Unscorable | ✅ (i) | 3 | 15.232 | 817 |
| q11 | no_answer (ii) | — | Unscorable | Unscorable | ✅ (ii) | 3 | 16.760 | 890 |
| q12 | no_answer (ii) | — | Unscorable | 0.40 | ✅ (ii) | 3 | 11.702 | 591 |
| **Tổng** | | **6/8** | 0/12 chấm được | **0,58** (3 câu) | **12/12** | **40** | **192.688** | **9.647** |

- **Trả lời đúng 6/8** (75%); hai ca sai là `q05`, `q08` — phân tích ở §6.5.
- **Từ chối đúng 12/12**, trong đó 4/4 `no_answer` đúng cả **loại** (2 loại i, 2 loại ii).
- **Context precision** chỉ 3 câu chấm được → trung bình **0,58**; phần còn lại `Unscorable` vì câu
  trả lời không kèm danh sách `doc_id` truy hồi tách rời.
- **Semantic gate** `overall: PASS`: `freeze_write_success` + `freeze_verify_success` (q05),
  `flag_write_success` + `flag_verify_success` (q06), `false_refusal_cases`/`false_answer_cases` rỗng.

### 6.4 Chi phí token

**192.688 prompt + 9.647 completion = 202.335 token** cho **40 lượt gọi** — trung bình **16.057
prompt / 803 completion** mỗi câu. Prompt dài nhất một lượt là **`q07` = 7.188 token** (phải nạp
đồng thời DOC0003 và DOC0007 để xử lý mâu thuẫn hiệu lực); tốn nhất cả câu là **`q05` = 24.539
token** (5 bước ReAct: tính hạn mức → `freeze_account_temporarily` → `get_account_risk_status`).
Mô hình: `llm.py:24` mặc định `qwen/qwen3.8-27b` qua endpoint tương thích OpenAI — **log staging
không ghi provider/model thực tế**, nên đây là cấu hình trong code, không phải bằng chứng.

### 6.5 Ca thất bại

**`q05` (calc) — không nêu con số tuyệt đối.** Gold cần `"44%"` **và** `"220.000.000 VND"`; agent
tính đúng công thức DOC0007 Điều 10 và ra đúng `44%`, nhưng chỉ in `[REDACTED] − [REDACTED]) ÷
[REDACTED] × 100% = 44%`, không nhắc lại tổng giá trị giao dịch. Nguyên nhân là **thiếu ràng buộc
định dạng trong prompt**, không phải tính sai. Sửa: buộc prompt nêu lại từng toán hạng, hoặc ghi rõ
trong testset là chỉ chấm kết quả cuối.

**`q08` (multi_doc) — lệch một từ.** Gold cần `"không được ra quyết định khóa"`; agent viết *"không
**thể** ra quyết định khóa tài khoản"*. Về nghiệp vụ câu trả lời đúng (nêu rõ "Không", dẫn DOC0006
chunk 4 và DOC0008 chunk 1), nhưng `_contains_literal` so khớp nguyên văn nên trả `False` — **hạn
chế của metric, không phải lỗi suy luận**. Nhóm đã khắc phục trực tiếp trong codebase: (1) bổ sung
cấu trúc từ đồng nghĩa `{"label": ..., "any": [...]}` vào `tests/testset.jsonl` và `eval/metrics.py`;
(2) phát triển module `eval/llm_judge.py` để chấm semantic entailment song song.

**Lấy từ**: `tests/testset.jsonl`, `eval/metrics.py`, `eval/run_eval.py`, `eval/report.py`,
`logs/staging_20261017_201308/`.

---

## §7 — Hạn chế & hướng phát triển · 0.5 trang · **A**

### 7.1 Hạn chế

**1. Embedding offline bằng hashing không nắm ngữ nghĩa tiếng Việt.** Không có key API thì băm
token thành 1024 chiều (`embed.py:124`) — chỉ bắt **trùng mặt chữ**, không bắt paraphrase. Đó là lý
do phải hạ ngưỡng xuống `MIN_SCORE_OFFLINE=0.10` (so với 0.45 khi có API), và hạ ngưỡng nghĩa là
tăng nguy cơ trả chunk không liên quan.

**2. Faithfulness đo bằng so khớp chuỗi.** `eval/metrics.py` kiểm tra claim có xuất hiện nguyên văn
trong context: rẻ và tái lập được, nhưng câu đúng mà diễn đạt khác bị chấm sai, còn câu chép nguyên
văn mà **hiểu sai** vẫn điểm cao. Faithfulness ≈ 1.0 không đồng nghĩa trả lời đúng.

**3. Trích dẫn phiên bản là trường dữ liệu, không phải ràng buộc của prompt.** `Chunk` mang
`version` nhưng **không prompt nào** buộc mô hình nêu version hay chọn bản mới hơn. DOC0003
(2025.2) vẫn nằm trong index và vẫn có thể lọt top-K: câu trả lời trích nó vẫn "có nguồn" nhưng có
thể sai hiệu lực.

**4. Corpus nhỏ và đơn miền.** 9 tài liệu, 16.293 token — chưa kiểm chứng hành vi khi corpus lên
hàng trăm tài liệu hoặc heading không theo khuôn Chương/Điều/Khoản (chunker structural sẽ thoái
hoá về cắt theo đoạn). Metadata filter `tier` cũng **chưa có câu testset nào** chạy qua (§3.4).

### 7.2 Hướng phát triển

1. **Rerank sau retrieval** — top-20 bằng hybrid rồi rerank bằng cross-encoder; giải quyết (1) mà
   không phải đổi embedding backend.
2. **Lọc theo `date`/`version` ở mức index** — coi "bản còn hiệu lực" là metadata giống `tier`, để
   tài liệu bị thay thế không bao giờ vào top-K.
3. **Human-in-the-loop cho tool ghi** — tách `freeze_account_temporarily` thành đề xuất + phê duyệt;
   verify giữ nguyên, thêm bước người duyệt trước khi ghi.
4. **Audit trail bất biến** — hiện `flags`/`accounts` ghi đè trạng thái; cần bảng append-only ghi
   mọi lần write kèm `actor`, `reason`, `evidence_doc_ids`.

**Lấy từ**: `src/trfc/rag/embed.py:33-34,124`, `eval/metrics.py`, `prompts/system.txt`,
`data/docs/DOC0003.md`, `tests/testset.jsonl`.

---

## §8 — Phân công & đóng góp · 0.5 trang · **C**

| Thành viên | Vai trò | File phụ trách chính | Commit tiêu biểu |
|---|---|---|---|
| **A** (CapyCoder) | Dữ liệu & Truy hồi | `data/docs/*.md` (9 văn bản), `src/trfc/rag/chunking.py`, `embed.py`, `store.py`, `search.py`, metadata filter `tier` | `d814a37` corpus · `6c28772` chunking · `d0210b2` embedding + hybrid search |
| **B** (Do Ngo, Do Coding) | Agent & Tool / MCP | `src/trfc/tools/schemas.py`, `impl.py`, `state.py`, `src/trfc/agent/loop.py`, `parse.py`, `llm.py`, `prompts/*.txt`, `src/trfc/mcp_server/server.py` | `6ccbdf1` `aae71ca` (loop) · `d12f5cc` decision prompt · `8612d50` MCP server · `41e2c13` tool tests |
| **C** (Penguin-cell34) | Đo lường & Tái lập | `tests/testset.jsonl`, `eval/metrics.py`, `run_eval.py`, `report.py`, `semantic_gate.py`, `redaction.py`, `src/trfc/mcp_server/client2.py`, `scripts/run_c4_staging.ps1`, `Makefile` | `8c77866` staging + charts · `86b144e` semantic gate · `2a6cffb` LLM client fix |

**Đối soát tài khoản Git** (tính đến `580e4f3`): tổng **69 commit** — Do Ngo 38 · CapyCoder 13 ·
Penguin-cell34 11 · Do Coding 7. `Do Ngo` và `Do Coding` là hai tài khoản của cùng **thành viên B**
(đề bài cho phép 3 SV/nhóm, git phải thể hiện cả 3 người làm thật).

Bảng trên **không có cột "tỷ lệ đóng góp %"**: ba cột 100% cộng lại thành 300% là con số vô nghĩa,
và không có cách đo khách quan nào cho một đồ án 10 ngày. Đóng góp được chứng minh bằng **commit
hash + file phụ trách**, đúng thứ GV đối chiếu khi vấn đáp.

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
