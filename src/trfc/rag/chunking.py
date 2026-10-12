"""Chunking — chủ sở hữu: A. Mốc: CP2.

Việc phải làm (xem PHAN_CONG.md §2 và DE_TAI_TRFC_Agent.md §3.2):
  - recursive split theo Chương → Điều → Khoản
  - chunk_size / overlap lấy từ config.toml, KHÔNG hard-code
  - BẢNG ATOMIC: không chunk nào được chứa nửa bảng hạn mức eKYC.
    Cắt vỡ bảng → chunk có "hạn mức 500 triệu" mà mất dòng "áp dụng cho
    tầng eKYC 2" → trả số ĐÚNG nhưng gán SAI tầng. Lỗi im lặng, không crash.
    tests/test_chunking.py canh đúng ca này.
"""

from __future__ import annotations

import re

from trfc.config import CONFIG
from trfc.tools.schemas import Chunk

# Heading markdown: "## Điều 5. ..." — số dấu # là cấp (Chương < Điều < Khoản).
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
# Dòng của bảng markdown.
_TABLE_ROW = re.compile(r"^\s*\|")

_encoder = None
_encoder_tried = False


def _count_tokens(text: str) -> int:
    """Đếm token bằng tiktoken; không có thì đếm từ (đủ để so ngưỡng chunk_size)."""
    global _encoder, _encoder_tried
    if not _encoder_tried:
        _encoder_tried = True
        try:
            import tiktoken

            _encoder = tiktoken.get_encoding("cl100k_base")
        except Exception:  # ponytail: thiếu tiktoken vẫn chạy được, chỉ kém chính xác
            _encoder = None
    if _encoder is None:
        return len(text.split())
    return len(_encoder.encode(text))


def _units(lines: list[str]) -> list[tuple[str, str]]:
    """Cắt thành các khối nguyên tử: ("heading"|"body"|"table", text).

    Bảng markdown là MỘT khối không thể chia. Dòng giới thiệu nằm ngay trên
    bảng được gộp vào cùng khối — đây chính là dòng nói bảng áp dụng cho tầng
    eKYC nào. Tách nó ra là mở đường cho lỗi im lặng ở tests/test_chunking.py.
    """
    units: list[tuple[str, str]] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            units.append(("body", "\n".join(buf)))
            buf.clear()

    i = 0
    while i < len(lines):
        line = lines[i]

        if _HEADING.match(line):
            flush()
            units.append(("heading", line.strip()))
            i += 1
            continue

        if _TABLE_ROW.match(line):
            flush()
            rows: list[str] = []
            while i < len(lines) and _TABLE_ROW.match(lines[i]):
                rows.append(lines[i].strip())
                i += 1
            # Kéo dòng giới thiệu ngay trên bảng vào khối bảng.
            intro = ""
            if units and units[-1][0] == "body":
                intro = units.pop()[1]
            units.append(("table", f"{intro}\n" + "\n".join(rows) if intro else "\n".join(rows)))
            continue

        if not line.strip():
            flush()
            i += 1
            continue

        buf.append(line.strip())
        i += 1

    flush()
    return units


def _segments(units: list[tuple[str, str]]) -> list[str]:
    """Gắn đường dẫn heading vào từng khối để chunk tự đứng một mình vẫn có ngữ cảnh.

    Mỗi chunk phải trích dẫn được ("Điều 5 > Khoản 2") mà không cần chunk bên cạnh.
    """
    stack: list[tuple[int, str]] = []
    segments: list[str] = []

    for kind, text in units:
        if kind == "heading":
            level = len(text) - len(text.lstrip("#"))
            stack = [(lv, h) for lv, h in stack if lv < level]
            stack.append((level, text.lstrip("# ").strip()))
            continue
        prefix = " > ".join(h for _, h in stack)
        segments.append(f"{prefix}\n{text}" if prefix else text)

    return segments


def _carry_tail(buf: list[str], overlap: int) -> tuple[list[str], int]:
    """Giữ đuôi chunk trước làm overlap. Cắt theo ranh giới khối, không theo ký tự."""
    if len(buf) < 2:
        return [], 0
    tail: list[str] = []
    total = 0
    for seg in reversed(buf):
        n = _count_tokens(seg)
        if total + n > overlap:
            break
        tail.insert(0, seg)
        total += n
    return tail, total


def chunk_document(
    doc_id: str,
    title: str,
    version: str,
    text: str,
    tier: int | None = None,
) -> list[Chunk]:
    """Cắt 1 document thành list[Chunk].

    `tier` là metadata tầng eKYC của cả tài liệu (nếu tài liệu chỉ nói về 1 tầng).
    Thêm làm tham số tuỳ chọn nên không phá vỡ hợp đồng cũ với B — search.py
    pre-filter theo tier dựa vào field này.
    """
    cfg = CONFIG["chunking"]
    size = cfg["chunk_size"]
    overlap = cfg["overlap"]

    segments = _segments(_units(text.splitlines()))
    chunks: list[Chunk] = []
    buf: list[str] = []
    buf_tokens = 0

    def emit() -> None:
        chunks.append(
            Chunk(
                doc_id=doc_id,
                title=title,
                version=version,
                chunk_index=len(chunks),
                text="\n\n".join(buf),
                score=0.0,
                tier=tier,
            )
        )

    for seg in segments:
        n = _count_tokens(seg)
        if buf and buf_tokens + n > size:
            emit()
            buf, buf_tokens = _carry_tail(buf, overlap)
        # Khối đơn lẻ vượt size vẫn giữ nguyên: atomic > đúng kích thước.
        buf.append(seg)
        buf_tokens += n

    if buf:
        emit()

    return chunks
