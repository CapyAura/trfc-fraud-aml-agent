"""Chunking — chủ sở hữu: A. Mốc: CP2.

Việc phải làm (xem PHAN_CONG.md §2 và DE_TAI_TRFC_Agent.md §3.2):
  - recursive split theo Chương → Điều → Khoản
  - chunk_size / overlap lấy từ config.toml, KHÔNG hard-code
  - BẢNG ATOMIC: không chunk nào được chứa nửa bảng hạn mức eKYC.
    Cắt vỡ bảng → chunk có "hạn mức 500 triệu" mà mất dòng "áp dụng cho
    tầng eKYC 2" → trả số ĐÚNG nhưng gán SAI tầng. Lỗi im lặng, không crash.
    tests/test_chunking.py canh đúng ca này.

ponytail: để trống có chủ đích — A viết, đừng để AI scaffold hộ phần logic
chính vì buổi bảo vệ sẽ hỏi "chỉ dòng code đảm bảo bảng không bị cắt vỡ".
"""

from trfc.tools.schemas import Chunk


def chunk_document(doc_id: str, title: str, version: str, text: str) -> list[Chunk]:
    """Cắt 1 document thành list[Chunk]. A cài đặt."""
    raise NotImplementedError("A — CP2. Xem docstring đầu file.")
