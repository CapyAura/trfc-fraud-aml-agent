"""Retrieval dense + hybrid — chủ sở hữu: A. Mốc: CP2.

  - dense : cosine top-K kèm score
  - hybrid: `w_bm25 * BM25_norm + w_vector * cosine` (trọng số ở config.toml)
  - tái dùng cách làm của `W4/ex2_1_hybrid_search.py`: BM25Okapi + min-max normalize
    rồi fuse. File W4 nằm NGOÀI repo và là stub hỏng (thiếu dấu `:` ở `def
    hybrid_search`) nên port lại cách làm, không import được.
  - metadata filter `tier`: PRE-FILTER trước khi rank (`store.rank_candidates`),
    không phải lọc sau — lọc sau thì top-K đã bị chunk sai tầng chiếm chỗ.

Hợp đồng với B (PHAN_CONG.md §7): không tìm thấy → trả [], KHÔNG trả None.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import numpy as np

from trfc.config import CONFIG
from trfc.rag import store
from trfc.rag.embed import min_score
from trfc.tools.schemas import Chunk


def normalize_scores(scores: np.ndarray) -> np.ndarray:
    """Min-max về [0,1]. Port từ `W4/ex2_1_hybrid_search.py::normalize_scores`.

    Dải bằng 0 (0 hoặc 1 ứng viên) → trả 0 hết: BM25 không có gì để phân biệt thì
    đừng để nó tự bịa ra thứ hạng.
    """
    if scores.size == 0:
        return scores
    lo, hi = float(scores.min()), float(scores.max())
    if hi - lo == 0.0:
        return np.zeros_like(scores)
    return (scores - lo) / (hi - lo)


def search_policy(
    query: str,
    k: int = 5,
    tier: int | None = None,
    mode: str = "hybrid",
) -> list[Chunk]:
    """Tra cứu chính sách. Trả top-K chunk kèm score, hoặc [] nếu không có gì đạt ngưỡng."""
    if not query.strip():
        return []
    k = max(1, k)

    # PRE-FILTER: chỉ số ứng viên hợp lệ được xét. Chunk sai tầng không bao giờ
    # vào được top-K, kể cả khi nó khớp từ khoá tốt hơn.
    candidates = store.rank_candidates(tier)
    if not candidates:
        return []

    cosine = store.dense_scores(query)[candidates]

    # Ngưỡng áp lên cosine — đây là tín hiệu đã hiệu chỉnh theo backend (hai backend
    # hai thang điểm, xem `embed.py`). Điểm fuse chỉ dùng để XẾP HẠNG, không để chặn:
    # nó là thang tương đối, ngưỡng trên nó sẽ vô nghĩa.
    floor = min_score()
    keep = cosine >= floor
    if not keep.any():
        return []

    if mode == "dense":
        fused = cosine
    elif mode == "hybrid":
        weights = CONFIG["retrieval"]
        fused = weights["w_bm25"] * normalize_scores(store.bm25_scores(query)[candidates]) \
            + weights["w_vector"] * cosine
    else:
        raise ValueError(f"mode không hợp lệ: {mode!r} (chỉ 'dense' | 'hybrid')")

    chunks = store.corpus()
    order = np.argsort(-np.where(keep, fused, -np.inf))[:k]
    return [
        replace(chunks[candidates[i]], score=round(float(fused[i]), 4))
        for i in order
        if keep[i]
    ]


def _main() -> int:
    parser = argparse.ArgumentParser(description="Tra cứu chính sách TRFC (dense | hybrid).")
    parser.add_argument("query", help="câu truy vấn")
    parser.add_argument("-k", type=int, default=CONFIG["retrieval"]["top_k"])
    parser.add_argument("--tier", type=int, default=None, choices=(1, 2, 3),
                        help="lọc theo tầng eKYC trước khi rank")
    parser.add_argument("--mode", default=CONFIG["retrieval"]["mode"], choices=("dense", "hybrid"))
    args = parser.parse_args()

    results = search_policy(args.query, k=args.k, tier=args.tier, mode=args.mode)
    print(f"query={args.query!r} mode={args.mode} tier={args.tier} k={args.k}")
    if not results:
        print("→ [] (không có chunk nào đạt ngưỡng)")
        return 0
    for chunk in results:
        head = f"doc_id={chunk.doc_id} chunk={chunk.chunk_index} score={chunk.score}"
        print(f"\n--- {head} tier={chunk.tier} v{chunk.version} · {chunk.title}")
        for line in chunk.text.splitlines():
            print(f"    {line}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(_main())
