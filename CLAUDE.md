# Final Project AIPR — Tổng hợp yêu cầu (W1–W7)

> Nguồn: `01-De-tai-upload-for-student.pdf`, `02-Yeu-cau-Thuc-hien.pdf` (Project/) và mục *Final Project Specification* trong `Ref/AIPR_Syllabus_for_student.md`.
> File này gộp key của cả 3 nguồn. Khi mâu thuẫn, ghi chú rõ ở [§10](#10-điểm-mâu-thuẫn-giữa-các-tài-liệu).

> **Đề tài nhóm (đã chọn): TRFC Agent — Trợ lý Kiểm soát Rủi ro & Gian lận Giao dịch.** Chi tiết ở [DE_TAI_TRFC_Agent.md](DE_TAI_TRFC_Agent.md).

---

## 1. Tổng quan

| Hạng mục | Nội dung |
|---|---|
| **Trọng tâm bắt buộc** | RAG (w3–w4) + Agent loop & tool (w6) + MCP (w7), **có đo lường** (w5) |
| **Nhóm** | 3 SV |
| **Thời gian** | 10 ngày |
| **Nộp** | `report.docx` (8–9 trang) + repo code kèm thư mục `.git` |
| **Bảo vệ** | 20 phút/nhóm: vấn đáp riêng từng người + **sửa code trực tiếp trên code đã nộp** |
| **Trọng số** | Nhóm 60 + Cá nhân 40 + cộng thêm tối đa **+6** |

---

## 2. Ba tầng bắt buộc — đề tài đạt yêu cầu phải có đủ cả 3

| Tầng | Nghĩa là | Nếu thiếu thì |
|---|---|---|
| **(a) Tra cứu** | Câu trả lời nằm ở đâu trong tài liệu? | Bị đánh giá chất lượng RAG |
| **(b) Biến đổi** | Từ các mảnh tài liệu đó, suy ra / tính / so sánh được gì? | Không có gì để đo → eval vô nghĩa |
| **(c) Hành động** | Sau khi hiểu, hệ thống làm gì và làm sao biết là đã làm? | Chỉ là pipeline tra cứu, **không phải agent** |

### (a) Tra cứu — tầng "có bằng chứng"

Mọi câu trả lời phải truy được về nguồn, có `doc_id` cụ thể — không phải "LLM nhớ mang máng". Hai kỹ năng tách biệt:

- **Grounding**: trích dẫn đúng mảnh tài liệu, **đúng phiên bản (version)**.
- **Calibration**: biết khi nào **không** trả lời. Đây là chỗ dễ mất điểm nhất — hệ thống luôn trả lời trông rất "giỏi" nhưng thực chất đang bịa.

> **Câu tự kiểm:** Đưa 1 câu mà đáp án không có trong corpus thì hệ thống có từ chối không, hay vẫn bịa ra một câu nghe hợp lý?

### (b) Biến đổi — tầng "có việc để đo"

Câu trả lời **không thể copy nguyên văn một chunk**. Phải đòi hỏi ít nhất một trong:

- **Tính toán** (T4: cộng tổng chi tiêu, đối chiếu hạn mức);
- **Tổng hợp nhiều tài liệu** (T1: phải trích ≥2 document mới trả lời được);
- **So sánh / phát hiện mâu thuẫn** (T1: hai bản policy khác phiên bản — phải chọn bản mới nhất; T2: chọn 1 trong 2 giả thuyết đều đúng một phần);
- **Từ chối vì thiếu dữ liệu để suy luận** (thiếu 1 vế thì không so sánh được → phải nói "không đủ dữ liệu").

> Nếu mọi câu hỏi đều là "tra 1 chunk rồi đọc lại" thì **faithfulness luôn ≈ 1.0, độ chính xác luôn ≈ 100%**, và bảng eval trở thành con số vô nghĩa. Tầng (b) tạo ra **chỗ có thể sai** — và chỗ có thể sai chính là chỗ chấm được điểm.

**Hai loại "từ chối" KHÁC NHAU** (không được trùng):

| Loại | Nguyên nhân | Lỗi ở khâu |
|---|---|---|
| (i) Tài liệu không chứa thông tin | Truy vấn không tìm ra | **Truy vấn** |
| (ii) Thông tin có nhưng không đủ để biến đổi (chỉ có hạn mức, không có hoá đơn) | Không suy luận được | **Suy luận** |

> **Câu tự kiểm:** Câu hỏi này nếu đưa cho một người chỉ được đọc 1 đoạn tài liệu, họ có trả lời được ngay không? Nếu "có" → đề tài đang **thiếu tầng (b)**.

### (c) Hành động — tầng "chứng minh là agent"

- Có ít nhất **một tool ghi** (thay đổi trạng thái thật: tạo request, chặn IP, submit quyết định, ghi log).
- Ngay sau đó **bắt buộc có bước verify** gọi lại một **tool đọc** để chứng minh trạng thái đã thực sự đổi.
- Cấu trúc bắt buộc là một cặp: **`write_tool()` → đọc lại → thấy thay đổi**.

Hai giá trị:

1. Chứng minh agent **thực sự dùng kết quả tool**, chứ không phải LLM tự diễn. Chỉ trả lời được câu "agent có thực sự dùng kết quả tool" nếu tool có **kết quả quan sát được**.
2. **Ràng buộc an toàn**: bước verify buộc agent phải quan sát hậu quả → có cơ chế "chỉ hành động khi bằng chứng đủ".

> Thiếu tầng này → chỉ có một pipeline tra cứu **đọc–rồi–in**. Không có side effect thì không có gì để verify, không có gì để agent "quyết định".
>
> **Câu tự kiểm:** Sau khi hệ thống chạy xong, có dòng dữ liệu nào trong DB/file/trạng thái **thật sự bị thay đổi** không? Và tôi chứng minh bằng lệnh đọc nào?

> **Tóm tắt:** (a) Trả lời **có nguồn** → (b) Suy ra được điều **không viết sẵn** → (c) **Làm thay đổi trạng thái và tự kiểm chứng**. Đủ 3 tầng mới là "agent có RAG có đo lường".

---

## 3. Năm đề tài gợi ý

| # | Đề tài | Sản phẩm chính |
|---|---|---|
| **T1** | Trợ lý quy chế + hành động | Hỏi quy chế → làm thủ tục → xác nhận |
| **T2** | Kiểm toán chi tiêu công tác | Báo cáo → đối chiếu hạn mức → duyệt/từ chối/leo thang |
| **T3** | Trợ lý học tập trên lesson plan môn học | Hỏi nội dung môn → trả lời có trích → từ chối nếu ngoài chương trình |
| **T4** | Trợ lý điểm rèn luyện + khiếu nại | Hỏi quy tắc → tính điểm rèn luyện → khiếu nại → xác nhận |
| **T5** | Trợ lý CTXH: quy đổi & đăng ký | Tra mã hoạt động → quy đổi ngày → đăng ký → xác nhận |

Có thể đề xuất đề tài riêng nhưng phải qua đúng bộ yêu cầu ở `02-yeu-cau-thuc-hien`.

### ❌ KHÔNG chọn loại đề tài

- Chỉ có **tra cứu** (chatbot hỏi đáp tài liệu).
- Dùng tool **chỉ để đọc** (không có side effect) → không chạy được bài kiểm tra "agent có thực sự dùng kết quả tool".
- Câu trả lời có thể **tra Google trong 10 giây**.

---

## 4. Sản phẩm phải nộp

| # | Sản phẩm | Ghi chú |
|---|---|---|
| 1 | `report.docx` | 8–9 trang, đúng khung [§7](#7-cấu-trúc-report-word-89-trang) |
| 2 | Repo code (zip hoặc link) | Kèm thư mục `.git` để xem lịch sử commit |
| 3 | `logs/` | ≥3 lần chạy thật, mỗi lần 1 file `jsonl` có timestamp, các bước, tool args/kết quả, `USAGE` từng câu (calls, prompt/completion tokens) |
| 4 | `tests/testset.jsonl` | ≥12 câu, trong đó **≥4 câu `no_answer`** |
| 5 | `ai-usage.md` | Khai báo dùng AI ở phần nào |
| 6 | `README.md` | Lệnh chạy **duy nhất** để tái lập demo và `make eval` |

---

## 5. Yêu cầu kỹ thuật bắt buộc

| # | Yêu cầu | Mức tối thiểu | GV kiểm tra bằng cách |
|---|---|---|---|
| **2.1** | Ngôn ngữ & môi trường | Python 3.11+; repo chạy trên máy GV bằng đúng 1 lệnh (`make setup && make demo`) | Chạy tại buổi bảo vệ |
| **2.2** | Orchestration **tự viết** | Vòng lặp agent do SV viết tay. Được dùng: `mcp` SDK, thư viện embedding, `rank_bm25`, `numpy`, `pandas`, `python-docx` | Đọc code, hỏi vấn đáp |
| **2.3** | Typing (w1) | Tool schema khai báo bằng `dataclass`/`TypedDict` có type hint — **không dùng dict thô** | `grep -n "@dataclass"` |
| **2.4** | Gọi API (w2) | Có retry/timeout, log lỗi HTTP; **prompt tách khỏi code** (template/`.txt`) | Đọc `call_llm` + file prompt |
| **2.5** | RAG (w3–w4) | **≥2 chế độ truy vấn: dense + hybrid BM25** — tái dùng `w4/ex2_1_hybrid_search.py`. Chunking có lý do (viết 3–5 dòng giải thích) | Chạy `make eval` |
| **2.6** | Agent loop (w6) | Có `MAX_STEPS`; tool lỗi trả chuỗi `"Error: ..."` (**không raise**); parse action an toàn (thiếu dấu ngoặc không làm chết run) | Đọc code + bài C2/C3 tại buổi bảo vệ |
| **2.7** | Side effect + verify | ≥1 tool thay đổi trạng thái; **bắt buộc có bước verify** (gọi lại tool đọc để chứng minh thay đổi) | Xem trace |
| **2.8** | MCP server (w7) | Server **do SV viết**, ≥2 tool (**≥1 tool ghi**), chạy qua **stdio**; **stdout sạch**; client **discover động** danh sách tool (không hard-code) | Chạy + đọc code server |

**Ràng buộc dữ liệu:**

- Tài liệu có metadata: `doc_id`, `title`, `date/version`, `owner`.
- Dữ liệu tiếng Việt hoặc tiếng Anh; **không dùng dữ liệu của nhóm khác cùng đề tài**.
- Được phép **tái dùng DOC0001–DOC0006 của lớp** và viết thêm **2–3 tài liệu mới**.

---

## 6. Điểm không bắt buộc — cộng thêm (tối đa +6)

| Việc làm thêm | Cộng | Hướng dẫn |
|---|---|---|
| Metadata filter dùng thật trong pipeline | +1 | Phối hợp w4 vào w6 |
| So sánh thêm 1 cấu hình (chunking hoặc dense-vs-hybrid) | +1 | `make eval` đã có sẵn |
| MCP server dùng được từ **host thứ hai** (client Python thứ hai là đủ) | +1 | Chứng minh interop |
| Đồ thị + CSV log chi tiết theo từng câu | +1 | Giúp phần eval dễ đọc hơn |

> Danh sách trên cộng tối đa +4 trong bảng gốc; trần chung của học phần là **+6** (mục 3 tài liệu 02 ghi "tối đa +6").

---

## 7. Cấu trúc report Word (đúng khung, 8–9 trang)

| # | Mục | Trang | Nội dung phải có |
|---|---|---|---|
| 1 | Vấn đề, phạm vi, giả định | 0.5–1 | Bài toán, người dùng, và hệ thống **KHÔNG làm gì** |
| 2 | Kiến trúc tổng thể | 1 | Sơ đồ agent/tool/MCP boundary + luồng xử lý 1 câu hỏi mẫu |
| 3 | Thiết kế RAG | 1.5 | Chunking + lý do, embedding, hybrid, dùng truy vấn nào |
| 4 | Thiết kế Agent & tool | 2 | Schema dataclass, mô tả tool viết như prompt, `MAX_STEPS`, xử lý lỗi, side effect + verify, trace thật 1 câu hỏi |
| 5 | MCP server | 1 | Danh sách tool + contract, transport, stdout, cách client discover |
| 6 | Đánh giá | 1.5 | Testset, cách đo, kết quả (kèm **chi phí token từng câu**), ≥1 ca thất bại + phân tích |
| 7 | Hạn chế & hướng phát triển | 0.5 | ≥2 hạn chế **trung thực** (không viết "chưa có thời gian") |
| 8 | Phân công & đóng góp | 0.5 | Ai làm gì + **commit hash tương ứng** (GV đối chiếu khi vấn đáp) |
| 9 | Phụ lục | — | Prompt gốc, trace dài, `ai-usage.md` |

---

## 8. Trọng số điểm

| Khối | Tiêu chí | Điểm |
|---|---|---|
| **A. Nhóm (60)** | Phạm vi & tính thực tiễn | 5 |
| | Chất lượng RAG | 13 |
| | Agent loop & thiết kế tool | 12 |
| | Tái lập & kỹ thuật (chạy 1 lệnh, README, không lộ key, git của cả 3 người, đúng checkpoint) | 12 |
| | MCP server | 8 |
| | Đánh giá & bằng chứng | 10 |
| **B. Cá nhân (40)** | Bảo vệ phần mình phụ trách | 15 |
| | Trả lời câu hỏi kỹ thuật | 15 |
| | Sửa code trực tiếp tại chỗ | 10 |
| **Cộng** | Việc làm thêm | tối đa +6 |

> **Ưu tiên:** Chất lượng RAG (13) > Agent loop & tool (12) = Tái lập & kỹ thuật (12) > Đánh giá (10) > MCP (8) > Phạm vi (5).

---

## 9. Liêm chính học thuật & buổi bảo vệ

### Dùng AI

- **Được phép** dùng AI/LLM để viết code (đúng tinh thần môn học).
- Nhưng **không giải thích được** và **không khai báo AI** → **B = 0**.
- **Bắt buộc nộp `ai-usage.md`**: dùng công cụ nào, cho phần nào, prompt chính, đoạn code nào do AI sinh.
- **Git history phải thể hiện cả ba thành viên làm việc thật** — không dồn 1 commit cuối kỳ.

### Bảo vệ 20 phút — vấn đáp riêng từng người

**Luật giải thích: SV phải giải thích được MỌI DÒNG trong phần mình nhận.**

| TT | Nội dung | SV chuẩn bị |
|---|---|---|
| 1 | **Cold start**: chạy lệnh README trên máy GV | README chính xác, `.env.example` đầy đủ, data có sẵn |
| 2 | **Demo**: mỗi SV 3 phút, có 1 câu hỏi GV đưa tại chỗ (**không có trong testset**) | Mở sẵn terminal |
| 3 | Trình bày kiến trúc, **không đọc slide** | Sơ đồ in sẵn; mỗi SV ~1.5 phút |
| 4 | Vấn đáp 1 câu chính + 1 câu đào sâu cho mỗi SV | Ôn khái niệm w1–w7; nhớ số liệu của chính mình |
| 5 | **Sửa code trực tiếp**: 1 yêu cầu/SV | Biết file/dòng mình viết; IDE quen tay |

---

## 10. Điểm mâu thuẫn giữa các tài liệu

| Điểm | `01-De-tai` | `02-Yeu-cau` | Xử lý |
|---|---|---|---|
| Số SV/nhóm | nhóm **3 SV** | nhóm **2 SV** | **Đã xác nhận: 3 SV** (mục 8 tài liệu 02 cũng ghi "git của cả 3 người") |
| Ngôn ngữ report | tiếng Việt | tiếng Việt | Không mâu thuẫn — syllabus (EN) chỉ nêu deliverable tương đương |
| Trần điểm cộng | — | mục 3 ghi "+6" nhưng bảng chỉ có 4 mục × +1 | Cần hỏi GV |

---

## 11. Phần bổ sung từ Syllabus (mục *Final Project Specification*)

Syllabus mô tả cùng đồ án nhưng ở góc nhìn học thuật. Các mục dưới **khớp** với tài liệu 01/02 và bổ sung thêm lựa chọn domain + thư viện.

### Domain gợi ý (tương ứng 5 đề tài ở [§3](#3-năm-đề-tài-gợi-ý))

1. **Course FAQ Bot** — hỏi đáp về syllabus và tài liệu môn học (≈ T3).
2. **Code Documentation Assistant** — index và hỏi đáp về docs của một thư viện Python.
3. **Research Paper Q&A** — index 5–10 bài báo, hỏi đáp nội dung.
4. **Personal Knowledge Base** — index ghi chú, bài viết, highlight sách.
5. **Product Documentation** — index user manual hoặc API docs.

### Minimum Requirements theo tầng (ánh xạ sang [§5](#5-yêu-cầu-kỹ-thuật-bắt-buộc))

| Tầng | Yêu cầu |
|---|---|
| **Data (w3)** | ≥5 documents, tối thiểu **10,000 tokens**; chunking có chunk size + overlap cấu hình được; metadata mỗi chunk (`source`, `date`, `chunk_index`) |
| **Retrieval (w3–w4)** | Vector store có embedding; similarity search trả **top-K chunks kèm score**; tùy chọn hybrid (BM25 + vector) hoặc re-ranking |
| **Generation (w4)** | Prompt template ép **grounded answers**; LLM call với context; **citation trong output** (vd `[Source: doc_title, chunk 3]`); xử lý edge case (rỗng, thiếu context) |
| **Evaluation (w5)** | RAGAS trên test set **≥5 câu**; báo cáo **faithfulness, answer relevance, context precision**; phân tích failure mode cho câu điểm thấp nhất |

### Deliverables (syllabus)

1. **Source code** — cấu trúc tốt, có docstring + README.
2. **Evaluation report** — Markdown với RAGAS metrics và failure mode analysis.
3. **Demo** — 5 phút, live, tại Session 2 của Week 8.

**Deadline:** hết Week 8, Session 1.

### Tools & Environment theo tuần

| Tuần | Thư viện |
|---|---|
| w1–2 | Python 3.11+, VS Code/PyCharm, `openai`, `python-dotenv` |
| w3–4 | `sentence-transformers` (hoặc OpenAI embedding API), `numpy`, `tiktoken`, `rank_bm25` |
| w5 | `ragas`, `datasets` |
| w6 | `openai` (function calling), `httpx` |
| w7 | `mcp` SDK (`pip install mcp`), `asyncio` |
| w8 | tất cả trên; tùy chọn `streamlit` / `gradio` |

**API keys:** SV tự lấy key (OpenAI hoặc provider khác); GV hướng dẫn budgeting. **Không commit key** (`.env.example` đầy đủ, `.env` trong `.gitignore`).

### Tài liệu tham khảo

- Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020.
- Yao, S., et al. (2023). *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023.
- Park, J. S., et al. (2023). *Generative Agents: Interactive Simulacra of Human Behavior.* UIST 2023.
- Packer, C., et al. (2023). *MemGPT: Towards LLMs as Operating Systems.* arXiv:2310.08560.
- Anthropic. (2024). *Model Context Protocol (MCP) Specification.* https://modelcontextprotocol.io
- RAGAS Documentation. https://docs.ragas.io
- OpenAI Function Calling Guide. https://platform.openai.com/docs/guides/function-calling

**Tools tham khảo (không dùng trực tiếp — môn học dùng Python thuần):** LangChain, LlamaIndex, ChromaDB/FAISS, Pydantic.

---

## 12. Checklist nhanh trước khi nộp

- [ ] Đủ 3 tầng (a) tra cứu + (b) biến đổi + (c) hành động
- [ ] ≥2 chế độ truy vấn (dense + hybrid BM25), tái dùng `w4/ex2_1_hybrid_search.py`
- [ ] Chunking có 3–5 dòng giải thích lý do
- [ ] Tool schema bằng `@dataclass`/`TypedDict`, không dict thô
- [ ] Prompt tách khỏi code (template/`.txt`)
- [ ] `call_llm` có retry/timeout + log lỗi HTTP
- [ ] Agent loop có `MAX_STEPS`; tool lỗi trả `"Error: ..."` không raise
- [ ] ≥1 tool side effect + bước verify đọc lại
- [ ] MCP server tự viết, ≥2 tool (≥1 ghi), stdio, stdout sạch, client discover động
- [ ] `tests/testset.jsonl` ≥12 câu, ≥4 `no_answer`
- [ ] `logs/` ≥3 lần chạy thật, mỗi file `jsonl` có `USAGE` từng câu
- [ ] `make setup && make demo` chạy được bằng 1 lệnh; `make eval` tái lập mọi số liệu
- [ ] `README.md`, `ai-usage.md`, `.env.example` đầy đủ; không lộ key
- [ ] `report.docx` 8–9 trang đúng 9 mục; có commit hash trong §8
- [ ] Git history thể hiện cả 3 thành viên, không dồn 1 commit cuối kỳ

---

## 13. Đề tài nhóm

Đề tài đã chọn: **TRFC Agent — Trợ lý Kiểm soát Rủi ro & Gian lận Giao dịch**.
Chi tiết đầy đủ (3 tầng, tool contract, gap analysis, rủi ro) ở [DE_TAI_TRFC_Agent.md](DE_TAI_TRFC_Agent.md).
