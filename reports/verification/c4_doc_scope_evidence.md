# C4 — Đối chiếu DOC0006 / DOC0007 / DOC0009 với contract hiện tại

**Người thực hiện:** A (dữ liệu & RAG)
**Ngày:** 2026-10-14
**Commit đối chiếu:** `b9f09ba`
**Yêu cầu nguồn:** tin nhắn C — xác định điều kiện liên quan tới phạm vi phương thức
thanh toán, log giao dịch, tính đầy đủ / đồng bộ / lưu trữ; chỉ rõ điều khoản **có thật**
và hành vi mong đợi.

**Phạm vi:** đọc trực tiếp `data/docs/DOC0006.md`, `DOC0007.md`, `DOC0009.md` và đối chiếu
với `c4_runtime_integration_contract.md`, `c4_final_report.md`, `src/trfc/agent/policy.py`.
**Không sửa code, không tạo mã điều khoản mới, không kết luận loại từ chối i/ii ngoài
phần tài liệu đã quy định rõ.** Đây là rà soát nguồn, không phải bằng chứng runtime.

---

## 1. Bảng điều khoản có thật trong tài liệu

Cả ba tài liệu chỉ dùng "Điều N" / "Chương" — **không có "khoản" đánh số**. Các mã dạng
`DOC0009_ART05` là quy ước truy vết của nhóm, không phải ký hiệu trong văn bản.

| Document ID | Điều khoản | Điều kiện kích hoạt | Hành vi mong đợi | Bằng chứng trong tài liệu |
|---|---|---|---|---|
| DOC0009 | **Điều 3** | Mã phương thức khớp PM01–PM04 | Trong phạm vi → đối chiếu hạn mức: PM01/PM03/PM04 theo DOC0007 Đ4, PM02 theo DOC0007 Đ7 | Bảng Đ3: PM01 Chuyển khoản trong nước; PM02 Thẻ quốc tế; PM03 CK liên ngân hàng 24/7; PM04 Thanh toán hoá đơn định kỳ |
| DOC0009 | **Điều 1 + Điều 4** | Phương thức thuộc danh sách ngoài phạm vi (ví điện tử bên thứ ba, thẻ nội địa phát hành riêng, tiền mã hoá, trung gian không giấy phép, quốc tế không qua kênh thẻ) | Trả lời "không có thông tin", không suy diễn; không hạn mức, không tính, không kết luận → **loại (i)** | Đ1: *"phải được trả lời là không có thông tin, không được suy diễn"*; Đ2: *"không thể đối chiếu, không thể tính toán và không thể kết luận"*; Đ4 liệt kê danh sách |
| DOC0009 | **Điều 5** | Phương thức **không khớp bất kỳ mã nào** ở Đ3 | Báo "không xác định được phương thức"; **không gán mặc định PM01** → loại (i) | Đ5: *"không được gán mặc định vào PM01… tạo ra hạn mức sai và dẫn tới kết luận sai về rủi ro"* |
| DOC0009 | **Điều 6** | Giao dịch khớp nhiều mã | Thứ tự ưu tiên PM02 → PM04 → PM03 → PM01; thẻ quốc tế luôn dùng hạn mức riêng DOC0007 Đ7 | Đ6 |
| DOC0009 | **Điều 7** | Bản ghi giao dịch thiếu mã phương thức | Không dùng bản ghi đó để đối chiếu hạn mức | Đ7: *"Bản ghi thiếu mã phương thức không được dùng để đối chiếu hạn mức"* |
| DOC0006 | **Điều 4** | Xác định thời hạn lưu trữ | Nhật ký giao dịch gốc **5 năm**; nhật ký xác thực 2 năm; cảnh báo vượt hạn mức 90 ngày; hồ sơ rủi ro & quyết định khoá 5 năm; hồ sơ STR 10 năm (tính từ ngày ghi nhận / ngày hồ sơ đóng) | Bảng Đ4 |
| DOC0006 | **Điều 5** | Dữ liệu trung gian (bảng tổng hợp ngày, bảng đối chiếu hạn mức, kết quả đánh giá quy tắc) | Lưu 90 ngày; sau đó xoá nhưng phải tái tạo được từ nhật ký gốc nếu nhật ký còn hạn | Đ5 |
| DOC0006 | **Điều 7** | Nhật ký giao dịch gốc **đã hết hạn và bị xoá** | Không tính được tổng giá trị ngày / tỷ lệ vượt hạn mức / bất khả thi địa lý → *"không đủ dữ liệu để kết luận"*, không ước lượng, không suy diễn từ dữ liệu trung gian đã xoá → **loại (ii)** | Đ7 |
| DOC0006 | **Điều 12** | Dữ liệu **còn trong hạn** nhưng không truy xuất được do **lỗi đồng bộ** | Báo **lỗi kỹ thuật**, khôi phục từ bản sao lưu **trước khi kết luận**; *"không được coi lỗi đồng bộ là dữ liệu đã bị xoá"* | Đ12 |
| DOC0006 | **Điều 3** | Đính chính nhật ký | Bất biến: không sửa, không ghi đè; ghi bản ghi điều chỉnh tham chiếu bản ghi gốc | Đ3 |
| DOC0006 | **Điều 11** | Xung đột yêu cầu xoá vs yêu cầu tra soát trên cùng tập dữ liệu | Tra soát ưu tiên tới khi hồ sơ tra soát đóng; chỉ xoá sau khi hồ sơ đóng **và** dữ liệu đã hết hạn | Đ11 |
| DOC0007 | **Điều 4** | Giao dịch chuyển khoản trong nước | Hạn mức theo tầng: T1 100M/ngày – 20M/giao dịch; T2 500M – 100M; T3 2.000M – 500M. Vượt hạn mức mỗi giao dịch → từ chối **ngay cả khi tổng luỹ kế ngày còn dưới hạn mức ngày** | Bảng Đ4 + câu cuối Đ4 |
| DOC0007 | **Điều 7** | Giao dịch thẻ quốc tế | 50.000.000 VND/ngày cho **mọi tầng eKYC**, **không cộng dồn** vào hạn mức CK trong nước | Đ7 |
| DOC0007 | **Điều 9** | Cách tính hạn mức ngày | Tổng trong ngày dương lịch 00:00–23:59 giờ VN; giao dịch **bị từ chối không tính**; **hoàn tiền được trừ**; giao dịch **tạm giữ vẫn tính** tới khi có kết quả cuối | Đ9 |
| DOC0007 | **Điều 10** | Tính tỷ lệ vượt hạn mức | `(tổng ngày − hạn mức ngày) / hạn mức ngày × 100%`; ví dụ tầng 2 với 720M/500M → 44% | Đ10 |
| DOC0007 | **Điều 11** | Tổng ngày vượt hạn mức tầng | Từ chối giao dịch vượt + ghi cảnh báo; **không tự khoá** tài khoản (khoá do kiểm soát viên theo DOC0008); cảnh báo lưu ≥90 ngày | Đ11 |
| DOC0007 | **Điều 12** | Không truy xuất đủ danh sách giao dịch trong ngày (**log gốc đã xoá HOẶC lỗi đồng bộ**) | Không kết luận vượt/không vượt; báo thiếu dữ liệu, không suy diễn từ số liệu không đầy đủ → **loại (ii)** | Đ12 |

### Trả lời trực tiếp 3 mục C hỏi

1. **DOC0009 — phạm vi phương thức:** có thật. Danh mục **đóng** PM01–PM04 (Đ3); ngoài
   phạm vi liệt kê tại Đ4; không xác định tại Đ5. Điều kiện từ chối nằm ở **Đ1** (câu
   "không có thông tin") + **Đ4** (danh sách) + **Đ5** (không khớp mã nào). Đ7 chặn dùng
   bản ghi thiếu mã phương thức để đối chiếu hạn mức.
2. **DOC0006/DOC0007 — log giao dịch:** có thật, và **tách thành 3 tình huống khác nhau**:
   (a) thời hạn lưu trữ — DOC0006 Đ4/Đ5/Đ6; (b) log gốc đã xoá do hết hạn — DOC0006 Đ7,
   DOC0007 Đ12 → "không đủ dữ liệu"; (c) lỗi đồng bộ khi dữ liệu **còn hạn** — DOC0006
   Đ12 → "lỗi kỹ thuật, khôi phục trước khi kết luận".
3. **Mã điều/khoản:** xem cột "Điều khoản" ở bảng trên. Các mã `DOC0009_ARTxx` /
   `DOC0007_ART12` dùng trong contract là quy ước nội bộ của nhóm.

---

## 2. Bốn điểm lệch cần chốt trước khi B tích hợp và C viết test

### Lệch 1 — `DOC0009_ART05` đang bị gán sai ca

`c4_runtime_integration_contract.md:112` gán `policy_rule_id="DOC0009_ART05"` cho ca
*phương thức ngoài danh mục đã liệt kê*. Nhưng Điều 5 nói về ca **không khớp mã nào**
(chưa xác định được phương thức), còn câu *"phải được trả lời là không có thông tin"* nằm
ở **Điều 1**, danh sách ngoài phạm vi nằm ở **Điều 4**.

Đáng chú ý: `c4_final_report.md:394-395` lại ghi `DOC0009_ART4` cho cùng ca đó — **hai tài
liệu của nhóm đang ghi hai mã khác nhau**. Cần tách rõ:

| Ca | Điều khoản đúng |
|---|---|
| Phương thức ngoài phạm vi đã liệt kê | **Điều 4** (+ Điều 1 cho câu "không có thông tin") |
| Phương thức không khớp mã nào | **Điều 5** |

### Lệch 2 — Gộp "lỗi đồng bộ" vào loại (ii) là trái tài liệu

`c4_runtime_integration_contract.md:150` gộp `sync_status != "synchronized"` vào Refusal
Type `ii` với `DOC0007_ART12`. Tài liệu tách rõ hai hành vi khác nhau:

- **Đã xoá do hết hạn** → "không đủ dữ liệu để kết luận" (DOC0006 Đ7; DOC0007 Đ12).
- **Lỗi đồng bộ, dữ liệu còn hạn** → **"lỗi kỹ thuật"**, khôi phục từ sao lưu trước khi kết
  luận (DOC0006 Đ12), và *"không được coi lỗi đồng bộ là dữ liệu đã bị xoá"*.

Không nên map 1-1 cả hai vào cùng một loại từ chối. Nếu B cần một nhánh xử lý cho lỗi đồng
bộ thì phải là nhánh **riêng**, không phải loại (ii) — nhưng việc đó cần chốt với GV vì
hợp đồng đề tài chỉ định nghĩa hai loại (i)/(ii) (`DE_TAI_TRFC_Agent.md` §2, §7).

### Lệch 3 — Report khẳng định code emit rule ID, nhưng code không emit

`c4_final_report.md:394-396` viết code phát ra `DOC0009_ART3`, `DOC0009_ART4`,
`DOC0007_ART12`. Thực tế `src/trfc/agent/policy.py` **mọi nhánh đều trả
`policy_rule_id=None`** — chỉ có `status="needs_information"` và `reason_code`. Đây là mô
tả stale, và nó mâu thuẫn với chính `c4_policy_source_inventory.md` (ghi "No outcome,
subtype, rule ID, or decision source"). Cần sửa lại câu trong report; không sửa code.

### Lệch 4 — Quy ước mã điều khoản chưa thống nhất

`DOC0009_ARTxx` là quy ước truy vết do nhóm tự đặt, **không tồn tại trong văn bản**. Dùng
được, nhưng (a) đừng trình bày như mã có trong tài liệu, và (b) phải thống nhất **một** quy
ước cho cả contract / report / eval. Hiện `DOC0009_ART05` (contract) và `DOC0009_ART4`
(report) xung đột nhau.

---

## 3. Việc A đã xác nhận vs việc còn thiếu

| Hạng mục | Trạng thái |
|---|---|
| Nội dung DOC0006/0007/0009 có thật, đủ căn cứ cho phạm vi phương thức và xử lý log | **Đã xác nhận** — bảng §1 |
| Điều khoản nào áp cho ca nào (out-of-scope đã liệt kê vs không xác định) | **Cần chốt** — Lệch 1 |
| Lỗi đồng bộ có phải loại (ii) hay nhánh riêng | **Cần chốt** — Lệch 2 (cần GV xác nhận vì chỉ có 2 loại được định nghĩa) |
| Runtime có emit `policy_rule_id` / `actual_refusal_type` | **Chưa có** — code chỉ trả `needs_information`, mọi field quyết định là `None` |
| Bằng chứng chạy thật | **Chưa có** — ngoài phạm vi rà soát này |

Không có thiếu sót thực tế nào trong ba tài liệu cần bổ sung. Không sửa file nào ngoài
việc tạo tài liệu này.
