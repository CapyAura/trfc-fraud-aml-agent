"""RAGAS + metric tự viết — chủ sở hữu: C. Mốc: CP4.

ponytail: RAGAS ở pyproject là optional-dep `[eval]`. Nếu cài RAGAS quá nặng
trên máy yếu thì tự viết faithfulness bằng 1 lần gọi LLM làm judge — vẫn tính
điểm, và giải thích được khi vấn đáp.
"""


def faithfulness(answer: str, contexts: list[str]) -> float:
    raise NotImplementedError("C — CP4.")


def context_precision(question: str, contexts: list[str]) -> float:
    raise NotImplementedError("C — CP4.")


def refusal_rate(results: list[dict]) -> dict:
    """Trả {'correct': n, 'total': n, 'by_type': {'i': ..., 'ii': ...}}. C cài đặt."""
    raise NotImplementedError("C — CP4. Tách loại (i) và (ii), đừng gộp.")
