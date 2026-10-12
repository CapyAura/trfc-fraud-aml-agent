# Corpus — chủ sở hữu: A. Mốc: CP2.

Đủ ≥5 tài liệu, ≥10,000 token. Metadata mỗi doc: `doc_id`, `title`, `date/version`, `owner`.

| doc_id | Nội dung | Nguồn |
|---|---|---|
| DOC0001–0006 | Quy định an toàn giao dịch thanh toán | **Tái dùng của lớp** (được phép) |
| DOC0007 | Hạn mức giao dịch theo tầng eKYC — **BẢNG** | A viết mới |
| DOC0008 | Quy trình xử lý & khoá tài khoản rủi ro | A viết mới |
| DOC0009 | Danh mục phương thức thanh toán **trong** phạm vi | A viết mới |

⚠️ Không dùng dữ liệu của nhóm khác cùng đề tài.

⚠️ DOC0009 không phải tài liệu cho có: thiếu nó thì **không dựng được ca
`no_answer` loại (i)** — hệ thống từ chối vì "ngoài phạm vi" sẽ không phân biệt
được với từ chối vì "retrieval trượt". Đây là rủi ro #2 trong DE_TAI_TRFC_Agent.md §10.

⚠️ DOC0007 chứa bảng hạn mức → phải atomic khi chunk (xem tests/test_chunking.py).

Định dạng: `.md`, mỗi file 1 document, frontmatter chứa metadata.
