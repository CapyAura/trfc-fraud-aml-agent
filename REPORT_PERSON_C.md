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
| **Metadata Filter Usage** | Câu khai báo `expected_tier` chỉ đạt khi trace có ít nhất một lệnh `search_policy` truyền đúng `tier` đó; chấm trên `tool_trace`, không chấm trên văn bản trả lời. Trace không thu được (`null`) trả `None`, không bao giờ đọc thành `True`. | `eval/metrics.py:metadata_filter_usage()` |
| **Resource & Cost** | Thống kê số lần gọi mô hình (`calls`), token đầu vào (`prompt_tokens`), token sinh ra (`completion_tokens`), và độ dài ngữ cảnh lớn nhất (`max_prompt`). | JSONL runtime trace trong `logs/` |

> **Lựa chọn thiết kế:** Hệ thống sử dụng **Phương pháp so khớp chuỗi xác định (Deterministic String Matching)** làm thước đo công bố chính thức thay vì phụ thuộc hoàn toàn vào LLM-as-a-Judge.
> * **Ưu điểm:** Tính toán tức thì, chi phí $0$ token, kết quả tái lập tuyệt đối $100\%$ qua các lần chạy (deterministic), không bị ảnh hưởng bởi độ trễ mạng hay tính bất định (temperature) của mô hình giám khảo.  
> * **Nhược điểm & giải pháp bổ trợ:** Không tự động nhận diện được các cách diễn đạt tương đương về nghĩa (paraphrasing). Để khắc phục, Person C đã triển khai thêm: (1) Cấu trúc từ đồng nghĩa `{"label": ..., "any": [...]}` trong `testset.jsonl` và `eval/metrics.py`; (2) Tùy chọn **LLM Judge độc lập** (`eval/llm_judge.py`, cờ `--judge`) chạy song song, phân tích claims và gán nhãn đối chiếu mà không ghi đè điểm tất định. Bộ judge này bị cấm chạy trên log đã qua redaction để đảm bảo tính khách quan.

---

### 6.3 Kết quả thực nghiệm chi tiết từng câu hỏi

Dữ liệu được trích xuất nguyên bản từ file [`logs/staging_20261017_201308/reports/evaluation.csv`](logs/staging_20261017_201308/reports/evaluation.csv) (bản re-score bằng `python -m eval.report --rescore`, khớp từng ô với [`eval/reports/evaluation.csv`](eval/reports/evaluation.csv)):

| ID | Nhóm (`category`) | Kết quả thực tế | Answer Correctness | Context Precision | Refusal đúng | Refusal Subtype | Số cuộc gọi (`calls`) | Prompt Tokens | Completion Tokens | Max Prompt |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **q01** | `retrieval` | `answer` | **Đúng (True)** | 0.60 (60%) | n/a | n/a | 2 | 7.627 | 448 | 4.842 |
| **q02** | `retrieval` | `answer` | **Đúng (True)** | 0.75 (75%) | n/a | n/a | 3 | 16.904 | 896 | 7.105 |
| **q03** | `retrieval` | `answer` | **Đúng (True)** | 0.83 (83%) | n/a | n/a | 3 | 13.188 | 568 | 5.242 |
| **q04** | `calc` | `answer` | **Đúng (True)** | 0.50 (50%) | n/a | n/a | 4 | 16.671 | 897 | 5.155 |
| **q05** | `calc` (freeze) | `answer` | Sai (False)* | 0.60 (60%) | n/a | n/a | 5 | 23.557 | 982 | 5.430 |
| **q06** | `contradiction` (flag) | `answer` | **Đúng (True)** | 1.00 (100%) | n/a | n/a | 5 | 22.637 | 987 | 5.167 |
| **q07** | `contradiction` | `answer` | **Đúng (True)** | 0.67 (67%) | n/a | n/a | 3 | 17.086 | 875 | **7.188** |
| **q08** | `multi_doc` | `answer` | Sai (False)* | 0.80 (80%) | n/a | n/a | 3 | 15.960 | 842 | 6.605 |
| **q09** | `no_answer` (i) | `refusal` | n/a | 0.90 (90%) | **Đúng (True)** | **Loại i (True)** | 3 | 15.364 | 854 | 6.337 |
| **q10** | `no_answer` (i) | `refusal` | n/a | 1.00 (100%) | **Đúng (True)** | **Loại i (True)** | 3 | 15.232 | 817 | 6.269 |
| **q11** | `no_answer` (ii) | `refusal` | n/a | 0.80 (80%) | **Đúng (True)** | **Loại ii (True)** | 3 | 16.760 | 890 | 7.026 |
| **q12** | `no_answer` (ii) | `refusal` | n/a | 0.40 (40%) | **Đúng (True)** | **Loại ii (True)** | 3 | 11.702 | 591 | 4.504 |
| **TỔNG / TB** | **12 câu** | **100% Hoàn thành** | **6/8 đạt (75%)** | **0.74 (74%) — 12/12 câu chấm được** | **12/12 đạt (100%)** | **4/4 đạt (100%)** | **40 calls** | **192.688** | **9.647** | **7.188** |

*\*Ghi chú — hai ca `False` có nguyên nhân KHÁC NHAU, không được gộp:*
> * **`q05` — marker bị che bởi redaction, không phải paraphrase.** Trong log `201308`, `expected.values[1]` đã bị ghi thành `[REDACTED] VND` và câu trả lời đã lưu có **9 vị trí `[REDACTED]`**, nên người đọc không thể đối chiếu marker tiền tệ. Các lần chạy sau có thêm trường `marker_results` (ghi **trước** redaction) xác nhận đúng cơ chế này: `q05` có `[{index: 1, satisfied: true}, {index: 2, satisfied: false}]` — `44%` đạt, marker tiền tệ không đạt. Điểm vẫn được tính **trước** redaction (`eval/run_eval.py:326` dựng `row["metrics"]`, `:378` mới gọi `redact_for_log`), nên `False` phản ánh câu trả lời gốc — nhưng đây là **giới hạn bằng chứng**, không phải kết luận agent tính sai.
> * **`q08` — paraphrase, không có redaction.** Câu trả lời đã lưu có **0 vị trí `[REDACTED]`**; agent viết *"không **thể** ra quyết định khóa"* thay vì *"không **được** ra quyết định khóa"*, nên `marker_satisfied()` trả `False`. Đây thuần túy là hạn chế của so khớp chuỗi literal.

Phân tích chi tiết tại Mục 6.5.

---

### 6.4 Phân tích chi phí tài nguyên và Token

* **Mô hình triển khai thử nghiệm:** **không ghi lại được.** Log của phiên staging không lưu trường provider/model, nên không thể điền từ log. Giá trị `qwen/qwen3.8-27b` trong `llm.py:24` chỉ là default trong code — đó không phải bằng chứng về model đã chạy thật. Đây là hạn chế của logging.
* **Tổng lượng Prompt Tokens tiêu thụ:** **192.688 tokens** (trung bình 16.057 tokens/câu hỏi gồm lịch sử ReAct loop và context luật).
* **Tổng lượng Completion Tokens tiêu thụ:** **9.647 tokens** (trung bình 803 tokens/câu hỏi cho suy luận và gọi tool).
* **Tổng chi phí toàn bộ testset:** **202.335 tokens** cho 40 lượt gọi LLM.
* **Câu hỏi có ngữ cảnh prompt đơn lẻ dài nhất (`max_prompt`):** **`q07`** đạt **7.188 tokens** do phải nạp đồng thời nhiều phiên bản tài liệu để xử lý mâu thuẫn hiệu lực văn bản.
* **Câu hỏi tiêu tốn tổng tài nguyên nhiều nhất:** **`q05`** với **24.539 tokens** (5 bước lặp ReAct, gồm tính toán hạn mức, gọi lệnh tạm khóa `freeze_account_temporarily`, và gọi lệnh kiểm tra đối soát trạng thái `get_account_risk_status`).

#### Metadata filter `tier` dùng thật trong pipeline (điểm cộng +1)

`search_policy` nhận tham số `tier` và `store.rank_candidates(tier)` lọc ứng viên **trước khi rank**. Để chứng minh filter đi vào pipeline chứ không chỉ tồn tại trong code, `q04` khai báo `expected_tier: 2` và evaluator ghi metric `metadata_filter_usage` (chấm trên `tool_trace`, không chấm trên văn bản trả lời):

| Lần chạy | Câu | `tier` model truyền vào `search_policy` | `metadata_filter_usage` |
|---|---|:---:|:---:|
| `logs/staging_20261018_014623/` | q04 | không truyền (`tier` vắng mặt) | **False** |
| `logs/staging_20261018_015357/` | q04 | `tier=2` | **True** |

Ca đầu cho thấy model tự bỏ qua filter dù câu hỏi có nêu tầng; ca sau, khi câu hỏi yêu cầu rõ "tra cứu bằng bộ lọc metadata tier=2", trace ghi nhận `{"query": "...", "tier": 2, "k": 5}` và metric đạt `True`. Đây là số đo từ log thật, không phải suy luận từ code.

Metric này được nối vào pipeline đánh giá: `eval/run_eval.py` ghi `metrics.metadata_filter_usage`, `eval/report.py` xuất cột `metadata_filter_usage` trong `evaluation.csv` và hỗ trợ `--rescore` trên log cũ. Lưu ý phạm vi: metric chứng minh filter **được yêu cầu và truyền đúng tham số**, không chứng minh nội dung chunk trả về đã lọc đúng — phần đó do `tests/test_chunking.py` canh riêng.

---

### 6.5 Phân tích ca thất bại điển hình (Failure Analysis)

Hai ca `Answer Correctness = False` có **hai nguyên nhân khác nhau** và phải được đọc tách biệt:

#### (a) `q05` — marker bị che bởi redaction (giới hạn bằng chứng, không phải lỗi suy luận)

* **Câu hỏi:** tính tỷ lệ vượt hạn mức ngày cho ACC001, rồi tạm khóa tài khoản và verify.
* **Marker kỳ vọng:** `"44%"` và `"220.000.000 VND"`.
* **Bằng chứng từ log:** câu trả lời đã lưu chứa **9 vị trí `[REDACTED]`**, và `expected.values[1]` trong log cũng đã thành `[REDACTED] VND`. Ở lần chạy `staging_20261018_012603` (có thêm trường `marker_results`), cùng câu này cho `[{index: 1, satisfied: true}, {index: 2, satisfied: false}]`: `44%` đạt, marker tiền tệ không đạt. Người đọc log `201308` không thể tự đối chiếu con số tiền.
* **Phân loại:** điểm được tính **trước** redaction — `eval/run_eval.py:326` dựng `row["metrics"]`, `:378` mới gọi `redact_for_log(row)` — nên `False` là kết quả trên câu trả lời gốc. Đây là **hạn chế bằng chứng**: kết luận đúng/sai không thể kiểm lại từ log đã commit, không phải kết luận agent tính sai.

#### (b) `q08` — so khớp chuỗi literal (hạn chế của bộ chấm, không phải lỗi suy luận)

* **Câu hỏi:** khi nhật ký giao dịch gốc đã hết hạn lưu trữ, kiểm soát viên có được quyết định khóa tài khoản không, và dữ liệu gốc lưu tối thiểu bao lâu?
* **Marker kỳ vọng:** `"không được ra quyết định khóa"` và `"5 năm"`.
* **Hành vi thực tế (trích log):** agent gọi `search_policy` tra cứu chéo DOC0006 và DOC0008, kết luận **"Không"** và giải thích rằng kiểm soát viên *"không **thể** ra quyết định khóa"*, đồng thời trả lời đúng `"5 năm"`. Câu trả lời đã lưu có **0 vị trí `[REDACTED]`**, nên redaction không tham gia vào ca này.
* **Phân loại:** `marker_satisfied()` yêu cầu đúng chuỗi *"không được ra quyết định khóa"*; cách diễn đạt *"không thể"* không khớp → `False`. Đây là hạn chế của so khớp chuỗi literal.

#### Giải pháp đã triển khai

1. **Biến thể diễn đạt trong testset:** `q08` dùng criterion dạng `{"label": ..., "any": [...]}` với ba cách nói tương đương (`không được ra quyết định khóa`, `không thể ra quyết định khóa`, `không được quyết định khóa`). Hàm chấm tương ứng là **`marker_satisfied()`** trong [`eval/metrics.py`](eval/metrics.py) — không có hàm `_contains_all()` trong repo.
2. **Ghi marker trước redaction:** `eval/run_eval.py:348` lưu `marker_results` (chỉ số thứ tự + kind + satisfied, không chứa số tiền) **trước** khi redaction chạy, để log vẫn kiểm chứng được ca như `q05` mà không làm lộ số tiền.
3. **LLM Judge độc lập:** `eval/llm_judge.py` (cờ `--judge`) trích claims và gán nhãn đối chiếu song song, **không ghi đè** điểm tất định, và **từ chối** chạy trên văn bản còn `[REDACTED]`.

---

### 6.6 Trạng thái xác minh bằng chứng thực nghiệm (Audit & Evidence Status)

Báo cáo tuân thủ nguyên tắc trung thực học thuật theo đúng hiện trạng hệ thống:
* **Các nội dung ĐÃ ĐƯỢC XÁC MINH bằng chứng thật:**
  1. Bộ unit test tự động đạt **401 passed, 1 skipped** trên môi trường Python 3.14.7 (bao gồm 4 bài test gọi tool ở `tests/test_tools.py`, 32 bài test evaluation/report ở `tests/test_eval.py`, 40 bài test cách ly database subprocess ở `tests/test_db_isolation.py`, 24 bài test `test_semantic_gate.py`, và 26 bài test `test_llm_judge.py`; ca skip duy nhất là tạo symlink trên Windows không có quyền Admin tại `tests/test_eval_db_isolation.py:73`).
  2. Phiên chạy Staging độc lập [`logs/staging_20261017_201308/`](logs/staging_20261017_201308/) đạt **PASS 100% trên Semantic Gate** với đủ 12 ca kiểm thử, ghi nhận đầy đủ `step_events.jsonl`, `decision_events.jsonl`, `evaluation.csv` và biểu đồ SVG.
  3. Cơ chế cách ly ghi an toàn: Quá trình chạy thử nghiệm chỉ thao tác trên database tạm thời (đường dẫn ngoài repo, đặt qua biến môi trường `TRFC_STATE_DB`), bảo toàn tuyệt đối database gốc `data/state.db` với SHA256 không đổi: `A86FCA5B32A0477CB1A511F57516AC991857FB7EF4F5836F915C685687E7E1A6`.
* **Các giới hạn kỹ thuật (Chưa xác minh):**
  - Hệ thống chưa kết nối môi trường Core Banking thời gian thực (chỉ chạy trên dữ liệu SQLite mô phỏng).
  - Chưa triển khai luồng phê duyệt trực tiếp của con người (Human-in-the-loop) cho các quyết định đóng băng tài khoản ngoài môi trường thử nghiệm.
  - `faithfulness` = `Unscorable` trên **12/12** câu vì runtime không sinh `claims`; đây là hạn chế đã biết, **không** phải điểm faithfulness đạt. Biểu đồ `faithfulness.svg` ghi đúng `Unscorable: 12`.

---

## §8 — Phân công & Đóng góp · 0.5 trang · Person C

### Bảng phân công trách nhiệm và minh chứng mã nguồn

| Thành viên | Vai trò | Phân hệ phụ trách chính | Danh sách Commit Hash tiêu biểu |
|---|---|---|---|
| **Thành viên A** | Dữ liệu & Truy hồi | Corpus 9 văn bản quy phạm (`data/docs/*.md`), module phân đoạn Chunking (`chunking.py`), Vector Store & Embedding (`embed.py`, `store.py`), Hybrid Search BM25 + Dense (`search.py`), Metadata filter `tier`. | `ed531d9`<br>`69dd5d8`<br>`b975579`<br>`0e0f6fc` |
| **Thành viên B** | Agent & Tool / MCP | Tool Schemas `@dataclass` (`schemas.py`), triển khai 5 Tool nghiệp vụ ghi/đọc SQLite (`impl.py`, `state.py`), MCP Server chuẩn stdio (`server.py`), Vòng lặp ReAct Loop (`loop.py`, `parse.py`), Bộ gọi LLM đa provider (`llm.py`), System Prompts (`prompts/*.txt`). | `6ccbdf1`<br>`84a69e7`<br>`d12f5cc`<br>`aae71ca` |
| **Thành viên C** | Đo lường & Tái lập | Xây dựng bộ Testset 12 câu (`testset.jsonl`), Pipeline đánh giá & Metrics (`metrics.py`, `run_eval.py`, `report.py`), MCP Client thứ hai (`client2.py`), Semantic Gate (`semantic_gate.py`), Staging Runner (`run_c4_staging.ps1`), Cấu hình Makefile, Ghép `report.docx`. | `8c77866`<br>`2a6cffb`<br>`86b144e`<br>`b9f09ba` |

### Bảng đối soát tài khoản Git trên Repository

Tính đến commit `580e4f3`, kho lưu trữ ghi nhận tổng cộng **69 commits** phân bổ theo các tài khoản Git:

| Tài khoản Git | Số lượng Commit | Vai trò tương ứng trong đồ án |
|---|:---:|---|
| **Do Ngo** | 38 commits | Thành viên B (Phát triển chính ReAct Loop, Tools, MCP Server và Decision Prompt) |
| **CapyCoder** | 13 commits | Thành viên A (Soạn thảo Corpus, RAG, Chunking, và tài liệu đặc tả) |
| **Penguin-cell34** | 11 commits | Thành viên C (Xây dựng Evaluator, Semantic Gate, Staging Runner, và sửa lỗi tích hợp) |
| **Do Coding** | 7 commits | Thành viên B (Tài khoản phụ hỗ trợ commit các module MCP và Tool schema) |
| **Tổng cộng** | **69 commits** | **Ghi chú bắt buộc:** Tài khoản `Do Ngo` và `Do Coding` thuộc cùng Thành viên B, đảm bảo dự án có đúng 3 thành viên thực hiện độc lập. |

---

## Bảng Checklist hoàn tất của Thành viên C (Verification Checklist)

- [x] **§6.1:** Bảng phân bố testset 12 câu đầy đủ, định nghĩa rõ ràng 2 dạng `no_answer` (Loại i ngoài phạm vi vs Loại ii thiếu dữ liệu), luận giải chi tiết lý do đo cặp Faithfulness & Refusal.
- [x] **§6.2:** Trình bày chính xác phương pháp đo lường so khớp chuỗi xác định (Deterministic Matching) khớp $100\%$ mã nguồn [`eval/metrics.py`](eval/metrics.py), kể cả metric `metadata_filter_usage`.
- [x] **§6.3:** Điền bảng kết quả 12 câu với đầy đủ thông số thực nghiệm lấy từ [`logs/staging_20261017_201308/reports/evaluation.csv`](logs/staging_20261017_201308/reports/evaluation.csv); bảng đã khớp từng ô với [`eval/reports/evaluation.csv`](eval/reports/evaluation.csv) sau khi cả hai được sinh lại từ cùng một JSONL bằng `--rescore`.
- [x] **§6.4:** Tính toán chính xác tổng chi phí: 192.688 Prompt Tokens, 9.647 Completion Tokens, 40 LLM Calls, Max Prompt 7.188 tokens (`q07`).
- [x] **§6.5:** Phân tích **hai** ca thất bại với **hai nguyên nhân khác nhau** dựa trên bằng chứng log thật: `q05` do redaction che marker tiền tệ (9 vị trí `[REDACTED]`), `q08` do so khớp chuỗi literal (0 vị trí `[REDACTED]`). Không đổ lỗi redaction cho `q08`.
- [x] **§6.6:** Báo cáo trung thực mức độ xác minh (Pass Semantic Gate, cách ly DB thành công, không bịa đặt môi trường production).
- [x] **§8:** Lập bảng commit hash thật từ lịch sử Git (`8c77866`, `6ccbdf1`, `ed531d9`...), ghi chú rõ ràng về 2 tài khoản commit của Thành viên B.
- [x] **Client thứ hai:** File [`src/trfc/mcp_server/client2.py`](src/trfc/mcp_server/client2.py) độc lập, chạy đạt 12/12 unit tests trong `test_client2.py`.
- [x] **Điểm cộng +1 Metadata Filter:** Bổ sung `expected_tier: 2` cho `q04`, thêm metric `metadata_filter_usage` vào `metrics.py`/`run_eval.py`/`report.py`, và đo được từ log trace thực tế (`staging_20261018_014623` → `False`, `staging_20261018_015357` → `True`).
- [x] **Đo lường bổ trợ LLM Judge:** Module `eval/llm_judge.py` + CLI `eval/run_judge.py` + 26 unit test trong `tests/test_llm_judge.py`; chạy song song với metric xác định, không ghi đè, và từ chối log còn `[REDACTED]`.
- [x] **Vệ sinh dữ liệu:** Đã rà lại toàn bộ ba file báo cáo; các TODO về số liệu dense-vs-hybrid (§3.5) và provider/model (§5) đã được thay bằng nội dung đúng thực tế. Mọi số liệu còn lại đều có căn cứ từ log thực nghiệm.
- [x] **Quy chuẩn trang:** Nội dung được căn chỉnh độ dài chặt chẽ, sẵn sàng để ghép vào văn bản `report.docx` đạt chuẩn 8–9 trang.
