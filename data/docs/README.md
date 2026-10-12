# Corpus — chủ sở hữu: A. Mốc: CP2.

Đủ ≥5 tài liệu, ≥10,000 token. Metadata mỗi doc: `doc_id`, `title`, `date/version`, `owner`.

| doc_id | Nội dung | Nguồn |
|---|---|---|
| DOC0001–0006 | Quy định an toàn giao dịch thanh toán | A viết mới |
| DOC0007 | Hạn mức giao dịch theo tầng eKYC — **BẢNG** | A viết mới |
| DOC0008 | Quy trình xử lý & khoá tài khoản rủi ro | A viết mới |
| DOC0009 | Danh mục phương thức thanh toán **trong** phạm vi | A viết mới |

⚠️ **DOC0001–0006 KHÔNG tái dùng được.** Yêu cầu §2.5 (`02-Yeu-cau-Thuc-hien.pdf`)
cho phép "tái dùng DOC0001–DOC0006 của lớp", nhưng bộ tài liệu lớp thực có trên đĩa
(`W8/data/data/01–07.txt`) là **Acme/Northwind**: remote work, IT helpdesk, procurement,
office directory, equipment catalog, security remote access — **không có một chữ nào về
thanh toán, eKYC hay AML**. Lấy nó làm corpus thì đề tài mất luôn tầng (b): không có
hạn mức, không có giao dịch, không có gì để tính hay đối chiếu.

⇒ Cả 9 tài liệu do A viết. Giữ đúng mã DOC0001–DOC0009 để khớp testset của C.

⚠️ Không dùng dữ liệu của nhóm khác cùng đề tài.

⚠️ DOC0009 không phải tài liệu cho có: thiếu nó thì **không dựng được ca
`no_answer` loại (i)** — hệ thống từ chối vì "ngoài phạm vi" sẽ không phân biệt
được với từ chối vì "retrieval trượt". Đây là rủi ro #2 trong DE_TAI_TRFC_Agent.md §10.

⚠️ DOC0007 chứa bảng hạn mức → phải atomic khi chunk (xem tests/test_chunking.py).

Định dạng: `.md`, mỗi file 1 document, frontmatter chứa metadata.
