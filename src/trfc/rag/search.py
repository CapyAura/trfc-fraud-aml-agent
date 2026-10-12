"""Retrieval dense + hybrid — chủ sở hữu: A. Mốc: CP2.

Việc phải làm:
  - dense: similarity search top-K kèm score
  - hybrid: fuse `w_bm25 * BM25_norm + w_vector * cosine` (trọng số ở config.toml)
  - tái dùng W4/ex2_1_hybrid_search.py — KHÔNG viết lại từ đầu
  - metadata filter `tier`: PRE-FILTER trước khi rank, không phải lọc sau
    (lọc sau thì top-K đã bị chunk sai tầng chiếm chỗ)

Hợp đồng với B (PHAN_CONG.md §7): không tìm thấy → trả [], KHÔNG trả None.
"""

from trfc.tools.schemas import Chunk


def search_policy(
    query: str,
    k: int = 5,
    tier: int | None = None,
    mode: str = "hybrid",
) -> list[Chunk]:
    """Tra cứu chính sách. A cài đặt."""
    raise NotImplementedError("A — CP2. Xem docstring đầu file.")
