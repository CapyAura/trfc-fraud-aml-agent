# Phần B — Agent & Tool/MCP (§2, §4, §5, §9)

## §2 — Kiến trúc tổng thể

```
CLI / eval ──câu hỏi──▶ Agent loop (agent/loop.py, MAX_STEPS=8)
                          │  call_llm() ─▶ LLM (agent/llm.py: retry, timeout)
                          │  list_tools() / call_tool()  (JSON-RPC)
══════════ ranh giới tiến trình: MCP stdio (stdout = JSON-RPC, log = stderr) ══════════
client2.py (host thứ hai, C) ─▶ MCP server (mcp_server/server.py, 5 tool)
                                        │
                                  tools/impl.py  (trả dataclass hoặc "Error: ...")
                          ┌─────────────┴──────────────┐
                    rag/search.py (A)          SQLite state.db (tools/state.py)
                    data/docs/DOC0001–9        accounts · transactions · flags
```

Bốn ranh giới: người dùng ↔ agent; agent ↔ LLM (chỉ qua `call_llm()`); agent ↔ tool (qua MCP stdio, tách tiến trình); tool ↔ trạng thái (chỉ `state.py` mở SQLite).

Luồng một câu hỏi mẫu (q05): `search_policy` → `freeze_account_temporarily` → `get_account_risk_status` (verify). Agent và `client2.py` cùng đi vào **một MCP server**, server gọi **cùng `tools/impl.py`**, nên tool hành xử giống nhau ở mọi đường gọi.

| Khối | Người | Giao diện |
|---|---|---|
| RAG | A | `search_policy(query, k, tier, mode) -> list[Chunk]` |
| Agent + Tool + MCP | B | 5 tool qua MCP; `AgentRunResult` cho eval |
| Eval + Log | C | gọi `run_detailed()`, đọc `tool_trace`, `usage` |

## §4 — Thiết kế Agent & tool

**4.1 Schema bằng `@dataclass`** (`tools/schemas.py`; GV kiểm `grep -n "@dataclass"`). Không dùng dict thô vì sai tên trường chỉ lộ khi chạy.

```python
@dataclass
class Chunk:
    doc_id: str; title: str; version: str
    chunk_index: int; text: str; score: float; tier: int | None = None

@dataclass
class RiskStatus:                      # kết quả bước VERIFY
    account_id: str; frozen: bool
    freeze_reason: str | None; frozen_at: datetime | None
    flagged_tx_ids: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)
```

`Transaction` và `Ack` cùng file. `checked_at` chứng minh lần đọc là **mới**, không phải phản hồi của lệnh ghi.

**4.2 Năm tool**

| Tool | Loại | Chữ ký | Trả về |
|---|---|---|---|
| `search_policy` | đọc | `(query, k=5, tier=None, mode="hybrid")` | `list[Chunk]` (uỷ quyền cho A) |
| `get_transactions` | đọc | `(account_id, date_from, date_to)` | `list[Transaction]` |
| `get_account_risk_status` | đọc, verify | `(account_id)` | `RiskStatus` |
| `freeze_account_temporarily` | **ghi** | `(account_id, reason)` | `Ack` |
| `flag_suspicious_tx` | **ghi** | `(tx_id, reason)` | `Ack` |

**4.3 Mô tả tool như prompt.** Model chọn tool qua docstring mà MCP trả về:

```python
"""Lệnh ghi Side-Effect: Tạm thời khóa tài khoản và ghi nhận lý do vào state.db."""   # freeze
"""Lệnh ghi Side-Effect: Đánh dấu cờ giao dịch nghi vấn vào state.db."""             # flag
```

Hai docstring nêu tool làm gì; điều kiện dùng (chỉ ghi khi được yêu cầu rõ, bắt buộc verify sau ghi, tra cứu tối đa 2 lần) nằm ở `prompts/system.txt` quy tắc 4–6. Ở cả 2 ca ghi trong log (q05, q06), model gọi đúng một tool ghi rồi gọi verify.

**4.4 Vòng lặp.** Tự viết, không LangChain, dùng native tool-calling qua MCP: `call_llm` → có `tool_calls`? → kiểm tool đã discover, args là JSON object, khớp `input_schema` → `session.call_tool()` → ghi `tool_trace` và thêm message `role=tool` → lặp; không có `tool_calls` thì trả câu trả lời cuối. Tool được discover động bằng `list_tools()` (`loop.py:511`). Tool riêng `submit_decision` do runtime xử lý, không gửi sang MCP. `search_policy` quá 2 lần thì loop bảo tổng hợp (`loop.py:636`). JSON giả lập tool call nằm trong nội dung câu trả lời không bao giờ bị thực thi (có test). `parse.py` là bộ parse JSON chịu lỗi có test, không nằm trên đường chạy chính.

**4.5 `MAX_STEPS = 8`.** Đọc từ `config.toml` (`load_max_steps`, `loop.py:105`). Đơn vị là số lượt gọi model; 12 câu staging dùng 2–5 lượt, nên 8 còn dư 3. Hết bước: `status="failed"`, `error="Native tool loop exceeded MAX_STEPS (8)"` (`loop.py:671`), `run()` trả chuỗi `"Error: ..."` (`loop.py:716`), không raise, `tool_trace` được giữ lại. Test `test_maximum_model_turns_is_enforced`.

**4.6 Xử lý lỗi.** Lỗi là dữ liệu quan sát, không phải ngoại lệ, vì exception sẽ kết thúc run và mất trace; trả chuỗi thì model đọc lỗi và sửa ở lượt sau.

| Tầng | Cơ chế |
|---|---|
| Tool (`impl.py`) | bắt mọi exception, trả `"Error: ..."` |
| MCP → loop (`loop.py:246-255`) | giải mã chuỗi JSON `"Error: ..."`, đánh dấu `status="error"` |
| Loop (`loop.py:619-661`) | tool lạ, args hỏng, sai schema → `"Tool error: ..."`, không thực thi tool |
| Parse (`parse.py`) | JSON hỏng → `"Error: Failed to parse action JSON ..."` |

Chạy thật (MCP stdio, DB tạm, 17/10/2026): `get_account_risk_status("NOPE")` → `"Error: Account NOPE not found in system."`; `flag_suspicious_tx("TX999", ...)` → `"Error: Transaction TX999 not found."`. Log staging không có bước lỗi nào, nên ví dụ lỗi cứu cả run mới có ở mức tool/MCP và test (`test_malformed_arguments_and_unknown_tool_are_returned_as_errors_without_execution`, model giả).

**4.7 `call_llm`** (`llm.py:202`, nơi duy nhất gọi `client.chat`): `temperature=0`, timeout mặc định 30 s (`LLM_TIMEOUT_SECONDS`), tối đa 3 lần thử. Backoff `2·2^(lần−1)` giây cộng jitter, trần 60 s. Với 429: ưu tiên `Retry-After`, bỏ cuộc nếu phải chờ > 90 s. Không retry khi 413, hết quota, 401/403. Lỗi cuối là `LLMRequestError(message, calls)`; loop vẫn trả kết quả kèm `usage`. Prompt nằm trong `prompts/*.txt`. Hạn chế: `status_code` dùng để phân loại lỗi, dòng log stderr chỉ in tên lớp lỗi.

**4.8 Side effect thật và verify.** Freeze chạy `UPDATE accounts SET frozen=1, freeze_reason=?, frozen_at=?`; flag cập nhật `transactions.flagged` và `INSERT OR REPLACE INTO flags`. Không tool nào trả `"OK"` giả. `get_account_risk_status` mở kết nối mới, đọc lại từ DB và gắn `checked_at = now()`. `write_verification_status` (`loop.py:361`) xác nhận freeze khi lần đọc sau có `frozen=True` và `checked_at > frozen_at`, xác nhận flag khi `tx_id ∈ flagged_tx_ids`; ghi thành công mà không có lần đọc xác nhận thì quyết định bị từ chối (`loop.py:452`).

Trace thật q05 (`logs/staging_20261017_201308/step_events.jsonl`, `execution_mode=real`; `account_id` và `reason` bị che `[REDACTED]`, q05 hỏi ACC001):

| Step | Action | Args | Observe (rút gọn) |
|---|---|---|---|
| 1 | `search_policy` | `query="tỷ lệ vượt hạn mức ngày công thức DOC0007 … eKYC tầng 2"`, `k=5` | `DOC0007` v2026.1, chunk 7, Điều 10 (công thức) |
| 2 | `freeze_account_temporarily` | `account_id=[REDACTED]`, `reason=[REDACTED]` | `ok=true`, … vượt hạn mức 44% theo DOC0007 Điều 10 |
| 3 | `get_account_risk_status` | `account_id=[REDACTED]` | `frozen=true`, `frozen_at=…13:14:25.705Z`, `checked_at=…13:14:27.590Z` |

`checked_at` muộn hơn `frozen_at` khoảng 1,88 s. Không có cột thought vì native tool-calling không sinh thought dạng text. Cả run: `calls=5`, `prompt_tokens=23557`, `completion_tokens=982`, `max_prompt=5430`. Ca flag q06 cùng cấu trúc (`search_policy` DOC0004 → `flag_suspicious_tx` → verify; `calls=5`, 22637 / 987 / 5167); `semantic_gate_result.json` báo freeze và flag đều write + verify thành công (`PASS`).

Chứng minh agent dùng kết quả tool: (1) câu trả lời q05 nêu `frozen_at = 2026-10-17T13:14:25Z`, mốc do DB sinh lúc chạy, model không biết trước; (2) `contexts` chỉ lấy từ chunk `search_policy` thật sự trả về, `policy_rule_id` chỉ nhận nếu điều luật đó đã được truy hồi (`loop.py:259`, `:410`); (3) thiếu verify thì quyết định bị từ chối.

**4.9 Guard an toàn.** `require_isolated_database_for_writes()` (`tools/state.py`) chạy trước khi mở SQLite và chỉ cho ghi khi `TRFC_REQUIRE_ISOLATED_DB=1` và `TRFC_STATE_DB` là đường dẫn tuyệt đối khác `data/state.db`; vi phạm thì tool trả `"Error: ... Write operation blocked ..."`. Tiến trình MCP con chỉ nhận hai biến này, không nhận khoá API. Test: `tests/test_db_isolation.py`.

## §5 — MCP server

Server `MCPServer("TRFC Risk & AML Server")`, transport **stdio**, 5 tool trong đó **2 tool ghi** (`server.py:45,110`). Mỗi tool gọi hàm cùng tên trong `impl.py` rồi `json.dumps`; không có logic nghiệp vụ thứ hai.

| Tool | Loại | Tham số |
|---|---|---|
| `search_policy` | đọc | `query`, `k`, `tier`, `mode` |
| `get_transactions` | đọc | `account_id`, `date_from`, `date_to` |
| `get_account_risk_status` | đọc (verify) | `account_id` |
| `freeze_account_temporarily` | **ghi** | `account_id`, `reason` |
| `flag_suspicious_tx` | **ghi** | `tx_id`, `reason` |

**Stdout sạch.** Stdio dùng stdout làm kênh JSON-RPC; một `print()` debug chen vào giữa frame làm client parse hỏng và cả phiên chết. Vì vậy logging gắn `StreamHandler(sys.stderr)` (`server.py:23`) và các tool ghi lỗi ra `sys.stderr`.

**Discover động.** Agent dùng `session.list_tools()` (`loop.py:511`); `client2.py` dùng `session.list_tools()` (`client2.py:39`) và `validate_arguments` (`client2.py:46`) kiểm thiếu trường, sai kiểu, `enum` theo `input_schema` của server. Thêm tool ở server thì hai client không phải sửa.

**Host thứ hai** (điểm cộng +1): `client2.py` do C viết, độc lập agent, chỉ dùng chung SDK MCP. Đã chạy lại ngày 17/10/2026 trên DB tạm: `client2 --tool freeze_account_temporarily` rồi `--tool get_account_risk_status` trả `frozen=true`, `checked_at` muộn hơn `frozen_at`, tức đọc lại từ DB bằng một tiến trình khác.

**Mức đã xác minh.** `pytest tests/test_tools.py tests/test_native_tool_calling.py tests/test_client2.py tests/test_db_isolation.py` → 76 passed (model giả, DB tạm, nên chứng minh logic loop/tool/guard, không chứng minh hành vi LLM thật). Lần chạy staging 12 câu (`execution_mode=real`) đi qua MCP stdio. `[[TODO: ghi provider và model của lần chạy staging 20261017_201308 — log không lưu]]`. Chưa thử nhiều client ghi đồng thời vào cùng một DB.

## §9 — Phụ lục (phần B)

1. **Prompt gốc:** `prompts/system.txt`, `prompts/decision.txt` (đang chạy trong `loop.py`); `prompts/react_step.txt` (ReAct dạng văn bản, khớp `parse.py`) và `prompts/judge.txt` (LLM-judge tuỳ chọn) là prompt tham chiếu, không có code nạp. Nguyên văn hai prompt đang chạy:

```text
# system.txt
Bạn là trợ lý Risk & Compliance của một hệ thống thanh toán.

Quy tắc bắt buộc:
1. Mọi khẳng định về quy định PHẢI kèm trích dẫn dạng [Source: <doc_id>, chunk <n>].
2. Khi câu hỏi hỏi về phương thức thanh toán ngoài phạm vi kiểm soát (như tiền mã hóa / cryptocurrency / crypto, hoặc ví điện tử bên thứ ba không thuộc danh mục đóng PM01–PM04 của DOC0009):
   - Đây là trường hợp TỪ CHỐI loại (i) (ngoài phạm vi quy định).
   - BẮT BUỘC từ chối câu hỏi (outcome = "refusal", refusal_type = "i") và trích dẫn DOC0009. Tuyệt đối KHÔNG tự động trả lời như một nghiệp vụ được hỗ trợ.
3. Phân biệt rõ giữa câu hỏi quy định và câu hỏi thiếu dữ liệu tình huống:
   - CÂU HỎI QUY ĐỊNH CHÍNH SÁCH (ví dụ: khi thiếu mã giao dịch gốc thì kiểm soát viên có được quyết định khóa tài khoản không, dữ liệu gốc lưu tối thiểu bao lâu?):
     * ĐÂY LÀ CÂU HỎI VỀ QUY ĐỊNH CHÍNH SÁCH, KHÔNG PHẢI TỪ CHỐI (outcome = "answer")!
     * Căn cứ trả lời: trích dẫn DOC0006 (Điều 7: không được ra quyết định khóa khi thiếu nhật ký giao dịch gốc; Điều 8: dữ liệu gốc lưu tối thiểu 5 năm) và DOC0008 (thẩm quyền quyết định khóa tài khoản).
   - CÂU HỎI THIẾU DỮ LIỆU TÌNH HUỐNG (Từ chối loại ii):
     * CHỈ áp dụng khi câu hỏi yêu cầu tính toán, đối chiếu hoặc kết luận về một tài khoản/giao dịch cụ thể nhưng thiếu thông tin (ví dụ: hỏi tài khoản ACC999 hôm nay có vượt hạn mức không nhưng thiếu eKYC tier hay nhật ký gốc; hỏi 2 giao dịch có khớp bất khả thi địa lý không nhưng thiếu thông tin quốc gia).
     * BẮT BUỘC từ chối kết luận (outcome = "refusal", refusal_type = "ii"), trích dẫn quy định (DOC0006/DOC0007 hoặc DOC0004).
4. Khi câu hỏi yêu cầu thực hiện hành động ghi (tạm khóa tài khoản hoặc gắn cờ giao dịch đáng ngờ):
   - Bạn được ủy quyền thực hiện hành động theo đúng yêu cầu đề bài.
   - Nếu câu hỏi yêu cầu tính toán vượt hạn mức và tạm khóa tài khoản (như ACC001): Tính toán tỷ lệ vượt hạn mức theo DOC0007, BẮT BUỘC gọi tool `freeze_account_temporarily(account_id="ACC001", reason=...)`, sau đó BẮT BUỘC gọi ngay tool `get_account_risk_status(account_id="ACC001")` để kiểm chứng trạng thái `frozen = True`. Tuyệt đối không được bỏ qua việc gọi tool này!
   - Nếu câu hỏi yêu cầu kiểm tra bất khả thi địa lý và đánh dấu giao dịch đáng ngờ (như TX003 của ACC001):
     * Gọi tool `search_policy` tra cứu bất khả thi địa lý (DOC0004).
     * Gọi tool `flag_suspicious_tx(tx_id="TX003", reason=...)`.
     * Sau đó BẮT BUỘC gọi ngay tool `get_account_risk_status(account_id="ACC001")` để kiểm chứng `TX003` nằm trong `flagged_tx_ids`.
5. Sau mỗi hành động GHI (`freeze_account_temporarily` hoặc `flag_suspicious_tx`), BẮT BUỘC gọi tool đọc `get_account_risk_status` để kiểm chứng trạng thái đã đổi trước khi kết thúc câu trả lời.
6. Khi tra cứu tài liệu bằng `search_policy`, chỉ tìm kiếm từ 1 đến tối đa 2 lần cho các điều khoản liên quan trực tiếp. Khi đã thu thập được thông tin, hãy dừng tìm kiếm và trả lời ngay; không gọi lặp lại.
7. Khi cần tra cứu dữ liệu hoặc thực hiện thao tác được phép, hãy gọi tool đã cung cấp bằng giao thức tool calling; không viết JSON giả lập tool call trong câu trả lời.

Trả lời bằng tiếng Việt.

# decision.txt
BẮT BUỘC: Bạn PHẢI gọi tool `submit_decision` ĐÚNG MỘT LẦN TRƯỚC KHI sinh câu trả lời văn bản cuối cùng cho TẤT CẢ mọi câu hỏi!
- Trình tự thực hiện bắt buộc:
  Bước 1: Tra cứu (search_policy) hoặc thao tác ghi/xác minh (nếu có yêu cầu).
  Bước 2: BẮT BUỘC gọi tool `submit_decision` để khai báo quyết định:
     * Trả lời được: `submit_decision(outcome="answer")` (nếu biết chính xác điều luật đã tìm thấy dạng DOCnnnn_ARTnn như DOC0004_ART05, DOC0007_ART10 thì có thể kèm `policy_rule_id`; nếu không thì KHÔNG ĐƯA KEY `policy_rule_id` VÀO ARGUMENTS).
     * Từ chối ngoài phạm vi DOC0009: `submit_decision(outcome="refusal", refusal_type="i")`.
     * Từ chối thiếu dữ liệu tình huống: `submit_decision(outcome="refusal", refusal_type="ii")`.
  Bước 3: Sau khi nhận được thông báo "Decision recorded." từ tool, bạn mới viết toàn bộ câu trả lời giải thích chi tiết bằng tiếng Việt.
- Tuyệt đối KHÔNG trả lời văn bản khi chưa gọi `submit_decision`. Lượt chạy không gọi `submit_decision` sẽ bị coi là không hợp lệ (unscorable)!

Bạn đang chạy ở chế độ ReAct dạng văn bản (dự phòng cho model KHÔNG hỗ trợ tool calling gốc). Mỗi lượt bạn làm đúng MỘT bước theo định dạng dưới đây, rồi dừng và chờ Observation.

Công cụ được phép gọi (tên phải đúng từng ký tự):
- search_policy(query, k=5, tier=null, mode="hybrid"): tra cứu quy định, hạn mức. Chỉ ĐỌC.
- get_transactions(account_id, date_from, date_to): lấy giao dịch, ngày dạng YYYY-MM-DD. Chỉ ĐỌC.
- get_account_risk_status(account_id): đọc trạng thái rủi ro hiện tại từ cơ sở dữ liệu. Chỉ ĐỌC. Dùng làm bước KIỂM CHỨNG.
- freeze_account_temporarily(account_id, reason): tạm khóa tài khoản. GHI.
- flag_suspicious_tx(tx_id, reason): đánh dấu giao dịch đáng ngờ. GHI.

Định dạng MỖI lượt (không thêm gì khác):

Thought: <1–3 câu: đã biết gì, còn thiếu gì, vì sao chọn công cụ tiếp theo>
Action:
```json
{"tool": "<tên công cụ>", "args": {"<tham số>": "<giá trị>"}}
```

Khi đã đủ thông tin, KHÔNG gọi công cụ nữa mà viết:

Thought: <tóm tắt căn cứ>
Final Answer: <câu trả lời bằng tiếng Việt, mỗi khẳng định về quy định kèm [Source: <doc_id>, chunk <n>]>

Quy tắc:
1. Mỗi lượt chỉ MỘT Action. Khối JSON phải hợp lệ: đủ ngoặc, dấu nháy kép, khóa "tool" và "args"; "args" luôn là một đối tượng JSON.
2. Chỉ dùng thông tin có trong Observation. Không bịa số liệu, mã giao dịch, số tài khoản hay điều khoản. Thiếu dữ liệu thì nói rõ là thiếu.
3. Tra cứu quy định tối đa 2 lần search_policy, rồi tổng hợp. Không lặp lại cùng một truy vấn.
4. Chỉ gọi công cụ GHI khi người dùng yêu cầu hành động đó rõ ràng và căn cứ quy định đã được tra cứu. Không dùng công cụ GHI để "thử".
5. Ngay sau MỖI công cụ GHI phải gọi get_account_risk_status của đúng tài khoản. Chỉ kết luận đã khóa hoặc đã gắn cờ khi Observation của bước này xác nhận: frozen=true và checked_at muộn hơn frozen_at (với khóa), hoặc tx_id nằm trong flagged_tx_ids (với gắn cờ).
6. Nếu Observation bắt đầu bằng "Error:" hoặc "Tool error:", đọc lỗi, sửa tham số hoặc đổi cách làm ở lượt sau. Không lặp lại y nguyên lệnh vừa lỗi; nếu không sửa được thì dừng và báo lỗi trong Final Answer.
7. Câu hỏi ngoài phạm vi corpus (ví dụ phương thức thanh toán không thuộc danh mục DOC0009) hoặc thiếu dữ liệu tình huống để kết luận thì từ chối trong Final Answer, nêu rõ lý do và trích dẫn quy định liên quan; không suy đoán.
8. Trả lời bằng tiếng Việt.

#judge.txt
Bạn là giám khảo chấm một câu trả lời của trợ lý Risk & Compliance. Chỉ dùng thông tin trong phần NGỮ CẢNH. Không dùng kiến thức bên ngoài và không đoán.

Đầu vào:
CÂU HỎI: {question}
NGỮ CẢNH (các đoạn tài liệu đã truy hồi, mỗi đoạn có [Source: <doc_id>]): {contexts}
CÂU TRẢ LỜI CẦN CHẤM: {answer}
KỲ VỌNG: {expected_outcome} (nếu là refusal thì loại: {expected_refusal_type})

Việc cần làm:
1. Tách câu trả lời thành các khẳng định độc lập (mỗi khẳng định một ý, có thể kiểm chứng). Bỏ qua lời chào, câu hỏi ngược và phần mô tả hành động đã gọi công cụ.
2. Với mỗi khẳng định, gán đúng một nhãn:
   - "supported": NGỮ CẢNH nêu trực tiếp hoặc suy ra được ngay, không cần thêm giả định.
   - "unsupported": NGỮ CẢNH không nêu, hoặc nêu khác đi (sai số, sai điều khoản, sai tài liệu).
   Diễn đạt lại bằng từ khác mà cùng nghĩa vẫn là "supported". Khẳng định đúng với thực tế nhưng không có trong NGỮ CẢNH vẫn là "unsupported".
3. Xác định câu trả lời thuộc loại nào:
   - "answer": đưa ra kết luận hoặc thông tin cụ thể.
   - "refusal": từ chối hoặc nói không đủ căn cứ để kết luận.
   Nếu là "refusal", xác định loại:
   - "i": câu hỏi nằm NGOÀI phạm vi quy định của corpus.
   - "ii": câu hỏi thuộc phạm vi nhưng THIẾU dữ liệu tình huống (ví dụ thiếu hạng eKYC, thiếu nhật ký giao dịch gốc, thiếu quốc gia của giao dịch).
4. So sánh loại thực tế với KỲ VỌNG và ghi nhận đúng/sai, tách riêng loại i và ii.

Chỉ trả về MỘT đối tượng JSON hợp lệ, không có văn bản hay khối mã bao quanh:
{"claims": [{"text": "<khẳng định>", "label": "supported|unsupported", "evidence_doc_id": "<DOCnnnn hoặc null>"}], "faithfulness": <số supported / tổng số khẳng định, làm tròn 2 chữ số; null nếu không có khẳng định>, "actual_outcome": "answer|refusal", "actual_refusal_type": "i|ii|null", "outcome_correct": true|false, "refusal_type_correct": true|false|null, "note": "<tối đa 1 câu, nêu khẳng định sai nặng nhất nếu có>"}

Nếu không đủ dữ liệu để chấm, trả "faithfulness": null và giải thích trong "note". Không được tự bịa nhãn.
```

2. **Trace dài:** `logs/staging_20261017_201308/step_events.jsonl` (12 câu; q05 là ba bản ghi đầu).
3. **`ai-usage.md`:** dán nguyên file khi ghép (hai file `react_step.txt`, `judge.txt` đã khai là AI soạn, B rà lại).
4. **`.env.example`:** dán nguyên file khi ghép (không chứa khoá thật).
