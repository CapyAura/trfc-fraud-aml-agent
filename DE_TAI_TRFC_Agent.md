# Đề tài nhóm — TRFC Agent

**Trợ lý Kiểm soát Rủi ro & Gian lận Giao dịch** (Transaction Fraud & AML Control Agent)

> Yêu cầu học phần: xem [CLAUDE.md](CLAUDE.md). File này chỉ chứa nội dung riêng của đề tài.
> Trạng thái: **thiết kế đã chốt**, chưa scaffold code.

---

## 1. Bài toán & giá trị

**Giá trị 20/80:** Bộ phận Risk & Compliance của ngân hàng số / sàn giao dịch cần tự động quét giao dịch bất thường, áp chính sách phòng chống rửa tiền (AML), và khóa tạm thời tài khoản nghi vấn.

| | |
|---|---|
| **Người dùng** | Chuyên viên Risk & Compliance |
| **Hệ thống KHÔNG làm** | Không phong tỏa vĩnh viễn, không ra quyết định pháp lý, không thay con người ký duyệt, không truy cập hệ thống ngân hàng thật (chỉ mô phỏng trên DB nội bộ) |

---

## 2. Ba tầng

| Tầng | Nội dung |
|---|---|
| **(a) Tra cứu** | Quy định An toàn giao dịch thanh toán; Hạn mức giao dịch theo tầng eKYC; Quy trình xử lý tài khoản rủi ro. **`no_answer`** nếu phương thức thanh toán không thuộc phạm vi quản lý. |
| **(b) Biến đổi** | Tính tổng giá trị giao dịch dồn trong ngày; tính **% vượt hạn mức**; so sánh **mâu thuẫn vị trí/thời gian** (2 giao dịch ở 2 quốc gia trong 10 phút). **Từ chối phán quyết nếu thiếu log lịch sử giao dịch gốc.** |
| **(c) Hành động** | **Write:** `freeze_account_temporarily(account_id, reason)` hoặc `flag_suspicious_tx(tx_id)`. **Verify:** `get_account_risk_status(account_id)` đọc lại, chứng minh khóa/cảnh báo đã có hiệu lực. |

### Hai loại từ chối — không được trùng nhau

| Loại | Ca của TRFC | Lỗi ở khâu |
|---|---|---|
| (i) Không có trong tài liệu | Phương thức thanh toán ngoài phạm vi quản lý | Truy vấn |
| (ii) Có nhưng thiếu để suy luận | Thiếu log lịch sử giao dịch gốc → không tính được | Suy luận |

---

## 3. Corpus & Chunking

### 3.1 Tài liệu

| Nguồn | Nội dung | Metadata |
|---|---|---|
| `DOC0001–DOC0006` (của lớp, tái dùng) | Quy định an toàn giao dịch thanh toán | `doc_id`, `title`, `date/version`, `owner` |
| **DOC0007** (mới) | Hạn mức giao dịch theo tầng eKYC (bảng) | `owner: Risk`, `version: 2026.1` |
| **DOC0008** (mới) | Quy trình xử lý & khóa tài khoản rủi ro | `owner: Compliance` |
| **DOC0009** (mới) | Danh mục phương thức thanh toán **trong** phạm vi quản lý | `owner: Risk` — dùng cho ca `no_answer` loại (i) |

Yêu cầu học phần: ≥5 tài liệu, ≥10,000 token tổng. **Không dùng dữ liệu nhóm khác.**

### 3.2 Chunking — quyết định & lý do

Dùng **recursive splitting theo cấu trúc văn bản** (Chương → Điều → Khoản), `chunk_size=400` token, `overlap=50`, **không cắt vỡ bảng**.

Lý do (đây là phần report §3 cần 3–5 dòng):

1. Văn bản quy định có cấu trúc phân cấp sẵn — cắt theo `Điều`/`Khoản` giữ nguyên đơn vị ngữ nghĩa, tốt hơn fixed-size cắt giữa câu.
2. **Bảng hạn mức eKYC phải nguyên khối**: cắt vỡ bảng thì chunk chứa "hạn mức 500 triệu" mà mất dòng "áp dụng cho tầng eKYC 2" → retrieval trả về số đúng nhưng gán sai tầng. Đây là lỗi im lặng, không crash.
3. `overlap=50` chỉ để bắc cầu các đoạn văn dài qua ranh giới Điều; bảng vẫn atomic nên overlap không làm hỏng bảng.
4. `chunk_size=400` đủ chứa 1 Điều trung bình + giữ được 3–5 chunk trong context mà không vượt ngân sách token.

> Ba tham số (`chunk_size`, `overlap`, `strategy`) để trong config, không hard-code — cần cho điểm cộng "so sánh 1 cấu hình".

---

## 4. Retrieval — dense + hybrid

**Bắt buộc ≥2 chế độ** (yêu cầu 2.5). Tái dùng `w4/ex2_1_hybrid_search.py`, không viết lại.

| Chế độ | Dùng khi | Lý do tồn tại trong domain này |
|---|---|---|
| **Dense** (embedding) | Câu hỏi diễn giải | "giao dịch bất thường" ≈ "giao dịch đáng ngờ" — paraphrase, BM25 trượt |
| **Hybrid** (BM25 + vector) | Câu hỏi có mã/số chính xác | "tầng eKYC 2", mã giao dịch, số tiền — BM25 khớp token chính xác, dense làm mờ |

Công thức fuse: `score = 0.3 * BM25_norm + 0.7 * cosine` (theo w4). Trả **top-K kèm score** (K=5 mặc định, config).

**Metadata filter** (điểm cộng +1): `tier` (eKYC 1/2/3) là metadata trên chunk hạn mức → pre-filter trước khi rank. Ví dụ: hỏi hạn mức của tầng eKYC 2 thì filter `tier==2` rồi mới search, tránh trả nhầm hạn mức tầng 3.

---

## 5. Tool contract

MCP server tự viết, chạy **stdio**, **stdout sạch** (log ra stderr). Client **discover động** — không hard-code danh sách tool.

### 5.1 Schema (`@dataclass` + type hint — yêu cầu 2.3, không dùng dict thô)

```python
@dataclass
class Chunk:
    doc_id: str
    title: str
    version: str
    chunk_index: int
    text: str
    score: float

@dataclass
class Transaction:
    tx_id: str
    account_id: str
    amount: float
    currency: str
    ts: datetime          # UTC
    country: str
    method: str           # khớp danh mục DOC0009
    location: str

@dataclass
class RiskStatus:
    account_id: str
    frozen: bool
    freeze_reason: str | None
    frozen_at: datetime | None
    flagged_tx_ids: list[str]
    checked_at: datetime  # để chứng minh verify đọc state MỚI
```

### 5.2 Danh sách tool

| Tool | Loại | Chữ ký | Trả về |
|---|---|---|---|
| `search_policy` | đọc | `(query, k, tier=None, mode="hybrid")` | `list[Chunk]` |
| `get_transactions` | đọc | `(account_id, date_from, date_to)` | `list[Transaction]` |
| `get_account_risk_status` | **đọc** | `(account_id)` | `RiskStatus` — **bước verify bắt buộc** |
| `freeze_account_temporarily` | **ghi** | `(account_id, reason)` | `Ack` |
| `flag_suspicious_tx` | **ghi** | `(tx_id, reason)` | `Ack` |

### 5.3 Side effect thật

`freeze_account_temporarily` / `flag_suspicious_tx` **ghi vào SQLite** (`state.db`) do MCP server sở hữu — không mock trả `"OK"`.

Verify phải đọc lại **từ state đã đổi**: `get_account_risk_status` đọc từ `state.db`, không đọc lại response của chính write. `RiskStatus.checked_at` chứng minh lần đọc là mới.

---

## 6. Agent loop

Vòng lặp **tự viết tay** (yêu cầu 2.2). Được dùng `mcp` SDK, embedding lib, `rank_bm25`, `numpy`, `pandas`, `python-docx` — không dùng LangChain/LlamaIndex.

| Hạng mục | Quyết định | Lý do |
|---|---|---|
| `MAX_STEPS` | **8** | Trace điển hình ~5 bước (search → get_tx → compute → freeze → verify); 8 đủ headroom, chặn loop vô hạn |
| Tool lỗi | trả chuỗi `"Error: ..."`, **không raise** | Agent phải thấy lỗi và tự điều chỉnh, không làm chết run (yêu cầu 2.6) |
| Parse action | regex an toàn, thiếu dấu ngoặc/JSON hỏng → trả lỗi parse cho agent, không crash | yêu cầu 2.6 |
| Prompt | tách khỏi code → `prompts/*.txt` | yêu cầu 2.4 |
| API call | retry + timeout + log lỗi HTTP | yêu cầu 2.4 |
| LLM | `call_llm()` bọc duy nhất, mọi chỗ đi qua đây | GV đọc 1 hàm khi vấn đáp |

**Trace mục tiêu** (1 câu hỏi mẫu, dùng cho report §4):

```
thought  → cần biết hạn mức eKYC của tài khoản này
action   → search_policy("hạn mức giao dịch tầng eKYC 2", tier=2)
observe  → [DOC0007, chunk 3, score 0.81]
action   → get_transactions("ACC001", 2026-10-09, 2026-10-09)
observe  → 4 giao dịch, tổng 720tr, hạn mức 500tr → vượt 44%
thought  → vượt hạn mức + 2 giao dịch 2 quốc gia trong 10 phút → đủ bằng chứng
action   → freeze_account_temporarily("ACC001", "vượt hạn mức 44% + bất khả thi địa lý")
observe  → Ack: frozen
action   → get_account_risk_status("ACC001")      ← VERIFY
observe  → frozen=True, frozen_at=...             ← chứng minh state đã đổi
```

---

## 7. Testset (`tests/testset.jsonl`)

**≥12 câu, ≥4 `no_answer`.** Phân bố có chủ đích để eval không vô nghĩa (tầng (b) tạo chỗ sai):

| Nhóm | Số câu | Nội dung |
|---|---|---|
| (a) Tra cứu đơn | 3 | Tra 1 chunk, trả lời có trích dẫn |
| (b) Tính toán | 2 | Tổng giá trị dồn ngày, % vượt hạn mức |
| (b) So sánh mâu thuẫn | 2 | 2 giao dịch 2 quốc gia trong 10 phút; chọn bản policy mới nhất giữa 2 version |
| (b) Tổng hợp nhiều doc | 1 | Phải trích ≥2 document mới trả lời được |
| **no_answer loại (i)** | 2 | Phương thức thanh toán ngoài phạm vi (không có trong DOC0009) |
| **no_answer loại (ii)** | 2 | Có quy định nhưng thiếu log giao dịch gốc → không tính được |
| **Tổng** | **12** | |

**Câu hỏi demo cho GV** (không có trong testset) phải chuẩn bị riêng cho buổi bảo vệ.

---

## 8. Đánh giá & log

### Metrics (bắt buộc)

- **Faithfulness** — mỗi claim trong câu trả lời có được context hỗ trợ không.
- **Tỉ lệ từ chối đúng** — trên 4 câu `no_answer`: hệ thống có từ chối, và từ chối **đúng loại** (i)/(ii) không.
- **Context precision** — chunk retrieve về có liên quan không.

> Nếu chỉ đo faithfulness thì một hệ thống luôn từ chối sẽ được điểm cao giả. Vì vậy phải đo **cặp**: faithfulness **và** tỉ lệ từ chối đúng **và** tỉ lệ trả lời đúng trên câu trả lời được.

### `USAGE` từng câu (yêu cầu §4)

Mỗi dòng log ghi: `calls`, `prompt_tokens`, `completion_tokens`, `max_prompt`. Tổng hợp thành bảng chi phí token từng câu cho report §6.

### `logs/` — ≥3 lần chạy thật

Mỗi lần 1 file `jsonl`, mỗi dòng 1 bước: timestamp, step, tool name, args, result, `USAGE`. ≥3 lần chạy phải có **kết quả khác nhau có chủ đích** (vd: 1 lần freeze, 1 lần chỉ flag, 1 lần từ chối) để chứng minh agent thực sự quyết định theo dữ liệu.

---

## 9. Điểm cộng đã lên kế hoạch

| Việc | Cộng | Cách làm |
|---|---|---|
| Metadata filter dùng thật | +1 | Filter `tier` trong `search_policy`, phối hợp w4→w6 |
| So sánh cấu hình | +1 | `make eval` chạy dense-vs-hybrid + 2 cấu hình chunking trên cùng testset |
| MCP từ host thứ hai | +1 | Client Python thứ hai (ngoài agent) discover & gọi tool — chứng minh interop |
| Đồ thị + CSV log | +1 | CSV theo từng câu + biểu đồ faithfulness/refusal |

---

## 10. Rủi ro

- **Gần đề tài T2** (Kiểm toán chi tiêu công tác: "đối chiếu hạn mức → duyệt/từ chối/leo thang"). Khác domain (chi tiêu công tác vs giao dịch thanh toán) nhưng **nên xác nhận với GV** để không bị coi là trùng đề tài.
- **Side effect giả** — nếu `freeze_account_temporarily` chỉ mock trả `"OK"` thì bài kiểm tra "agent có thực sự dùng kết quả tool" của GV sẽ trượt. Bắt buộc ghi SQLite thật + verify đọc lại từ đó.
- **Bảng hạn mức bị cắt vỡ** khi chunk → gán sai tầng eKYC. Xử lý bằng rule "bảng atomic" ở §3.2; cần 1 test khẳng định không chunk nào chứa nửa bảng.
