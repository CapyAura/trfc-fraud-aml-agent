"""Tool contract — A import Chunk, B sở hữu file này.

Yêu cầu 2.3: schema bằng @dataclass có type hint, KHÔNG dùng dict thô.
GV kiểm tra bằng `grep -n "@dataclass"`.

Đổi bất kỳ dataclass nào ở đây thì sửa CẢ impl.py + server.py trong CÙNG 1 commit
(xem PHAN_CONG.md §7).
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Chunk:
    """Một mảnh tài liệu trả về từ search_policy."""

    doc_id: str
    title: str
    version: str
    chunk_index: int
    text: str
    score: float
    tier: int | None = None      # tầng eKYC — metadata filter (điểm cộng +1)


@dataclass
class Transaction:
    """Một giao dịch đọc từ DB mô phỏng."""

    tx_id: str
    account_id: str
    amount: float
    currency: str
    ts: datetime                 # UTC
    country: str
    method: str                  # phải khớp danh mục DOC0009
    location: str


@dataclass
class RiskStatus:
    """Trạng thái rủi ro của tài khoản — kết quả của bước VERIFY.

    `checked_at` tồn tại để chứng minh lần đọc này là MỚI, không phải đọc lại
    response của chính lệnh write.
    """

    account_id: str
    frozen: bool
    freeze_reason: str | None
    frozen_at: datetime | None
    flagged_tx_ids: list[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Ack:
    """Xác nhận một tool ghi đã thực thi."""

    ok: bool
    message: str
    tx_id: str | None = None
