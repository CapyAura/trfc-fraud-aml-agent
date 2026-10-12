"""SQLite state store — chủ sở hữu: B.

Đây là chỗ side effect THẬT xảy ra (yêu cầu 2.7). KHÔNG mock trả "OK".
`get_account_risk_status` đọc từ đây, không đọc lại response của lệnh write —
đó là toàn bộ ý nghĩa của bước verify.

Chạy trực tiếp để tạo + seed DB và tự kiểm:
    python -m trfc.tools.state
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trfc.config import ROOT

DB_PATH = ROOT / "data" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id   TEXT PRIMARY KEY,
    ekyc_tier    INTEGER NOT NULL,
    frozen       INTEGER NOT NULL DEFAULT 0,
    freeze_reason TEXT,
    frozen_at    TEXT
);
CREATE TABLE IF NOT EXISTS transactions (
    tx_id      TEXT PRIMARY KEY,
    account_id TEXT NOT NULL REFERENCES accounts(account_id),
    amount     REAL NOT NULL,
    currency   TEXT NOT NULL,
    ts         TEXT NOT NULL,          -- ISO-8601 UTC
    country    TEXT NOT NULL,
    method     TEXT NOT NULL,
    location   TEXT NOT NULL,
    flagged    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS flags (
    tx_id     TEXT PRIMARY KEY REFERENCES transactions(tx_id),
    reason    TEXT NOT NULL,
    flagged_at TEXT NOT NULL
);
"""

# ponytail: seed cố định, đủ cho testset của C. Ca ACC001 cố ý dựng để vượt
# hạn mức tầng 2 + bất khả thi địa lý (2 quốc gia trong 10 phút).
_SEED_ACCOUNTS = [("ACC001", 2), ("ACC002", 3), ("ACC003", 1)]
_SEED_TXS = [
    # ACC001 — tầng eKYC 2, hạn mức 500tr/ngày: 4 giao dịch tổng 720tr = vượt 44%
    ("TX001", "ACC001", 300_000_000, "VND", "2026-10-09T08:00:00", "VN", "chuyen_khoan", "Ha Noi"),
    ("TX002", "ACC001", 250_000_000, "VND", "2026-10-09T09:30:00", "VN", "chuyen_khoan", "Ha Noi"),
    ("TX003", "ACC001", 120_000_000, "VND", "2026-10-09T14:00:00", "SG", "the_quoc_te", "Singapore"),
    ("TX004", "ACC001",  50_000_000, "VND", "2026-10-09T14:07:00", "VN", "chuyen_khoan", "Ha Noi"),
    # ACC002 — tầng eKYC 3, trong hạn mức, sạch
    ("TX005", "ACC002", 100_000_000, "VND", "2026-10-09T10:00:00", "VN", "chuyen_khoan", "Da Nang"),
    # ACC003 — tầng eKYC 1, hạn mức thấp
    ("TX006", "ACC003",  20_000_000, "VND", "2026-10-09T11:00:00", "VN", "vi_dien_tu", "Hue"),
]


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Mở connection, tạo schema nếu chưa có."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def reset(path: Path = DB_PATH) -> None:
    """Xoá DB rồi seed lại. Gọi trước mỗi lần eval để log tái lập được."""
    if path.exists():
        path.unlink()
    conn = connect(path)
    conn.executemany("INSERT INTO accounts (account_id, ekyc_tier) VALUES (?, ?)", _SEED_ACCOUNTS)
    conn.executemany(
        "INSERT INTO transactions (tx_id, account_id, amount, currency, ts, country, method, location)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        _SEED_TXS,
    )
    conn.commit()
    conn.close()


def _self_check() -> None:
    """Verify phải đọc được state MỚI hơn thời điểm write — đây là điều GV hỏi."""
    reset()
    conn = connect()

    # write
    frozen_at = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "UPDATE accounts SET frozen = 1, freeze_reason = ?, frozen_at = ? WHERE account_id = ?",
        ("test", frozen_at, "ACC001"),
    )
    conn.commit()

    # verify — đọc lại từ DB, không đọc response của lệnh trên
    row = conn.execute("SELECT * FROM accounts WHERE account_id = 'ACC001'").fetchone()
    assert row["frozen"] == 1, dict(row)
    assert row["freeze_reason"] == "test", dict(row)
    assert row["frozen_at"] == frozen_at, dict(row)

    txs = conn.execute(
        "SELECT * FROM transactions WHERE account_id = 'ACC001' ORDER BY ts"
    ).fetchall()
    total = sum(t["amount"] for t in txs)
    assert len(txs) == 4, len(txs)
    assert total == 720_000_000, total  # ca testset: 720tr / hạn mức 500tr = vượt 44%

    conn.close()
    print(f"self-check OK — {len(_SEED_ACCOUNTS)} accounts, {len(_SEED_TXS)} txs, "
          f"ACC001 tổng {total:,} VND")


if __name__ == "__main__":
    _self_check()
