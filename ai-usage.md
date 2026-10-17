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

Không dùng AI để sinh log chạy hay số liệu eval. Mọi số trong `eval/reports/` đều lấy từ lần chạy thật
với agent + LLM sống. `make eval` **tái lập** các số đó mà không cần key: nó chấm lại
`logs/staging_20261017_201308/evaluation.jsonl`, so từng byte với `eval/reports/` (lệch là fail) rồi chạy
lại `eval.semantic_gate`. Muốn sinh log mới thì dùng `make eval-live` (cần LLM key + network + một
`TRFC_STATE_DB` cách ly). Log của lần chạy được trích trong report nằm ở `logs/staging_20261017_201308/`.

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

### Person C (Phạm vi công việc C4)

| File | Trạng thái Git | Mức độ AI can thiệp | Vai trò chính |
|---|---|---|---|
| `eval/agent_adapter.py` | Đã push (`origin/main`) | C viết, AI chỉnh sửa | Thêm sleep giãn cách `CASE_INTERVAL_SECONDS` điều tiết tần suất gọi LLM provider |
| `eval/step_events.py` | Đã push (`origin/main`) | C viết, AI chỉnh sửa | Defensive coercion cho arguments khi tool status là error, đảm bảo JSONL hợp lệ |
| `eval/semantic_gate.py` | Đã push (`origin/main`) | AI tạo mới phần lớn | Cổng thẩm định ngữ nghĩa độc lập cho 12 case, kiểm tra write/verify và phân loại từ chối |
| `tests/testset.jsonl` | Đã push (`origin/main`) | C viết | Bổ sung metadata `scenario` (`freeze`, `flag`, `refusal`) cho các ca kiểm thử |
| `tests/test_semantic_gate.py` | Đã push (`origin/main`) | AI tạo mới | Bộ 24 unit tests offline kiểm định toàn bộ các quy tắc và nhánh rẽ của Semantic Gate |
| `scripts/run_c4_staging.ps1` | Đã push (`origin/main`) | AI tạo mới | Runner PowerShell tự động hóa staging C4, cô lập DB và đối soát SHA256 DB production |
| `eval/run_eval.py` | Đã push (`origin/main`) | C viết | Runner CLI chạy evaluation, quản lý batching, gọi adapter và xuất logs JSONL |
| `eval/metrics.py` | Đã push (`origin/main`) | C viết | Hàm tính toán độ chính xác từ chối (loại i/ii), faithfulness và trích dẫn theo so khớp chuỗi |
| `eval/report.py` | Đã push (`origin/main`) | C viết | Xuất kết quả đánh giá ra bảng CSV (`evaluation.csv`) và vẽ biểu đồ cột SVG (`faithfulness.svg`, `refusal_correctness.svg`) |
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
| `eval/README.md` | Đã push (`origin/main`) | C viết | Tài liệu đặc tả kiến trúc evaluation framework, các chế độ chạy và CLI schema |
| `eval/PERSON_B_C4_METADATA_CONTRACT.md` | Đã push (`origin/main`) | C viết AI hỗ trợ soạn | Đặc tả hợp đồng giao diện metadata runtime giữa Person B và Person C |
| `reports/verification/c4_runtime_integration_contract.md` | Đã push (`origin/main`) | C viết, AI hỗ trợ soạn | Hợp đồng tích hợp runtime agent với hệ thống kiểm thử C4 |
| `reports/verification/c4_b2_runtime_contract.md` | Đã push (`origin/main`) | C viết, AI hỗ trợ soạn | Tài liệu đối chiếu hợp đồng metadata runtime B2 |
| `reports/verification/c4_policy_source_inventory.md` | Đã push (`origin/main`) | C viết, AI hỗ trợ soạn | Bảng kiểm kê nguồn chính sách và căn cứ pháp lý phục vụ testset C4 |

## 4. Phần tự viết (không dùng AI)

- **A** — cấu trúc corpus (doc nào chứa gì, doc nào mâu thuẫn doc nào), chọn `chunk_size=400`,
  ràng buộc bảng atomic, thiết kế "view 1 tầng" cho pre-filter `tier`, toàn bộ
  `src/trfc/rag/chunking.py`, `embed.py`, `store.py`, `search.py` (viết theo khung do AI gợi ý).
- **B** — tool contract, side effect SQLite, luồng verify, toàn bộ `agent/loop.py` và
  `mcp_server/server.py`, prompt `system.txt` / `react_step.txt` / `judge.txt`.
- **C** — thiết kế tiêu chí đánh giá và ground truth cho 12 câu hỏi testset C4 (quy định thẩm
  quyền, hạn mức, căn cứ từ chối DOC0004/DOC0006/DOC0007/DOC0009); thiết kế quy tắc cổng ngữ
  nghĩa phân định rạch ròi giữa write và verify (`checked_at > frozen_at`, tx nằm trong
  `flagged_tx_ids`); thiết lập nguyên tắc an toàn cô lập staging DB ra ngoài repo để bảo vệ
  production DB; trực tiếp chạy staging thực tế và nghiệm thu kết quả; cách chấm refusal loại
  (i)/(ii), logging `USAGE`, quy trình git; quyết định **không** để LLM-judge tính điểm thay
  cho metric tất định, và lý do judge bị cấm chạy trên văn bản đã redact.

## 5. Trạng thái đối chiếu

`git log` thể hiện đủ 4 tài khoản commit (CapyCoder, Do Ngo, Do Coding, Penguin-cell34) — 2 bạn
Do Ngo/Do Coding dùng chung phần B. Mỗi người phải giải thích được mọi dòng trong file mình
đứng tên; dòng nào AI viết thì nêu được AI viết gì và mình đã sửa gì.

⚠️ Mọi dòng AI sinh đều phải giải thích được khi vấn đáp — không giải thích được thì B = 0.
