# ai-usage.md

> Bắt buộc nộp (yêu cầu §4). Không khai báo AI → **B = 0**.
> Điền khi làm, không phải viết lại cuối kỳ — git history phải khớp.

## Công cụ đã dùng

| Công cụ | Dùng cho phần nào |s
|---|---|
| Claude Code | Scaffold cấu trúc thư mục, viết docstring khung, rà yêu cầu học phần |
| Claude Code | Soạn 9 tài liệu corpus `data/docs/DOC0001–0009.md` từ đề cương do A chốt |
| Claude Code | Cài đặt `src/trfc/rag/chunking.py` + `tests/test_chunking.py` |
| Claude Code | Cài đặt `src/trfc/rag/embed.py` + `store.py` + `search.py` (port cách làm từ `W4/vector_store.py` + `W4/ex2_1_hybrid_search.py`) |

## Prompt chính

<!-- Dán prompt thật đã dùng, không tóm tắt -->

- "Đọc `DE_TAI_TRFC_Agent.md` §3 rồi viết 9 tài liệu corpus DOC0001–DOC0009 theo đúng metadata
  frontmatter và phân bố đã chốt. DOC0007 phải có bảng hạn mức atomic; DOC0003 phải là bản cũ
  đã bị thay thế; mỗi doc phải có một Điều nói rõ trường hợp không đủ dữ liệu."
- "Viết chunker cắt theo Chương→Điều→Khoản, gắn đường dẫn heading vào mỗi chunk, và giữ bảng
  markdown nguyên tử cùng dòng giới thiệu ngay trên bảng. `chunk_size`/`overlap` đọc từ
  `config.toml`, không hard-code."
- "Viết `search_policy` dense + hybrid theo đúng docstring khung: fuse `w_bm25 * BM25_norm +
  w_vector * cosine` với trọng số đọc từ `config.toml`; `tier` là PRE-FILTER trước khi rank chứ
  không lọc sau; không tìm thấy trả `[]` không trả `None`. Port cách làm từ `W4/vector_store.py`
  và `W4/ex2_1_hybrid_search.py` — file W4 nằm ngoài repo và là stub hỏng nên chỉ tham khảo."
- "Bảng hạn mức phải nguyên khối, mà `tier` là metadata mức dòng. Thiết kế cách pre-filter theo
  tầng mà không phá rule atomic và không làm hỏng `test_bang_dai_hon_chunk_size_van_khong_bi_cat`."

## Đoạn code do AI sinh

| File | Ghi chú |
|---|---|
| `src/trfc/rag/chunking.py` | AI viết; A đã đọc lại và sửa phần gộp dòng giới thiệu vào khối bảng |
| `src/trfc/rag/embed.py`, `store.py`, `search.py` | AI viết theo docstring khung của A; **A chốt thiết kế pre-filter theo tầng bằng "view 1 tầng"** (không doc nào có `tier:` trong frontmatter) |
| `tests/test_chunking.py` | AI viết khung; A thêm ca bảng 39 dòng vượt `chunk_size` |
| `data/docs/DOC0001–0009.md` | AI soạn văn bản theo đề cương; **số liệu và quan hệ giữa các doc do A chốt** |
| `Makefile`, `pyproject.toml`, `.env.example`, `config.toml` | AI viết |

## Phần tự viết

<!-- Logic chunking, agent loop, MCP server — nêu rõ ai viết, vì đây là phần bị hỏi nặng nhất -->

- **A**: cấu trúc corpus (doc nào chứa gì, doc nào mâu thuẫn doc nào), chọn `chunk_size=400`,
  ràng buộc bảng atomic, thiết kế "view 1 tầng" cho pre-filter `tier`, `src/trfc/rag/embed.py` +
  `store.py` + `search.py`.
- **B**: tool schema, agent loop, MCP server (chưa viết).
- **C**: testset, eval, log (chưa viết).

⚠️ Mọi dòng AI sinh đều phải giải thích được khi vấn đáp — không giải thích được thì B = 0.
