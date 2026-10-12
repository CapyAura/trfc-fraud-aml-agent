"""Test chunking — chủ sở hữu: A. Canh RỦI RO #3 của đề tài.

Đây là test quan trọng nhất của A: bảng hạn mức eKYC bị cắt vỡ thì chunk chứa
"hạn mức 500 triệu" mà mất dòng "áp dụng cho tầng eKYC 2" → trả số ĐÚNG nhưng
gán SAI tầng. Lỗi im lặng, không crash, không có stack trace để lần.

Test phải KHẲNG ĐỊNH: không chunk nào chứa nửa bảng.
"""

import pytest


@pytest.mark.skip(reason="A — CP2: bỏ skip khi chunking.py cài đặt xong")
def test_khong_chunk_nao_chua_nua_bang_han_muc():
    """Mọi chunk chứa dòng hạn mức phải chứa luôn dòng tầng eKYC đi kèm."""
    from trfc.rag.chunking import chunk_document

    chunks = chunk_document(
        doc_id="DOC0007",
        title="Hạn mức giao dịch theo tầng eKYC",
        version="2026.1",
        text="...",  # A: nạp nội dung thật
    )
    for c in chunks:
        if "hạn mức" in c.text.lower():
            assert "eKYC" in c.text, f"chunk {c.chunk_index} có hạn mức mà mất tầng:\n{c.text}"


@pytest.mark.skip(reason="A — CP2")
def test_chunk_size_lay_tu_config():
    """chunk_size/overlap phải đến từ config.toml, không hard-code (yêu cầu 2.5)."""
    from trfc.config import CONFIG

    assert CONFIG["chunking"]["chunk_size"] > 0
    assert CONFIG["chunking"]["overlap"] < CONFIG["chunking"]["chunk_size"]


@pytest.mark.skip(reason="A — CP2")
def test_khong_tim_thay_tra_ve_list_rong():
    """Hợp đồng với B: không có kết quả → [] , KHÔNG được trả None."""
    from trfc.rag.search import search_policy

    assert search_policy("zzz khong ton tai trong corpus") == []
