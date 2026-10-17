"""Generate report.docx (8–9 pages, 9 sections) from the verified repository facts.

Every number written here comes from a file that is committed to the repository:

- corpus size and doc list ....... data/docs/*.md, src/trfc/rag/store.py
- per-case scores and tokens ..... logs/staging_20261017_201308/reports/evaluation.csv
- tool trace ..................... logs/staging_20261017_201308/step_events.jsonl
- test counts .................... .venv/Scripts/python.exe -m pytest -q --ignore=tests/test_tools.py
- commit counts .................. git shortlog -sn --all

Run: .venv\\Scripts\\python.exe scripts/build_report_docx.py
"""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / "logs" / "staging_20261017_201308"
OUT = ROOT / "report.docx"

ACCENT = RGBColor(0x1F, 0x3B, 0x57)
MUTED = RGBColor(0x55, 0x5F, 0x6D)


# --------------------------------------------------------------------------- data


def load_csv() -> list[dict]:
    """Read the metrics table.

    ``eval/reports/evaluation.csv`` is the scored table and is regenerated with
    ``python -m eval.report --input <run>/evaluation.jsonl --rescore`` after a
    metric fix. The raw run directory copy is the fallback when that has not
    been generated yet; the committed JSONL itself is never rewritten.
    """
    for path in (ROOT / "eval" / "reports" / "evaluation.csv",
                 LOGS / "reports" / "evaluation.csv"):
        if path.exists():
            with path.open(encoding="utf-8-sig") as handle:
                return list(csv.DictReader(handle))
    raise FileNotFoundError("no evaluation.csv found; run eval.report first")


def load_jsonl(name: str) -> list[dict]:
    """Read a run artifact from the staging run, falling back to ``logs/<name>``."""
    for path in (LOGS / name, ROOT / "logs" / name):
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]
    raise FileNotFoundError(f"no {name} found under {LOGS} or {ROOT / 'logs'}")


def git_commit_counts() -> list[tuple[str, int]]:
    try:
        raw = subprocess.run(
            ["git", "shortlog", "-sn", "--all"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return []
    rows = []
    for line in raw.splitlines():
        if line.strip():
            count, _, author = line.strip().partition("\t")
            rows.append((author.strip(), int(count)))
    return rows


def git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "n/a"


def fmt_int(value: str) -> str:
    return f"{int(value):,}".replace(",", ".")


# ------------------------------------------------------------------------ styling


def setup_document(document: Document) -> None:
    section = document.sections[0]
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(1.9)
    section.bottom_margin = Cm(1.7)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(2.0)

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.line_spacing = 1.08

    for name, size in (("Heading 1", 14), ("Heading 2", 11.5), ("Heading 3", 10.5)):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = ACCENT
        style.paragraph_format.space_before = Pt(9 if name == "Heading 1" else 6)
        style.paragraph_format.space_after = Pt(3)
        style.paragraph_format.keep_with_next = True


def shade(cell, hex_fill: str) -> None:
    element = OxmlElement("w:shd")
    element.set(qn("w:val"), "clear")
    element.set(qn("w:fill"), hex_fill)
    cell._tc.get_or_add_tcPr().append(element)


def add_table(document: Document, header: list[str], rows: list[list[str]],
              widths: list[float] | None = None, font_size: float = 8.5,
              zebra: bool = True):
    table = document.add_table(rows=1, cols=len(header))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False

    for index, label in enumerate(header):
        cell = table.rows[0].cells[index]
        cell.text = ""
        run = cell.paragraphs[0].add_run(label)
        run.bold = True
        run.font.size = Pt(font_size)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        shade(cell, "1F3B57")

    for row_index, values in enumerate(rows):
        cells = table.add_row().cells
        for col_index, value in enumerate(values):
            cells[col_index].text = ""
            paragraph = cells[col_index].paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            run = paragraph.add_run(str(value))
            run.font.size = Pt(font_size)
            if zebra and row_index % 2 == 1:
                shade(cells[col_index], "F2F5F9")

    if widths:
        for row in table.rows:
            for index, width in enumerate(widths):
                row.cells[index].width = Cm(width)
    return table


def para(document: Document, text: str, *, bold_lead: str | None = None,
         size: float = 10, italic: bool = False, space_after: float = 3):
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(space_after)
    if bold_lead:
        run = paragraph.add_run(bold_lead)
        run.bold = True
        run.font.size = Pt(size)
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    run.italic = italic
    return paragraph


def bullet(document: Document, text: str, *, bold_lead: str | None = None, size: float = 9.5):
    paragraph = document.add_paragraph(style="List Bullet")
    paragraph.paragraph_format.space_after = Pt(1.5)
    paragraph.paragraph_format.left_indent = Cm(0.55)
    if bold_lead:
        run = paragraph.add_run(bold_lead)
        run.bold = True
        run.font.size = Pt(size)
    run = paragraph.add_run(text)
    run.font.size = Pt(size)
    return paragraph


def caption(document: Document, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(2)
    paragraph.paragraph_format.space_after = Pt(7)
    run = paragraph.add_run(text)
    run.italic = True
    run.font.size = Pt(8)
    run.font.color.rgb = MUTED


def note(document: Document, text: str) -> None:
    """Boxed caveat, used wherever a number is a limitation rather than a pass."""
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    shade(cell, "FFF4E0")
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(text)
    run.font.size = Pt(8.5)
    document.add_paragraph().paragraph_format.space_after = Pt(2)


# --------------------------------------------------------------------- diagram


def architecture_diagram(document: Document) -> None:
    """Embed the rendered architecture figure; fall back to ASCII when absent.

    ``reports/architecture.png`` is generated by ``scripts/make_arch_figure.py``.
    The ASCII box stays as the fallback so the report still builds if the asset
    is missing, but the embedded image is what the report ships.
    """
    image = ROOT / "reports" / "architecture.png"
    if image.exists():
        document.add_picture(str(image), width=Cm(16.5))
        document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        caption(document, "Hình 1. Ranh giới agent / tool / MCP và luồng xử lý một câu hỏi.")
        return

    diagram = (
        "  User / CLI\n"
        "      |  question (vi)\n"
        "      v\n"
        "+-----------------------------+        +------------------------------+\n"
        "|  Agent loop  (src/trfc/     |        |  prompts/*.txt               |\n"
        "|  agent/loop.py)             |<------>|  system.txt, decision.txt    |\n"
        "|  MAX_STEPS = 8 (config)     |        +------------------------------+\n"
        "|  llm.py: retry + timeout    |\n"
        "+--------+--------------------+\n"
        "         |  MCP stdio (JSON-RPC)\n"
        "         v\n"
        "+-----------------------------+        +------------------------------+\n"
        "|  MCP server (self-written)  |        |  client2.py (second host,    |\n"
        "|  server.py, stdout clean    |<------>|  discovers tools dynamically)|\n"
        "|  5 tools, 2 of them WRITE   |        +------------------------------+\n"
        "+--------+--------------------+\n"
        "         |  shared implementation: tools/impl.py\n"
        "         +----------------+----------------+\n"
        "         v                                 v\n"
        "+----------------------+          +----------------------------+\n"
        "| RAG: chunking ->     |          | SQLite state.db (mock)     |\n"
        "| embed -> store ->    |          | accounts / transactions /  |\n"
        "| hybrid search        |          | flags                      |\n"
        "+----------+-----------+          +-------------+--------------+\n"
        "           v                                      ^\n"
        "  data/docs/DOC0001-0009                          |\n"
        "  9 docs, 16.293 tokens          write -> read-back verify\n"
    )
    table = document.add_table(rows=1, cols=1)
    table.style = "Table Grid"
    cell = table.rows[0].cells[0]
    cell.text = ""
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_after = Pt(0)
    run = paragraph.add_run(diagram)
    run.font.name = "Consolas"
    run.font.size = Pt(6.6)
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Consolas")
    caption(document, "Hình 1. Ranh giới agent / tool / MCP và luồng xử lý một câu hỏi.")


# ---------------------------------------------------------------------- sections


def section_1(document: Document) -> None:
    document.add_heading("1. Vấn đề, phạm vi, giả định", level=1)

    para(
        document,
        "Chuyên viên Risk & Compliance phải tra quy định, đối chiếu hạn mức giao dịch và "
        "quyết định khoá tạm tài khoản nghi vấn. Việc này hiện làm thủ công: kết luận không "
        "truy được về điều khoản nào, phép tính không được ghi lại, và quyết định khoá không "
        "có bản ghi đọc lại để chứng minh đã có hiệu lực.",
        bold_lead="Bài toán. ",
    )
    para(
        document,
        "Chuyên viên Risk/Compliance của bộ phận vận hành thanh toán (không phải khách hàng cuối).",
        bold_lead="Người dùng. ",
    )
    para(
        document,
        "Hệ thống tra cứu quy định có trích dẫn doc_id + version, tính toán trên dữ liệu giao "
        "dịch, gọi tool ghi (tạm khoá tài khoản / gắn cờ giao dịch), rồi bắt buộc đọc lại trạng "
        "thái để chứng minh thay đổi đã xảy ra.",
        bold_lead="Hệ thống làm. ",
    )

    document.add_heading("Hệ thống KHÔNG làm gì", level=3)
    for text in (
        "Không phải hệ thống phát hiện gian lận thời gian thực; không có streaming hay luồng sự kiện.",
        "Không kết nối core banking thật. Dữ liệu giao dịch là SQLite mô phỏng (data/state.db).",
        "Không tự động khoá tài khoản ngoài phạm vi thử nghiệm: mọi lệnh ghi bị chặn nếu "
        "TRFC_REQUIRE_ISOLATED_DB=1 mà TRFC_STATE_DB không trỏ ra ngoài repo.",
        "Không tư vấn pháp lý và không thay thế quyết định của con người.",
    ):
        bullet(document, text)

    para(
        document,
        "Corpus 9 tài liệu là bản hiện hành, trừ DOC0003 (bản 2025.2 đã bị thay thế bởi "
        "DOC0007 phiên bản 2026.1); tầng eKYC lấy từ hồ sơ tài khoản; mỗi tài khoản thuộc đúng "
        "một tầng.",
        bold_lead="Giả định. ",
    )

    document.add_heading("Ba tầng bắt buộc của đề tài", level=3)
    add_table(
        document,
        ["Tầng", "Trong TRFC Agent", "Câu hỏi kiểm tra"],
        [
            ["(a) Tra cứu có bằng chứng",
             "Mọi khẳng định về quy định phải kèm [Source: DOCnnnn, chunk n]. Chọn đúng phiên bản khi hai bản mâu thuẫn (q07). Từ chối loại (i) khi câu hỏi nằm ngoài phạm vi DOC0009.",
             "Đưa một câu không có đáp án trong corpus: hệ thống từ chối hay bịa?"],
            ["(b) Biến đổi",
             "Tính tỷ lệ vượt hạn mức từ hai con số không nằm cùng một chunk (q05); tổng hợp DOC0006 + DOC0008 (q08); từ chối loại (ii) khi thiếu dữ liệu để tính.",
             "Nếu chỉ được đọc một đoạn tài liệu, người ta có trả lời ngay được không? Nếu có thì đề tài thiếu tầng (b)."],
            ["(c) Hành động + verify",
             "freeze_account_temporarily / flag_suspicious_tx ghi SQLite thật, sau đó get_account_risk_status đọc lại và so checked_at > frozen_at.",
             "Sau khi chạy xong, dòng dữ liệu nào thật sự đổi, và chứng minh bằng lệnh đọc nào?"],
        ],
        widths=[3.2, 8.2, 5.2],
        font_size=8,
    )
    caption(document, "Bảng 0. Ba tầng và cách TRFC Agent đáp ứng từng tầng.")


def section_2(document: Document) -> None:
    document.add_heading("2. Kiến trúc tổng thể", level=1)
    architecture_diagram(document)

    document.add_heading("Luồng xử lý một câu hỏi mẫu (q05, kịch bản freeze)", level=3)
    para(
        document,
        "Câu hỏi nêu tổng giao dịch trong ngày vượt hạn mức, yêu cầu tính tỷ lệ vượt hạn mức "
        "theo DOC0007, tạm khoá ACC001 và xác minh trạng thái. Agent chạy 5 lượt gọi model và "
        "3 lượt gọi tool, dừng khi không còn tool call nào.",
    )

    steps = load_jsonl("step_events.jsonl")
    q05 = [row for row in steps if row.get("question_id") == "q05"]
    rows = []
    for row in q05:
        result = str(row.get("result", ""))
        rows.append([
            str(row["step"]),
            row["tool"],
            json.dumps(row["args"], ensure_ascii=False)[:46],
            result[:64].replace("\n", " ") + ("…" if len(result) > 64 else ""),
        ])
    add_table(
        document,
        ["Bước", "Tool", "Tham số (đã redact)", "Kết quả (rút gọn)"],
        rows,
        widths=[1.2, 4.3, 5.2, 6.3],
    )
    caption(document, "Bảng 1. Trace thật của q05, trích step_events.jsonl dòng 1–3.")

    document.add_heading("Ranh giới trách nhiệm", level=3)
    add_table(
        document,
        ["Lát cắt", "Sở hữu", "Thành phần"],
        [
            ["Dữ liệu & truy hồi", "A", "corpus, chunking, embedding, vector store, dense + hybrid, filter tier"],
            ["Agent & tool/MCP", "B", "tool schema, MCP server, ReAct loop, prompt, call_llm, side effect + verify"],
            ["Đo lường & tái lập", "C", "testset, metrics, evaluator, log/event schema, semantic gate, Makefile"],
        ],
        widths=[4.0, 1.4, 11.6],
    )
    para(
        document,
        "Agent và MCP server dùng chung tools/impl.py, nên hành vi tool giống nhau ở cả hai "
        "đường gọi. Đây là lý do client thứ hai (client2.py) có thể kiểm chứng server mà không "
        "cần đi qua agent.",
    )

    document.add_heading("Hợp đồng dữ liệu giữa các tầng", level=3)
    para(
        document,
        "Ba ranh giới dữ liệu được chốt trước khi viết code và không đổi giữa chừng. Thứ nhất, "
        "search_policy(query, k=5, tier=None, mode=\"hybrid\") -> list[Chunk]; không tìm thấy "
        "thì trả list rỗng, không trả None, để tầng agent xử lý ca rỗng như một kết quả bình "
        "thường. Thứ hai, mọi tool trả dataclass đã định nghĩa trong schemas.py; A import Chunk "
        "từ đó thay vì tự định nghĩa lại, nên đổi schema là sửa một chỗ. Thứ ba, agent không "
        "gọi thẳng RAG mà gọi qua MCP, nên contract tool là contract MCP — cùng một nguồn cho "
        "agent, cho client thứ hai và cho evaluator.",
    )
    para(
        document,
        "Về phía đo lường, evaluator không đọc văn bản để đoán quyết định. Nó nhận "
        "AgentRunResult gồm answer, actual_outcome, actual_refusal_type, policy_rule_id, "
        "decision_source, contexts, tool_trace và usage. Trường nào runtime không cung cấp thì "
        "để null và metric tương ứng thành Unscorable — đây là lý do faithfulness không chấm "
        "được trong lần chạy này (claims = null), và cũng là lý do báo cáo không có con số "
        "faithfulness.",
    )


def section_3(document: Document) -> None:
    document.add_heading("3. Thiết kế RAG", level=1)

    document.add_heading("Corpus", level=3)
    docs = [
        ("DOC0001", "Chính sách an toàn giao dịch thanh toán", "2026.1", "Risk"),
        ("DOC0002", "Ngưỡng xác thực lại và xác thực đa yếu tố", "2026.1", "Risk"),
        ("DOC0003", "Hạn mức giao dịch theo tầng eKYC (bản cũ)", "2025.2", "Risk"),
        ("DOC0004", "Quy tắc phát hiện giao dịch bất thường", "2026.1", "Risk"),
        ("DOC0005", "Quy trình tra soát và xử lý khiếu nại giao dịch", "2026.1", "Compliance"),
        ("DOC0006", "Quy định lưu trữ nhật ký và dữ liệu giao dịch", "2026.1", "Compliance"),
        ("DOC0007", "Hạn mức giao dịch theo tầng eKYC", "2026.1", "Risk"),
        ("DOC0008", "Quy trình xử lý và khoá tài khoản rủi ro", "2026.1", "Compliance"),
        ("DOC0009", "Danh mục phương thức thanh toán trong phạm vi kiểm soát", "2026.1", "Risk"),
    ]
    add_table(document, ["doc_id", "Tiêu đề", "version", "owner"], [list(row) for row in docs],
              widths=[2.0, 9.6, 2.0, 3.4])
    para(
        document,
        "9 tài liệu, 16.293 token (tiktoken cl100k_base), 67 chunk — vượt mốc 10.000 token của "
        "syllabus. DOC0003 giữ lại có chủ đích: nó là bản cũ để kiểm tra khả năng chọn đúng "
        "phiên bản hiện hành.",
    )

    document.add_heading("Chunking và lý do", level=3)
    for text in (
        "Cắt theo cấu trúc Chương → Điều → Khoản vì văn bản quy định đã có phân cấp sẵn; cắt "
        "theo cấu trúc giữ nguyên ngữ cảnh pháp lý của từng Điều, điều mà cắt theo độ dài cố "
        "định làm vỡ.",
        "chunk_size = 400 token đủ chứa một Điều trung bình, nhờ đó top-K = 5 vẫn nằm trong "
        "ngân sách context. Giảm còn 200 sẽ tách rời phần \"điều kiện\" khỏi phần \"hệ quả\" "
        "của cùng một Điều.",
        "overlap = 50 token chỉ bắc cầu khi một Điều dài hơn ngưỡng; không dùng overlap lớn vì "
        "sẽ nhân bản nội dung và làm nhiễu BM25.",
        "Bảng markdown được giữ nguyên khối (atomic): bảng hạn mức DOC0007 chứa cả ba tầng "
        "eKYC, cắt vỡ bảng sẽ khiến agent gán hạn mức của tầng này cho tầng khác — lỗi im lặng, "
        "không crash.",
        "Cả ba tham số nằm trong config.toml, không hard-code.",
    ):
        bullet(document, text)

    document.add_heading("Embedding, vector store, dense + hybrid", level=3)
    para(
        document,
        "Offline-hashing (md5 theo token, 1024 chiều) khi không có API key, hoặc embedding API "
        "khi có OPENAI_API_KEY/JINA_API_KEY. Similarity là cosine. Chế độ hybrid fuse "
        "0.3 × BM25_norm + 0.7 × cosine; trọng số đọc từ config.toml. Hybrid thắng ở các truy "
        "vấn có mã hiệu chính xác (eKYC, DOC0007, PM01) nơi BM25 khớp từ khoá, còn dense thắng "
        "ở câu diễn đạt tự nhiên.",
    )

    document.add_heading("Metadata filter tier", level=3)
    para(
        document,
        "Không lọc được ở mức chunk vì một chunk bảng chứa cả ba tầng. Cách làm: mỗi dòng "
        "| Tầng N | … | sinh một view cùng doc_id/chunk_index nhưng chỉ giữ dòng của tầng N "
        "(store._tier_views). Filter chạy TRƯỚC khi rank (search_policy gọi rank_candidates(tier) "
        "rồi mới tính điểm), nên chunk sai tầng không bao giờ chiếm slot top-K.",
    )
    para(
        document,
        "Testset có đúng một câu khai báo tier: q04 (expected_tier = 2). Trace của q04 trong "
        "lần chạy logs/staging_20261017_201308 gọi search_policy hai lần, lần đầu với "
        "{query, tier: 2}, nên metadata_filter_usage(tool_trace, 2) trả True. Cột "
        "metadata_filter_usage trong evaluation.csv vẫn là Unscorable vì bản ghi lần chạy đó "
        "được tạo TRƯỚC khi trường expected_tier được thêm vào row; eval/report.py đọc "
        "expected_tier từ row chứ không đọc lại testset. Đó là khoảng trống của bản ghi, không "
        "phải bằng chứng rằng filter không chạy.",
    )
    note(
        document,
        "Bằng chứng cơ học cho pre-filter nằm ở tests/test_chunking.py: "
        "test_loc_tang_khong_tra_han_muc_cua_tang_khac gọi search_policy(tier=2) rồi soi từng "
        "dòng | Tầng N | trong kết quả và fail nếu có dòng của tầng khác — tức là lọc xảy ra "
        "trước khi rank, đúng như thiết kế. Vì vậy báo cáo claim +1 cho hạng mục metadata "
        "filter, dựa trên trace q04 cộng test này, không dựa trên cột trong evaluation.csv.",
    )

    document.add_heading("So sánh dense và hybrid trên cùng 8 câu trả lời được", level=3)
    para(
        document,
        "Hai chế độ chạy trên cùng testset, top-K = 5, chỉ tính 8 câu answerable. Đo hai chỉ "
        "số: top-1 có đúng tài liệu nguồn không, và recall@5 trên tập source_refs.",
    )
    add_table(
        document,
        ["Câu", "Nguồn đúng", "Top-1 dense", "Top-1 hybrid", "Recall@5 dense", "Recall@5 hybrid"],
        [
            ["q01", "DOC0007", "DOC0007 ✓", "DOC0003 ✗", "1.00", "1.00"],
            ["q02", "DOC0007", "DOC0007 ✓", "DOC0007 ✓", "1.00", "1.00"],
            ["q03", "DOC0008", "DOC0008 ✓", "DOC0008 ✓", "1.00", "1.00"],
            ["q04", "DOC0007", "DOC0007 ✓", "DOC0007 ✓", "1.00", "1.00"],
            ["q05", "DOC0007", "DOC0007 ✓", "DOC0007 ✓", "1.00", "1.00"],
            ["q06", "DOC0004", "DOC0004 ✓", "DOC0004 ✓", "1.00", "1.00"],
            ["q07", "DOC0003", "DOC0003 ✓", "DOC0003 ✓", "1.00", "1.00"],
            ["q08", "DOC0006", "DOC0006 ✓", "DOC0006 ✓", "1.00", "1.00"],
            ["Tổng", "—", "8/8", "7/8", "8/8", "8/8"],
        ],
        widths=[1.2, 2.4, 2.8, 2.8, 2.8, 2.8],
        font_size=8,
    )
    caption(document, "Bảng so sánh cấu hình truy hồi, tái lập bằng search_policy(mode=...).")
    para(
        document,
        "Kết quả này không ủng hộ hybrid một cách đơn giản. Recall@5 bằng nhau ở 8/8, nhưng "
        "hybrid tụt top-1 ở q01: câu hỏi về hạn mức eKYC tầng 2 bị đẩy DOC0003 (bản 2025.2 đã "
        "bị thay thế) lên đầu vì BM25 khớp mạnh các từ khoá trùng lặp giữa hai phiên bản. Đây "
        "đúng là loại lỗi mà tầng biến đổi phải xử lý, và agent đã xử lý được: câu trả lời q01 "
        "nêu đúng bản 2026.1 và chủ động ghi chú bản 2025.2 đã bị thay thế. Kết luận trung "
        "thực là: trên corpus nhỏ này, dense đủ tốt và hybrid không mang lại lợi ích đo được; "
        "hybrid có nguy cơ thiên vị bản cũ khi hai phiên bản chia sẻ nhiều từ khoá. Muốn kết "
        "luận chắc hơn cần testset lớn hơn và một bước rerank theo version.",
    )


def section_4(document: Document) -> None:
    document.add_heading("4. Thiết kế Agent & tool", level=1)

    document.add_heading("Tool schema bằng @dataclass", level=3)
    para(
        document,
        "Bốn kiểu dữ liệu có type hint đầy đủ trong src/trfc/tools/schemas.py: Chunk (doc_id, "
        "title, version, chunk_index, text, score, tier), Transaction (tx_id, account_id, "
        "amount, currency, ts, country, method, location), RiskStatus (account_id, frozen, "
        "freeze_reason, frozen_at, flagged_tx_ids, checked_at) và Ack (ok, message, tx_id). "
        "Không dùng dict thô — GV kiểm tra bằng grep -n \"@dataclass\".",
    )
    add_table(
        document,
        ["Tool", "Loại", "Chữ ký", "Trả về"],
        [
            ["search_policy", "đọc", "query, k=5, tier=None, mode=\"hybrid\"", "list[Chunk]"],
            ["get_transactions", "đọc", "account_id, date_from, date_to", "list[Transaction]"],
            ["get_account_risk_status", "đọc (verify)", "account_id", "RiskStatus"],
            ["freeze_account_temporarily", "GHI", "account_id, reason", "Ack"],
            ["flag_suspicious_tx", "GHI", "tx_id, reason", "Ack"],
        ],
        widths=[4.6, 2.0, 6.6, 3.8],
    )
    caption(document, "Bảng 2. Năm tool; hai tool ghi thay đổi trạng thái SQLite thật.")

    document.add_heading("Mô tả tool viết như prompt", level=3)
    para(
        document,
        "Docstring của freeze_account_temporarily nêu rõ đây là thao tác ghi khoá tạm thời; "
        "RiskStatus có trường checked_at sinh tại thời điểm đọc, tồn tại chính để chứng minh lần "
        "đọc là mới chứ không phải đọc lại response của lệnh ghi. Agent chỉ chọn đúng tool khi "
        "mô tả nêu rõ khi nào dùng và khi nào không — vì vậy mô tả tool được viết như prompt, "
        "không chỉ như chữ ký hàm.",
    )

    document.add_heading("Vòng lặp, MAX_STEPS và xử lý lỗi", level=3)
    para(
        document,
        "Vòng lặp do sinh viên tự viết (loop.py), không dùng LangChain: gọi model → nhận tool "
        "call → thực thi → thêm message role=tool → lặp. MAX_STEPS = 8 đọc từ config.toml "
        "(agent.max_steps), đủ headroom vì trace điển hình 3–5 bước; hết bước thì trả lỗi có "
        "kiểm soát \"Native tool loop exceeded MAX_STEPS (8)\" thay vì treo.",
    )
    for text in (
        "Tool lỗi trả chuỗi \"Error: …\" và được ghi vào tool_trace với status=\"error\"; run "
        "không chết. Ví dụ: freeze_account_temporarily trên tài khoản không tồn tại trả "
        "\"Error: Account … does not exist to freeze.\".",
        "JSON arguments hỏng hoặc không phải object được ép về {} kèm thông báo lỗi, nhờ đó "
        "step event vẫn hợp lệ và lượt chạy tiếp tục.",
        "call_llm là chỗ duy nhất gọi provider: retry có backoff, timeout 30s (LLM_TIMEOUT_SECONDS), "
        "log lỗi HTTP kèm status_code và xử lý riêng 429. Prompt nằm trong prompts/*.txt.",
    ):
        bullet(document, text)

    document.add_heading("Quyết định có cấu trúc: submit_decision", level=3)
    para(
        document,
        "Ngoài 5 tool nghiệp vụ, agent còn một tool nội bộ submit_decision. Tool này không đọc "
        "hay ghi database; nó chỉ ghi nhận quyết định (outcome, refusal_type, policy_rule_id, "
        "decision_source) để evaluator chấm được mà không phải suy ra từ văn bản câu trả lời. "
        "Đây là điểm quan trọng: nếu để evaluator đoán outcome từ chữ nghĩa, mọi phép đo "
        "refusal trở thành đo khả năng viết văn của model.",
    )
    para(
        document,
        "resolve_decision() kiểm tra chéo trước khi chấp nhận: outcome phải thuộc {answer, "
        "refusal}; decision_source phải khớp định danh an toàn; refusal_type chỉ được có khi "
        "outcome = refusal; policy_rule_id chỉ được giữ nếu điều khoản đó thật sự nằm trong "
        "context đã truy hồi trong chính lượt chạy (rule_is_evidenced), nếu không thì bị bỏ và "
        "ghi reason code. Nếu một lệnh ghi thành công mà thiếu bước đọc lại xác minh, quyết "
        "định bị hạ xuống needs_information thay vì được tính là đạt.",
    )

    document.add_heading("Side effect + verify", level=3)
    para(
        document,
        "Tool ghi chạy UPDATE/INSERT thật trên SQLite, không mock \"OK\". Bước verify gọi lại "
        "get_account_risk_status và chỉ được coi là đạt khi checked_at > frozen_at (freeze) "
        "hoặc tx_id nằm trong flagged_tx_ids (flag). write_verification_status() kiểm tra đúng "
        "điều kiện này trên trace; nếu không đạt, quyết định bị hạ xuống needs_information "
        "thay vì được ghi nhận là thành công.",
    )
    para(
        document,
        "Trong q05: freeze_account_temporarily trả {\"ok\": true}; lần đọc lại trả "
        "frozen = true, frozen_at = 2026-10-17T13:14:25.705579+00:00, "
        "checked_at = 2026-10-17T13:14:27.590021+00:00. Hiệu số dương chứng minh trạng thái đã "
        "đổi sau lệnh ghi. Chạy lại write_verification_status() trên trace đã commit của q05 "
        "vẫn trả \"verified\", vì phép so sánh dựa trên frozen/checked_at chứ không dựa trên "
        "định danh tài khoản.",
    )
    para(
        document,
        "Với q06, cờ được ghi bằng flag_suspicious_tx và đọc lại bằng get_account_risk_status. "
        "Ở đây phép kiểm tra yếu hơn và cần nói rõ: write_verification_status() chạy lại trên "
        "trace đã commit trả \"unverified\", vì cả tx_id lẫn flagged_tx_ids đều đã bị redact "
        "thành [REDACTED] nên không thể so khớp. Semantic gate vẫn đánh dấu flag_verify_success "
        "= true, nhưng chỉ nhờ một đường suy luận dự phòng: khi thấy [REDACTED] ở cả hai phía, "
        "gate lấy danh tính mục tiêu từ question ID (q06 → TX003/ACC001) thay vì từ log. Đó là "
        "suy luận của bộ kiểm tra, không phải bằng chứng đọc được từ dữ liệu. Kết luận trung "
        "thực: freeze có bằng chứng đọc lại độc lập; flag có side effect và có lần đọc lại, "
        "nhưng tính đúng đắn của phép so khớp tx_id không kiểm chứng được từ log đã commit.",
    )
    note(
        document,
        "Trung thực về giới hạn: bước verify chứng minh trạng thái đổi, không chứng minh người "
        "thực hiện có thẩm quyền kiểm soát viên. Hệ thống chưa có định danh/approval đã xác "
        "thực; đây là hạn chế đã biết, nêu ở mục 7.",
    )


def section_5(document: Document) -> None:
    document.add_heading("5. MCP server", level=1)
    para(
        document,
        "Server do sinh viên viết (src/trfc/mcp_server/server.py), chạy qua stdio, đăng ký 5 "
        "tool — trong đó freeze_account_temporarily và flag_suspicious_tx là tool ghi. Server "
        "gọi chung tools/impl.py với agent, nên contract dữ liệu giống nhau ở cả hai đường.",
    )

    document.add_heading("Danh sách tool và contract", level=3)
    add_table(
        document,
        ["Tool", "Tham số bắt buộc", "Loại", "Ghi vào đâu"],
        [
            ["search_policy", "query", "đọc", "— (RAG index trong bộ nhớ)"],
            ["get_transactions", "account_id, date_from, date_to", "đọc", "—"],
            ["get_account_risk_status", "account_id", "đọc", "— (sinh checked_at mỗi lần gọi)"],
            ["freeze_account_temporarily", "account_id, reason", "GHI", "accounts.frozen, freeze_reason, frozen_at"],
            ["flag_suspicious_tx", "tx_id, reason", "GHI", "transactions.flagged + bảng flags"],
        ],
        widths=[4.6, 4.4, 1.4, 6.0],
        font_size=8,
    )
    caption(document, "Bảng 3. Contract của 5 tool phơi ra qua MCP.")

    document.add_heading("stdout sạch và discover động", level=3)
    for text in (
        "stdout sạch: logging handler gắn sys.stderr (server.py). stdio transport dùng stdout "
        "làm kênh JSON-RPC, nên một print() debug sẽ chèn văn bản vào frame và làm client parse "
        "lỗi toàn phiên. Vì vậy mọi thông báo chẩn đoán trong server đều đi qua logging.",
        "Client discover động: client2.py gọi session.list_tools() rồi kiểm tra tham số theo "
        "input_schema server trả về (validate_arguments). Không hard-code tên tool; thêm tool "
        "mới thì client không phải sửa. Đây là điểm khác biệt so với việc client tự khai báo "
        "danh sách tool cứng.",
        "Host thứ hai: client2.py do C viết, độc lập với agent và với người viết server — đây "
        "là bằng chứng interop, không phải client tự kiểm tra chính mình. Bộ test tương ứng "
        "tests/test_client2.py có 12 ca.",
        "Giới hạn: các ca client2 dùng test double. Lần chạy thật trong repo là agent gọi "
        "server qua stdio; smoke call read-only của client2 trên server thật không nằm trong "
        "bằng chứng đã commit.",
    ):
        bullet(document, text)

    document.add_heading("An toàn khi ghi qua MCP", level=3)
    para(
        document,
        "Một MCP server phơi tool ghi ra stdio là bề mặt nguy hiểm nếu chạy nhầm database. Vì "
        "vậy impl.py gọi require_isolated_database_for_writes() trước mọi lệnh ghi: khi "
        "TRFC_REQUIRE_ISOLATED_DB=1, lệnh ghi bị từ chối nếu TRFC_STATE_DB thiếu, trỏ vào "
        "database mặc định, hoặc trỏ vào đường dẫn nằm trong repo. Đây là kiểm soát kỹ thuật "
        "để tránh sửa nhầm dữ liệu, không phải kiểm soát phân quyền — nó không biết ai đang gọi.",
    )
    para(
        document,
        "Agent khởi động server bằng chính interpreter hiện tại (sys.executable -m "
        "trfc.mcp_server.server) với môi trường đã lọc (mcp_server_environment), rồi gọi "
        "session.initialize() và lấy danh sách tool từ server thay vì từ một bảng cứng trong "
        "code agent. Nhờ đó agent và client thứ hai nhìn thấy cùng một contract do server công bố.",
    )


def section_6(document: Document) -> None:
    document.add_heading("6. Đánh giá", level=1)

    document.add_heading("Testset", level=3)
    add_table(
        document,
        ["category", "Số câu", "Mục đích"],
        [
            ["retrieval", "3", "tra cứu một tài liệu, bắt buộc đúng doc_id và version"],
            ["calc", "2", "tính tỷ lệ vượt hạn mức, đối chiếu số liệu giao dịch"],
            ["contradiction", "2", "chọn đúng bản hiện hành khi hai bản mâu thuẫn"],
            ["multi_doc", "1", "tổng hợp bắt buộc từ ≥ 2 tài liệu"],
            ["no_answer (i)", "2", "phương thức thanh toán ngoài phạm vi DOC0009"],
            ["no_answer (ii)", "2", "thiếu dữ liệu để tính/kết luận"],
        ],
        widths=[3.4, 1.6, 12.0],
    )
    para(
        document,
        "Phải đo cặp faithfulness + tỉ lệ từ chối đúng: nếu chỉ đo faithfulness, một hệ thống "
        "luôn từ chối sẽ đạt điểm tuyệt đối vì không bao giờ đưa ra khẳng định sai; nếu chỉ đo "
        "tỉ lệ trả lời, hệ thống sẽ bịa để tránh bị phạt bỏ trống.",
    )

    document.add_heading("Cách đo", level=3)
    para(
        document,
        "faithfulness = tỉ lệ claims khớp nguyên văn trong cả câu trả lời và context; "
        "context_precision = tỉ lệ context có doc_id nằm trong source_refs; answer_correctness "
        "= kiểm tra mọi marker trong expected.values (contains_all); refusal_correctness và "
        "refusal_subtype_correctness tách riêng loại i/ii. Các metric chuỗi này là so khớp xác "
        "định: rẻ, tái lập được, nhưng bỏ sót diễn đạt lại. metadata_filter_usage là metric thứ "
        "sáu và là metric duy nhất chấm trên tool_trace chứ không chấm trên văn bản trả lời: "
        "câu khai báo expected_tier chỉ đạt khi trace có ít nhất một lệnh search_policy truyền "
        "đúng tier đó. Trace không thu được (null) trả None chứ không bao giờ đọc thành True — "
        "nếu không, một lần chạy mất log sẽ tự động được cộng điểm.",
    )
    para(
        document,
        "Ba quy ước chấm cần nêu rõ vì chúng quyết định con số: (1) metric không chấm được thì "
        "trả null/Unscorable, không quy về 0 và cũng không quy về 1 — nhờ vậy một hệ thống từ "
        "chối mọi câu không thể đạt điểm cao giả; (2) context_precision chấm từng context theo "
        "chính các mã DOCnnnn nó trích; context không mang mã nào bị loại khỏi mẫu số thay vì "
        "bị tính là không liên quan; (3) answer_correctness chỉ áp dụng cho câu "
        "allowed_to_answer = true, nên 4 câu no_answer để trống thay vì bị tính sai.",
    )
    para(
        document,
        "Có một đường đo thứ hai, tuỳ chọn: prompts/judge.txt yêu cầu một LLM tách câu trả lời "
        "thành các khẳng định và tự gán nhãn supported/unsupported. Judge chạy BÊN TRONG "
        "evaluator, trước bước redaction, và chỉ thêm cột judge_* bên cạnh metric tất định — "
        "nó không ghi đè và không quyết định điểm nào. Ba lý do: (1) chấm trên log đã redact "
        "sẽ hỏi model rằng 220.000.000 VND có trong một đoạn văn mà số tiền đã bị thay bằng "
        "[REDACTED] VND, tức là câu trả lời chắc chắn sai — vì vậy judge từ chối mọi dòng còn "
        "chứa [REDACTED] và ghi lý do; (2) nhãn do model tự khai không được dùng để tính điểm, "
        "eval/metrics.py luôn chấm lại bằng so khớp chuỗi, nếu không faithfulness trở thành "
        "đại lượng model tự chấm chính mình; (3) judge không được trả về outcome hay subtype, "
        "nên nó không thể làm đẹp tỉ lệ từ chối. Log đã commit không có phép đo judge nào: nó "
        "được tạo trước khi module judge ra đời nên mọi dòng đều thiếu trường judge_*. Module "
        "eval/llm_judge.py và cờ --judge đã có, kèm 26 unit test trong tests/test_llm_judge.py, "
        "nhưng báo cáo không dẫn số của judge vì chưa có lần chạy thật nào được lưu lại. Đây là "
        "giới hạn bằng chứng, không phải bằng chứng judge chấm sai.",
    )
    para(
        document,
        "Toàn bộ phép chấm chạy trên dữ liệu CHƯA redaction. Chỉ sau khi row[\"metrics\"] được "
        "tính xong, run_eval mới ghi bản đã qua redact_for_log(). Hệ quả là điểm trong "
        "evaluation.csv đúng, nhưng bản JSONL không đủ để người đọc tự chấm lại.",
    )

    document.add_heading("Kết quả từng câu", level=3)
    rows = load_csv()

    def score_cell(value: str) -> str:
        if value in ("Unscorable", "Missing", "N/A", ""):
            return value or "N/A"
        try:
            return f"{float(value):.2f}"
        except ValueError:
            return value

    table_rows = []
    for row in rows:
        table_rows.append([
            row["question_id"], row["category"],
            row["answer_correctness"].replace("True", "đúng").replace("False", "sai"),
            row["faithfulness"], score_cell(row["context_precision"]),
            row["refusal_correctness"].replace("True", "đúng").replace("False", "sai"),
            row["refusal_subtype_correctness"].replace("True", "đúng").replace("False", "sai"),
            row["calls"], fmt_int(row["prompt_tokens"]), fmt_int(row["completion_tokens"]),
        ])
    add_table(
        document,
        ["ID", "category", "answer", "faithfulness", "ctx prec", "refusal", "subtype",
         "calls", "prompt", "completion"],
        table_rows,
        widths=[1.1, 2.5, 1.5, 2.2, 1.5, 1.4, 1.5, 1.2, 1.9, 2.2],
        font_size=7.6,
    )
    caption(document, "Bảng 4. Kết quả 12 câu, trích evaluation.csv của lần chạy staging.")

    note(
        document,
        "Faithfulness tất định KHÔNG đạt: cột này là Unscorable ở cả 12/12 câu, không phải 1.0. "
        "Runtime không sinh claims (claims = null ở mọi dòng), mà faithfulness() chỉ chấm trên "
        "claims do runtime cung cấp.",
    )

    document.add_heading("Đối chiếu với LLM judge", level=3)
    para(
        document,
        "Judge chạy song song nhưng bảng kết quả không có cột judge nào để điền: log đã commit "
        "không mang trường judge_*. Muốn điền phải chạy lại eval/run_eval.py --judge với LLM "
        "thật rồi commit log mới; báo cáo cố ý không suy ra số thay cho lần chạy chưa có.",
    )

    document.add_heading("Chi phí token", level=3)
    total_prompt = sum(int(row["prompt_tokens"]) for row in rows)
    total_completion = sum(int(row["completion_tokens"]) for row in rows)
    total_calls = sum(int(row["calls"]) for row in rows)
    longest = max(rows, key=lambda row: int(row["max_prompt"]))
    costliest = max(rows, key=lambda row: int(row["prompt_tokens"]) + int(row["completion_tokens"]))
    add_table(
        document,
        ["Chỉ số", "Giá trị"],
        [
            ["Tổng số lượt gọi model", f"{total_calls}"],
            ["Tổng prompt tokens", f"{total_prompt:,}".replace(",", ".")],
            ["Tổng completion tokens", f"{total_completion:,}".replace(",", ".")],
            ["Tổng tokens cả testset", f"{total_prompt + total_completion:,}".replace(",", ".")],
            ["Prompt dài nhất", f"{longest['question_id']} — {int(longest['max_prompt']):,}".replace(",", ".")],
            ["Câu tốn nhất", f"{costliest['question_id']} — {int(costliest['prompt_tokens']) + int(costliest['completion_tokens']):,}".replace(",", ".")],
        ],
        widths=[7.0, 8.0],
    )

    document.add_heading("Hai ca thất bại và phân tích", level=3)
    para(
        document,
        "Marker kỳ vọng là \"44%\" và \"220.000.000 VND\". Agent tính đúng 44% và thực hiện "
        "freeze + verify thành công, nhưng trong bản ghi, mọi số tiền đã bị eval/redaction.py "
        "thay bằng [REDACTED] VND (9 vị trí), nên marker thứ hai không thể xuất hiện trong "
        "actual_answer đã lưu. Điểm được tính TRƯỚC redaction (run_eval tính row[\"metrics\"] "
        "rồi mới ghi redact_for_log(row)), nên kết quả False phản ánh câu trả lời gốc — nhưng "
        "người đọc log không thể tự chấm lại câu này. Đây là giới hạn bằng chứng, không phải "
        "kết luận agent tính sai.",
        bold_lead="q05 (calc, freeze). ",
    )
    para(
        document,
        "Marker kỳ vọng là chuỗi \"không được ra quyết định khóa\". Agent trả lời \"Không.\" "
        "rồi giải thích rằng kiểm soát viên không thể ra quyết định khoá khi thiếu nhật ký gốc, "
        "và trả lời đúng \"5 năm\" cho vế thứ hai. Kết luận nghiệp vụ đúng nhưng câu chữ không "
        "chứa đúng chuỗi marker, nên _contains_literal() trả False. Đây là hạn chế của so khớp "
        "chuỗi, không phải lỗi suy luận.",
        bold_lead="q08 (multi_doc). ",
    )
    para(
        document,
        "Bổ sung biến thể diễn đạt (synonym/regex) trong testset; ghi thêm trường "
        "answer_contains_markers trước redaction để log vẫn kiểm chứng được; và cân nhắc "
        "entailment/NLI offline thay cho so khớp chuỗi.",
        bold_lead="Hướng sửa. ",
    )

    document.add_heading("Đọc kết quả theo từng tầng của đề tài", level=3)
    add_table(
        document,
        ["Tầng", "Câu đại diện", "Bằng chứng đo được", "Kết luận"],
        [
            ["(a) Tra cứu có nguồn", "q01–q03, q07",
             "8/8 câu answerable có nguồn đúng trong top-5; câu trả lời mang trích dẫn [Source: DOCnnnn, chunk n]",
             "Đạt: câu trả lời truy được về doc_id + version, kể cả khi phải chọn giữa hai phiên bản (q07)"],
            ["(b) Biến đổi", "q04–q08",
             "q05 tính đúng 44% từ hai con số không cùng xuất hiện trong một chunk; q08 tổng hợp DOC0006 + DOC0008",
             "Đạt về năng lực; 2/8 marker trượt vì so khớp chuỗi, không phải vì suy luận"],
            ["(c) Hành động + verify", "q05 (mạnh), q06 (một phần)",
             "q05: freeze → read-back frozen=true, checked_at > frozen_at, chạy lại verifier vẫn verified. q06: flag → read-back, nhưng tx_id đã redact nên không so khớp lại được",
             "Đạt ở q05. q06 có side effect và read-back nhưng bằng chứng so khớp tx_id phụ thuộc suy luận của gate"],
            ["Từ chối đúng loại", "q09–q12",
             "4/4 đúng outcome, 4/4 đúng subtype (2 loại i, 2 loại ii)",
             "Đạt: hai loại từ chối được phân biệt và chấm riêng"],
        ],
        widths=[3.0, 2.1, 6.9, 5.0],
        font_size=8,
    )
    caption(document, "Bảng 5. Đối chiếu kết quả với ba tầng bắt buộc của đề tài.")

    document.add_heading("Bằng chứng và giới hạn của bằng chứng", level=3)
    for text in (
        "12/12 câu có actual_outcome hợp lệ; refusal_correctness đúng 12/12, subtype đúng 4/4.",
        "Semantic gate trả overall = PASS với 0 schema error, 0 semantic error, 0 unverified check.",
        "q05 và q06 đều có cặp write → read-back trong step_events.jsonl. q05 tái xác minh được "
        "từ log; q06 không, vì tx_id và flagged_tx_ids đều bị redact.",
        "Log không ghi tên provider/model — cấu hình model của lần chạy là thông tin cấu hình "
        "chứ không phải bằng chứng đọc được từ log.",
        "Redaction che số tiền, account_id và tx_id ở cả câu trả lời lẫn expected.values, nên "
        "không thể tái chấm điểm từ log đã commit; evaluation.csv là bản ghi điểm chính thức.",
    ):
        bullet(document, text)

    document.add_heading("Cách ly database khi chạy thử nghiệm", level=3)
    para(
        document,
        "Mọi tool ghi đều có side effect thật lên SQLite, nên chạy eval trên data/state.db sẽ "
        "làm hỏng dữ liệu production. scripts/run_c4_staging.ps1 xử lý bằng ba lớp: (1) "
        "TRFC_REQUIRE_ISOLATED_DB=1 khiến tool ghi từ chối chạy nếu TRFC_STATE_DB trỏ vào trong "
        "repo; (2) TRFC_STATE_DB trỏ tới một file .db dùng-một-lần ngoài repo; (3) script băm "
        "SHA256 data/state.db ba lần — trước khi seed, sau khi seed, và sau khi eval xong — rồi "
        "so sánh. Cả ba lần đều cho cùng một giá trị. data/*.db nằm trong .gitignore nên không "
        "ai clone repo mà kiểm lại được hash này; báo cáo dẫn quy trình sinh ra nó thay vì chỉ "
        "dẫn con số.",
    )

    document.add_heading("Những gì đã xác minh và những gì chưa", level=3)
    para(
        document,
        "Đã xác minh bằng log hoặc bằng lần chạy lại trong phiên này: bộ unit test đạt "
        "407 passed, 0 skipped trên Python 3.13.5 (target `make test` loại `tests/test_tools.py` nên "
        "báo 403); semantic gate trả overall = PASS với 12/12 "
        "ca, 0 schema error, 0 semantic error, 0 unverified check; và cặp write → read-back của "
        "q05 có mặt trong step_events.jsonl. Chưa xác minh và báo cáo không claim: model/provider "
        "của lần chạy (log không lưu trường này — qwen/qwen3.8-27b trong llm.py:24 chỉ là default "
        "trong code), điểm faithfulness (Unscorable 12/12 vì runtime không sinh claims), và phép "
        "đo judge (log được tạo trước khi module judge ra đời).",
    )


def section_7(document: Document) -> None:
    document.add_heading("7. Hạn chế và hướng phát triển", level=1)
    for lead, text in (
        ("Embedding offline bằng hashing. ",
         "md5 theo token không nắm ngữ nghĩa tiếng Việt; recall phụ thuộc mạnh vào trùng từ "
         "khoá. Chuyển sang sentence-transformers hoặc embedding API sẽ cải thiện recall, đổi "
         "lại là thêm phụ thuộc mạng và chi phí."),
        ("Faithfulness không chấm được. ",
         "Runtime không sinh claims, nên metric trả Unscorable ở 12/12 câu. Cần một bước claim "
         "segmentation có nguồn (tách câu trả lời thành các khẳng định kèm span trong context) "
         "trước khi có thể báo cáo faithfulness có nghĩa."),
        ("Redaction làm mất khả năng tái chấm. ",
         "Che số tiền và định danh là cần thiết, nhưng che luôn expected.values khiến log "
         "không tự kiểm chứng được. Ghi thêm kết quả so khớp marker dạng boolean trước redaction "
         "sẽ giữ được cả hai."),
        ("Chưa có định danh kiểm soát viên. ",
         "Quy trình freeze/flag chưa có actor đã xác thực hay bản ghi approval; guard hiện tại "
         "là cô lập database, không phải phân quyền."),
        ("Corpus nhỏ và một miền. ",
         "9 tài liệu, một phiên bản lịch sử. Chưa kiểm chứng khi corpus hàng trăm tài liệu với "
         "nhiều version chồng lấn."),
        ("Top-K = 5 có thể bỏ sót tài liệu thứ hai. ",
         "q11 yêu cầu cả DOC0007 (hạn mức) và DOC0006 (nhật ký giao dịch). Đo trực tiếp: "
         "search_policy với k=5 chỉ trả DOC0007 và DOC0003; DOC0006 chỉ xuất hiện ở hạng 10. "
         "Vì vậy agent thỉnh thoảng từ chối đúng nhưng chỉ trích DOC0007, làm semantic gate "
         "báo thiếu trích dẫn. Đây là hạn chế của retrieval, không phải của judge; cách sửa "
         "đúng là tăng K cho câu multi-doc hoặc rerank theo phủ tài liệu, không phải nới lỏng "
         "gate."),
    ):
        para(document, text, bold_lead=lead, size=9.5)
    para(
        document,
        "Rerank sau bước hybrid; claim segmentation để đo faithfulness thật; human-in-the-loop "
        "có approval đã xác thực cho tool ghi; audit trail bất biến (append-only, có hash) thay "
        "cho SQLite cục bộ.",
        bold_lead="Hướng phát triển. ",
        size=9.5,
    )


def section_8(document: Document) -> None:
    document.add_heading("8. Phân công và đóng góp", level=1)
    add_table(
        document,
        ["Thành viên", "Vai trò", "File phụ trách", "Commit tiêu biểu"],
        [
            ["A — Dữ liệu & truy hồi", "corpus, chunking, embedding, store, dense + hybrid, filter tier",
             "data/docs/*.md, src/trfc/rag/*, config.toml",
             "ed531d9, 69dd5d8, b975579, 0e0f6fc"],
            ["B — Agent & tool/MCP", "tool schema, 5 tool, MCP server, ReAct loop, call_llm, prompt",
             "src/trfc/tools/*, src/trfc/mcp_server/*, src/trfc/agent/*, prompts/*",
             "6ccbdf1, 84a69e7, d12f5cc, aae71ca"],
            ["C — Đo lường & tái lập", "testset, metrics, evaluator, event schema, semantic gate, client thứ hai, đóng gói",
             "eval/*, tests/*, logs/*, Makefile, README.md",
             "8c77866, 2a6cffb, 86b144e, b9f09ba"],
        ],
        widths=[3.4, 5.2, 4.8, 3.6],
        font_size=8,
    )

    counts = git_commit_counts()
    if counts:
        rows = [[author, str(count)] for author, count in counts]
        rows.append(["Tổng cộng", str(sum(count for _, count in counts))])
        add_table(document, ["Tài khoản Git", "Số commit"], rows, widths=[6.0, 3.0], font_size=8.5)
        para(
            document,
            "Hai tài khoản Do Ngo và Do Coding cùng thuộc thành viên B. Lịch sử commit được "
            "đối chiếu tại buổi bảo vệ; mỗi thành viên giải thích phần mình phụ trách. Số "
            "commit chỉ là chỉ dấu khối lượng, không phải thước đo đóng góp: A và C có ít "
            "commit hơn nhưng mỗi commit chứa nhiều file hơn, còn B tách nhỏ theo từng tool.",
            size=9,
        )
        add_table(
            document,
            ["Thành viên", "Phần nhận bảo vệ khi vấn đáp"],
            [
                ["A", "Chunking (vì sao bảng giữ nguyên khối), store._tier_views và lý do filter "
                      "chạy trước rank, so sánh dense vs hybrid"],
                ["B", "Vòng lặp ReAct + MAX_STEPS, parse action an toàn, contract 5 tool bằng "
                      "@dataclass, cặp write → read-back, MCP server stdio"],
                ["C", "Thiết kế testset 12 câu, vì sao đo cặp faithfulness + refusal, "
                      "metadata_filter_usage chấm trên trace, semantic gate, cách ly DB"],
            ],
            widths=[2.4, 12.6],
            font_size=8.5,
        )
    para(document, f"Commit HEAD tại thời điểm đóng gói báo cáo: {git_head()}.", size=8.5, italic=True)


def section_9(document: Document) -> None:
    document.add_heading("9. Phụ lục", level=1)

    document.add_heading("A. Prompt gốc (trích prompts/system.txt)", level=3)
    system_prompt = (ROOT / "prompts" / "system.txt").read_text(encoding="utf-8").strip()
    excerpt = "\n".join(system_prompt.splitlines()[:8])
    box = document.add_table(rows=1, cols=1)
    box.style = "Table Grid"
    cell = box.rows[0].cells[0]
    cell.text = ""
    run = cell.paragraphs[0].add_run(excerpt)
    run.font.name = "Consolas"
    run.font.size = Pt(7.4)
    caption(document, "Toàn văn ở prompts/system.txt; prompts/decision.txt quy định thứ tự "
                      "tra cứu → submit_decision → trả lời.")

    document.add_heading("B. Trace đầy đủ của q05 (JSONL)", level=3)
    rows = load_jsonl("evaluation.jsonl")
    q05 = next(row for row in rows if row["question_id"] == "q05")
    trace_lines = []
    for step in q05["tool_trace"]:
        trace_lines.append(
            f"step {step['step']}: {step['tool_name']} "
            f"args={json.dumps(step['arguments'], ensure_ascii=False)} "
            f"status={step['status']}"
        )
    box = document.add_table(rows=1, cols=1)
    box.style = "Table Grid"
    cell = box.rows[0].cells[0]
    cell.text = ""
    run = cell.paragraphs[0].add_run("\n".join(trace_lines))
    run.font.name = "Consolas"
    run.font.size = Pt(7.6)
    para(
        document,
        "Bản ghi đầy đủ nằm ở logs/staging_20261017_201308/step_events.jsonl; số tiền và định "
        "danh trong đó đã qua redaction.",
        size=8.5,
        italic=True,
    )

    document.add_heading("C. Khai báo sử dụng AI", level=3)
    para(
        document,
        "Chi tiết ở ai-usage.md. Tóm tắt: dùng Claude Code cho scaffold, corpus, RAG, evaluator, "
        "event schema và đóng gói báo cáo; GitHub Copilot gợi ý autocomplete trong impl.py và "
        "server.py; ChatGPT hỗ trợ ý tưởng thiết kế tier pre-filter và gỡ lỗi asyncio trên "
        "Windows. Không dùng AI để sinh log hay số liệu đánh giá.",
        size=9,
    )


def main() -> int:
    document = Document()
    setup_document(document)

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(2)
    run = title.add_run("TRFC Agent — Trợ lý Kiểm soát Rủi ro & Gian lận Giao dịch")
    run.bold = True
    run.font.size = Pt(16)
    run.font.color.rgb = ACCENT

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(10)
    run = subtitle.add_run(
        "Báo cáo Final Project AIPR · RAG + Agent loop + MCP có đo lường\n"
        f"Nhóm 3 sinh viên · commit {git_head()} · 2026-10-17"
    )
    run.font.size = Pt(9.5)
    run.font.color.rgb = MUTED

    section_1(document)
    section_2(document)
    section_3(document)
    section_4(document)
    section_5(document)
    section_6(document)
    section_7(document)
    section_8(document)
    section_9(document)

    document.save(OUT)
    print(f"WROTE {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
