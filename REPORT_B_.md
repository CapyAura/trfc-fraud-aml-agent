# Bản nháp phần B — §2, §4, §5, §9 (gửi C ghép `report.docx`)

> Người viết: **B** (Agent & Tool/MCP). Mọi số liệu dưới đây truy được về code trong repo, `logs/staging_20261017_201308/`, hoặc lệnh chạy ghi kèm. Chỗ nào chưa có bằng chứng thì ghi rõ, không điền số.

## 0. Ghi chú cho C và cả nhóm — chỗ KHUNG `REPORT.md` lệch với CODE

Đọc kỹ trước khi ghép, vì GV sẽ đọc code chứ không đọc khung:

| # | Khung nói | Code thật | Cách đã viết trong bản nháp |
|---|---|---|---|
| 1 | Vòng ReAct: `LLM → parse action JSON → gọi tool` | `agent/loop.py` dùng **native tool-calling** (model trả `tool_calls` có cấu trúc). `parse.py` **không nằm trên đường chạy của loop**, chỉ có test `test_parse_action_khong_crash_voi_json_hong`. Test `test_json_text_in_assistant_content_is_never_executed_as_a_tool_call` chứng minh JSON viết trong nội dung câu trả lời không bao giờ bị thực thi. | §4.4 mô tả đúng native loop; `parse.py` nêu là tiện ích dự phòng có test, không claim là đường chính. |
| 2 | Sơ đồ: agent gọi thẳng `tools/impl.py`, MCP là nhánh riêng | Agent chạy **qua MCP stdio**: `run_detailed()` mở `trfc.mcp_server.server` bằng `stdio_client`, rồi `list_tools()` → `call_tool()`. | Sơ đồ §2 vẽ lại đúng luồng. |
| 3 | "Thought" trong bảng trace | Native tool-calling **không có thought dạng text** trong log. | Bảng trace dùng cột step · action · args · observe, nói rõ lý do bỏ cột thought. |
| 4 | `call_llm` "log lỗi HTTP kèm `status_code`" | `status_code` được dùng để **phân loại** (429/401/403/413) nhưng dòng log stderr chỉ in tên lớp lỗi (`llm.py:~303`). Chi tiết HTTP nằm trong `LLMRequestError`. | §4.7 mô tả đúng. Đề xuất sửa 1 dòng ở §0.1 bên dưới. |
| 5 | Docstring tool nêu "khi nào dùng / khi nào không" | Docstring `freeze`/`flag` **ngắn**, không nêu điều kiện. Hướng dẫn chọn tool nằm ở `prompts/system.txt` quy tắc 4–6. | §4.3 dán docstring thật và nói thẳng. |
| 6 | `prompts/react_step.txt`, `judge.txt` | Trước đây **rỗng** (1 byte). Nay đã có nội dung, nhưng **không có code nào nạp** hai file này: loop dùng `system.txt` + `decision.txt`, eval chấm bằng so khớp chuỗi (`eval/README.md`: "No LLM judge is used"). | §9.1 dán nguyên văn và ghi đúng trạng thái "tham chiếu, không chạy". `ai-usage.md` đã sửa: hai file do AI soạn, B rà lại. |
| 7 | Trace "thật" từ `logs/` | Log staging đã **che** `account_id`, `tx_id`, `reason` (`[REDACTED]`) bằng `eval/redaction.py`. | Bảng trace giữ nguyên `[REDACTED]`; ánh xạ sang `ACC001`/`TX003` lấy từ câu hỏi q05/q06 trong `tests/testset.jsonl`. |
| 8 | — | `step_events.jsonl` ghi `timestamp` **cùng một mốc** cho cả run (ghi sau khi chạy xong), nên không dùng làm bằng chứng thứ tự. | Bằng chứng thứ tự dùng `frozen_at` < `checked_at` nằm trong kết quả tool. |

### 0.1 Đề xuất sửa nhỏ trước khi nộp (không bắt buộc, nhưng GV có thể hỏi)

1. `llm.py`: thêm `status_code` vào dòng log lỗi, ví dụ `f"... failed: {type(e).__name__} status={status_code}"`. Hiện `status_code` được tính ở dòng sau dòng `print`, nên cần dời `status_code = getattr(e, "status_code", None)` lên trước.
2. `server.py`: viết lại docstring hai tool ghi theo kiểu prompt. Ví dụ cho `freeze_account_temporarily`: *"Tạm khoá một tài khoản và ghi lý do vào state.db. Chỉ dùng khi người dùng yêu cầu khoá rõ ràng VÀ đã xác định tỷ lệ vượt hạn mức hoặc căn cứ quy định. Không dùng để chỉ kiểm tra trạng thái (dùng get_account_risk_status). Sau khi gọi PHẢI gọi get_account_risk_status để xác minh."* (Đây là **đề xuất**, chưa có trong code.)
3. ~~`react_step.txt`/`judge.txt` rỗng~~ → **đã điền** (B rà lại nội dung trước khi nộp; nếu không giải thích được từng quy tắc thì không nên nhận là tự viết). `prompts/README.md` và `ai-usage.md` đã cập nhật.

---

## §2 — Kiến trúc tổng thể · 1 trang · B (vẽ), A + C review

### 2.1 Sơ đồ khối

```
┌──────────────┐  câu hỏi   ┌───────────────────────────────────────┐
│ CLI / eval   │ ─────────▶ │ Agent loop  agent/loop.py             │
│ (run_eval,   │            │  • messages = system.txt + câu hỏi    │
│  loop.main)  │ ◀───────── │  • tối đa MAX_STEPS = 8 lượt model    │
└──────────────┘  AgentRun  │  • kiểm schema args trước khi gọi     │
                  Result    └───────┬───────────────────▲───────────┘
                                    │ call_llm()        │ tool_calls
                                    ▼                   │
                          ┌──────────────────┐          │
                          │ agent/llm.py     │ ─────────┘
                          │ retry·timeout    │   LLM provider (Groq mặc định)
                          └──────────────────┘
                                    │ list_tools() / call_tool()  (JSON-RPC)
══════════════ ranh giới tiến trình: stdio (stdout = JSON-RPC, log = stderr) ══════════════
┌───────────────────────────────────────┐        ┌──────────────────────────┐
│ MCP server  mcp_server/server.py      │◀───────│ client2.py (host thứ hai │
│ 5 tool, ≥1 tool ghi                   │  stdio │ do C viết, độc lập agent)│
└───────────────────┬───────────────────┘        └──────────────────────────┘
                    │ gọi hàm cùng tên
                    ▼
┌───────────────────────────────────────┐
│ tools/impl.py  (5 hàm, trả dataclass  │
│ hoặc chuỗi "Error: ...", không raise) │
└───────┬───────────────────────┬───────┘
        │ search_policy         │ get_transactions / get_account_risk_status
        ▼                       │ freeze_account_temporarily / flag_suspicious_tx
┌───────────────┐               ▼
│ rag/search.py │      ┌──────────────────────────────┐
│ (A) dense +   │      │ SQLite  tools/state.py (B)   │
│ hybrid, tier  │      │ accounts · transactions ·    │
└───────┬───────┘      │ flags  — GHI THẬT            │
        ▼              │ guard: TRFC_REQUIRE_ISOLATED_DB│
 data/docs/DOC0001–9   └──────────────────────────────┘
```

Bốn ranh giới cần nói được khi vấn đáp: (1) người dùng ↔ agent; (2) agent ↔ LLM, chỉ đi qua `call_llm()`; (3) agent ↔ tool, qua **MCP stdio**, tách tiến trình; (4) tool ↔ trạng thái, chỉ `state.py` mở SQLite.

### 2.2 Luồng một câu hỏi mẫu (q05, ca freeze)

`search_policy` (tra công thức vượt hạn mức, DOC0007 Điều 10) → `freeze_account_temporarily` (ghi `state.db`) → `get_account_risk_status` (verify, đọc lại từ DB). Trace chi tiết ở §4.8, không lặp lại ở đây.

### 2.3 Bảng ranh giới trách nhiệm

| Khối | Người | Thư mục | Giao diện với khối khác |
|---|---|---|---|
| RAG | A | `src/trfc/rag/`, `data/docs/`, `config.toml` | `search_policy(query, k, tier, mode) -> list[Chunk]`, `Chunk` định nghĩa ở `tools/schemas.py` |
| Agent + Tool + MCP | B | `src/trfc/agent/`, `tools/`, `mcp_server/server.py`, `prompts/` | 5 tool qua MCP; `AgentRunResult` cho eval |
| Eval + Log | C | `eval/`, `tests/`, `logs/`, `mcp_server/client2.py` | gọi `run_detailed()`; đọc `tool_trace`, `usage` |

**Điểm cần nhấn:** agent và `client2.py` cùng đi vào **một MCP server**, và server gọi **cùng `tools/impl.py`**, nên hành vi tool giống nhau ở mọi đường gọi. Không có hai bản cài đặt tool để lệch nhau.

---

## §4 — Thiết kế Agent & tool · 2 trang · B

### 4.1 Tool schema bằng `@dataclass` (yêu cầu 2.3)

Schema nằm ở `src/trfc/tools/schemas.py`, GV kiểm bằng `grep -n "@dataclass"`. Không dùng dict thô vì dict không có kiểu, sai tên trường chỉ lộ khi chạy.

```python
@dataclass
class Chunk:                      # A import, B sở hữu file
    doc_id: str; title: str; version: str
    chunk_index: int; text: str; score: float
    tier: int | None = None

@dataclass
class RiskStatus:                 # kết quả của bước VERIFY
    account_id: str
    frozen: bool
    freeze_reason: str | None
    frozen_at: datetime | None
    flagged_tx_ids: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)
```

`Transaction` (tx_id, account_id, amount, currency, ts, country, method, location) và `Ack` (ok, message, tx_id) cùng file. `checked_at` có mặt để chứng minh lần đọc là **mới**, không phải đọc lại phản hồi của lệnh ghi.

### 4.2 Năm tool

| Tool | Loại | Chữ ký | Trả về |
|---|---|---|---|
| `search_policy` | đọc | `(query, k=5, tier=None, mode="hybrid")` | `list[Chunk]` (uỷ quyền cho `rag.search`, B không sửa logic) |
| `get_transactions` | đọc | `(account_id, date_from, date_to)` | `list[Transaction]` |
| `get_account_risk_status` | đọc, **bước verify** | `(account_id)` | `RiskStatus` |
| `freeze_account_temporarily` | **GHI** | `(account_id, reason)` | `Ack` |
| `flag_suspicious_tx` | **GHI** | `(tx_id, reason)` | `Ack` |

Qua MCP, kết quả được `json.dumps` (dataclass → dict, `datetime` → ISO) nên model nhận chuỗi JSON.

### 4.3 Mô tả tool là một phần của prompt

Model chọn tool dựa trên mô tả mà MCP trả về từ `list_tools()`, chính là docstring trong `server.py`. Hai docstring thật của tool ghi:

```python
def freeze_account_temporarily(account_id: str, reason: str) -> str:
    """Lệnh ghi Side-Effect: Tạm thời khóa tài khoản và ghi nhận lý do vào state.db."""

def flag_suspicious_tx(tx_id: str, reason: str) -> str:
    """Lệnh ghi Side-Effect: Đánh dấu cờ giao dịch nghi vấn vào state.db."""
```

**Nói thẳng:** hai docstring này nêu *tool làm gì*, chưa nêu *khi nào dùng / khi nào không*. Điều kiện chọn tool hiện nằm trong `prompts/system.txt`: quy tắc 4 (chỉ ghi khi câu hỏi yêu cầu hành động, kèm cách tính tỷ lệ vượt hạn mức), quy tắc 5 (sau mỗi lệnh ghi bắt buộc gọi `get_account_risk_status`), quy tắc 6 (tra cứu tối đa 2 lần). Tác dụng thực tế đã thấy ở log: ở cả 2 ca ghi (q05, q06), model gọi đúng một tool ghi rồi gọi verify, không gọi tool ghi còn lại. Đây mới là **hai ca** nên chỉ kết luận được ở mức đó. Hướng cải thiện (đưa điều kiện vào docstring) nằm ở §7 và §0.1.

### 4.4 Vòng lặp agent (yêu cầu 2.2)

Tự viết, không LangChain/LlamaIndex. Mỗi lượt (`loop.py:541`):

```
call_llm(messages, tools) ─▶ có tool_calls? ─ không ─▶ câu trả lời cuối (status=completed)
                                   │ có
                                   ▼
        kiểm: tool có được discover? · args là JSON object? · khớp input_schema?
                                   │ hợp lệ                │ sai
                                   ▼                       ▼
                    session.call_tool() qua MCP     "Tool error: ..." (không gọi tool)
                                   └───────── ghi tool_trace, thêm message role=tool ─▶ lặp
```

Điểm thiết kế:

- **Tool được discover động** bằng `session.list_tools()` (`loop.py:511`), không hard-code danh sách; thêm tool ở server thì loop không phải sửa.
- **Kiểm đối số theo `input_schema` do server cung cấp** (`_validate_arguments`, `loop.py:184`): thiếu trường bắt buộc, sai kiểu, ngoài `enum`.
- **Tool riêng của runtime** `submit_decision` (khai `answer`/`refusal`, loại i/ii, mã điều luật) được xử lý trong loop, không gửi sang MCP và không vào `tool_trace` (`loop.py:297`). Mã điều luật chỉ được nhận nếu điều đó thật sự đã được truy hồi trong run (`_rule_is_evidenced`, `loop.py:410`).
- **Giới hạn tra cứu**: `search_policy` quá 2 lần thì loop trả thông báo hệ thống bảo tổng hợp, không gọi tiếp (`loop.py:636-643`).
- `parse.py` (`parse_action`) là bộ parse JSON chịu lỗi, có test, **không nằm trên đường chạy chính**; `prompts/react_step.txt` là prompt ReAct dạng văn bản có định dạng `Action` khớp với `parse_action` (đã kiểm: ví dụ trong prompt parse ra `Action(tool='search_policy', ...)`), dùng làm dự phòng cho model không có tool calling và cũng không được loop nạp. Trên đường chính, JSON giả lập tool call viết trong nội dung câu trả lời không bao giờ được thực thi (test `test_json_text_in_assistant_content_is_never_executed_as_a_tool_call`).

### 4.5 `MAX_STEPS = 8`

- Đọc từ `config.toml` mục `[agent] max_steps` (`load_max_steps`, `loop.py:105`), không hard-code; giá trị sai thì quay về 8 và ghi cảnh báo.
- Đơn vị là **số lượt gọi model**. Trên 12 câu của lần chạy staging, số lượt dao động **2–5** (`usage.calls`; q05 và q06 cao nhất, 5 lượt), nên 8 còn dư 3 lượt.
- **Hết bước mà chưa xong**: loop thoát có kiểm soát, `status="failed"`, `error="Native tool loop exceeded MAX_STEPS (8)"` (`loop.py:671`). `run()` trả chuỗi `"Error: ..."` (`loop.py:716`), không ném exception. `tool_trace` đã thu thập được giữ lại. Có test `test_maximum_model_turns_is_enforced` (đặt `max_steps=2`, model cứ gọi tool mãi, kết quả đúng 2 lần gọi tool rồi dừng).

### 4.6 Xử lý lỗi (yêu cầu 2.6)

Nguyên tắc: **lỗi là dữ liệu quan sát, không phải ngoại lệ.** Agent thấy lỗi và tự điều chỉnh; run không chết.

| Tầng | Cơ chế | Vị trí |
|---|---|---|
| Tool | bắt mọi exception, trả `"Error: ..."` | `tools/impl.py`, từng hàm |
| MCP | kết quả `"Error: ..."` bị bọc thành chuỗi JSON; loop giải mã lại và đánh dấu `status="error"` | `loop.py:246-255` |
| Loop | tool lạ, args JSON hỏng, sai schema, tool ném lỗi → `"Tool error: ..."` làm quan sát, **không thực thi tool** | `loop.py:619-661` |
| Parse | JSON hỏng/thiếu ngoặc → `"Error: Failed to parse action JSON ..."` | `parse.py:50-52` |

**Vì sao trả chuỗi thay vì raise:** exception trong một lượt sẽ kết thúc cả run và mất `tool_trace`. Trả chuỗi thì model đọc lỗi ở lượt kế và sửa (ví dụ gọi lại với tham số đúng).

**Ví dụ chạy thật (offline, MCP stdio, DB tạm `/tmp/iso/state.db`, chạy ngày 17/10/2026):**

```text
get_account_risk_status(account_id="NOPE")
  → "Error: Account NOPE not found in system."

(thiếu TRFC_REQUIRE_ISOLATED_DB) freeze_account_temporarily("ACC001", "x")
  → "Error: Failed to freeze account ACC001: Write operation blocked:
     set TRFC_REQUIRE_ISOLATED_DB=1 to enable isolated writes"

(đã bật guard) flag_suspicious_tx("TX999", "x")
  → "Error: Transaction TX999 not found."
```

**Giới hạn trung thực:** log staging (`logs/staging_20261017_201308/`) **không có bước nào lỗi** (mọi tool call `status=completed`), nên chưa có trace thật nào trong đó cho thấy lỗi tool "cứu" một run. Ví dụ trên chứng minh hành vi ở mức tool/MCP, và test `test_malformed_arguments_and_unknown_tool_are_returned_as_errors_without_execution` chứng minh ở mức loop (dùng model giả).

### 4.7 `call_llm` (yêu cầu 2.4)

Hàm duy nhất chứa lời gọi `client.chat` (`llm.py:202`); loop chỉ gọi qua `call_llm_async` bọc ngoài. Cấu hình: `temperature=0.0`, `max_tokens=650`, timeout mặc định **30 s** (ghi đè bằng `LLM_TIMEOUT_SECONDS`), `max_retries=3` (`LLM_MAX_RETRIES`).

- **Retry có backoff**: chờ `2·2^(lần−1)` giây cộng jitter, trần 60 s.
- **429**: ưu tiên header `Retry-After`/`ratelimit-reset`; nếu không có thì đọc chuỗi "try again in …s" của provider; nếu thời gian chờ > 90 s thì bỏ cuộc có kiểm soát.
- **Không retry** khi lỗi vô ích: 413 (payload quá lớn), hết quota/billing, 401/403.
- Lỗi cuối cùng ném `LLMRequestError(message, calls)`; loop bắt lại, ghi `result.error` và vẫn trả kết quả có `usage`, nên số lần gọi đếm được kể cả khi thất bại. SDK retry nội bộ bị tắt để `usage.calls` phản ánh đúng số request thật.
- Prompt nằm ngoài code: `prompts/system.txt`, `prompts/decision.txt`.
- Hạn chế: dòng log stderr chỉ in tên lớp lỗi và số lần thử; `status_code` dùng để phân loại chứ chưa in ra (xem §0.1).

### 4.8 Side effect thật và bước verify (yêu cầu 2.7)

- **Ghi SQLite thật**: `freeze_account_temporarily` chạy `UPDATE accounts SET frozen=1, freeze_reason=?, frozen_at=?`; `flag_suspicious_tx` cập nhật `transactions.flagged` và `INSERT OR REPLACE INTO flags`. Không có hàm nào trả `"OK"` giả.
- **Verify đọc lại từ DB**: `get_account_risk_status` mở kết nối mới, đọc `accounts` và `flags`, gắn `checked_at = now()` (`impl.py`).
- **Hai điều kiện verify** (`write_verification_status`, `loop.py:361`): freeze được xác nhận khi lần đọc **sau đó** của đúng tài khoản có `frozen=True` và `checked_at > frozen_at`; flag được xác nhận khi `tx_id ∈ flagged_tx_ids`. Hàm chỉ duyệt trace, không tự gọi tool. Nếu có lệnh ghi thành công mà không có lần đọc xác nhận thì quyết định bị từ chối với mã `write_verification_missing` (`loop.py:452`).

**Trace thật q05 (ca freeze)** — `logs/staging_20261017_201308/step_events.jsonl`, `execution_mode=real`:

| Step | Action | Args (như trong log) | Observe (rút gọn) |
|---|---|---|---|
| 1 | `search_policy` | `query="tỷ lệ vượt hạn mức ngày công thức DOC0007 hạn mức giao dịch eKYC tầng 2"`, `k=5` | chunk `DOC0007` v`2026.1`, `chunk_index=7`, Điều 10 (công thức tỷ lệ vượt hạn mức) |
| 2 | `freeze_account_temporarily` | `account_id=[REDACTED]`, `reason=[REDACTED]` | `{"ok":true,"message":"Account [REDACTED] successfully frozen temporarily. Reason=… tỷ lệ vượt hạn mức 44% theo DOC0007 Điều 10 …"}` |
| 3 | `get_account_risk_status` | `account_id=[REDACTED]` | `frozen=true`, `frozen_at=2026-10-17T13:14:25.705579+00:00`, `checked_at=2026-10-17T13:14:27.590021+00:00` |

`checked_at − frozen_at ≈ 1,88 s > 0` nên lần đọc là mới. `account_id` bị che theo `eval/redaction.py`; câu hỏi q05 trong `tests/testset.jsonl` là tài khoản ACC001 (tầng eKYC 2). Không có cột thought vì native tool-calling không sinh thought dạng text. Cả run dùng `calls=5`, `prompt_tokens=23557`, `completion_tokens=982`, `max_prompt=5430`; trong 5 lượt gọi model chỉ có 3 tool MCP được ghi vào trace (lượt còn lại là `submit_decision` của runtime và câu trả lời cuối, theo thiết kế ở `loop.py:297`).

**Ca flag q06** cùng cấu trúc: `search_policy` (DOC0004, chunk 2, quy tắc bất khả thi địa lý) → `flag_suspicious_tx` → `get_account_risk_status`; `usage`: `calls=5`, `prompt_tokens=22637`, `completion_tokens=987`, `max_prompt=5167`. `semantic_gate_result.json` của lần chạy này báo `freeze_write_success`, `freeze_verify_success`, `flag_write_success`, `flag_verify_success` đều `true` (overall `PASS`).

**Chứng minh agent dùng kết quả tool, không tự diễn** (3 bằng chứng):

1. Câu trả lời cuối của q05 nêu `frozen_at = 2026-10-17T13:14:25Z`. Mốc này do DB sinh lúc chạy, model không thể biết trước.
2. `contexts` chỉ được lấy từ chunk mà `search_policy` thật sự trả về (`_retrieved_contexts`, `loop.py:259`); `policy_rule_id` chỉ được nhận nếu điều luật đó nằm trong các chunk đã truy hồi.
3. Kết quả quyết định phụ thuộc verify: không có lần đọc xác nhận thì bị từ chối (`loop.py:452`).

**Lưu ý trung thực về bằng chứng (nên nói trước khi GV hỏi):** q05 trong lần chạy này tra về cả chunk của `DOC0003` (bản cũ đã bị thay thế) cùng với `DOC0007`, và chỉ số `answer_correctness` của q05 trong `evaluation.jsonl` là `False` do tiêu chí `contains_all` có chuỗi `"[REDACTED] VND"`. Hai điểm này thuộc phần A và C, ghi ở đây để cả nhóm thống nhất cách giải thích.

### 4.9 Guard an toàn cho tool ghi

`require_isolated_database_for_writes()` (`tools/state.py`) chạy **trước khi mở SQLite**, và chỉ cho ghi khi:

- `TRFC_REQUIRE_ISOLATED_DB=1`;
- `TRFC_STATE_DB` là **đường dẫn tuyệt đối**, khác `data/state.db` mặc định;
- tuỳ chọn thêm: `TRFC_REQUIRE_OUTSIDE_REPO=1` (DB nằm ngoài repo), `TRFC_PREVENT_DB_OVERWRITE=1` (không ghi đè DB đã có).

Vi phạm → tool trả `"Error: ... Write operation blocked: ..."`. Tiến trình MCP con nhận đúng hai biến môi trường này từ `mcp_server_environment()` và **không** thừa hưởng khoá API. Bộ test `tests/test_db_isolation.py` bao phủ các nhánh trên.

---

## §5 — MCP server · 1 trang · B

### 5.1 Bảng tool và hợp đồng

Server: `MCPServer("TRFC Risk & AML Server")`, transport **stdio** (`server.py:45,110`). 5 tool, trong đó **2 tool ghi** (yêu cầu tối thiểu là ≥2 tool, ≥1 tool ghi).

| Tool | Loại | Tham số (theo `input_schema` sinh từ type hint) | Ghi chú |
|---|---|---|---|
| `search_policy` | đọc | `query: str`, `k: int=5`, `tier: int\|None`, `mode: str="hybrid"` | trả JSON danh sách chunk |
| `get_transactions` | đọc | `account_id`, `date_from`, `date_to` (YYYY-MM-DD) | trả JSON danh sách giao dịch |
| `get_account_risk_status` | đọc (verify) | `account_id` | trả `RiskStatus` dạng JSON |
| `freeze_account_temporarily` | **ghi** | `account_id`, `reason` | ghi `accounts` |
| `flag_suspicious_tx` | **ghi** | `tx_id`, `reason` (cả hai bắt buộc) | ghi `transactions` + `flags` |

Server là lớp mỏng: mỗi tool gọi hàm cùng tên trong `tools/impl.py` rồi `json.dumps`. Không có logic nghiệp vụ thứ hai.

### 5.2 Stdout sạch

Với transport stdio, **stdout là kênh JSON-RPC**. Một `print()` debug sẽ chen vào giữa các frame, client không parse được và cả phiên hỏng. Vì vậy:

- logging gắn `logging.StreamHandler(sys.stderr)` (`server.py:23`), `basicConfig` truyền `handlers` rõ ràng;
- các tool trong `impl.py` ghi lỗi bằng `print(..., file=sys.stderr)`;
- tiến trình MCP con do agent khởi chạy (`mcp_server_environment`) chỉ nhận biến môi trường cần thiết.

Bằng chứng chạy thật: lệnh `client2` ở §5.4 chạy trọn một phiên (initialize, list_tools, call_tool) với log hiện ở stderr và kết quả JSON sạch ở stdout.

### 5.3 Discover động, không hard-code

Cả hai client lấy danh sách và schema từ server lúc chạy:

- agent: `session.list_tools()` (`loop.py:511`), schema gửi thẳng cho model, đối số kiểm theo `input_schema` (`loop.py:184`);
- `client2.py`: `session.list_tools()` (`client2.py:39`), `call_discovered_tool` từ chối tên không có trong lần discover và gọi `validate_arguments` (`client2.py:46`) kiểm thiếu trường, sai kiểu, `enum`.

**Thêm tool mới ở `server.py` thì cả hai client không phải sửa.** Ngoại lệ duy nhất trong loop là tên `submit_decision`, đã được đặt trước làm tên dành riêng của runtime (trùng tên với tool MCP thì loop báo lỗi, `loop.py:519-520`).

### 5.4 Host thứ hai (điểm cộng +1)

`src/trfc/mcp_server/client2.py` do **C** viết, không dùng chung code với agent loop, chỉ dùng cùng SDK MCP. Người viết client khác người viết server nên interop được kiểm tra thật.

Lệnh đã chạy lại ngày 17/10/2026, DB tạm đặt ngoài repo:

```bash
export PYTHONPATH=src TRFC_STATE_DB=/tmp/iso/state.db TRFC_REQUIRE_ISOLATED_DB=1
python -m trfc.mcp_server.client2 --tool freeze_account_temporarily \
    --arguments '{"account_id":"ACC001","reason":"demo"}'
python -m trfc.mcp_server.client2 --tool get_account_risk_status \
    --arguments '{"account_id":"ACC001"}'
```

Kết quả: lệnh đầu in `{"ok": true, "message": "Account ACC001 successfully frozen temporarily. Reason: demo", ...}`; lệnh sau in `frozen: true`, `frozen_at = 2026-10-17T16:28:34.97…`, `checked_at = 2026-10-17T16:28:36.65…`, tức đọc lại **từ DB** sau lệnh ghi, bằng một tiến trình khác. Gọi tài khoản không tồn tại trả `"Error: Account NOPE not found in system."`.

### 5.5 Kiểm thử và giới hạn trung thực

- **Đã kiểm:** `PYTHONPATH=src pytest tests/test_tools.py tests/test_native_tool_calling.py tests/test_client2.py tests/test_db_isolation.py -q` → **76 passed** (chạy lại ngày 17/10/2026 trong môi trường sandbox). Các test này dùng model giả và DB tạm, nên chứng minh logic loop/tool/guard, **không** chứng minh hành vi của LLM thật.
- **Đường chạy thật qua MCP:** lần chạy staging 12 câu (`execution_mode=real`) đi qua `run_detailed()` tức qua MCP stdio. `[[TODO: ghi provider và model đã dùng trong lần chạy staging 20261017_201308 — log không lưu trường này; C/B xác nhận từ máy chạy]]`.
- **Chưa kiểm:** chạy dài hạn nhiều phiên song song, và server MCP với nhiều client đồng thời ghi cùng một DB (SQLite một file, chưa thử tranh chấp ghi).


---

## §9 — Phụ lục · không tính trang · B

### 9.1 Prompt gốc (nguyên văn)

Trạng thái từng file: `system.txt` và `decision.txt` **đang chạy** trong `agent/loop.py`. `react_step.txt` và `judge.txt` là prompt tham chiếu, **không có code nào nạp** (xem `prompts/README.md`).

**`prompts/system.txt`**

```text
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
```

**`prompts/decision.txt`**

```text
BẮT BUỘC: Bạn PHẢI gọi tool `submit_decision` ĐÚNG MỘT LẦN TRƯỚC KHI sinh câu trả lời văn bản cuối cùng cho TẤT CẢ mọi câu hỏi!
- Trình tự thực hiện bắt buộc:
  Bước 1: Tra cứu (search_policy) hoặc thao tác ghi/xác minh (nếu có yêu cầu).
  Bước 2: BẮT BUỘC gọi tool `submit_decision` để khai báo quyết định:
     * Trả lời được: `submit_decision(outcome="answer")` (nếu biết chính xác điều luật đã tìm thấy dạng DOCnnnn_ARTnn như DOC0004_ART05, DOC0007_ART10 thì có thể kèm `policy_rule_id`; nếu không thì KHÔNG ĐƯA KEY `policy_rule_id` VÀO ARGUMENTS).
     * Từ chối ngoài phạm vi DOC0009: `submit_decision(outcome="refusal", refusal_type="i")`.
     * Từ chối thiếu dữ liệu tình huống: `submit_decision(outcome="refusal", refusal_type="ii")`.
  Bước 3: Sau khi nhận được thông báo "Decision recorded." từ tool, bạn mới viết toàn bộ câu trả lời giải thích chi tiết bằng tiếng Việt.
- Tuyệt đối KHÔNG trả lời văn bản khi chưa gọi `submit_decision`. Lượt chạy không gọi `submit_decision` sẽ bị coi là không hợp lệ (unscorable)!
```

**`prompts/react_step.txt`** (ReAct dạng văn bản, dự phòng; định dạng khớp `parse.py`)

```text
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
```

**`prompts/judge.txt`** (LLM-judge tuỳ chọn; `eval/` hiện KHÔNG dùng LLM-judge, chấm bằng so khớp chuỗi xác định)

```text
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

Hai file cuối do AI soạn nội dung và B rà lại; đã khai trong `ai-usage.md`. Vì chưa được chạy, **không** dùng chúng làm bằng chứng cho kết quả đánh giá trong §6.

### 9.2 Trace dài — q05 (ca freeze), JSONL nguyên văn từ `logs/staging_20261017_201308/step_events.jsonl`

Ba bản ghi của q05 (`account_id`, số tiền và `reason` đã bị che bởi `eval/redaction.py`; `timestamp` cùng mốc vì log ghi sau khi chạy xong):

```jsonl
{"record_type": "step_event", "timestamp": "2026-10-17T13:14:33.843226+00:00", "run_id": "5c16b57a7fa94c4db8564dde64d2b15f", "question_id": "q05", "scenario": "freeze", "execution_mode": "real", "step": 1, "tool": "search_policy", "args": {"query": "tỷ lệ vượt hạn mức ngày công thức DOC0007 hạn mức giao dịch eKYC tầng 2", "k": 5}, "result": "[{\"doc_id\":\"DOC0007\",\"title\":\"Hạn mức giao dịch theo tầng eKYC\",\"version\":\"2026.1\",\"chunk_index\":7,\"text\":\"Hạn mức giao dịch theo tầng eKYC > Chương IV — Tính hạn mức và xử lý vượt hạn mức > Điều 10. Tỷ lệ vượt hạn mức\\nTỷ lệ vượt hạn mức được tính bằng công thức: (tổng giá trị giao dịch trong ngày trừ hạn\\nmức mỗi ngày) chia cho hạn mức mỗi ngày, nhân 100 phần trăm. Ví dụ: tài khoản tầng 2 có\\ntổng giao dịch trong ngày là [REDACTED] VND, hạn mức mỗi ngày là [REDACTED] VND, tỷ lệ\\nvượt hạn mức là 44 phần trăm. Tỷ lệ này là căn cứ để phân loại mức độ rủi ro.\",\"score\":0.8713,\"tier\":null},{\"doc_id\":\"DOC0003\",\"title\":\"Hạn mức giao dịch theo tầng eKYC (bản 2025.2, đã bị thay thế)\",\"version\":\"2025.2\",\"chunk_index\":3,\"text\":\"Hạn mức giao dịch theo tầng eKYC > Chương II — Bảng hạn mức > Điều 6. Tỷ lệ vượt hạn mức\\nTỷ lệ vượt hạn mức tính bằng (tổng giá trị trong ngày trừ hạn mức mỗi ngày) chia hạn mức\\nmỗi ngày, nhân 100 phần trăm.\\n\\nHạn mức giao dịch theo tầng eKYC > Chương III — Giao dịch quốc tế > Điều 7. Hạn mức giao dịch thẻ quốc tế\\nGiao dịch thẻ quốc tế chịu hạn mức riêng [REDACTED] VND mỗi ngày cho mọi tầng eKYC,\\nkhông cộng dồn vào hạn mức chuyển khoản trong nước.\\n\\nHạn mức giao dịch theo tầng eKYC > Chương III — Giao dịch quốc tế > Điều 8. Quy đổi ngoại tệ\\nGiá trị đối chiếu hạn mức là giá trị quy đổi sang VND theo tỷ giá bán ra tại thời điểm\\ngiao dịch được ghi nhận.\",\"score\":0.7282,\"tier\":null},{\"doc_id\":\"DOC0007\",\"title\":\"Hạn mức giao dịch theo tầng eKYC\",\"version\":\"2026.1\",\"chunk_index\":2,\"text\":\"Hạn mức giao dịch theo tầng eKYC > Chương II — Bảng hạn mức > Điều 4. Hạn mức theo tầng eKYC\\nBảng dưới đây là hạn mức giao dịch áp dụng cho giao dịch chuyển khoản trong nước theo\\ntầng định danh hiện tại của chủ tài khoản. Hạn mức mỗi ngày là tổng giá trị luỹ kế\\ntrong một ngày dương lịch; hạn mức mỗi giao dịch là giá trị tối đa của một giao dịch\\nđơn lẻ. Khi một giao dịch vượt hạn mức mỗi giao dịch, hệ thống từ chối ngay cả khi tổng\\nluỹ kế trong ngày vẫn còn dưới hạn mức mỗi ngày.\\n| Tầng eKYC | Hạn mức mỗi ngày | Hạn mức mỗi giao dịch | Yêu cầu định danh bổ sung |\\n|---|---|---|---|\\n| Tầng 1 | [REDACTED] VND | [REDACTED] VND | Số điện thoại + giấy tờ tuỳ thân |\\n| Tầng 2 | [REDACTED] VND | [REDACTED] VND | Thêm xác thực khuôn mặt |\\n| Tầng 3 | 2.[REDACTED] VND | [REDACTED] VND | Thêm hồ sơ thu nhập + phê duyệt |\",\"score\":0.6109,\"tier\":null},{\"doc_id\":\"DOC0007\",\"title\":\"Hạn mức giao dịch theo tầng eKYC\",\"version\":\"2026.1\",\"chunk_index\":8,\"text\":\"Hạn mức giao dịch theo tầng eKYC > Chương IV — Tính hạn mức và xử lý vượt hạn mức > Điều 11. Xử lý khi vượt hạn mức\\nKhi tổng giá trị giao dịch trong ngày vượt hạn mức của tầng eKYC hiện tại, hệ thống phải\\ntừ chối giao dịch vượt và ghi nhận cảnh báo. Tài khoản không bị khoá tự động; việc khoá\\ntài khoản do kiểm soát viên quyết định theo quy trình tại DOC0008. Cảnh báo vượt hạn mức\\nphải được lưu tối thiểu 90 ngày để phục vụ tra soát.\",\"score\":0.5883,\"tier\":null},{\"doc_id\":\"DOC0003\",\"title\":\"Hạn mức giao dịch theo tầng eKYC (bản 2025.2, đã bị thay thế)\",\"version\":\"2025.2\",\"chunk_index\":2,\"text\":\"Hạn mức giao dịch theo tầng eKYC > Chương II — Bảng hạn mức > Điều 4. Hạn mức theo tầng eKYC\\nBảng dưới đây là hạn mức giao dịch áp dụng cho giao dịch chuyển khoản trong nước theo\\ntầng định danh, có hiệu lực trong giai đoạn 01/08/2025 đến 14/01/2026.\\n| Tầng eKYC | Hạn mức mỗi ngày | Hạn mức mỗi giao dịch |\\n|---|---|---|\\n| Tầng 1 | [REDACTED] VND | [REDACTED] VND |\\n| Tầng 2 | [REDACTED] VND | [REDACTED] VND |\\n| Tầng 3 | 1.[REDACTED] VND | [REDACTED] VND |\\n\\nHạn mức giao dịch theo tầng eKYC > Chương II — Bảng hạn mức > Điều 5. Cách xác định tầng áp dụng\\nTầng áp dụng là tầng định danh tại thời điểm giao dịch được ghi nhận. Việc nâng tầng\\nkhông áp dụng hồi tố.\",\"score\":0.5705,\"tier\":null}]", "usage": {"calls": 5, "prompt_tokens": 23557, "completion_tokens": 982, "max_prompt": 5430}, "status": "completed", "scenario_evidence_status": "context_only", "business_outcome_verified": false}
{"record_type": "step_event", "timestamp": "2026-10-17T13:14:33.843355+00:00", "run_id": "5c16b57a7fa94c4db8564dde64d2b15f", "question_id": "q05", "scenario": "freeze", "execution_mode": "real", "step": 2, "tool": "freeze_account_temporarily", "args": {"account_id": "[REDACTED]", "reason": "[REDACTED]"}, "result": "{\"ok\":true,\"message\":\"Account [REDACTED] successfully frozen temporarily. Reason=[REDACTED] hạn mức ngày tầng eKYC 2: tổng giao dịch trong ngày [REDACTED] VND so với hạn mức [REDACTED] VND, tỷ lệ vượt hạn mức 44% theo DOC0007 Điều 10; tạm khóa theo quy trình kiểm soát viên tại DOC0008 (DOC0007 Điều 11).\",\"tx_id\":\"[REDACTED]\"}", "usage": {"calls": 5, "prompt_tokens": 23557, "completion_tokens": 982, "max_prompt": 5430}, "status": "completed", "scenario_evidence_status": "tool_call_completed_outcome_unverified", "business_outcome_verified": false}
{"record_type": "step_event", "timestamp": "2026-10-17T13:14:33.843460+00:00", "run_id": "5c16b57a7fa94c4db8564dde64d2b15f", "question_id": "q05", "scenario": "freeze", "execution_mode": "real", "step": 3, "tool": "get_account_risk_status", "args": {"account_id": "[REDACTED]"}, "result": "{\"account_id\":\"[REDACTED]\",\"frozen\":true,\"freeze_reason\":\"Vượt hạn mức ngày tầng eKYC 2: tổng giao dịch trong ngày [REDACTED] VND so với hạn mức [REDACTED] VND, tỷ lệ vượt hạn mức 44% theo DOC0007 Điều 10; tạm khóa theo quy trình kiểm soát viên tại DOC0008 (DOC0007 Điều 11).\",\"frozen_at\":\"2026-10-17T13:14:25.705579+00:00\",\"flagged_tx_ids\":\"[REDACTED]\",\"checked_at\":\"2026-10-17T13:14:27.590021+00:00\"}", "usage": {"calls": 5, "prompt_tokens": 23557, "completion_tokens": 982, "max_prompt": 5430}, "status": "completed", "scenario_evidence_status": "context_only", "business_outcome_verified": false}
```

Bản đầy đủ cả 12 câu: `logs/staging_20261017_201308/` (`step_events.jsonl`, `decision_events.jsonl`, `evaluation.jsonl`, `semantic_gate_result.json`).

### 9.3 `ai-usage.md` (nguyên văn, đã cập nhật)

# ai-usage.md

> Khai báo bắt buộc (§4). Dùng AI **được phép** — chỉ mất điểm khi không giải thích được code
> hoặc không khai báo. File này ghi đúng những gì đã xảy ra, đối chiếu được với `git log`.

## 1. Công cụ đã dùng

| Công cụ | Phiên bản / model | Dùng cho phần nào |
|---|---|---|
| Claude Code | Claude Sonnet 4.5 | Scaffold repo, viết corpus, chunking, RAG retrieval, rà yêu cầu học phần |
| Claude Code | Claude Sonnet 4.5 | Viết khung `eval/`, testset, MCP client thứ hai, README/Makefile |
| Claude Code / AntiGravity | — | Cài đặt và hoàn thiện toàn bộ C4 evaluation framework, logging schema, semantic gate, bộ unit test, staging runner và báo cáo nghiệm thu |
| GitHub Copilot | — | Gợi ý autocomplete trong `impl.py`, `server.py` (B) |
| ChatGPT | — | Hỏi ý tưởng thiết kế `tier` pre-filter, debug lỗi asyncio trên Windows |

Không dùng AI để sinh log chạy hay số liệu eval. Mọi số trong `eval/reports/` đều lấy từ lần
chạy thật, tái lập bằng `make eval`.

## 2. Prompt chính

<!-- Prompt thật, dán nguyên văn, không tóm tắt -->

### Person A (Corpus & RAG)

**Corpus + chunking (A):**
> "Đọc `DE_TAI_TRFC_Agent.md` §3 rồi viết 9 tài liệu corpus DOC0001–DOC0009 theo đúng metadata
> frontmatter và phân bố đã chốt. DOC0007 phải có bảng hạn mức atomic; DOC0003 phải là bản cũ
> đã bị thay thế; mỗi doc phải có một Điều nói rõ trường hợp không đủ dữ liệu."

**Chunking (A):**
> "Viết chunker cắt theo Chương→Điều→Khoản, gắn đường dẫn heading vào mỗi chunk, và giữ bảng
> markdown nguyên tử cùng dòng giới thiệu ngay trên bảng. `chunk_size`/`overlap` đọc từ
> `config.toml`, không hard-code."

**Retrieval (A):**
> "Viết `search_policy` dense + hybrid theo đúng docstring khung: fuse `w_bm25 * BM25_norm +
> w_vector * cosine` với trọng số đọc từ `config.toml`; `tier` là PRE-FILTER trước khi rank chứ
> không lọc sau; không tìm thấy trả `[]` không trả `None`. Port cách làm từ `W4/vector_store.py`
> và `W4/ex2_1_hybrid_search.py` — file W4 nằm ngoài repo và là stub hỏng nên chỉ tham khảo."

**Thiết kế tier pre-filter (A):**
> "Bảng hạn mức phải nguyên khối, mà `tier` là metadata mức dòng. Thiết kế cách pre-filter theo
> tầng mà không phá rule atomic và không làm hỏng `test_bang_dai_hon_chunk_size_van_khong_bi_cat`."

### Person B (Agent loop & MCP)

**Agent loop (B):**
> "Viết ReAct loop tự viết, `MAX_STEPS` đọc từ `config.toml`, tool lỗi trả chuỗi `'Error: ...'`
> không raise, parse action chịu được JSON hỏng hoặc thiếu ngoặc. Prompt để trong `prompts/*.txt`,
> không nhúng trong code."

**MCP server (B):**
> "Viết MCP server stdio, mọi log đi stderr để stdout sạch, ≥1 tool ghi. Client phải discover
> tool động qua `list_tools()`, không hard-code danh sách."

### Person C (Evaluation, Logging, Semantic Gate & C4 Staging)

> *Ghi chú:* Đây là bản tóm tắt 4 nhóm yêu cầu chính đã sử dụng trong các phiên làm việc với AI qua các giai đoạn (tổng hợp theo xác nhận/hồi tưởng của người thực hiện), không phải trích dẫn nguyên văn toàn bộ lịch sử hội thoại dài.

- **Khung đánh giá chất lượng RAG, Schema Validator & Client MCP thứ hai (Giai đoạn nền tảng):** Tóm tắt yêu cầu: Xây dựng runner `eval/run_eval.py`, các hàm tính metric theo cơ chế so khớp chuỗi xác định trong `eval/metrics.py` (faithfulness, context precision, refusal type i/ii), validator schema `eval/log_validation.py`, và cài đặt client MCP độc lập `src/trfc/mcp_server/client2.py` phục vụ yêu cầu host thứ hai theo hợp đồng interop.
- **Adapter & Logging phòng thủ:** Tóm tắt yêu cầu: Nâng cấp `eval/agent_adapter.py` và `eval/step_events.py`, bổ sung biến môi trường `CASE_INTERVAL_SECONDS` chống nghẽn HTTP 429 và ép kiểu phòng thủ cho trường `arguments` khi tool gặp lỗi để không làm đứt gãy schema logging.
- **Semantic Gate & Offline Unit Tests:** Tóm tắt yêu cầu: Xây dựng `eval/semantic_gate.py` cùng 24 offline unit tests trong `tests/test_semantic_gate.py` để kiểm định độc lập 12 test case, xác minh chặt chẽ cơ chế read-after-write của Freeze (`checked_at > frozen_at`) và Flag (`tx_id` nằm trong danh sách), cùng phân loại từ chối loại I/II.
- **Kịch bản Staging & Báo cáo Nghiệm thu C4:** Tóm tắt yêu cầu: Bổ sung nhãn `scenario` cho `tests/testset.jsonl`, viết runner `scripts/run_c4_staging.ps1` đảm bảo kiểm soát hash SHA256 DB production và cô lập DB ngoài repo, đồng thời cập nhật `reports/verification/c4_final_report.md` theo bằng chứng thực tế từ run staging đạt chuẩn.

## 3. Đoạn code do AI sinh

### Person A

| File | Ghi chú |
|---|---|
| `src/trfc/rag/chunking.py` | Tôi viết dựa trên khung đề xuất của AI (gộp dòng giới thiệu vào khối bảng) |
| `src/trfc/rag/embed.py`, `store.py`, `search.py` | Tôi viết dựa trên khung đề xuất của AI; **tôi chốt thiết kế pre-filter theo tầng bằng "view 1 tầng"** (không doc nào có `tier:` trong frontmatter) |
| `tests/test_chunking.py` | AI viết khung; A thêm ca bảng 39 dòng vượt `chunk_size` |
| `data/docs/DOC0001–0009.md` | AI soạn văn bản theo đề cương; **số liệu và quan hệ giữa các doc do A chốt** |
| `Makefile`, `pyproject.toml`, `.env.example`, `config.toml` | AI viết |

### Person B

| File | Ai viết | Ghi chú |
|---|---|---|
| `src/trfc/tools/schemas.py` | AI khung dataclass | B chốt field và contract §7 |
| `src/trfc/tools/impl.py`, `state.py` | B viết, Copilot gợi ý | B viết phần SQLite side effect |
| `src/trfc/agent/loop.py`, `parse.py`, `llm.py` | B viết | B đọc lại toàn bộ, sửa luồng verify |
| `src/trfc/mcp_server/server.py` | B viết | MCP server stdio, stdout sạch |
| `prompts/react_step.txt`, `prompts/judge.txt` | **AI soạn nội dung** (Claude), B rà lại | Trước đó rỗng. Là prompt tham chiếu: `react_step.txt` cho chế độ ReAct dạng văn bản (khớp `parse.py`), `judge.txt` cho LLM-judge tuỳ chọn. **Không được code nào nạp**; loop dùng `system.txt` + native tool-calling, eval dùng so khớp chuỗi |

### Person C (Phạm vi công việc C4)

| File | Trạng thái Git | Mức độ AI can thiệp | Vai trò chính |
|---|---|---|---|
| `eval/agent_adapter.py` | Đã push (`origin/main`) | AI hỗ trợ chỉnh sửa | Thêm sleep giãn cách `CASE_INTERVAL_SECONDS` điều tiết tần suất gọi LLM provider |
| `eval/step_events.py` | Đã push (`origin/main`) | AI hỗ trợ chỉnh sửa | Defensive coercion cho arguments khi tool status là error, đảm bảo JSONL hợp lệ |
| `eval/semantic_gate.py` | Đã push (`origin/main`) | AI tạo mới phần lớn | Cổng thẩm định ngữ nghĩa độc lập cho 12 case, kiểm tra write/verify và phân loại từ chối |
| `tests/testset.jsonl` | Đã push (`origin/main`) | AI hỗ trợ chỉnh sửa | Bổ sung metadata `scenario` (`freeze`, `flag`, `refusal`) cho các ca kiểm thử |
| `tests/test_semantic_gate.py` | Đã push (`origin/main`) | AI tạo mới | Bộ 24 unit tests offline kiểm định toàn bộ các quy tắc và nhánh rẽ của Semantic Gate |
| `scripts/run_c4_staging.ps1` | Đã push (`origin/main`) | AI tạo mới | Runner PowerShell tự động hóa staging C4, cô lập DB và đối soát SHA256 DB production |
| `eval/run_eval.py` | Đã push (`origin/main`) | AI viết phần lớn | Runner CLI chạy evaluation, quản lý batching, gọi adapter và xuất logs JSONL |
| `eval/metrics.py` | Đã push (`origin/main`) | AI viết | Hàm tính toán độ chính xác từ chối (loại i/ii), faithfulness và trích dẫn theo so khớp chuỗi |
| `eval/report.py` | Đã push (`origin/main`) | AI viết | Xuất kết quả đánh giá ra bảng CSV (`evaluation.csv`) và vẽ biểu đồ cột SVG (`faithfulness.svg`, `refusal_correctness.svg`) |
| `eval/log_validation.py` | Đã push (`origin/main`) | AI viết | Bộ thẩm định định dạng JSONL theo schema (case, event, decision) |
| `eval/decision_events.py` | Đã push (`origin/main`) | AI viết | Data class và hàm emitter ghi nhận sự kiện quyết định `decision_events.jsonl` |
| `eval/redaction.py` | Đã push (`origin/main`) | AI viết | Tiện ích che giấu dữ liệu nhạy cảm (PII/account/tx) phục vụ logging an toàn |
| `eval/provenance.py` | Đã push (`origin/main`) | AI viết | Theo dõi nguồn gốc trích dẫn tài liệu phục vụ đối soát faithfulness |
| `eval/database_isolation.py` | Đã push (`origin/main`) | AI viết | Tiện ích bảo vệ và kiểm soát cô lập database cho evaluation runner |
| `src/trfc/mcp_server/client2.py` | Đã push (`origin/main`) | AI viết | Client MCP độc lập thứ hai thực thi tool call, chứng minh tính interop (Task C6) |
| `tests/test_eval.py` | Đã push (`origin/main`) | AI viết | Bộ unit test kiểm định hoạt động của `run_eval.py` và luồng đánh giá |
| `tests/test_log_validation.py` | Đã push (`origin/main`) | AI viết | Unit test kiểm tra các ràng buộc schema của case và event JSONL |
| `tests/test_client2.py` | Đã push (`origin/main`) | AI viết | Unit test cho client MCP thứ hai tương tác với MCP server |
| `tests/test_agent_adapter.py` | Đã push (`origin/main`) | AI viết | Unit test kiểm tra adapter và khả năng lan truyền metadata quyết định |
| `tests/test_decision_events.py` | Đã push (`origin/main`) | AI viết | Unit test kiểm định schema và serialization của decision events |
| `tests/test_step_events.py` | Đã push (`origin/main`) | AI viết | Unit test cho luồng ghi nhận step events của tool trace |
| `tests/test_offline_policy.py` | Đã push (`origin/main`) | AI viết | Unit test kiểm tra logic đánh giá chính sách và phân loại từ chối offline |
| `tests/test_db_isolation.py` | Đã push (`origin/main`) | AI viết | Unit test kiểm tra cơ chế cô lập database runtime |
| `tests/test_eval_db_isolation.py` | Đã push (`origin/main`) | AI viết | Unit test bảo đảm quá trình evaluation không ghi đè DB thật |
| `tests/test_verify_mcp_write_isolation.py` | Đã push (`origin/main`) | AI viết | Unit test kiểm tra ranh giới an toàn của các thao tác ghi MCP |
| `tests/test_asyncio_startup_diagnostic.py` | Đã push (`origin/main`) | AI viết | Unit test chẩn đoán tương thích vòng lặp asyncio trên nền tảng Windows |
| `tests/test_eval_redaction.py` | Đã push (`origin/main`) | AI viết | Unit test cho module che giấu dữ liệu nhạy cảm `eval/redaction.py` |
| `tests/test_native_tool_calling.py` | Đã push (`origin/main`) | AI viết | Unit test kiểm định tương thích gọi tool native cho evaluator |
| `scripts/verify_mcp_write_isolation.py` | Đã push (`origin/main`) | AI viết | Kịch bản kiểm chứng độc lập tính cô lập của MCP write tool |
| `scripts/verify_mcp_isolation.py` | Đã push (`origin/main`) | AI viết | Kịch bản kiểm chứng mức độ cô lập của MCP server runtime |
| `scripts/diagnose_windows_asyncio.py` | Đã push (`origin/main`) | AI viết | Kịch bản chẩn đoán tương thích vòng lặp asyncio trên nền tảng Windows |
| `eval/README.md` | Đã push (`origin/main`) | AI soạn thảo | Tài liệu đặc tả kiến trúc evaluation framework, các chế độ chạy và CLI schema |
| `eval/PERSON_B_C4_METADATA_CONTRACT.md` | Đã push (`origin/main`) | AI hỗ trợ soạn | Đặc tả hợp đồng giao diện metadata runtime giữa Person B và Person C |
| `reports/verification/c4_runtime_integration_contract.md` | Đã push (`origin/main`) | AI hỗ trợ soạn | Hợp đồng tích hợp runtime agent với hệ thống kiểm thử C4 |
| `reports/verification/c4_b2_runtime_contract.md` | Đã push (`origin/main`) | AI hỗ trợ soạn | Tài liệu đối chiếu hợp đồng metadata runtime B2 |
| `reports/verification/c4_policy_source_inventory.md` | Đã push (`origin/main`) | AI hỗ trợ soạn | Bảng kiểm kê nguồn chính sách và căn cứ pháp lý phục vụ testset C4 |

## 4. Phần tự viết (không dùng AI)

- **A** — cấu trúc corpus (doc nào chứa gì, doc nào mâu thuẫn doc nào), chọn `chunk_size=400`,
  ràng buộc bảng atomic, thiết kế "view 1 tầng" cho pre-filter `tier`, toàn bộ
  `src/trfc/rag/chunking.py`, `embed.py`, `store.py`, `search.py` (viết theo khung do AI gợi ý).
- **B** — tool contract, side effect SQLite, luồng verify, toàn bộ `agent/loop.py` và
  `mcp_server/server.py`, prompt `system.txt`.
- **C** — thiết kế tiêu chí đánh giá và ground truth cho 12 câu hỏi testset C4 (quy định thẩm
  quyền, hạn mức, căn cứ từ chối DOC0004/DOC0006/DOC0007/DOC0009); thiết kế quy tắc cổng ngữ
  nghĩa phân định rạch ròi giữa write và verify (`checked_at > frozen_at`, tx nằm trong
  `flagged_tx_ids`); thiết lập nguyên tắc an toàn cô lập staging DB ra ngoài repo để bảo vệ
  production DB; trực tiếp chạy staging thực tế và nghiệm thu kết quả; cách chấm refusal loại
  (i)/(ii), logging `USAGE`, quy trình git.

## 5. Trạng thái đối chiếu

`git log` thể hiện đủ 4 tài khoản commit (CapyCoder, Do Ngo, Do Coding, Penguin-cell34) — 2 bạn
Do Ngo/Do Coding dùng chung phần B. Mỗi người phải giải thích được mọi dòng trong file mình
đứng tên; dòng nào AI viết thì nêu được AI viết gì và mình đã sửa gì.

⚠️ Mọi dòng AI sinh đều phải giải thích được khi vấn đáp — không giải thích được thì B = 0.

### 9.4 `.env.example` (không chứa khoá thật)

```bash
# ==============================================================================
# TRFC Fraud & AML Agent - Shared Environment Configuration Template
# ==============================================================================
# Copy this file to .env and configure credentials for your local machine.
# Never commit .env or paste real API keys into version control.

# ------------------------------------------------------------------------------
# 1. LLM Provider Configuration
# ------------------------------------------------------------------------------
# CODEBASE PROVIDER PRECEDENCE:
# 1. If LLM_PROVIDER is explicitly set ("groq", "deepseek", "custom", "dashscope"):
#    Code strictly uses that provider and raises an error if required credentials
#    or endpoints are missing. No silent fallback occurs.
# 2. If LLM_PROVIDER is unset:
#    - Custom endpoint (LLM_BASE_URL) > DashScope (DASHSCOPE_API_KEY) >
#      DeepSeek (DEEPSEEK_API_KEY) > Groq (GROQ_API_KEY) > fallback LLM_API_KEY.
# 3. If no provider is configured, runtime raises a clear descriptive error.

# --- Option A: Groq (Recommended default for Person A / Person B) ---
# LLM_PROVIDER=groq
# GROQ_API_KEY=replace_with_groq_api_key
# LLM_MODEL=qwen/qwen3.8-27b

# --- Option B: DeepSeek (Official API for Person C) ---
# LLM_PROVIDER=deepseek
# LLM_API_KEY=replace_with_deepseek_api_key
# DEEPSEEK_API_KEY=replace_with_deepseek_api_key
# LLM_BASE_URL=https://api.deepseek.com/v1
# LLM_MODEL=deepseek-chat

# --- Option C: Custom OpenAI-Compatible Gateway (Vilao / DashScope / vLLM) ---
# LLM_PROVIDER=custom
# LLM_BASE_URL=https://api.vilao.ai/v1
# LLM_API_KEY=replace_with_gateway_api_key
# LLM_MODEL=qwen3.8-max-0902-req

# ------------------------------------------------------------------------------
# 2. LLM Call Tuning (Optional)
# ------------------------------------------------------------------------------
# LLM_TIMEOUT_SECONDS=30.0
# LLM_MAX_RETRIES=3
# LLM_MAX_TOKENS=650

# ------------------------------------------------------------------------------
# 3. Optional Embedding Keys
# ------------------------------------------------------------------------------
# Uncomment and set at most one; OpenAI takes precedence.
# Without either key, embeddings use deterministic offline hashing.
# OPENAI_API_KEY=replace_with_openai_api_key
# JINA_API_KEY=replace_with_jina_api_key

# ------------------------------------------------------------------------------
# 4. Database Isolation for Controlled Testing
# ------------------------------------------------------------------------------
# Use an absolute, disposable path; isolated writes are blocked if this is
# unset or points to the repository's default data/state.db.
# TRFC_STATE_DB=replace_with_disposable_sqlite_path
# TRFC_REQUIRE_ISOLATED_DB=1
```
