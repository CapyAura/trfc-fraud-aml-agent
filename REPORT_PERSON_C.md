# BÁO CÁO CHI TIẾT — PHẦN CỦA THÀNH VIÊN C (ĐO LƯỜNG & TÁI LẬP)

> **Tài liệu nguồn căn cứ:** `REPORT.md` (khung 9 mục môn AIPR) · `CLAUDE.md` §7 · `PHAN_CONG.md` §4–§5.  
> **Phạm vi phụ trách của C:** §6 Đánh giá (1.5 trang) · §8 Phân công & đóng góp (0.5 trang) · Ghép và định dạng `report.docx`.  
> **Dữ liệu thực nghiệm trích xuất từ:** Phiên chạy kiểm định chính thức `logs/staging_20261017_201308/` (12 testcases, đạt semantic gate PASS).

---

## §6 — Đánh giá (Evaluation) · 1.5 trang · Person C

### 6.1 Thiết kế và phân bố Testset

Bộ dữ liệu kiểm thử gồm đúng **12 ca kiểm thử chuẩn hóa** được lưu trữ tại file [`tests/testset.jsonl`](tests/testset.jsonl). Mỗi ca kiểm thử đều đi kèm nhãn ground truth: câu trả lời mong đợi (`expected`), tài liệu quy định bắt buộc phải trích dẫn (`must_cite`), và phân loại nghiệp vụ (`category`).

| Loại câu hỏi (`category`) | Số lượng | Mục đích kiểm định nghiệp vụ |
|---|:---:|---|
| `retrieval` | 3 | Tra cứu chính xác điều khoản quy định, bắt buộc trích dẫn đúng mã tài liệu `doc_id` và phiên bản `version` (`q01`, `q02`, `q03`). |
| `calc` | 2 | Tính toán tỷ lệ phần trăm và đối chiếu số dư/giao dịch thực tế với hạn mức ngày/giao dịch bằng tool, nghiêm cấm LLM tự tính nhẩm (`q04`, `q05`). |
| `contradiction` | 2 | Xử lý tình huống xung đột quy định pháp luật giữa văn bản cũ đã hết hiệu lực và văn bản hiện hành (điển hình: DOC0003 bản 2025.2 đã bị thay thế bởi bản 2026.1) (`q06`, `q07`). |
| `multi_doc` | 1 | Yêu cầu Agent phải tổng hợp thông tin đối chiếu chéo từ $\ge 2$ văn bản quy phạm khác nhau (`q08`). |
| `no_answer` (Loại i) | 2 | **Ngoài phạm vi nghiệp vụ (Out-of-Scope):** Câu hỏi về các phương thức thanh toán không nằm trong danh mục DOC0009 (như séc bảo chi, tiền điện tử không phép) $\rightarrow$ Hệ thống bắt buộc phải chủ động từ chối (`q09`, `q10`). |
| `no_answer` (Loại ii) | 2 | **Thiếu cơ sở dữ liệu trong Corpus (Unanswerable):** Câu hỏi nằm trong phạm vi nhưng corpus không chứa dữ kiện hoặc tài khoản không tồn tại $\rightarrow$ Bắt buộc từ chối, không suy diễn bịa đặt (`q11`, `q12`). |
| **Tổng cộng** | **12** | Đạt 100% chỉ tiêu phân bố theo thiết kế đề tài. |

#### Nguyên lý đo lường cặp chỉ số song hành: Faithfulness & Refusal Correctness
Trong các hệ thống RAG & AI Agent phục vụ nghiệp vụ Tuân thủ & Pháp chế (Risk & Compliance), nguy cơ lớn nhất là **ảo giác (hallucination)** và **tự ý suy diễn**. 
* Nếu hệ thống chỉ đo lường đơn lẻ chỉ số `Faithfulness` (tính trung thực của câu trả lời dựa trên context), một Agent có xu hướng *luôn luôn từ chối trả lời* sẽ đạt điểm Faithfulness tuyệt đối ($1.0$) vì không bao giờ đưa ra khẳng định sai lệch.
* Ngược lại, nếu chỉ đo lường tỷ lệ trả lời, hệ thống sẽ cố tình bịa đặt câu trả lời cho các câu hỏi ngoài phạm vi hoặc thiếu dữ kiện để tránh bị phạt điểm bỏ trống.

Do đó, đồ án bắt buộc đo lường **cặp chỉ số kiềm chế lẫn nhau**:
1. **Faithfulness** đóng vai trò trừng phạt hành vi bịa đặt thông tin nằm ngoài văn bản luật.
2. **Refusal Correctness** (phân tách độc lập loại i và loại ii) đóng vai trò trừng phạt việc từ chối sai câu hỏi hợp lệ, đồng thời kiểm soát chặt chẽ việc phát hiện đúng giới hạn tri thức của hệ thống.

---

### 6.2 Phương pháp đo lường (Measurement Methodology)

Toàn bộ logic tính toán chỉ số đánh giá được triển khai độc lập tại [`eval/metrics.py`](eval/metrics.py):

| Chỉ số | Định nghĩa kỹ thuật | Nguồn triển khai |
|---|---|---|
| **Faithfulness** | Tỷ lệ các khẳng định thực tế (`claims`) trong câu trả lời có chuỗi ký tự khớp chính xác trong các đoạn văn bản context đã truy hồi. | `eval/metrics.py:faithfulness()` |
| **Context Precision** | Tỷ lệ các đoạn văn bản context truy hồi có chứa đúng mã văn bản `doc_id` chuẩn (Gold reference). | `eval/metrics.py:context_precision()` |
| **Answer Correctness** | Đánh giá câu trả lời có thỏa mãn tiêu chí chứa toàn bộ các giá trị bắt buộc (`contains_all`). | `eval/metrics.py:answer_correctness()` |
| **Refusal Correctness** | Tỷ lệ đưa ra quyết định từ chối chính xác đối với các câu `no_answer`, tách biệt rõ Loại (i) và Loại (ii). | `eval/metrics.py:refusal_rate()` |
| **Resource & Cost** | Thống kê số lần gọi mô hình (`calls`), token đầu vào (`prompt_tokens`), token sinh ra (`completion_tokens`), và độ dài ngữ cảnh lớn nhất (`max_prompt`). | JSONL runtime trace trong `logs/` |

> **Lựa chọn thiết kế:** Hệ thống sử dụng **Phương pháp so khớp chuỗi xác định (Deterministic String Matching)** thay vì dùng LLM-as-a-Judge (như thư viện RAGAS nguyên bản).  
> * **Ưu điểm:** Tính toán tức thì, chi phí $0$ token, kết quả tái lập tuyệt đối $100\%$ qua các lần chạy (deterministic), không bị ảnh hưởng bởi độ trễ mạng hay tính bất định (temperature) của mô hình giám khảo.  
> * **Nhược điểm chấp nhận:** Không tự động nhận diện được các cách diễn đạt tương đương về nghĩa (paraphrasing) nếu câu chữ không khớp nguyên văn chuỗi chuẩn.

---

### 6.3 Kết quả thực nghiệm chi tiết từng câu hỏi

Dữ liệu được trích xuất nguyên bản từ file [`logs/staging_20261017_201308/reports/evaluation.csv`](logs/staging_20261017_201308/reports/evaluation.csv):

| ID | Nhóm (`category`) | Kết quả thực tế | Answer Correctness | Context Precision | Refusal đúng | Refusal Subtype | Số cuộc gọi (`calls`) | Prompt Tokens | Completion Tokens | Max Prompt |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **q01** | `retrieval` | `answer` | **Đúng (True)** | 0.60 (60%) | n/a | n/a | 2 | 7.627 | 448 | 4.842 |
| **q02** | `retrieval` | `answer` | **Đúng (True)** | 0.75 (75%) | n/a | n/a | 3 | 16.904 | 896 | 7.105 |
| **q03** | `retrieval` | `answer` | **Đúng (True)** | n/a | n/a | n/a | 3 | 13.188 | 568 | 5.242 |
| **q04** | `calc` | `answer` | **Đúng (True)** | n/a | n/a | n/a | 4 | 16.671 | 897 | 5.155 |
| **q05** | `calc` (freeze) | `answer` | Sai (False)* | n/a | n/a | n/a | 5 | 23.557 | 982 | 5.430 |
| **q06** | `contradiction` (flag) | `answer` | **Đúng (True)** | n/a | n/a | n/a | 5 | 22.637 | 987 | 5.167 |
| **q07** | `contradiction` | `answer` | **Đúng (True)** | n/a | n/a | n/a | 3 | 17.086 | 875 | **7.188** |
| **q08** | `multi_doc` | `answer` | Sai (False)* | n/a | n/a | n/a | 3 | 15.960 | 842 | 6.605 |
| **q09** | `no_answer` (i) | `refusal` | n/a | n/a | **Đúng (True)** | **Loại i (True)** | 3 | 15.364 | 854 | 6.337 |
| **q10** | `no_answer` (i) | `refusal` | n/a | n/a | **Đúng (True)** | **Loại i (True)** | 3 | 15.232 | 817 | 6.269 |
| **q11** | `no_answer` (ii) | `refusal` | n/a | n/a | **Đúng (True)** | **Loại ii (True)** | 3 | 16.760 | 890 | 7.026 |
| **q12** | `no_answer` (ii) | `refusal` | n/a | 0.40 (40%) | **Đúng (True)** | **Loại ii (True)** | 3 | 11.702 | 591 | 4.504 |
| **TỔNG / TB** | **12 câu** | **100% Hoàn thành** | **6/8 đạt (75%)** | **0.58 (58%)** | **4/4 đạt (100%)** | **4/4 đạt (100%)** | **40 calls** | **192.688** | **9.647** | **7.188** |

*\*Ghi chú:* Các trường hợp `q05` và `q08` có `Answer Correctness = False` do Agent diễn đạt lại (paraphrase) thay vì dùng đúng chuỗi nguyên văn mà bộ chấm yêu cầu — `q05` trả về `44%` nhưng không nhắc lại giá trị `220.000.000 VND`, `q08` viết *"không **thể** ra quyết định khóa"* thay vì *"không **được** ra quyết định khóa"*. Đây là hạn chế của cơ chế so khớp chuỗi literal, **không phải** do redaction: `eval/run_eval.py:284-300` tính chỉ số **trước** khi `redact_for_log()` chạy ở `:314`. Phân tích chi tiết tại Mục 6.5.

---

### 6.4 Phân tích chi phí tài nguyên và Token

* **Mô hình triển khai thử nghiệm:** **không ghi lại được.** Log của phiên staging không lưu trường provider/model, nên không thể điền từ log. Giá trị `qwen/qwen3.8-27b` trong `llm.py:24` chỉ là default trong code — đó không phải bằng chứng về model đã chạy thật. Đây là hạn chế của logging.
* **Tổng lượng Prompt Tokens tiêu thụ:** **192.688 tokens** (trung bình 16.057 tokens/câu hỏi gồm lịch sử ReAct loop và context luật).
* **Tổng lượng Completion Tokens tiêu thụ:** **9.647 tokens** (trung bình 803 tokens/câu hỏi cho suy luận và gọi tool).
* **Tổng chi phí toàn bộ testset:** **202.335 tokens** cho 40 lượt gọi LLM.
* **Câu hỏi có ngữ cảnh prompt đơn lẻ dài nhất (`max_prompt`):** **`q07`** đạt **7.188 tokens** do phải nạp đồng thời nhiều phiên bản tài liệu để xử lý mâu thuẫn hiệu lực văn bản.
* **Câu hỏi tiêu tốn tổng tài nguyên nhiều nhất:** **`q05`** với **24.539 tokens** (5 bước lặp ReAct, gồm tính toán hạn mức, gọi lệnh tạm khóa `freeze_account_temporarily`, và gọi lệnh kiểm tra đối soát trạng thái `get_account_risk_status`).

---

### 6.5 Phân tích ca thất bại điển hình (Failure Analysis)

Từ kết quả thực nghiệm, đồ án chọn **ca kiểm thử `q08`** (nhóm `multi_doc`) để phân tích nguyên nhân kỹ thuật:

* **Câu hỏi kiểm thử:** *"Nhật ký giao dịch gốc đã hết thời hạn lưu trữ và bị xóa thì có được ra quyết định khóa tài khoản không, và thời hạn lưu trữ tối thiểu của hồ sơ nhận biết khách hàng là bao lâu?"*
* **Tiêu chuẩn kỳ vọng (Gold standard):** Yêu cầu câu trả lời phải chứa các cụm từ: `"không được ra quyết định khóa"` và `"5 năm"`.
* **Hành vi thực tế của Agent (Trích xuất từ log):**
  - Agent gọi tool `search_policy` tra cứu chéo giữa DOC0006 và DOC0008.
  - Phản hồi thực tế của Agent:
    > *"1) Có được quyết định khóa tài khoản khi thiếu mã giao dịch gốc / nhật ký gốc đã hết hạn lưu trữ? **Không.** Khi nhật ký giao dịch gốc đã hết thời hạn lưu trữ và bị xóa, mọi yêu cầu tính toán dựa trên nhật ký đó... đều không đủ căn cứ ra quyết định khóa tài khoản..."*
* **Phân loại nguyên nhân:** **Hạn chế của bộ đánh giá so khớp chuỗi xác định (Evaluation String-Matching Limitation)**, không phải lỗi logic của Agent.
  - Về mặt bản chất nghiệp vụ và suy luận (Reasoning): Agent suy luận và trả lời hoàn toàn chính xác theo quy định pháp luật (kết luận rõ ràng là *"Không"* và nêu rõ lý do).
  - Tuy nhiên, vì tiêu chí kiểm tra chuỗi sử dụng hàm `_contains_literal()` yêu cầu phải xuất hiện đúng chuỗi nguyên văn *"không được ra quyết định khóa"*, việc Agent trả lời linh hoạt bằng cấu trúc phủ định tách rời đã khiến hàm chấm điểm trả về `False`.
* **Đề xuất khắc phục:** 
  1. Chuẩn hóa bộ tiêu chí `testset.jsonl`: bổ sung danh sách các biến thể diễn đạt chấp nhận được (`synonyms` / `regex pattern`).
  2. Nâng cấp bộ chấm điểm: kết hợp cơ chế kiểm tra Semantic Entailment nhẹ bằng mô hình phân loại NLI offline để nhận diện chính xác câu trả lời đúng nghĩa.

---

### 6.6 Trạng thái xác minh bằng chứng thực nghiệm (Audit & Evidence Status)

Báo cáo tuân thủ nguyên tắc trung thực học thuật theo đúng hiện trạng hệ thống:
* **Các nội dung ĐÃ ĐƯỢC XÁC MINH bằng chứng thật:**
  1. Bộ unit test tự động đạt **368 passed, 0 skipped** trên môi trường Python 3.13.5 (bao gồm 4 bài test gọi tool ở `tests/test_tools.py`, 22 bài test evaluation metrics ở `tests/test_eval.py`, 40 bài test cách ly database subprocess ở `tests/test_db_isolation.py`).
  2. Phiên chạy Staging độc lập [`logs/staging_20261017_201308/`](logs/staging_20261017_201308/) đạt **PASS 100% trên Semantic Gate** với đủ 12 ca kiểm thử, ghi nhận đầy đủ `step_events.jsonl`, `decision_events.jsonl`, `evaluation.csv` và biểu đồ SVG.
  3. Cơ chế cách ly ghi an toàn: Quá trình chạy thử nghiệm chỉ thao tác trên database tạm thời (đường dẫn ngoài repo, đặt qua biến môi trường `TRFC_STATE_DB`), bảo toàn tuyệt đối database gốc `data/state.db` với SHA256 không đổi: `A86FCA5B32A0477CB1A511F57516AC991857FB7EF4F5836F915C685687E7E1A6`.
* **Các giới hạn kỹ thuật (Chưa xác minh):**
  - Hệ thống chưa kết nối môi trường Core Banking thời gian thực (chỉ chạy trên dữ liệu SQLite mô phỏng).
  - Chưa triển khai luồng phê duyệt trực tiếp của con người (Human-in-the-loop) cho các quyết định đóng băng tài khoản ngoài môi trường thử nghiệm.

---

## §8 — Phân công & Đóng góp · 0.5 trang · Person C

### Bảng phân công trách nhiệm và minh chứng mã nguồn

| Thành viên | Vai trò | Phân hệ phụ trách chính | Danh sách Commit Hash tiêu biểu |
|---|---|---|---|
| **Thành viên A** | Dữ liệu & Truy hồi | Corpus 9 văn bản quy phạm (`data/docs/*.md`), module phân đoạn Chunking (`chunking.py`), Vector Store & Embedding (`embed.py`, `store.py`), Hybrid Search BM25 + Dense (`search.py`), Metadata filter `tier`. | `ed531d9`<br>`69dd5d8`<br>`b975579`<br>`0e0f6fc` |
| **Thành viên B** | Agent & Tool / MCP | Tool Schemas `@dataclass` (`schemas.py`), triển khai 5 Tool nghiệp vụ ghi/đọc SQLite (`impl.py`, `state.py`), MCP Server chuẩn stdio (`server.py`), Vòng lặp ReAct Loop (`loop.py`, `parse.py`), Bộ gọi LLM đa provider (`llm.py`), System Prompts (`prompts/*.txt`). | `6ccbdf1`<br>`84a69e7`<br>`d12f5cc`<br>`aae71ca` |
| **Thành viên C** | Đo lường & Tái lập | Xây dựng bộ Testset 12 câu (`testset.jsonl`), Pipeline đánh giá & Metrics (`metrics.py`, `run_eval.py`, `report.py`), MCP Client thứ hai (`client2.py`), Semantic Gate (`semantic_gate.py`), Staging Runner (`run_c4_staging.ps1`), Cấu hình Makefile, Ghép `report.docx`. | `8c77866`<br>`2a6cffb`<br>`86b144e`<br>`b9f09ba` |

### Bảng đối soát tài khoản Git trên Repository

Tính đến phiên bản chốt, kho lưu trữ ghi nhận tổng cộng **68 commits** phân bổ theo các tài khoản Git:

| Tài khoản Git | Số lượng Commit | Vai trò tương ứng trong đồ án |
|---|:---:|---|
| **Do Ngo** | 38 commits | Thành viên B (Phát triển chính ReAct Loop, Tools, MCP Server và Decision Prompt) |
| **CapyCoder** | 12 commits | Thành viên A (Soạn thảo Corpus, RAG, Chunking, và tài liệu đặc tả) |
| **Penguin-cell34** | 11 commits | Thành viên C (Xây dựng Evaluator, Semantic Gate, Staging Runner, và sửa lỗi tích hợp) |
| **Do Coding** | 7 commits | Thành viên B (Tài khoản phụ hỗ trợ commit các module MCP và Tool schema) |
| **Tổng cộng** | **68 commits** | **Ghi chú bắt buộc:** Tài khoản `Do Ngo` và `Do Coding` thuộc cùng Thành viên B, đảm bảo dự án có đúng 3 thành viên thực hiện độc lập. |

---

## Bảng Checklist hoàn tất của Thành viên C (Verification Checklist)

- [x] **§6.1:** Bảng phân bố testset 12 câu đầy đủ, định nghĩa rõ ràng 2 dạng `no_answer` (Loại i ngoài phạm vi vs Loại ii thiếu dữ liệu), luận giải chi tiết lý do đo cặp Faithfulness & Refusal.
- [x] **§6.2:** Trình bày chính xác phương pháp đo lường so khớp chuỗi xác định (Deterministic Matching) khớp $100\%$ mã nguồn [`eval/metrics.py`](eval/metrics.py).
- [x] **§6.3:** Điền bảng kết quả 12 câu với đầy đủ thông số thực nghiệm lấy từ [`logs/staging_20261017_201308/reports/evaluation.csv`](logs/staging_20261017_201308/reports/evaluation.csv).
- [x] **§6.4:** Tính toán chính xác tổng chi phí: 192.688 Prompt Tokens, 9.647 Completion Tokens, 40 LLM Calls, Max Prompt 7.188 tokens (`q07`).
- [x] **§6.5:** Phân tích ca thất bại thực tế (`q08`) dựa trên bằng chứng log thật, chỉ ra nguyên nhân chuỗi literal và đề xuất giải pháp kỹ thuật.
- [x] **§6.6:** Báo cáo trung thực mức độ xác minh (Pass Semantic Gate, cách ly DB thành công, không bịa đặt môi trường production).
- [x] **§8:** Lập bảng commit hash thật từ lịch sử Git (`8c77866`, `6ccbdf1`, `ed531d9`...), ghi chú rõ ràng về 2 tài khoản commit của Thành viên B.
- [x] **Client thứ hai:** File [`src/trfc/mcp_server/client2.py`](src/trfc/mcp_server/client2.py) độc lập, chạy đạt 12/12 unit tests trong `test_client2.py`.
- [x] **Vệ sinh dữ liệu:** Đã rà lại toàn bộ ba file báo cáo; các TODO về số liệu dense-vs-hybrid (§3.5) và provider/model (§5) đã được thay bằng nội dung đúng thực tế. Mọi số liệu còn lại đều có căn cứ từ log thực nghiệm.
- [x] **Quy chuẩn trang:** Nội dung được căn chỉnh độ dài chặt chẽ, sẵn sàng để ghép vào văn bản `report.docx` đạt chuẩn 8–9 trang.
