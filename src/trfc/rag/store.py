"""Vector store + nạp corpus — chủ sở hữu: A. Mốc: CP2.

Nạp `data/docs/*.md` → bỏ frontmatter → chunk → index (vector + BM25). Dense
similarity search trả top-K kèm score. Không tìm thấy → `[]`, không trả `None`.

**Vì sao có "view theo tầng".** Bảng hạn mức eKYC phải nguyên khối (rule atomic ở
`chunking.py`), nên MỘT chunk chứa cả 3 tầng. Metadata filter `tier` cần đơn vị nhỏ
hơn chunk — nếu không thì `tier==2` vẫn trả về nguyên bảng, tức là trả luôn hạn mức
tầng 1 và tầng 3. Nên mỗi dòng `| Tầng N | ...` sinh thêm một *view*: cùng
`doc_id`/`chunk_index`, chỉ giữ dòng của tầng N. Đây chính là "chunk hạn mức" mà
`DE_TAI_TRFC_Agent.md` §4 nói tới. Bảng gốc vẫn nằm trong index cho câu hỏi không
lọc tầng.
"""

from __future__ import annotations

import re
from dataclasses import replace
from functools import lru_cache
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from trfc.config import ROOT
from trfc.rag.chunking import chunk_document
from trfc.rag.embed import content_tokens, embed_texts
from trfc.tools.schemas import Chunk

DOCS_DIR = ROOT / "data" / "docs"

_FRONTMATTER = re.compile(r"\A---[ \t]*\n(.*?)\n---[ \t]*\n", re.DOTALL)
# Dòng bảng hạn mức: "| Tầng 2 | 500.000.000 VND | ..."
_TIER_ROW = re.compile(r"^\s*\|\s*Tầng\s*(\d+)\s*\|")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Tách khối YAML frontmatter. Không có → ({}, nguyên văn).

    Không cần PyYAML: frontmatter của corpus chỉ có `key: value` phẳng.
    """
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip()] = value.strip().strip("\"'")
    return meta, text[match.end():]


def _tier_views(chunk: Chunk) -> list[Chunk]:
    """Một chunk bảng hạn mức → nhiều view 1-tầng (xem docstring đầu file)."""
    rows = [m.group(1) for m in (_TIER_ROW.match(l) for l in chunk.text.splitlines()) if m]
    views: list[Chunk] = []
    for tier in dict.fromkeys(rows):  # dict giữ thứ tự, bỏ tầng trùng
        kept = []
        for line in chunk.text.splitlines():
            row = _TIER_ROW.match(line)
            if row is None or row.group(1) == tier:
                kept.append(line)
        views.append(replace(chunk, text="\n".join(kept), tier=int(tier)))
    return views


def load_corpus(docs_dir: Path = DOCS_DIR) -> list[Chunk]:
    """Đọc mọi `DOC*.md`, bỏ frontmatter rồi chunk. Trả về chunk GỐC (chưa tách view)."""
    chunks: list[Chunk] = []
    for path in sorted(docs_dir.glob("DOC*.md")):
        meta, body = _split_frontmatter(path.read_text(encoding="utf-8"))
        chunks.extend(
            chunk_document(
                doc_id=meta.get("doc_id", path.stem),
                title=meta.get("title", path.stem),
                version=meta.get("version", ""),
                text=body,
            )
        )
    return chunks


@lru_cache(maxsize=1)
def _index() -> tuple[tuple[Chunk, ...], np.ndarray, np.ndarray, BM25Okapi | None, int]:
    """(chunks, vectors, norms, bm25, n_base) — dựng 1 lần cho cả run.

    `chunks[:n_base]` là chunk gốc, phần còn lại là view theo tầng. Vector và BM25
    phủ cả hai để `dense_scores`/`bm25_scores` luôn cùng thứ tự chỉ số.
    """
    base = load_corpus()
    all_chunks: list[Chunk] = list(base)
    for chunk in base:
        all_chunks.extend(_tier_views(chunk))
    if not all_chunks:
        return (), np.zeros((0, 0)), np.zeros(0), None, 0

    vectors = np.asarray(embed_texts([c.text for c in all_chunks]), dtype=float)
    norms = np.linalg.norm(vectors, axis=1)
    bm25 = BM25Okapi([content_tokens(c.text) for c in all_chunks])
    return tuple(all_chunks), vectors, norms, bm25, len(base)


def corpus() -> tuple[Chunk, ...]:
    """Toàn bộ chunk trong index, kèm view theo tầng."""
    return _index()[0]


def rank_candidates(tier: int | None) -> list[int]:
    """Chỉ số các chunk được phép vào top-K — PRE-FILTER, chạy TRƯỚC khi rank.

    `tier=None` → chỉ chunk gốc (bảng gốc đầy đủ hơn view, trả cả hai là trùng).
    `tier=N`    → chỉ view của tầng N, nên chunk sai tầng không bao giờ chiếm slot
                  top-K (lọc sau thì slot đã bị chiếm mất rồi).
    """
    chunks, _, _, _, n_base = _index()
    if tier is None:
        return list(range(n_base))
    return [i for i in range(n_base, len(chunks)) if chunks[i].tier == tier]


def dense_scores(query: str) -> np.ndarray:
    """Cosine giữa query và MỌI chunk trong index (cùng thứ tự với `corpus()`)."""
    chunks, vectors, norms, _, _ = _index()
    if not chunks:
        return np.zeros(0)
    query_vec = np.asarray(embed_texts([query])[0], dtype=float)
    query_norm = float(np.linalg.norm(query_vec))
    if query_norm == 0.0:
        return np.zeros(len(chunks))
    dots = vectors @ query_vec
    denom = norms * query_norm
    return np.divide(dots, denom, out=np.zeros_like(dots), where=denom > 0)


def bm25_scores(query: str) -> np.ndarray:
    """Điểm BM25 thô (không chuẩn hoá) cho MỌI chunk."""
    chunks, _, _, bm25, _ = _index()
    if not chunks or bm25 is None:
        return np.zeros(len(chunks))
    return np.asarray(bm25.get_scores(content_tokens(query)), dtype=float)


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    chunks, vectors, _, bm25, n_base = _index()
    views = chunks[n_base:]
    print(f"corpus: {n_base} chunk gốc + {len(views)} view theo tầng = {len(chunks)}")
    print(f"vector: {vectors.shape} · bm25: {'có' if bm25 else 'không'}")
    for tier in (1, 2, 3):
        print(f"  tier={tier}: {len(rank_candidates(tier))} candidate")
