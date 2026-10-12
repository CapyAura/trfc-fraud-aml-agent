# Phân công — TRFC Agent (3 SV)

> Đọc kèm [DE_TAI_TRFC_Agent.md](DE_TAI_TRFC_Agent.md) (thiết kế) và [CLAUDE.md](CLAUDE.md) (yêu cầu học phần).
> Nguyên tắc chia: mỗi người sở hữu **một lát cắt dọc** trọn vẹn, không ai làm rời rạc nhiều mảng.
> Lý do: buổi bảo vệ chấm **bảo vệ phần mình (15đ) + sửa code trực tiếp (10đ)** — phải giải thích được *mọi dòng* trong phần mình nhận.

---

## 1. Tổng quan

| | **A — Dữ liệu & Truy hồi** | **B — Agent & Tool/MCP** | **C — Đo lường & Tái lập** |
|---|---|---|---|
| **Mảng** | Corpus, chunking, embedding, vector store, dense+hybrid, metadata filter | Tool schema, MCP server, ReAct loop, prompt, `call_llm`, side effect + verify | Testset, RAGAS, log/USAGE, biểu đồ, Makefile, README, git |
| **Mục report** | §3 (RAG) | §4 (Agent & tool) + §5 (MCP) | §6 (Đánh giá) |
| **Điểm nhóm liên quan** | RAG 13 | Agent 12 + MCP 8 | Đánh giá 10 + Tái lập 12 |
| **Điểm cộng nhắm** | +1 metadata filter, +1 so sánh cấu hình | — | +1 host thứ hai, +1 đồ thị + CSV |
| **Thư mục sở hữu** | `src/rag/`, `data/docs/`, `config.yaml` | `src/tools/`, `src/mcp_server/`, `src/agent/`, `prompts/` | `eval/`, `tests/`, `logs/`, `Makefile`, `README.md` |

**Điểm cộng "host thứ hai"** giao cho C nhưng **B cung cấp server** — C viết client thứ hai, đây là chủ ý: người viết client không phải người viết server thì mới chứng minh được interop thật.

---

## 2. A — Dữ liệu & Truy hồi

**Sản phẩm:** `search_policy(query, k, tier=None, mode="hybrid") -> list[Chunk]` chạy được, trả top-K kèm `score`, mọi chunk truy được về `doc_id` + `version`.

| # | Việc | File |
|---|---|---|
| A1 | Thu thập & chuẩn hoá corpus: DOC0001–0006 (tái dùng của lớp) + viết mới DOC0007 (bảng hạn mức eKYC), DOC0008 (quy trình khóa TK), DOC0009 (danh mục phương thức trong phạm vi). Đủ ≥5 doc, ≥10,000 token | `data/docs/*.md` |
| A2 | Chunking recursive theo Chương→Điều→Khoản, `chunk_size=400`, `overlap=50`, **bảng atomic** | `src/rag/chunking.py` |
| A3 | Embedding + vector store, similarity search top-K kèm score | `src/rag/embed.py`, `src/rag/store.py` |
| A4 | Dense + hybrid BM25, fuse `0.3*BM25_norm + 0.7*cosine` (tái dùng `w4/ex2_1_hybrid_search.py`) | `src/rag/search.py` |
| A5 | Metadata filter `tier` — pre-filter trước khi rank | `src/rag/search.py` |
| A6 | 3 tham số chunking để trong `config.yaml`, không hard-code | `config.yaml` |

**Định nghĩa "xong":** chạy `python -m src.rag.search "hạn mức giao dịch tầng eKYC 2" --tier 2` in ra chunk có `doc_id=DOC0007`, `score`, và **không** trả hạn mức của tầng khác.

**Test bắt buộc để lại:** 1 test khẳng định **không chunk nào chứa nửa bảng hạn mức** (rủi ro §10 của file thiết kế — lỗi im lặng, không crash).

**Câu hỏi GV dự kiến:**
- `chunk_size=400` chọn thế nào? Thử 200 thì hỏng ở đâu?
- Vì sao câu này hybrid thắng dense, câu kia dense thắng? *(chỉ vào bảng eval của C)*
- Metadata filter nằm **trước hay sau** khi rank? Vì sao?
- Chỉ ra dòng code đảm bảo bảng hạn mức không bị cắt vỡ.

---

## 3. B — Agent & Tool/MCP

**Sản phẩm:** vòng lặp ReAct tự viết chạy end-to-end 1 câu hỏi, có **side effect thật + bước verify**; MCP server stdio mà client discover động được.

| # | Việc | File |
|---|---|---|
| B1 | Tool schema `@dataclass` + type hint: `Chunk`, `Transaction`, `RiskStatus`, `Ack` | `src/tools/schemas.py` |
| B2 | 5 tool: `search_policy`, `get_transactions`, `get_account_risk_status`, `freeze_account_temporarily`, `flag_suspicious_tx` | `src/tools/impl.py` |
| B3 | Side effect **ghi SQLite thật** (`data/state.db`), không mock trả `"OK"` | `src/tools/impl.py` |
| B4 | MCP server stdio, **stdout sạch** (log ra stderr) | `src/mcp_server/server.py` |
| B5 | ReAct loop, `MAX_STEPS=8`, tool lỗi trả `"Error: ..."` **không raise**, parse action an toàn | `src/agent/loop.py`, `src/agent/parse.py` |
| B6 | `call_llm()` bọc duy nhất — retry + timeout + log lỗi HTTP | `src/agent/llm.py` |
| B7 | Prompt tách khỏi code | `prompts/*.txt` |

**Định nghĩa "xong":** chạy được trace mục tiêu ở §6 file thiết kế — `search → get_tx → tính → freeze → verify`, và dòng verify cho thấy `frozen=True`, `checked_at` mới hơn `frozen_at`.

**Test bắt buộc để lại:** 1 test khẳng định (a) verify đọc lại **từ `state.db`** ra đúng trạng thái đã ghi, (b) tool lỗi trả chuỗi `"Error: ..."` mà không ném exception.

**Câu hỏi GV dự kiến:**
- `MAX_STEPS=8` hết bước mà chưa xong thì agent làm gì?
- Vì sao tool lỗi trả chuỗi thay vì raise? Cho ví dụ trace mà điều này cứu cả run.
- **Chứng minh agent thực sự dùng kết quả tool**, không phải LLM tự diễn.
- stdout sạch để làm gì? `print()` debug ra stdout thì hỏng cái gì?
- Thêm tool mới thì client có phải sửa không? Chỉ dòng code discover.

---

## 4. C — Đo lường & Tái lập

**Sản phẩm:** `make setup && make demo` chạy được trên máy sạch; `make eval` tái lập mọi số liệu trong report.

| # | Việc | File |
|---|---|---|
| C1 | `tests/testset.jsonl` ≥12 câu, ≥4 `no_answer` — phân bố theo §7 file thiết kế | `tests/testset.jsonl` |
| C2 | RAGAS: faithfulness, context precision; **tỉ lệ từ chối đúng** (tách loại (i)/(ii)) | `eval/metrics.py` |
| C3 | Log `jsonl` mỗi bước: timestamp, step, tool, args, result, `USAGE` (calls, prompt/completion tokens, max_prompt) | `eval/run_eval.py` |
| C4 | `logs/` ≥3 lần chạy thật, **kết quả khác nhau có chủ đích** (1 freeze / 1 flag / 1 từ chối) | `logs/*.jsonl` |
| C5 | CSV theo từng câu + biểu đồ faithfulness/refusal | `eval/` |
| C6 | Client MCP thứ hai (ngoài agent) discover & gọi tool | `src/mcp_server/client2.py` |
| C7 | `Makefile` (`setup`, `demo`, `eval`), `README.md`, `.env.example`, `ai-usage.md` | gốc repo |
| C8 | Kỷ luật git: `.gitignore`, `.git` trong bản nộp, không lộ key | — |

**Định nghĩa "xong":** clone repo vào thư mục trống, chạy đúng **1 lệnh**, demo ra kết quả; `make eval` in ra bảng khớp số trong report.

**Lưu ý:** C viết testset và chấm điểm cả A lẫn B — **chủ ý**, vì C không viết retrieval lẫn agent nên không tự chấm bài mình. C không được để A/B sửa testset.

**Câu hỏi GV dự kiến:**
- 12 câu lấy từ đâu? 4 câu `no_answer` chia thế nào giữa loại (i) và (ii)?
- **Vì sao phải đo cặp** faithfulness + tỉ lệ từ chối, mà không đo mỗi faithfulness?
- Đưa 1 ca thất bại và phân tích nguyên nhân.
- `make setup && make demo` trên máy sạch — chỗ nào dễ hỏng nhất?
- `USAGE` lấy từ đâu, tổng chi phí token cả testset là bao nhiêu?

---

## 5. Việc chung — cả 3

| Việc | Ai chủ trì |
|---|---|
| Sơ đồ kiến trúc (report §2) | B vẽ, A + C review |
| Chốt interface ở CP1 (§6 dưới) | cả 3, bắt buộc có mặt |
| §1 Vấn đề & phạm vi, §7 Hạn chế | A |
| §8 Phân công + **commit hash** | C tổng hợp |
| §9 Phụ lục (prompt gốc, trace dài, `ai-usage.md`) | B |
| Ghép & format `report.docx` 8–9 trang | C |
| Tập bảo vệ, mỗi người 3 phút demo + tự sửa code mình | cả 3 |

---

## 6. Mốc thời gian (10 ngày)

| Mốc | Ngày | Nội dung | Điều kiện qua mốc |
|---|---|---|---|
| **CP0** | 1 | **Chốt interface + xác nhận đề tài với GV** | Bảng §7 dưới đã ký; GV xác nhận không trùng T2 |
| **CP1** | 2 | Scaffold: cấu trúc thư mục, `config.yaml`, `Makefile` rỗng, `schemas.py` | `git log` có commit của **cả 3 người** |
| **CP2** | 3–5 | Mỗi lát cắt chạy độc lập | A: search trả top-K có score · B: loop chạy với tool giả · C: testset nháp + logging chạy |
| **CP3** | 6–7 | **Tích hợp** — end-to-end 1 câu hỏi thật | Trace đủ `search → freeze → verify` |
| **CP4** | 8–9 | Eval + ≥3 log + report | `make eval` ra số; report đủ 9 mục |
| **CP5** | 10 | Đóng băng, tổng duyệt, tập bảo vệ | Mỗi người sửa được code mình trước mặt nhóm |

**CP3 là mốc rủi ro nhất.** Nếu đến hết ngày 7 chưa tích hợp được, cắt bớt điểm cộng (ưu tiên đủ 3 tầng hơn là đủ bonus).

---

## 7. Hợp đồng giao diện — CHỐT Ở CP0, sau đó không tự ý đổi

Đây là ranh giới giữa A và B. Đổi sau CP0 mà không báo → cả hai vỡ.

```python
# A cung cấp — B tiêu thụ
search_policy(query: str, k: int = 5, tier: int | None = None,
              mode: Literal["dense", "hybrid"] = "hybrid") -> list[Chunk]

# Chunk (B định nghĩa trong schemas.py, A import — KHÔNG định nghĩa lại)
@dataclass
class Chunk:
    doc_id: str
    title: str
    version: str
    chunk_index: int
    text: str
    score: float
```

**Quy tắc:**
1. `Chunk` sống ở `src/tools/schemas.py` (B sở hữu). A **import**, không copy.
2. A không được trả `None` — không tìm thấy thì trả `[]`, B xử lý ca rỗng.
3. B không được sửa `search_policy` — cần đổi thì mở issue/báo A.
4. Đổi chữ ký tool → sửa **cả** `impl.py`, `server.py`, `schemas.py` trong **cùng 1 commit**.

---

## 8. Rủi ro phối hợp

| Rủi ro | Cách tránh |
|---|---|
| **Git history chỉ có 1 người commit** → mất điểm "git của cả 3 người" | Mỗi người `git config user.name` + `user.email` **của mình** trước commit đầu tiên. Không ai commit hộ ai |
| Đổi interface sau CP0 | Bảng §7; đổi phải sửa cả 3 file trong 1 commit |
| C viết testset rồi A/B "gợi ý" sửa cho dễ đạt | Testset đóng băng ở CP4; A/B không được xem trước câu hỏi |
| B vừa viết MCP server vừa viết client → interop giả | Client thứ hai do C viết |
| Dồn hết vào 2 ngày cuối | Mốc CP2/CP3 là mốc cứng, trượt thì cắt bonus chứ không lùi mốc |
| **Đề tài gần T2** (Kiểm toán chi tiêu công tác) | CP0: xác nhận với GV trước khi viết code |
