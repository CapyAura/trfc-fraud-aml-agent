"""SQLite state store — chủ sở hữu: B.

Đây là chỗ side effect THẬT xảy ra (yêu cầu 2.7). KHÔNG mock trả "OK".
`get_account_risk_status` đọc từ đây, không đọc lại response của lệnh write —
đó là toàn bộ ý nghĩa của bước verify.

Chạy trực tiếp để tạo + seed DB và tự kiểm:
    python -m trfc.tools.state
"""

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from trfc.config import ROOT

DB_PATH = ROOT / "data" / "state.db"
DB_PATH_ENV = "TRFC_STATE_DB"
REQUIRE_ISOLATED_DB_ENV = "TRFC_REQUIRE_ISOLATED_DB"

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


def resolve_db_path(path: Path | str | None = None) -> Path:
    """Resolve the one database path used by all tool connections.

    Explicit arguments take precedence (notably for seeding a test database),
    followed by ``TRFC_STATE_DB`` and then the historical project default.
    """
    if path is not None:
        configured = path
    elif DB_PATH_ENV in os.environ:
        configured = os.environ[DB_PATH_ENV]
        if not configured.strip():
            raise ValueError(f"{DB_PATH_ENV} must not be empty")
    else:
        configured = DB_PATH
    return Path(configured).expanduser().resolve()


class _WriteBlockedError(RuntimeError):
    """Actionable validation rejection that is safe to return to tool callers."""


def require_isolated_database_for_writes(path: Path | str | None = None) -> None:
    """Require the configured isolated database before any write operation.

    The optional path is used by ``reset``; it must agree with the environment
    selected for the rest of the tools and cannot override that configuration.
    This validation never opens or creates a SQLite connection.
    """
    if os.environ.get(REQUIRE_ISOLATED_DB_ENV, "").strip().lower() not in {"1", "true", "yes"}:
        raise _WriteBlockedError(
            f"Write operation blocked: set {REQUIRE_ISOLATED_DB_ENV}=1 to enable isolated writes"
        )

    configured = os.environ.get(DB_PATH_ENV)
    if not isinstance(configured, str) or not configured.strip():
        raise _WriteBlockedError(
            f"Write operation blocked: {DB_PATH_ENV} must name an isolated database"
        )

    try:
        configured_raw = Path(configured).expanduser()
        if not configured_raw.is_absolute():
            raise _WriteBlockedError(
                f"Write operation blocked: {DB_PATH_ENV} must be an absolute path"
            )
        configured_path = resolve_db_path()

        if path is not None:
            requested_raw = Path(path).expanduser()
            if not requested_raw.is_absolute():
                raise _WriteBlockedError("Write operation blocked: requested database path is not absolute")
            requested_path = resolve_db_path(path)
            if requested_path != configured_path:
                raise _WriteBlockedError(
                    "Write operation blocked: requested database path does not match "
                    f"{DB_PATH_ENV}"
                )

        default_path = DB_PATH.resolve()
        if configured_path == default_path:
            raise _WriteBlockedError(
                "Write operation blocked: configured database resolves to the default state.db"
            )
        prod_path = (ROOT / "data" / "state.db").resolve()
        if configured_path == prod_path:
            raise _WriteBlockedError(
                "Write operation blocked: configured database resolves to the production data/state.db"
            )
        if os.environ.get("TRFC_REQUIRE_OUTSIDE_REPO", "").strip().lower() in {"1", "true", "yes"}:
            try:
                configured_path.relative_to(ROOT.resolve())
                raise _WriteBlockedError(
                    f"Write operation blocked: {DB_PATH_ENV} must be outside the repository ({configured_path})"
                )
            except ValueError:
                pass  # verified outside repository
        if os.environ.get("TRFC_PREVENT_DB_OVERWRITE", "").strip().lower() in {"1", "true", "yes"}:
            if configured_path.exists():
                raise _WriteBlockedError(
                    f"Write operation blocked: staging database already exists at {configured_path} (collision prevented)"
                )
        if configured_path.exists() and not configured_path.is_file():
            raise _WriteBlockedError(
                f"Write operation blocked: {DB_PATH_ENV} must identify a SQLite file path"
            )
    except _WriteBlockedError:
        raise
    except Exception:
        raise RuntimeError(
            "Write operation blocked: configured database path could not be validated"
        ) from None


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection, creating the schema at the resolved database path."""
    resolved_path = resolve_db_path(path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(resolved_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def reset(path: Path | str | None = None) -> None:
    """Xoá DB rồi seed lại. Gọi trước mỗi lần eval để log tái lập được."""
    resolved_path = resolve_db_path(path)
    require_isolated_database_for_writes(resolved_path)
    if resolved_path.exists():
        resolved_path.unlink()
    conn = connect(resolved_path)
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
