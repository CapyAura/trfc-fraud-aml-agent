"""Embedding + token hoá — chủ sở hữu: A. Mốc: CP2.

Một cửa duy nhất để sinh vector VÀ để tách token nội dung. Có key
(`OPENAI_API_KEY` / `JINA_API_KEY`) thì gọi API; không có key thì rơi về
offline-hashing — đúng như `.env.example` hứa. Không có key vẫn chạy được
end-to-end, chỉ kém chính xác hơn (xem hai ngưỡng MIN_SCORE bên dưới).

ponytail: port từ `W4/vector_store.py`. Offline hashing = md5 từng token nội dung →
1024 chiều, chuẩn hoá L2. Không học được ngữ nghĩa (câu diễn giải sẽ trượt), nhưng
deterministic, không mạng, không key — đủ để test và để máy GV chạy cold start.
"""

from __future__ import annotations

import hashlib
import math
import os
import sys

import numpy as np
from dotenv import load_dotenv

load_dotenv()

DIM_OFFLINE = 1024
MODEL_OFFLINE = "offline-hashing"

# Ngưỡng điểm tối thiểu. Hai backend cho hai thang điểm KHÁC NHAU nên phải hai
# ngưỡng — dùng chung một số là hoặc lọt rác, hoặc mất hết kết quả.
# Số lấy từ `W4/vector_store.py` (đo trên corpus W4):
#   model thật:    liên quan 0.46–0.81 · không liên quan 0.00–0.31
#   offline hash:  liên quan 0.12–0.57 · không liên quan 0.00–0.09
MIN_SCORE = 0.45
MIN_SCORE_OFFLINE = 0.10

# Từ dừng — tiếng Anh (corpus lẫn thuật ngữ EN) + tiếng Việt (hư từ).
# Có cả dạng KHÔNG DẤU: người dùng hay gõ không dấu, corpus thì có dấu. Nếu chỉ
# loại dạng có dấu thì "khong"/"trong"/"tai" vẫn "khớp" được với corpus, và một
# câu hỏi ngoài corpus sẽ trả về kết quả rác chỉ nhờ mấy hư từ này.
STOPWORDS = frozenset(
    """
    a an and are as at be by for from has have how i in is it its may of on or that the
    their they this to up was were what when where which who will with
    và là của cho với theo trong trên dưới khi thì để do đó này các một những được có
    tại từ đến về hoặc nếu nhưng mà ở ra vào sẽ đã đang bị ấy nó họ tôi bạn gì sao nào
    rất quá cũng chỉ còn đều vẫn phải nên vì bởi bằng giữa đây không
    va la cua cho voi theo trong tren duoi khi thi de do nay cac mot nhung duoc co
    tai tu den ve hoac neu ma o ra vao se da dang bi ay no ho toi ban gi sao nao
    rat qua cung chi con deu van phai nen vi boi bang giua day khong
    """.split()
)

# Ký tự dính vào token khi cắt theo khoảng trắng (dấu câu + cú pháp markdown).
_PUNCT = ".,;:?!()\"'|*[]{}<>`#—-–…"

_backend: tuple | None = None


def content_tokens(text: str) -> list[str]:
    """Token nội dung: bỏ từ dừng và dấu câu. Dùng cho cả offline-hash lẫn BM25.

    Một hàm token hoá duy nhất cho cả index lẫn query — hai bên lệch nhau thì
    điểm số vô nghĩa.
    """
    return [
        t
        for t in (w.strip(_PUNCT) for w in text.lower().split())
        if t and t not in STOPWORDS
    ]


def _make_client():
    """Chọn backend theo key có trong môi trường. Không key → (None, offline)."""
    if key := os.getenv("OPENAI_API_KEY"):
        from openai import OpenAI

        return OpenAI(api_key=key), "text-embedding-3-small"
    if key := os.getenv("JINA_API_KEY"):
        from openai import OpenAI

        return OpenAI(api_key=key, base_url="https://api.jina.ai/v1"), "jina-embeddings-v3"
    return None, MODEL_OFFLINE


def _probe() -> tuple:
    """Chốt backend MỘT LẦN cho cả run.

    Có key nhưng gọi không được (hết quota, mất mạng, key sai) thì rơi về offline
    và cảnh báo ra stderr — thà demo chạy được còn hơn chết giữa buổi bảo vệ.
    Chốt một lần để vector của query và của chunk luôn cùng một không gian;
    đổi backend giữa run thì điểm số vô nghĩa.
    """
    client, model = _make_client()
    if client is None:
        return None, MODEL_OFFLINE
    try:
        client.embeddings.create(model=model, input=["ping"])
        return client, model
    except Exception as exc:  # ponytail: bắt rộng vì đây là đường lui, không phải logic
        print(
            f"[embed] không gọi được {model} ({type(exc).__name__}: {exc}) "
            "→ rơi về offline-hashing",
            file=sys.stderr,
        )
        return None, MODEL_OFFLINE


def backend() -> tuple:
    """(client, model) — client=None nghĩa là offline-hashing."""
    global _backend
    if _backend is None:
        _backend = _probe()
    return _backend


def is_offline() -> bool:
    return backend()[0] is None


def min_score() -> float:
    return MIN_SCORE_OFFLINE if is_offline() else MIN_SCORE


def _offline_embed(texts: list[str]) -> list[list[float]]:
    """Embedding bằng hash token nội dung — không mạng, không key, deterministic."""
    vectors: list[list[float]] = []
    for text in texts:
        vec = [0.0] * DIM_OFFLINE
        for token in content_tokens(text):
            digest = hashlib.md5(token.encode("utf-8")).digest()
            vec[int.from_bytes(digest[:4], "big") % DIM_OFFLINE] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        vectors.append([v / norm for v in vec] if norm else vec)
    return vectors


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Sinh vector cho danh sách văn bản. Rỗng vào → rỗng ra."""
    if not texts:
        return []
    client, model = backend()
    if client is None:
        return _offline_embed(texts)
    # ponytail: retry/timeout để cho SDK openai (mặc định 2 lần, 600s).
    # Yêu cầu 2.4 chỉ bắt buộc retry/timeout ở `call_llm` của B.
    resp = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in resp.data]


def cosine_similarity(a, b) -> float:
    """Cosine giữa hai vector. Vector 0 chiều dài 0 → 0.0 (không chia cho 0)."""
    va = np.asarray(a, dtype=float)
    vb = np.asarray(b, dtype=float)
    na = float(np.linalg.norm(va))
    nb = float(np.linalg.norm(vb))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


def _self_check() -> None:
    """Kiểm tra nhanh: vector đúng chiều, chuẩn hoá, và cosine phân biệt được văn bản."""
    client, model = backend()
    print(f"backend = {model}{' (offline)' if client is None else ''}")
    assert content_tokens("Hạn mức trong ngày của tầng 2") == ["hạn", "mức", "ngày", "tầng", "2"], (
        "từ dừng/dấu câu phải bị loại: " + str(content_tokens("Hạn mức trong ngày của tầng 2"))
    )
    assert content_tokens("| Tầng 2 | 500.000.000 VND |") == ["tầng", "2", "500.000.000", "vnd"], (
        "ô bảng phải cắt được: " + str(content_tokens("| Tầng 2 | 500.000.000 VND |"))
    )
    vecs = embed_texts(["hạn mức giao dịch tầng eKYC 2", "hạn mức giao dịch tầng eKYC 2", "zzz"])
    assert len(vecs) == 3, "số vector phải khớp số văn bản"
    assert len(vecs[0]) == len(vecs[2]), "vector phải cùng chiều"
    same = cosine_similarity(vecs[0], vecs[1])
    other = cosine_similarity(vecs[0], vecs[2])
    assert abs(same - 1.0) < 1e-6, f"văn bản giống nhau phải cho cosine ~1.0, được {same}"
    assert same > other, "văn bản giống nhau phải gần hơn văn bản lạ"
    assert embed_texts([]) == [], "rỗng vào phải rỗng ra"
    print(f"cosine(giống) = {same:.3f} > cosine(lạ) = {other:.3f} — OK")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _self_check()
