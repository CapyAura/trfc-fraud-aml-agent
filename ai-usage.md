# ai-usage.md

> Bắt buộc nộp (yêu cầu §4). Không khai báo AI → **B = 0**.
> Điền khi làm, không phải viết lại cuối kỳ — git history phải khớp.

## Công cụ đã dùng

| Công cụ | Dùng cho phần nào |
|---|---|
| Claude Code | Scaffold cấu trúc thư mục, viết docstring khung, rà yêu cầu học phần |
| Claude Code | Soạn 9 tài liệu corpus `data/docs/DOC0001–0009.md` từ đề cương do A chốt |
| Claude Code | Cài đặt `src/trfc/rag/chunking.py` + `tests/test_chunking.py` |
| | |

## Prompt chính

<!-- Dán prompt thật đã dùng, không tóm tắt -->

- "Đọc `DE_TAI_TRFC_Agent.md` §3 rồi viết 9 tài liệu corpus DOC0001–DOC0009 theo đúng metadata
  frontmatter và phân bố đã chốt. DOC0007 phải có bảng hạn mức atomic; DOC0003 phải là bản cũ
  đã bị thay thế; mỗi doc phải có một Điều nói rõ trường hợp không đủ dữ liệu."
- "Viết chunker cắt theo Chương→Điều→Khoản, gắn đường dẫn heading vào mỗi chunk, và giữ bảng
  markdown nguyên tử cùng dòng giới thiệu ngay trên bảng. `chunk_size`/`overlap` đọc từ
  `config.toml`, không hard-code."

## Đoạn code do AI sinh

| File | Ghi chú |
|---|---|
| `src/trfc/rag/chunking.py` | AI viết; A đã đọc lại và sửa phần gộp dòng giới thiệu vào khối bảng |
| `tests/test_chunking.py` | AI viết khung; A thêm ca bảng 39 dòng vượt `chunk_size` |
| `data/docs/DOC0001–0009.md` | AI soạn văn bản theo đề cương; **số liệu và quan hệ giữa các doc do A chốt** |
| `Makefile`, `pyproject.toml`, `.env.example`, `config.toml` | AI viết |

## Phần tự viết

<!-- Logic chunking, agent loop, MCP server — nêu rõ ai viết, vì đây là phần bị hỏi nặng nhất -->

- **A**: cấu trúc corpus (doc nào chứa gì, doc nào mâu thuẫn doc nào), chọn `chunk_size=400`,
  ràng buộc bảng atomic, `src/trfc/rag/embed.py` + `store.py` + `search.py` (chưa viết).
- **B**: tool schema, agent loop, MCP server (chưa viết).
- **C**: testset, eval, log (chưa viết).

⚠️ Mọi dòng AI sinh đều phải giải thích được khi vấn đáp — không giải thích được thì B = 0.
